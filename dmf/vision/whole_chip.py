"""Whole-chip sensing only: bounded queues, native geometry, no actuator seam."""
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import queue
import threading
import time

import numpy as np
import cv2
from dmf.recording import AsyncCsvLog
from .whole_chip_geometry import plan_tiles, extract_tile, stitch_core, components


@dataclass(frozen=True)
class DetectionFrame:
    packet: object
    mask: object
    roi: tuple
    components: tuple
    tile_count: int
    submitted_perf_ns: int
    started_perf_ns: int
    completed_perf_ns: int
    backend: str
    batch_size: int
    error: str=''
    quality_diagnostic: str=''

    @property
    def processing_ms(self): return (self.completed_perf_ns-self.started_perf_ns)/1e6


FIELDS=('frame_id','sdk_frame_number','source_timestamp_s','source_timestamp_kind','clock_domain',
    'device_ticks_raw','receive_monotonic_ns','receive_perf_counter_ns','submitted_perf_ns','started_perf_ns',
    'completed_perf_ns','pipeline_ms','processing_ms','roi','tile_count','backend','batch_size',
    'components','foreground_px','mean_luma','quality_diagnostic','inference_queue_overwrites',
    'source_queue_overwrites','preview_queue_overwrites','delivered_sdk_number_gaps','sdk_capture_skips','error')


