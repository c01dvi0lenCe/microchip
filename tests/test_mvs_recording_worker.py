"""Software-only SDK contract: pool buffers expire at FreeImageBuffer."""
import ctypes
import csv
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from dmf.experiment.mvs_camera import MvsCamera
from dmf.recording import sidecar_paths
from tests.test_mvs_camera import PixelTypes


class Audit:
    def __init__(self, *args):
        self.captured, self.written, self.lost = [], [], []
        self.preview_replacements = 0
        self.log = SimpleNamespace(error='')

    def observe_capture(self, meta):
        self.captured.append(dict(meta))

    def add_frame(self, meta):
        self.written.append(dict(meta))

    def record_loss(self, meta, reason):
        self.lost.append((meta['sdk_frame_number'], reason))

    def record_preview_replacement(self):
        self.preview_replacements += 1

    def close(self, error=''):
        if error:
            raise OSError(error)


class RecordingSdk:
    """Real pointer handoff, bounded Get timeout, slow/failed encoder injection."""
    def __init__(self, side=4):
        self.frames = queue.Queue()
        self.side = side
        self.pool = (ctypes.c_ubyte * (side*side))()
        self.encoded = []
        self.calls = []
        self.encoder_entered = threading.Event()
        self.allow_encode = threading.Event()
        self.allow_encode.set()
        self.fail_encode = None
        self.stop_called = threading.Event()
        self.strategy = 'latest'
        self.fault_seen = threading.Event()

    def MV_CC_SetGrabStrategy(self, strategy):
        self.calls.append(strategy)
        self.strategy = strategy
        return 0

    def feed(self, *ids):
        for frame_id in ids:
            self.frames.put(frame_id)
        fence = threading.Event()
        self.frames.put(fence)
        return fence

    def MV_CC_ClearImageBuffer(self):
        self.calls.append('clear')
        while True:
            try: self.frames.get_nowait()
            except queue.Empty: return 0

    def MV_CC_GetImageBuffer(self, out, timeout):
        try: frame_id = self.frames.get(timeout=min(.02, timeout / 1000))
        except queue.Empty: return 0x80000007
        if isinstance(frame_id, threading.Event):
            frame_id.set()
            return 0x80000007
        if frame_id == 'disconnected':
            self.fault_seen.set()
            return 0x80000302
        if self.strategy == 'latest':
            while not self.frames.empty():
                frame_id = self.frames.get_nowait()
        ctypes.memset(self.pool, frame_id % 256, len(self.pool))
        out.stFrameInfo = SimpleNamespace(nFrameLen=len(self.pool), nWidth=self.side, nHeight=self.side,
            nExtendWidth=0, nExtendHeight=0, enPixelType=1, nFrameNum=frame_id,
            nDevTimeStampHigh=2, nDevTimeStampLow=42, nHostTimeStamp=123)
        out.pBufAddr = ctypes.addressof(self.pool)
        return 0

    def MV_CC_FreeImageBuffer(self, frame):
        ctypes.memset(self.pool, 0xee, len(self.pool))
        return 0

    def MV_CC_InputOneFrameEx(self, info):
        self.encoder_entered.set()
        if not self.allow_encode.wait(3):
            raise RuntimeError('test encoder release timeout')
        value = bytes(info.pData[:info.nDataLen])
        if value[0] == self.fail_encode:
            return 1
        self.encoded.append(value)
        return 0

    def MV_CC_StartRecord(self, _):
        self.calls.append('start')
        return 0

    def MV_CC_StopRecord(self):
        self.stop_called.set()
        return 0


def synthetic_camera(sdk):
    camera = MvsCamera.__new__(MvsCamera)
    camera.closed = False
    camera.started = True
    camera.recording = False
    camera.electrode_stream = None
    camera.pixels = PixelTypes
    camera.camera = sdk
    camera.headers = SimpleNamespace(MV_CC_RECORD_PARAM=SimpleNamespace,
        MvGvspPixelType=int, MV_FormatType_AVI=1, MV_FRAME_OUT=SimpleNamespace,
        MV_CC_INPUT_FRAME_INFO_EX=SimpleNamespace, MV_GrabStrategy_OneByOne='ordered',
        MV_GrabStrategy_LatestImagesOnly='latest')
    camera._get_int = lambda name: sdk.side
    camera._get_enum = lambda name: 1
    camera._get_float = lambda name: 20.0
    return camera


class MvsRecordingWorkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.video = Path(temp.name) / 'stream.avi'
        self.sdk = RecordingSdk()
        self.camera = synthetic_camera(self.sdk)
        self.audit = Audit()
        journal = patch('dmf.experiment.mvs_camera.RecordingJournal', return_value=self.audit)
        journal.start()
        self.addCleanup(journal.stop)
        self.addCleanup(self.finish)

    def finish(self):
        self.sdk.allow_encode.set()
        if self.camera.recording:
            try: self.camera.stop_recording()
            except OSError: pass

    def test_stale_sdk_frames_are_excluded_from_record_boundary(self):
        self.sdk.feed(91)
        self.camera.start_recording(self.video)
        self.assertIn('clear', self.sdk.calls)
        self.assertTrue(self.sdk.feed(92).wait(.5))
        self.camera.stop_recording()
        self.assertEqual([r['sdk_frame_number'] for r in self.audit.captured], [92])
        self.assertEqual(self.sdk.encoded, [bytes([92]) * 16])

    def test_preview_keeps_only_newest_or_lone_trigger_before_and_after_ordered_recording(self):
        self.sdk.frames.put(17)
        self.assertTrue((self.camera.read(.05) == 17).all(), 'lone trigger was discarded')
        self.camera.start_recording(self.video)
        self.assertEqual(self.sdk.strategy, 'ordered')
        self.assertTrue(self.sdk.feed(18,19).wait(.5))
        self.camera.stop_recording()
        self.assertEqual(self.sdk.strategy, 'latest')
        self.sdk.frames.put(20)
        self.sdk.frames.put(21)
        self.assertTrue((self.camera.read(.05) == 21).all())
        self.assertEqual(self.sdk.encoded, [bytes([18])*16, bytes([19])*16])

    def test_device_error_after_a_valid_frame_is_not_swallowed_as_a_recoverable_timeout(self):
        self.camera.start_recording(self.video)
        self.sdk.frames.put(22)
        self.assertTrue((self.camera.read(.5) == 22).all())
        self.sdk.frames.put('disconnected')
        self.assertTrue(self.sdk.fault_seen.wait(.5))
        with self.assertRaisesRegex(OSError, '80000302'):
            self.camera.stop_recording()
        self.assertEqual(self.sdk.encoded, [bytes([22])*16])

    def test_failed_sdk_buffer_release_is_a_local_loss_with_the_original_id(self):
        self.sdk.MV_CC_FreeImageBuffer = lambda frame: (_ for _ in ()).throw(OSError('release error'))
        self.camera.start_recording(self.video)
        self.sdk.frames.put(28)
        with self.assertRaisesRegex(RuntimeError, 'release error'):
            self.camera.read(.5)
        with self.assertRaisesRegex(OSError, 'release error'):
            self.camera.stop_recording()
        self.assertEqual([r['sdk_frame_number'] for r in self.audit.captured], [28])
        self.assertEqual(self.audit.lost, [(28,'sdk_buffer_release_failed')])

    def test_slow_encoder_and_unread_preview_do_not_stall_capture_or_reuse_sdk_buffer(self):
        self.sdk.allow_encode.clear()
        self.camera.start_recording(self.video)
        self.assertTrue(self.sdk.feed(10, 11, 14).wait(.5), 'capture blocked behind preview/encoder')
        self.assertTrue(self.sdk.encoder_entered.wait(.5))
        self.assertFalse(self.audit.written)
        image = self.camera.read(.1)
        self.assertTrue((image == 14).all())
        self.assertEqual(self.camera.last_frame_metadata['sdk_frame_number'], 14)
        self.assertEqual(self.audit.preview_replacements, 2)
        self.sdk.allow_encode.set()
        self.camera.stop_recording()
        self.assertEqual(self.sdk.encoded, [bytes([i])*16 for i in (10, 11, 14)])
        self.assertEqual([r['sdk_frame_number'] for r in self.audit.written], [10,11,14])
        self.assertFalse(self.audit.lost)

    def test_fifo_counts_inflight_raw_bytes_and_never_replaces_an_accepted_frame(self):
        self.camera.recording_byte_limit = 32  # two 16-byte frames INCLUDING active encode
        self.sdk.allow_encode.clear()
        self.camera.start_recording(self.video)
        self.assertTrue(self.sdk.feed(30,31,32,33).wait(.5))
        self.assertEqual(self.audit.lost, [(32,'raw_queue_overflow'),(33,'raw_queue_overflow')])
        self.sdk.allow_encode.set()
        self.assertEqual(Path(self.camera.stop_recording()), self.video.resolve())
        self.assertEqual(self.sdk.encoded, [bytes([i])*16 for i in (30,31)])
        self.assertEqual(len(self.audit.captured), 4)

    def test_stop_does_not_close_encoder_under_queued_or_active_writes(self):
        self.sdk.allow_encode.clear()
        self.camera.start_recording(self.video)
        self.assertTrue(self.sdk.feed(40,41).wait(.5))
        self.assertTrue(self.sdk.encoder_entered.wait(.5))
        stop = threading.Thread(target=self.camera.stop_recording)
        stop.start()
        try:
            self.assertFalse(self.sdk.stop_called.wait(.08))
        finally:
            self.sdk.allow_encode.set()
            stop.join(2)
        self.assertFalse(stop.is_alive())
        self.assertTrue(self.sdk.stop_called.is_set())
        self.assertEqual([r['sdk_frame_number'] for r in self.audit.written], [40,41])

    def test_first_failed_input_and_later_unwritten_frames_have_individual_identity(self):
        self.sdk.fail_encode = 52
        self.camera.start_recording(self.video)
        self.assertTrue(self.sdk.feed(51,52,54).wait(.5))
        with self.assertRaises(OSError):
            self.camera.stop_recording()
        self.assertEqual([r['sdk_frame_number'] for r in self.audit.captured], [51,52,54])
        self.assertEqual([r['sdk_frame_number'] for r in self.audit.written], [51])
        self.assertEqual(self.audit.lost, [(52,'encoder_input_failed'),(54,'encoder_unavailable')])
        self.assertTrue(self.sdk.stop_called.is_set())


