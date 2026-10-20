"""Hikrobot MVS USB3 camera adapter for the live-source contract."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import ctypes
import time
from threading import Lock
from pathlib import Path

import cv2
import numpy as np
from dmf.recording import RecordingJournal, sidecar_paths, clock_stamp


_sdk_lock = Lock()
_sdk_initialized = False


def _load_sdk(parameters):
    sdk_path = parameters.get("sdk_python_path") or os.environ.get("MVS_SDK_PYTHON")
    if not sdk_path:
        runtime = os.environ.get("MVCAM_COMMON_RUNENV")
        if runtime:
            sdk_path = str(Path(runtime) / "Samples" / "Python" / "MvImport")
    if not sdk_path or not Path(sdk_path).is_dir():
        raise RuntimeError(
            "MVS Python SDK bindings not found; set source.parameters.sdk_python_path "
            "or MVS_SDK_PYTHON to the MvImport directory"
        )

    sdk_path = str(Path(sdk_path).resolve())
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)
    try:
        camera_module = importlib.import_module("MvCameraControl_class")
        params = importlib.import_module("CameraParams_const")
        headers = importlib.import_module("CameraParams_header")
        pixels = importlib.import_module("PixelType_header")
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"Could not load Hikrobot MVS SDK: {exc}") from exc
    return camera_module.MvCamera, params, headers, pixels


def _serial_bytes(device_info):
    if device_info.nTLayerType == 0x00000004:
        return bytes(device_info.SpecialInfo.stUsb3VInfo.chSerialNumber).split(b"\0", 1)[0]
    if device_info.nTLayerType in (0x00000001, 0x00000040):
        return bytes(device_info.SpecialInfo.stGigEInfo.chSerialNumber).split(b"\0", 1)[0]
    return b""


def convert_mvs_buffer(width, height, pixel_type, buffer, pixels):
    """Convert supported 8-bit MVS frames to owned BGR uint8 arrays."""
    image = np.frombuffer(buffer, dtype=np.uint8)
    expected = int(width) * int(height)
    if image.size != expected:
        raise ValueError(f"Expected {expected} image bytes, received {image.size}")
    image = image.reshape((int(height), int(width)))
    # PFNC sensor order differs from OpenCV's historical two-letter aliases.
    conversions = {
        pixels.PixelType_Gvsp_BayerRG8: cv2.COLOR_BayerRGGB2BGR,
        pixels.PixelType_Gvsp_BayerGR8: cv2.COLOR_BayerGRBG2BGR,
        pixels.PixelType_Gvsp_BayerGB8: cv2.COLOR_BayerGBRG2BGR,
        pixels.PixelType_Gvsp_BayerBG8: cv2.COLOR_BayerBGGR2BGR,
    }
    if pixel_type == pixels.PixelType_Gvsp_Mono8:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if pixel_type not in conversions:
        raise ValueError(
            f"Unsupported MVS pixel format 0x{int(pixel_type):08x}; "
            "configure the camera for Mono8 or an 8-bit Bayer format"
        )
    return cv2.cvtColor(image, conversions[pixel_type])


class MvsCamera:
    def __init__(self, parameters):
        global _sdk_initialized
        self.camera = None
        self.started = False
        self.closed = False
        self.handle_created = False
        self.device_open = False
        self.recording = False
        self.recording_path = None
        self.recording_journal = None
        self.last_recording_error = ''
        self.last_frame_metadata = None
        self.electrode_stream = None
        self.camera_type, self.params, self.headers, self.pixels = _load_sdk(parameters)
        self._initialize_sdk()
        try:
            self._open(parameters)
        except Exception:
            self.close()
            raise

    def _initialize_sdk(self):
        global _sdk_initialized
        with _sdk_lock:
            if not _sdk_initialized:
                code = self.camera_type.MV_CC_Initialize()
                if code != 0:
                    raise RuntimeError(f"MVS SDK initialization failed (0x{code:08x})")
                _sdk_initialized = True

    def _check(self, code, operation):
        if code != 0:
            raise RuntimeError(f"MVS {operation} failed (0x{code:08x}); close MVS live view if it owns the camera")

    def _open(self, parameters):
        devices = self.headers.MV_CC_DEVICE_INFO_LIST()
        transport = self.params.MV_USB_DEVICE | self.params.MV_GIGE_DEVICE
        self._check(self.camera_type.MV_CC_EnumDevices(transport, devices), "device enumeration")
        serial = str(parameters.get("serial_number", "")).strip()
        selected = None
        available = []
        for index in range(devices.nDeviceNum):
            info = ctypes.cast(
                devices.pDeviceInfo[index], ctypes.POINTER(self.headers.MV_CC_DEVICE_INFO)
            ).contents
            found = _serial_bytes(info).decode("ascii", errors="replace")
            available.append(found or f"device[{index}] without a readable serial number")
            if (serial and found == serial) or (not serial and selected is None):
                selected = info
        if selected is None:
            raise RuntimeError(f"MVS camera {serial!r} not found; available devices: {available}")

        self.camera = self.camera_type()
        self._check(self.camera.MV_CC_CreateHandle(selected), "create handle")
        self.handle_created = True
        self._check(self.camera.MV_CC_OpenDevice(self.params.MV_ACCESS_Exclusive, 0), "open device")
        self.device_open = True
        self._check(
            self.camera.MV_CC_SetGrabStrategy(self.headers.MV_GrabStrategy_LatestImagesOnly),
            "set latest-frame strategy",
        )
        self._check(self.camera.MV_CC_StartGrabbing(), "start acquisition")
        self.started = True

    def read(self, timeout_s):
        if self.closed or not self.started:
            raise RuntimeError("MVS camera is closed")
        frame = self.headers.MV_FRAME_OUT()
        code = self.camera.MV_CC_GetImageBuffer(frame, max(1, int(float(timeout_s) * 1000)))
        if code != 0:
            raise TimeoutError(f"MVS did not deliver a frame before timeout (0x{code:08x})")
        received = clock_stamp()
        try:
            info = frame.stFrameInfo
            ticks = ((int(info.nDevTimeStampHigh) << 32) | int(info.nDevTimeStampLow)
                     if hasattr(info, 'nDevTimeStampHigh') else '')
            self.last_frame_metadata = dict(
                sdk_frame_number=getattr(info, 'nFrameNum', ''), device_timestamp_raw=ticks,
                sdk_host_timestamp_raw=getattr(info, 'nHostTimeStamp', ''),
                host_receive_monotonic_ns=received['host_monotonic_ns'],
                host_receive_perf_counter_ns=received['host_perf_counter_ns'],
                host_utc_ns=received['host_utc_ns'], timestamp_source='host_receive_perf_counter',
                width=info.nWidth, height=info.nHeight, pixel_type=int(info.enPixelType))
            if self.recording:
                self._input_record_frame(frame)
                self.recording_journal.add_frame(dict(self.last_frame_metadata,
                    input_completed_monotonic_ns=time.monotonic_ns()))
            raw = ctypes.string_at(frame.pBufAddr, info.nFrameLen)
            return convert_mvs_buffer(info.nWidth, info.nHeight, info.enPixelType, raw, self.pixels)
        except Exception as exc:
            if self.recording:
                self.recording_journal.log.error = str(exc)
            raise
        finally:
            self._check(self.camera.MV_CC_FreeImageBuffer(frame), "release image buffer")

    def start_recording(self, path):
        if self.recording:
            raise RuntimeError("camera recording is already active")
        output = Path(path).expanduser().resolve()
        if output.suffix.lower() != ".avi":
            raise ValueError("MVS recording output must use the .avi extension")
        output.parent.mkdir(parents=True, exist_ok=True)
        def occupied(candidate):
            return candidate.exists() or any(path.exists() for path in sidecar_paths(candidate).values())
        if occupied(output):
            base = output
            index = 1
            while occupied(output):
                output = base.with_name(f"{base.stem}_{index:03d}{base.suffix}")
                index += 1

        width = self._get_int("Width")
        height = self._get_int("Height")
        pixel_type = self._get_enum("PixelFormat")
        frame_rate = self._get_float("ResultingFrameRate")
        record = self.headers.MV_CC_RECORD_PARAM()
        record.enPixelType = self.headers.MvGvspPixelType(pixel_type)
        record.nWidth = width
        record.nHeight = height
        record.fFrameRate = frame_rate
        record.nBitRate = 8000
        record.enRecordFmtType = self.headers.MV_FormatType_AVI
        record.strFilePath = str(output).encode("utf-8")
        journal = RecordingJournal(output, frame_rate, getattr(self, 'electrode_stream', None))
        try:
            self._check(self.camera.MV_CC_StartRecord(record), "start recording")
        except Exception as exc:
            journal.close(str(exc))
            raise
        self.recording_journal = journal
        self.last_recording_error = ''
        self.recording = True
        self.recording_path = output
        return str(output)

    def _get_int(self, name):
        value = self.headers.MVCC_INTVALUE()
        self._check(self.camera.MV_CC_GetIntValue(name, value), f"read {name}")
        return int(value.nCurValue)

    def _get_enum(self, name):
        value = self.headers.MVCC_ENUMVALUE()
        self._check(self.camera.MV_CC_GetEnumValue(name, value), f"read {name}")
        return int(value.nCurValue)

    def _get_float(self, name):
        value = self.headers.MVCC_FLOATVALUE()
        self._check(self.camera.MV_CC_GetFloatValue(name, value), f"read {name}")
        rate = float(value.fCurValue)
        if not np.isfinite(rate) or rate <= 0:
            raise RuntimeError(f"MVS returned invalid recording frame rate: {rate}")
        return rate

    def _input_record_frame(self, frame):
        info = frame.stFrameInfo
        frame_info = self.headers.MV_CC_INPUT_FRAME_INFO_EX()
        frame_info.enPixelType = info.enPixelType
        frame_info.nWidth = info.nExtendWidth or info.nWidth
        frame_info.nHeight = info.nExtendHeight or info.nHeight
        frame_info.pData = ctypes.cast(frame.pBufAddr, ctypes.POINTER(ctypes.c_ubyte))
        frame_info.nDataLen = info.nFrameLen
        self._check(self.camera.MV_CC_InputOneFrameEx(frame_info), "write recording frame")

    def stop_recording(self):
        if not self.recording:
            return None
        path = self.recording_path
        error = ''
        try:
            self._check(self.camera.MV_CC_StopRecord(), "stop recording")
        except Exception as exc:
            error = str(exc)
        finally:
            self.recording = False
            self.recording_path = None
            try:
                self.recording_journal.close(error)
            except Exception as exc:
                self.last_recording_error = str(exc)
                raise
            finally:
                self.recording_journal = None
        return str(path)

    def close(self):
        global _sdk_initialized
        if self.closed:
            return
        self.closed = True
        try:
            if self.camera is not None:
                if self.recording:
                    try:
                        self.stop_recording()
                    except Exception:
                        pass
                if self.started:
                    self.camera.MV_CC_StopGrabbing()
                    self.started = False
                if self.device_open:
                    self.camera.MV_CC_CloseDevice()
                    self.device_open = False
                if self.handle_created:
                    self.camera.MV_CC_DestroyHandle()
                    self.handle_created = False
        finally:
            with _sdk_lock:
                if _sdk_initialized:
                    self.camera_type.MV_CC_Finalize()
                    _sdk_initialized = False


def open_camera(parameters):
    return MvsCamera(parameters)