class WholeChipDetector:
    """Start once, submit owned FramePackets, poll completed same-frame results."""
    def __init__(self,predictor_factory,output,roi=None):
        self.output=Path(output)
        self.output.mkdir(parents=True,exist_ok=False)
        self.roi=tuple(roi) if roi is not None else None
        self.input=queue.Queue(maxsize=1); self.results=queue.Queue(maxsize=1)
        self.stopping=threading.Event(); self.lock=threading.Lock()
        self.ready=False; self.error=''; self.predictor=None
        self.queue_overwrites=0; self.result_overwrites=0; self.duplicate_frames=0
        self.delivered_sdk_number_gaps=0; self.sdk_resets=0; self.last_capture=None
        self.source_queue_overwrites=0;self.preview_queue_overwrites=0
        self.submitted=0; self.completed=0; self.failed=0
        self._last_key=None; self._last_submit=None; self.receive_fps=0.
        self.log=AsyncCsvLog({'frames':(self.output/'frames.csv',FIELDS),
            'events':(self.output/'events.csv',('event','host_perf_counter_ns','frame_id','detail')),
            'components':(self.output/'components.csv',('frame_id','sdk_frame_number','component_id','area_px','centroid_px','bbox_xywh'))})
        self.worker=threading.Thread(target=self._run,args=(predictor_factory,),name='whole-chip-inference',daemon=True)
        self.worker.start()

    def _event(self,name,frame='',detail=''):
        self.log.append('events',dict(event=name,host_perf_counter_ns=time.perf_counter_ns(),frame_id=frame,detail=detail))

    def submit(self,packet):
        with self.lock:
            if self.stopping.is_set() or self.log.error:return False
            key=(packet.video_id,packet.capture_identity)
            same_source=self._last_key is not None and key[0]==self._last_key[0]
            if self._last_key is not None and key[0]==self._last_key[0] and key[1]<=self._last_key[1]:
                self.duplicate_frames+=1; self._event('duplicate_or_old_frame',packet.frame_id,str(key)); return False
            stamp=time.perf_counter_ns()
            if self._last_submit is not None and stamp>self._last_submit:
                instantaneous=1e9/(stamp-self._last_submit)
                self.receive_fps=instantaneous if not self.receive_fps else .9*self.receive_fps+.1*instantaneous
            self._last_submit=stamp; self._last_key=key
            capture=packet.timing.capture_frame_id if packet.timing else None
            if same_source and capture is not None and self.last_capture is not None:
                if capture>self.last_capture:self.delivered_sdk_number_gaps+=max(0,capture-self.last_capture-1)
                elif capture<self.last_capture:self.sdk_resets+=1
            self.last_capture=capture
            self.source_queue_overwrites=max(self.source_queue_overwrites,
                packet.timing.queue_overwrites if packet.timing else 0)
            # No producer/camera buffer is retained by reference.
            owned=replace(packet,image_bgr=packet.image_bgr.copy())
            while True:
                try:self.input.put_nowait((owned,stamp)); break
                except queue.Full:
                    try:self.input.get_nowait()
                    except queue.Empty:pass
                    else:self.queue_overwrites+=1
            self.submitted+=1
            self._event('submitted',packet.frame_id,json.dumps(dict(
                capture_identity=packet.capture_identity,source_timestamp_s=packet.timestamp_s,
                timestamp_source=packet.timestamp_source,timing=asdict(packet.timing) if packet.timing else None,
                inference_queue_overwrites=self.queue_overwrites),ensure_ascii=False))
            return True

    def poll_result(self):
        try:return self.results.get_nowait()
        except queue.Empty:return None

    def note_preview_overwrite(self):
        with self.lock:
            if not self.stopping.is_set():
                self.preview_queue_overwrites+=1
                self._event('preview_queue_overwrite',detail=str(self.preview_queue_overwrites))

    def stop(self):
        with self.lock:
            self.stopping.set()
            while not self.input.empty():
                try:self.input.get_nowait()
                except queue.Empty:break
            while not self.results.empty():
                try:self.results.get_nowait()
                except queue.Empty:break

    def _put_result(self,value):
        with self.lock:
            if self.stopping.is_set():return
            while True:
                try:self.results.put_nowait(value);return
                except queue.Full:
                    try:self.results.get_nowait()
                    except queue.Empty:pass
                    else:self.result_overwrites+=1

    def _run(self,factory):
        try:
            self.predictor=factory(); self.ready=True; self._event('model_ready')
            while not self.stopping.is_set():
                if self.log.error:raise RuntimeError('vision journal: '+self.log.error)
                try:packet,submitted=self.input.get(timeout=.05)
                except queue.Empty:continue
                started=time.perf_counter_ns(); mask=None; parts=(); error=''; tiles=()
                image=packet.image_bgr
                roi=self.roi or (0,0,image.shape[1],image.shape[0])
                try:
                    tiles=plan_tiles(image.shape,roi)
                    full=np.zeros(image.shape[:2],np.uint8)
                    index=0
                    while index<len(tiles):
                        if self.stopping.is_set():break
                        batch=tiles[index:index+max(1,self.predictor.batch_size)]
                        predicted=self.predictor.predict_batch([extract_tile(image,tile) for tile in batch])
                        if len(predicted)!=len(batch):raise ValueError('incomplete predicted tile batch')
                        for tile,pred in zip(batch,predicted):stitch_core(full,pred,tile)
                        index+=len(batch)
                    if self.stopping.is_set():self._event('cancelled_inflight',packet.frame_id);break
                    parts=tuple(components(full)); mask=full; self.completed+=1
                except Exception as exc:
                    error=f'{type(exc).__name__}: {exc}'; self.failed+=1
                ended=time.perf_counter_ns()
                timing=packet.timing
                area=int(np.count_nonzero(mask)) if mask is not None else ''
                fraction=area/(roi[2]*roi[3]) if area!='' else 0.
                mean_luma='';diagnostic=[]
                if mask is not None:
                    x,y,w,h=roi;b,g,r,_=cv2.mean(image[y:y+h,x:x+w])
                    mean_luma=.114*b+.587*g+.299*r
                    if mean_luma<20:diagnostic.append('low_brightness_candidate')
                    if fraction>.99:diagnostic.append('near_full_foreground')
                    if area==0:diagnostic.append('empty')
                quality=';'.join(diagnostic)
                result=DetectionFrame(packet,mask,roi,parts,len(tiles),submitted,started,ended,
                    str(self.predictor.device),int(self.predictor.batch_size),error,quality)
                self.log.append('frames',dict(frame_id=packet.frame_id,sdk_frame_number=packet.capture_identity,
                    source_timestamp_s=packet.timestamp_s,source_timestamp_kind=packet.timestamp_source,
                    clock_domain=packet.timestamp_clock_domain,device_ticks_raw=timing.device_ticks_raw if timing else '',
                    receive_monotonic_ns=timing.receive_monotonic_ns if timing else '',
                    receive_perf_counter_ns=timing.receive_perf_counter_ns if timing else '',
                    submitted_perf_ns=submitted,started_perf_ns=started,completed_perf_ns=ended,
                    pipeline_ms=(ended-submitted)/1e6,processing_ms=result.processing_ms,roi=json.dumps(roi),
                    tile_count=len(tiles),backend=result.backend,batch_size=result.batch_size,components=len(parts),
                    foreground_px=area,mean_luma=mean_luma,quality_diagnostic=quality,
                    inference_queue_overwrites=self.queue_overwrites,
                    source_queue_overwrites=timing.queue_overwrites if timing else 0,
                    preview_queue_overwrites=self.preview_queue_overwrites,
                    delivered_sdk_number_gaps=self.delivered_sdk_number_gaps,sdk_capture_skips='',error=error))
                for part in parts:
                    self.log.append('components',dict(frame_id=packet.frame_id,sdk_frame_number=packet.capture_identity,**part))
                self._put_result(result)
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}'; self._event('fatal_error',detail=self.error)
        finally:
            with self.lock:
                self.ready=False; self.stopping.set()
            # Submit is sealed before flushing. Never hold the GUI stop lock
            # across the writer's potentially slow filesystem join.
            self.log.close()
            data=dict(schema='whole_chip_sensing_session_v1',control_output=False,physical_exposure_verified=False,
                calibration_bound=False,arrival_evaluated=False,roi=self.roi,tile_size=512,stride=384,halo=64,
                submitted=self.submitted,completed=self.completed,failed=self.failed,
                inference_queue_overwrites=self.queue_overwrites,result_overwrites=self.result_overwrites,
                duplicate_frames=self.duplicate_frames,delivered_sdk_number_gaps=self.delivered_sdk_number_gaps,
                sdk_capture_skips=None,source_queue_overwrites=self.source_queue_overwrites,
                preview_queue_overwrites=self.preview_queue_overwrites,
                delivered_sdk_gap_scope='includes_upstream_queue_replacement_not_independent_capture_loss',
                diagnostic_mean_luma_threshold=20,diagnostics_not_validated_quality_gate=True,
                sdk_resets=self.sdk_resets,error=self.error,log_error=self.log.error,
                model_manifest=getattr(self.predictor,'manifest',{}),backend=getattr(self.predictor,'device','unknown'))
            (self.output/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
