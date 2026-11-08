"""Cooperative sensing only: task round-robin, rolling scan, never an actuator."""
from collections import OrderedDict
from dataclasses import asdict,dataclass,replace
import hashlib
import json
import math
from pathlib import Path
import threading
import time

import numpy as np

from .region_journal import RegionJournal
from .task_regions import TaskRegion
from .whole_chip_geometry import Tile,plan_tiles,extract_tile,stitch_core,components


@dataclass(frozen=True)
class RegionObservation:
    region_id: str
    epoch: int
    kind: str
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
    source_age_ms: float
    data_valid: bool
    reason: str
    needs_relocalization: bool
    error: str = ''
    quality_diagnostic: str = ''
    source_electrode: int | None = None
    target_electrode: int | None = None
    binding_sha256: str = ''

    @property
    def processing_ms(self):return (self.completed_perf_ns-self.started_perf_ns)/1e6

    @property
    def control_eligible(self):return False

    @property
    def identity_verified(self):return False


@dataclass
class _Job:
    region: TaskRegion
    packet: object
    submitted: int
    generation: int
    tiles: tuple
    mask: object
    started: int
    index: int = 0
    inspection: bool = False
    cycle_end: bool = False


class PriorityVisionDetector:
    MAX_REGIONS=8

    def __init__(self,factory,output,regions=(),inspection_roi=None,task_period_s=.1,
                 max_task_age_s=.25,max_inspection_age_s=1.,inspection_period_s=1.,
                 clock_policy='live',save_masks=True,inspection_enabled=True):
        for value in (task_period_s,max_task_age_s,max_inspection_age_s):
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                raise ValueError('positive finite scheduling/age parameters required')
        if type(inspection_period_s) not in (int,float) or not math.isfinite(inspection_period_s) or inspection_period_s<0:
            raise ValueError('invalid inspection period')
        if clock_policy not in ('live','replay'):raise ValueError('clock_policy must be live/replay')
        self.regions=self._region_map(regions)
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=False)
        self.inspection_roi=tuple(inspection_roi) if inspection_roi is not None else None
        self.task_period_s=float(task_period_s);self.max_task_age_s=float(max_task_age_s)
        self.max_inspection_age_s=float(max_inspection_age_s);self.inspection_period_s=float(inspection_period_s)
        self.clock_policy=clock_policy;self.inspection_enabled=bool(inspection_enabled)
        self.condition=threading.Condition();self.stopping=threading.Event()
        self.journal=RegionJournal(self.output,save_masks);self.log=self.journal.csv
        self.latest=None;self.generation=0;self.last_key=None;self.last_time=None;self.last_domain=None
        self.source_floor_generation=0
        self.source_history={};self.last_shape=None
        self.results=OrderedDict();self.jobs={};self.min_generation={k:0 for k in self.regions}
        self.last_task_keys={};self.next_due={};self.round_robin=0
        self.scan_tiles=();self.scan_geometry=None;self.scan_cursor=0;self.scan_keys={}
        self.scan_next_cycle=0.;self.scan_cycle_started=None;self.scan_cycles=0
        self.sequence=0;self.completed=0;self.failed=0;self.scan_completed=0
        self.submitted=0;self.duplicate_frames=0;self.temporal_conflicts=0
        self.stale_inputs=0
        self.queue_overwrites=0;self.result_overwrites=0;self.cancelled_jobs=0
        self.preview_queue_overwrites=0;self.source_queue_overwrites=0;self.delivered_sdk_number_gaps=0
        self._last_capture=None;self._last_submit=None;self._last_claimed_generation=0;self.receive_fps=0.
        self.ready=False;self.error='';self.predictor=None
        self.worker=threading.Thread(target=self._run,args=(factory,),name='priority-vision-inference',daemon=True)
        self.worker.start()

    @classmethod
    def _region_map(cls,regions):
        values=tuple(regions)
        if len(values)>cls.MAX_REGIONS:raise ValueError(f'at most {cls.MAX_REGIONS} task regions per session')
        if any(not isinstance(r,TaskRegion) or r.region_id.startswith('__') for r in values):
            raise ValueError('TaskRegion required; reserved region IDs cannot be used')
        result={r.region_id:r for r in values}
        if len(result)!=len(values):raise ValueError('duplicate task region ID')
        return result

    def _event(self,event,region='',capture='',detail=''):
        self.log.append('events',dict(event=event,host_perf_counter_ns=time.perf_counter_ns(),
            region_id=region,capture_identity=capture,detail=detail))

    def update_regions(self,regions):
        fresh=self._region_map(regions)
        with self.condition:
            if self.stopping.is_set():return False
            for key,region in fresh.items():
                if self.regions.get(key)!=region:
                    self.min_generation[key]=self.generation+1
                    self.last_task_keys.pop(key,None);self.next_due.pop(key,None)
                    self.results.pop(key,None)
            for key in set(self.regions)-set(fresh):
                self.results.pop(key,None);self.min_generation.pop(key,None)
                self.last_task_keys.pop(key,None);self.next_due.pop(key,None)
            self.regions=fresh
            self._event('regions_changed',detail=json.dumps([asdict(r) for r in fresh.values()]))
            self.condition.notify_all()
        return True

    def submit(self,packet):
        with self.condition:
            if self.stopping.is_set() or self.journal.error:return False
            key=(packet.video_id,packet.capture_identity)
            same=self.last_key is not None and key[0]==self.last_key[0]
            history=self.source_history.get(key[0])
            if history is not None and key[1]<=history[0]:
                self.duplicate_frames+=1;self._event('duplicate_or_old_frame',capture=key[1]);return False
            stamp=packet.timestamp_s;domain=packet.timestamp_clock_domain
            old_stamp=None if history is None else history[1].get(domain)
            if not math.isfinite(stamp) or (old_stamp is not None and stamp<=old_stamp):
                self.temporal_conflicts+=1;self._event('time_conflict',capture=key[1]);return False
            if history is None and len(self.source_history)>=16:
                self._event('source_history_capacity');return False
            now=time.perf_counter_ns()
            if self._last_submit is not None:
                fps=1e9/max(1,now-self._last_submit)
                self.receive_fps=fps if not self.receive_fps else .9*self.receive_fps+.1*fps
            self._last_submit=now
            if self.latest is not None and self.generation>self._last_claimed_generation:self.queue_overwrites+=1
            capture=packet.timing.capture_frame_id if packet.timing else None
            if same and capture is not None and self._last_capture is not None:
                self.delivered_sdk_number_gaps+=max(0,capture-self._last_capture-1)
            if self.last_key is not None and (not same or domain!=self.last_domain or packet.image_bgr.shape!=self.last_shape):
                self.jobs.clear();self.results.clear();self.scan_keys.clear();self.last_task_keys.clear()
                self.source_floor_generation=self.generation+1
                self._event('source_or_clock_changed',capture=key[1])
            self.last_key=key;self.last_time=stamp;self.last_domain=domain;self._last_capture=capture
            stamps={} if history is None else dict(history[1]);stamps[domain]=stamp
            self.source_history[key[0]]=(key[1],stamps);self.last_shape=packet.image_bgr.shape
            self.source_queue_overwrites=max(self.source_queue_overwrites,packet.timing.queue_overwrites if packet.timing else 0)
            image=packet.image_bgr.copy();image.flags.writeable=False
            owned=replace(packet,image_bgr=image)
            self.generation+=1;self.latest=(owned,now,self.generation)
            self.submitted+=1;self.condition.notify_all()
            return True

    def note_preview_overwrite(self):
        with self.condition:
            if not self.stopping.is_set():self.preview_queue_overwrites+=1

    def poll_result(self):
        with self.condition:
            for key in tuple(self.results):
                if key!='__inspection__':return self.results.pop(key)
            return self.results.pop('__inspection__',None)

    def stop(self):
        with self.condition:
            self.stopping.set();self.latest=None;self.results.clear();self.condition.notify_all()

    def _job(self,region,latest,*,inspection=False,tiles=None,cycle_end=False):
        packet,submitted,generation=latest
        region.validate_packet(packet)
        self._last_claimed_generation=max(self._last_claimed_generation,generation)
        return _Job(region,packet,submitted,generation,tiles or plan_tiles(packet.image_bgr.shape,region.roi),
                    np.zeros((region.roi[3],region.roi[2]),np.uint8),time.perf_counter_ns(),
                    inspection=inspection,cycle_end=cycle_end)

    def _choose(self):
        # Called with condition held. One returned job means exactly one tile.
        if self.latest is None:return None
        packet,_,generation=self.latest;now=time.perf_counter()
        ids=tuple(self.regions)
        for offset in range(len(ids)):
            index=(self.round_robin+offset)%len(ids);key=ids[index];region=self.regions[key]
            job=self.jobs.get(key)
            if job is not None and (job.region!=region or job.generation<self.min_generation.get(key,0)):
                self.jobs.pop(key,None);self.cancelled_jobs+=1;job=None
            if job is None and (generation>=self.min_generation.get(key,0)
                and self.last_task_keys.get(key)!=self.last_key and now>=self.next_due.get(key,0.)):
                try:job=self._job(region,self.latest)
                except ValueError as exc:
                    self.last_task_keys[key]=self.last_key;self._event('invalid_region',key,packet.capture_identity,str(exc));continue
                self.jobs[key]=job;self.last_task_keys[key]=self.last_key
                self.next_due[key]=now+self.task_period_s
            if job is not None:
                self.round_robin=(index+1)%len(ids);return job
        if not self.inspection_enabled or now<self.scan_next_cycle:return None
        geometry=(packet.image_bgr.shape,self.inspection_roi)
        if geometry!=self.scan_geometry:
            self.scan_tiles=plan_tiles(packet.image_bgr.shape,self.inspection_roi)
            self.scan_geometry=geometry;self.scan_cursor=0;self.scan_keys.clear()
        for _ in self.scan_tiles:
            index=self.scan_cursor;tile=self.scan_tiles[index]
            self.scan_cursor=(index+1)%len(self.scan_tiles)
            if self.scan_keys.get(index)==self.last_key:continue
            self.scan_keys[index]=self.last_key
            if self.scan_cycle_started is None:self.scan_cycle_started=now
            region=TaskRegion('__inspection__',(tile.core_x,tile.core_y,tile.core_w,tile.core_h),self.scan_cycles)
            return self._job(region,self.latest,inspection=True,tiles=(tile,),cycle_end=self.scan_cursor==0)
        return None

    def _age(self,job,ended):
        age=(ended-job.submitted)/1e9
        timing=job.packet.timing
        if self.clock_policy=='live':
            if timing is None or timing.receive_monotonic_ns is None or timing.clock_domain!='host_monotonic':
                return age,'host_receive_clock_unverified'
            receive_age=(time.monotonic_ns()-timing.receive_monotonic_ns)/1e9
            if receive_age<0:return age,'host_receive_time_in_future'
            age=max(age,receive_age)
        return age,''

    def _finish(self,job,error=''):
        mask=None if error else job.mask
        parts=()
        if mask is not None:
            x,y,_,_=job.region.roi
            parts=tuple(dict(p,centroid_px=(p['centroid_px'][0]+x,p['centroid_px'][1]+y),
                bbox_xywh=(p['bbox_xywh'][0]+x,p['bbox_xywh'][1]+y,*p['bbox_xywh'][2:])) for p in components(mask))
        quality=[]
        if mask is not None:
            if not np.any(mask):quality.append('empty_mask')
            elif np.count_nonzero(mask)>.99*mask.size:quality.append('near_full_foreground')
            if len(parts)>1:quality.append('multiple_unassociated_components')
            if np.any(mask[0]) or np.any(mask[-1]) or np.any(mask[:,0]) or np.any(mask[:,-1]):quality.append('foreground_at_region_edge')
        ended=time.perf_counter_ns()
        age,clock_reason=self._age(job,ended)
        limit=self.max_inspection_age_s if job.inspection else self.max_task_age_s
        reasons=([error] if error else [])+([clock_reason] if clock_reason else [])+(['stale'] if age>limit else [])
        valid=not reasons
        result=RegionObservation(job.region.region_id,job.region.epoch,
            'rolling_inspection' if job.inspection else job.region.kind,job.packet,mask,job.region.roi,parts,
            len(job.tiles),job.submitted,job.started,ended,str(self.predictor.device),1,age*1000,
            valid,';'.join(reasons) or 'fresh_complete_region',
            (not job.inspection) and (not valid or len(parts)!=1 or bool(quality)),error,';'.join(quality),
            job.region.source_electrode,job.region.target_electrode,job.region.binding_sha256)
        with self.condition:
            if self.stopping.is_set():return
            current=self.regions.get(job.region.region_id)
            same_source=self.latest is not None and (job.packet.video_id,job.packet.timestamp_clock_domain)==(
                self.latest[0].video_id,self.latest[0].timestamp_clock_domain)
            invalid_generation=job.generation<max(self.source_floor_generation,
                0 if job.inspection else self.min_generation.get(job.region.region_id,0))
            if (not job.inspection and current!=job.region) or not same_source or invalid_generation:
                self.cancelled_jobs+=1;self._event('cancelled_epoch_or_source',job.region.region_id,job.packet.capture_identity);return
            self.sequence+=1;sequence=self.sequence
            if error:self.failed+=1
            elif job.inspection:self.scan_completed+=1
            else:self.completed+=1
            if job.region.region_id in self.results:self.result_overwrites+=1
            self.results[job.region.region_id]=result
        relative=self.journal.mask(f'masks/{job.region.region_id}/{sequence:08d}.png',mask) if mask is not None else ''
        row=dict(sequence=sequence,region_id=result.region_id,epoch=result.epoch,kind=result.kind,
            source_electrode=result.source_electrode,target_electrode=result.target_electrode,binding_sha256=result.binding_sha256,
            video_id=job.packet.video_id,frame_id=job.packet.frame_id,capture_identity=job.packet.capture_identity,
            source_timestamp_s=job.packet.timestamp_s,clock_domain=job.packet.timestamp_clock_domain,
            timing_json=json.dumps(asdict(job.packet.timing) if job.packet.timing else None),
            roi=json.dumps(result.roi),source_shape=json.dumps(job.packet.image_bgr.shape),tile_count=result.tile_count,
            backend=result.backend,batch_size=1,submitted_perf_ns=result.submitted_perf_ns,started_perf_ns=result.started_perf_ns,
            completed_perf_ns=result.completed_perf_ns,processing_ms=result.processing_ms,pipeline_ms=(ended-job.submitted)/1e6,
            source_age_ms=result.source_age_ms,data_valid=result.data_valid,reason=result.reason,identity_verified=False,
            control_eligible=False,needs_relocalization=result.needs_relocalization,quality_diagnostic=result.quality_diagnostic,
            components=json.dumps(parts),foreground_px=int(np.count_nonzero(mask)) if mask is not None else '',
            mask_path=relative,mask_pixels_sha256=hashlib.sha256(mask.tobytes()).hexdigest() if mask is not None else '',error=error)
        self.log.append('regions',row)
        if job.inspection and job.cycle_end:
            with self.condition:
                self.scan_cycles+=1;self.scan_next_cycle=time.perf_counter()+self.inspection_period_s
                duration=time.perf_counter()-(self.scan_cycle_started or time.perf_counter());self.scan_cycle_started=None
            self._event('scan_cycle_attempt_finished',detail=json.dumps(dict(duration_s=duration,cycle=self.scan_cycles)))

    def _run(self,factory):
        try:
            self.predictor=factory();self.ready=True;self._event('model_ready')
            while not self.stopping.is_set():
                if self.journal.error:raise RuntimeError(self.journal.error)
                with self.condition:
                    job=self._choose()
                    if job is None:self.condition.wait(.01);continue
                tile=job.tiles[job.index]
                error=''
                age,_=self._age(job,time.perf_counter_ns())
                limit=self.max_inspection_age_s if job.inspection else self.max_task_age_s
                if age>limit:
                    self.stale_inputs+=1;error='stale_input'
                    self._event('stale_input',job.region.region_id,job.packet.capture_identity)
                else:
                    self._event('tile_started',job.region.region_id,job.packet.capture_identity,
                                json.dumps(dict(core=[tile.core_x,tile.core_y,tile.core_w,tile.core_h])))
                    try:
                        predicted=self.predictor.predict_batch([extract_tile(job.packet.image_bgr,tile)])
                        if len(predicted)!=1:raise ValueError('one tile output required')
                        x,y,_,_=job.region.roi
                        local=Tile(tile.core_x-x,tile.core_y-y,tile.core_w,tile.core_h)
                        stitch_core(job.mask,predicted[0],local);job.index+=1
                    except Exception as exc:error=f'{type(exc).__name__}: {exc}'
                if error or job.index==len(job.tiles):
                    if not job.inspection:
                        with self.condition:
                            if self.jobs.get(job.region.region_id) is job:self.jobs.pop(job.region.region_id,None)
                    self._finish(job,error)
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}';self._event('fatal_error',detail=self.error)
        finally:
            with self.condition:self.ready=False;self.stopping.set();self.latest=None;self.jobs.clear()
            self.journal.close()
            if self.journal.error:self.error=self.error or self.journal.error
            manifest=dict(schema='dmf_priority_sensing_session_v1',control_output=False,arrival_evaluated=False,
                identity_verified=False,physical_exposure_verified=False,rolling_regions_not_one_frame=True,
                task_period_s=self.task_period_s,max_task_age_s=self.max_task_age_s,
                max_inspection_age_s=self.max_inspection_age_s,clock_policy=self.clock_policy,
                regions=[asdict(r) for r in self.regions.values()],inspection_roi=self.inspection_roi,
                submitted=self.submitted,task_completed=self.completed,scan_completed=self.scan_completed,
                scan_cycles_attempted=self.scan_cycles,failed=self.failed,cancelled_jobs=self.cancelled_jobs,
                input_overwrites_before_any_inference=self.queue_overwrites,result_overwrites=self.result_overwrites,
                duplicate_frames=self.duplicate_frames,temporal_conflicts=self.temporal_conflicts,
                stale_inputs=self.stale_inputs,
                preview_queue_overwrites=self.preview_queue_overwrites,source_queue_overwrites=self.source_queue_overwrites,
                delivered_sdk_number_gaps=self.delivered_sdk_number_gaps,sdk_capture_skips=None,
                error=self.error,log_error=self.journal.error,model_manifest=getattr(self.predictor,'manifest',{}))
            try:(self.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
            except OSError as exc:self.error=self.error or f'manifest write failed: {exc}'
