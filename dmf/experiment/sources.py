"""Video and bounded live capture. Camera plugins return BGR uint8 frames."""
import importlib
import queue
import threading
import time
import cv2
import numpy as np
from concurrent.futures import Future
from dmf.vision.contracts import FramePacket
from dmf.vision.timebase import VideoTimestampResolver
from dmf.recording import load_recorded_timestamps


class VideoSource:
    def __init__(self,config):
        self.capture=cv2.VideoCapture(str(config['video']))
        if not self.capture.isOpened():raise FileNotFoundError(f"Cannot open video: {config['video']}")
        try:
            self.clock=VideoTimestampResolver(float(self.capture.get(cv2.CAP_PROP_FPS) or config.get('fps_fallback',0)))
            self.recorded_times=load_recorded_timestamps(config['video'],config.get('timestamps_csv'))
            if self.recorded_times is not None and len(self.recorded_times)!=int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)):
                raise ValueError('video frame count does not match recorded timestamps')
        except Exception:self.capture.release();raise
        self.max_frames=config.get('max_frames');self.index=0

    def __iter__(self):return self
    def __next__(self):
        if self.max_frames is not None and self.index>=self.max_frames:raise StopIteration
        ok,frame=self.capture.read()
        if not ok:
            if self.recorded_times is not None and self.index<len(self.recorded_times):
                raise ValueError('video decode ended before recorded timestamps')
            raise StopIteration
        if self.recorded_times is not None:
            if self.index>=len(self.recorded_times):raise ValueError('video has extra frames without timestamps')
            t,kind=self.recorded_times[self.index],'host_receive_perf_counter'
        else:t,kind=self.clock.resolve(self.index,self.capture.get(cv2.CAP_PROP_POS_MSEC))
        packet=FramePacket('offline',self.index,t,kind,frame);self.index+=1;return packet
    def close(self):self.capture.release()


class OpenCVCamera:
    def __init__(self,config):
        self.capture=cv2.VideoCapture(config.get('device',0))
        if not self.capture.isOpened():raise RuntimeError('Camera open failed; use an SDK plugin for vendor-only devices')
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
    def read(self,timeout_s):
        ok,image=self.capture.read()
        if not ok:raise RuntimeError('camera frame read failed')
        return image
    def close(self):self.capture.release()


def camera_backend(config):
    if config['backend']=='opencv':return OpenCVCamera(config)
    module,name=config['factory'].split(':',1)
    return getattr(importlib.import_module(module),name)(config.get('parameters',{}))


class LiveSource:
    def __init__(self,config,factory=None,electrode_stream=None):
        self.config=config;self.timeout=float(config['frame_timeout_s'])
        self.startup_timeout=float(config.get('startup_timeout_s',self.timeout))
        self.capture_stall_timeout=float(config.get('capture_stall_timeout_s',5.0))
        self.received_first_frame=False
        if self.startup_timeout<=0:raise ValueError('startup_timeout_s must be positive')
        if self.capture_stall_timeout<=self.timeout:raise ValueError('capture_stall_timeout_s must exceed frame_timeout_s')
        self.queue=queue.Queue(maxsize=1);self.stop=threading.Event();self.index=0
        self.commands=queue.Queue()
        self.command_lock=threading.Lock()
        self.accepting_commands=True
        self.electrode_stream=electrode_stream
        self.close_error=''
        self.worker=threading.Thread(target=self._capture,args=(factory or (lambda:camera_backend(config)),),daemon=True)
        self.worker.start()

    def _put(self,value):
        try:self.queue.put_nowait(value)
        except queue.Full:
            try:self.queue.get_nowait()
            except queue.Empty:pass
            try:self.queue.put_nowait(value)
            except queue.Full:pass

    def _capture(self,factory):
        camera=None
        try:
            camera=factory()
            if self.electrode_stream is not None:camera.electrode_stream=self.electrode_stream
            timeout_started=None
            while not self.stop.is_set():
                self._run_camera_commands(camera)
                try:
                    image=camera.read(self.timeout)
                except TimeoutError as exc:
                    now=time.monotonic()
                    if timeout_started is None:timeout_started=now
                    if now-timeout_started>=self.capture_stall_timeout:
                        raise TimeoutError(
                            f'camera produced no frame for {self.capture_stall_timeout:g}s: {exc}'
                        ) from exc
                    continue
                timeout_started=None
                if not isinstance(image,np.ndarray) or image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8:
                    raise ValueError('camera.read must return HxWx3 uint8 BGR')
                metadata=getattr(camera,'last_frame_metadata',None)
                t=metadata['host_receive_monotonic_ns']/1e9 if metadata else time.monotonic()
                kind='host_receive_monotonic' if metadata else 'host_monotonic'
                self._put((t,image.copy(),kind))
        except Exception as exc:
            if camera is not None and getattr(camera,'recording_journal',None) is not None:
                camera.recording_journal.log.error=str(exc)
            self._put(exc)
        finally:
            with self.command_lock:self.accepting_commands=False
            self._run_camera_commands(camera)
            if camera is not None:
                try:camera.close()
                except Exception as exc:self.close_error=str(exc);self._put(exc)
                self.close_error=self.close_error or getattr(camera,'last_recording_error','')

    def _run_camera_commands(self,camera):
        while True:
            try:method,args,future=self.commands.get_nowait()
            except queue.Empty:return
            try:
                if camera is None:raise RuntimeError('camera is not connected')
                result=getattr(camera,method)(*args)
            except Exception as exc:future.set_exception(exc)
            else:future.set_result(result)

    def submit_camera_command(self,method,*args):
        future=Future()
        with self.command_lock:
            if not self.accepting_commands or self.stop.is_set():
                future.set_exception(RuntimeError('camera is closing or closed'))
            else:self.commands.put((method,args,future))
        return future

    def __iter__(self):return self
    def __next__(self):
        wait_timeout=self.timeout if self.received_first_frame else self.startup_timeout
        try:item=self.queue.get(timeout=wait_timeout)
        except queue.Empty:raise TimeoutError('camera frame timeout') from None
        if isinstance(item,Exception):raise item
        t,image,kind=item
        if time.monotonic()-t>self.timeout:raise TimeoutError('stale camera frame')
        self.received_first_frame=True
        packet=FramePacket('live',self.index,t,kind,image);self.index+=1;return packet
    def close(self):self.stop.set() # SDK read/close must be bounded; daemon protects the CLI.
