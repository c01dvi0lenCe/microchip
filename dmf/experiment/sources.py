"""Video and bounded live capture. Camera plugins return BGR uint8 frames."""
import importlib
import queue
import threading
import time
import cv2
import numpy as np
from dmf.vision.contracts import FramePacket
from dmf.vision.timebase import VideoTimestampResolver


class VideoSource:
    def __init__(self,config):
        self.capture=cv2.VideoCapture(str(config['video']))
        if not self.capture.isOpened():raise FileNotFoundError(f"Cannot open video: {config['video']}")
        try:self.clock=VideoTimestampResolver(float(self.capture.get(cv2.CAP_PROP_FPS) or config.get('fps_fallback',0)))
        except Exception:self.capture.release();raise
        self.max_frames=config.get('max_frames');self.index=0

    def __iter__(self):return self
    def __next__(self):
        if self.max_frames is not None and self.index>=self.max_frames:raise StopIteration
        ok,frame=self.capture.read()
        if not ok:raise StopIteration
        t,kind=self.clock.resolve(self.index,self.capture.get(cv2.CAP_PROP_POS_MSEC))
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
    def __init__(self,config,factory=None):
        self.config=config;self.timeout=float(config['frame_timeout_s'])
        self.queue=queue.Queue(maxsize=1);self.stop=threading.Event();self.index=0
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
            while not self.stop.is_set():
                image=camera.read(self.timeout)
                if not isinstance(image,np.ndarray) or image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8:
                    raise ValueError('camera.read must return HxWx3 uint8 BGR')
                self._put((time.monotonic(),image.copy()))
        except Exception as exc:self._put(exc)
        finally:
            if camera is not None:camera.close()

    def __iter__(self):return self
    def __next__(self):
        try:item=self.queue.get(timeout=self.timeout)
        except queue.Empty:raise TimeoutError('camera frame timeout') from None
        if isinstance(item,Exception):raise item
        t,image=item
        if time.monotonic()-t>self.timeout:raise TimeoutError('stale camera frame')
        packet=FramePacket('live',self.index,t,'host_monotonic',image);self.index+=1;return packet
    def close(self):self.stop.set() # SDK read/close must be bounded; daemon protects the CLI.
