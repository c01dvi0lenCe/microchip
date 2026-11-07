"""Mask geometry, causal position prior, and configurable five-state rules."""
from collections import deque
from dataclasses import dataclass
import math
import cv2
import numpy as np

from dmf.vision.features import DropletFeatureExtractor, transport_projection
from dmf.vision.contracts import DropletState as S, VisionResult
from .config import StateConfig
from .evidence import EvidenceWindow


@dataclass(frozen=True)
class Observation:
    valid: bool = False
    centroid: tuple | None = None
    area: float | None = None
    eta_source: float | None = None
    eta_target: float | None = None
    distance: float | None = None
    velocity: float | None = None
    predicted_position: tuple | None = None
    spatial_ok: bool = False
    temporal_ok: bool = False
    error: str = ''
    rho_target: float | None = None
    source_intersection_px: int | None = None
    target_intersection_px: int | None = None
    progress_mm: float | None = None
    progress_fraction: float | None = None
    lateral_error_mm: float | None = None
    velocity_parallel_mm_s: float | None = None
    target_position_ok: bool | None = None
    geometry_quality: str = ''

    @property
    def observation_quality(self):
        if not self.valid:return 'invalid'
        return 'reliable' if self.spatial_ok and self.temporal_ok else 'conflict'


class PriorFeatures:
    def __init__(self,electrode_map,config:StateConfig,*,spatial_prior=True,temporal_prior=True,quality_checks=True):
        self.map=electrode_map;self.config=config
        # Explicit research ablations only; normal experiment defaults are unchanged.
        self.spatial_prior=spatial_prior;self.temporal_prior=temporal_prior;self.quality_checks=quality_checks
        self.extractor=DropletFeatureExtractor(electrode_map)
        self.history=deque(maxlen=2);self.last_timestamp=None;self.last_frame_id=None;self.video_id=None
        self.identity_source=None;self.frame_high_water={}
        self.clock_domain=None
        self.polygons={r.electrode_id:np.asarray([self.map.calibration.pixel_to_mm(p) for p in r.polygon_px],np.float32) for r in self.map}

    def reset(self):
        # Command epochs invalidate kinematics, not global identity/time marks.
        self.history.clear()
        self.extractor.reset()

    def extract(self,packet,result,source,target,candidates):
        cfg=self.config;t=packet.timestamp_s
        clock=(packet.video_id,packet.timestamp_clock_domain)
        if self.clock_domain is not None and self.clock_domain!=clock:
            self.reset();self.last_timestamp=None
        self.clock_domain=clock
        if not math.isfinite(t) or (self.last_timestamp is not None and t<=self.last_timestamp):
            return Observation(error='INVALID_TIMESTAMP')
        identity_source='sdk' if packet.timing and packet.timing.capture_frame_id is not None else 'consumer'
        key=(packet.video_id,identity_source)
        if packet.capture_identity<=self.frame_high_water.get(key,-1):
            return Observation(error='DUPLICATE_OR_REVERSED_FRAME')
        if self.identity_source is not None and identity_source!=self.identity_source:self.reset()
        self.identity_source=identity_source;self.frame_high_water[key]=packet.capture_identity
        self.video_id,self.last_frame_id=packet.video_id,packet.capture_identity
        self.last_timestamp=t
        try:result.validate(packet.image_bgr.shape)
        except (ValueError,TypeError):return Observation(error='INVALID_MASK')
        if result.mask is None or not result.detected or (self.quality_checks and result.confidence<cfg.min_confidence):
            return Observation(error=result.error_code or 'NO_RELIABLE_MASK')
        # Recompute geometry from the binary mask, not a stale model-side centroid.
        mask=result.mask;area=int(np.count_nonzero(mask))
        if not area or (self.quality_checks and not cfg.min_area_px<=area<=cfg.max_area_px):return Observation(error='MASK_AREA')
        count,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        if self.quality_checks and sum(int(s[cv2.CC_STAT_AREA])>=cfg.min_area_px for s in stats[1:])!=1:
            return Observation(error='AMBIGUOUS_MASK')
        moments=cv2.moments(mask,binaryImage=True)
        centroid=(moments['m10']/moments['m00'],moments['m01']/moments['m00'])
        clean=VisionResult(mask,centroid,float(area),result.confidence,result.processing_time_ms,True)
        f=self.extractor.extract(packet,clean,source,target)
        point=f.centroid_mm
        spatial=not self.spatial_prior or any(cv2.pointPolygonTest(self.polygons[i],point,True)>=-cfg.position_tolerance_mm for i in set(candidates)|{source,target})
        velocity=None;parallel=None;predicted=None;temporal=True
        if self.history and t-self.history[-1][0]>cfg.history_max_gap_s:self.history.clear()
        if self.temporal_prior and self.history:
            t1,p1=self.history[-1];dt=t-t1
            displacement=math.dist(point,p1);velocity=displacement/dt;predicted=p1
            previous=transport_projection(p1,self.map[source].center_mm,self.map[target].center_mm)
            parallel=(f.progress_mm-previous.progress_mm)/dt
            if len(self.history)==2:
                t0,p0=self.history[0]
                predicted=tuple(p1[i]+(p1[i]-p0[i])*dt/(t1-t0) for i in (0,1))
            temporal=not self.quality_checks or (displacement<=cfg.max_speed_mm_s*dt+cfg.position_tolerance_mm and
                      math.dist(point,predicted)<=cfg.prediction_tolerance_mm+cfg.max_speed_mm_s*dt)
        if self.temporal_prior and spatial and temporal:self.history.append((t,point))
        return Observation(True,point,float(area),f.source_coverage,f.target_coverage,
            f.distance_to_target_mm,velocity,predicted,spatial,temporal,
            rho_target=f.target_electrode_coverage,source_intersection_px=f.source_intersection_px,
            target_intersection_px=f.target_intersection_px,progress_mm=f.progress_mm,
            progress_fraction=f.progress_fraction,lateral_error_mm=f.lateral_error_mm,
            velocity_parallel_mm_s=parallel,
            target_position_ok=not self.spatial_prior or cv2.pointPolygonTest(self.polygons[target],point,True)>=-cfg.position_tolerance_mm,
            geometry_quality=f.geometry_quality)