class MvsRecordingFileTests(unittest.TestCase):
    def test_real_avi_and_audits_reconcile_sdk_gap_overflow_and_preview_replacement(self):
        class AviSdk(RecordingSdk):
            def MV_CC_StartRecord(self, params):
                self.avi = cv2.VideoWriter(params.strFilePath.decode('utf-8'),
                    cv2.VideoWriter_fourcc(*'MJPG'), params.fFrameRate, (self.side, self.side))
                return 0 if self.avi.isOpened() else 1

            def MV_CC_InputOneFrameEx(self, info):
                code = super().MV_CC_InputOneFrameEx(info)
                if code == 0:
                    pixels = np.frombuffer(self.encoded[-1], np.uint8).reshape(self.side, self.side)
                    self.avi.write(cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR))
                return code

            def MV_CC_StopRecord(self):
                self.avi.release()
                return super().MV_CC_StopRecord()

        sdk = AviSdk(side=16)
        camera = synthetic_camera(sdk)
        camera.recording_byte_limit = 2 * 16 * 16
        sdk.allow_encode.clear()
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'run.avi'
            camera.start_recording(video)
            try:
                self.assertTrue(sdk.feed(30,31,35,36).wait(1))
                self.assertTrue((camera.read(.5) == 36).all())
            finally:
                sdk.allow_encode.set()
                camera.stop_recording()
            paths = sidecar_paths(video)
            manifest = json.loads(paths['manifest'].read_text(encoding='utf-8'))
            self.assertEqual(manifest['encoded_frame_count'], 2)
            self.assertEqual(manifest['written_timestamp_rows'], 2)
            self.assertEqual(manifest['status'], 'complete')
            continuity = manifest['continuity']
            self.assertEqual(continuity['status'], 'gaps_observed')
            self.assertEqual(continuity['captured_frames'], 4)
            self.assertEqual(continuity['sdk_missing_between_received'], 3)
            self.assertEqual(continuity['local_dropped_frames'], 2)
            self.assertEqual(continuity['preview_replacements'], 3)
            with paths['timestamps'].open(encoding='utf-8', newline='') as handle:
                self.assertEqual([r['sdk_frame_number'] for r in csv.DictReader(handle)], ['30','31'])