class StateRecognizer:
    def __init__(self,config:StateConfig):self.config=config;self.reset()

    def reset(self):
        self.pending=None;self.count=0;self.since=None;self.window=None
        self.clock=EvidenceWindow(1,0.,self.config.evidence_max_gap_s)
        self.last_quality='invalid';self.last_reason='RESET'

    def recognize(self,f:Observation,t,frame_id=None,context=None):
        cfg=self.config
        self.last_quality=f.observation_quality
        if not self.clock.observe(context,frame_id,t,True):
            self.pending=None;self.window=None;self.count=0
            self.last_quality='conflict';self.last_reason=self.clock.last_reason
            return S.UNKNOWN
        if not f.valid or not f.temporal_ok:
            self.pending=None;self.window=None;self.count=0
            self.last_reason=f.error or ('INVALID_OBSERVATION' if not f.valid else 'TEMPORAL_CONFLICT')
            return S.UNKNOWN
        if not f.spatial_ok:state=S.DEVIATION
        elif any(value is None or not math.isfinite(value) for value in (f.eta_target,f.eta_source)):
            self.pending=None;self.window=None;self.count=0
            self.last_quality='invalid';self.last_reason='INVALID_COVERAGE'
            return S.UNKNOWN
        elif f.eta_target>=cfg.eta_arr and f.eta_source<=cfg.eta_release and f.target_position_ok is not False:state=S.ARRIVED
        elif f.eta_target>=cfg.eta_enter and f.eta_source>cfg.eta_release:state=S.PARTIAL
        elif f.velocity is None:
            self.pending=None;self.window=None;self.count=0;self.last_reason='INSUFFICIENT_VELOCITY'
            return S.UNKNOWN
        elif f.velocity<cfg.v_th_mm_s:state=S.STATIONARY
        else:state=S.MOVING
        frames=(cfg.arrival_frames if state is S.ARRIVED else cfg.deviation_frames if state is S.DEVIATION
                else cfg.consistency_frames)
        duration=cfg.arrival_duration_s if state is S.ARRIVED else 0
        if state!=self.pending or self.window is None:
            self.pending=state;self.since=t
            self.window=EvidenceWindow(frames,duration,cfg.evidence_max_gap_s,
                cfg.arrival_max_centroid_span_mm if state is S.ARRIVED else None,
                cfg.arrival_max_coverage_span if state is S.ARRIVED else None)
        confirmed=self.window.observe((context,state.value),frame_id,t,True,f.centroid,f.eta_target)
        self.count=self.window.count
        self.last_reason=('CONFIRMED_SPATIAL_DEVIATION' if state is S.DEVIATION and confirmed else
                          'SPATIAL_CONFLICT_PENDING' if state is S.DEVIATION else
                          'TARGET_POSITION_NOT_MET' if f.target_position_ok is False and f.eta_target>=cfg.eta_arr
                          else self.window.last_reason)
        return state if confirmed else S.UNKNOWN
