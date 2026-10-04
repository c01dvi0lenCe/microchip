"""Mask geometry, causal position prior, and configurable five-state rules."""
from collections import deque
from dataclasses import dataclass
import math
import cv2
import numpy as np

from dmf.vision.features import DropletFeatureExtractor
from dmf.vision.contracts import DropletState as S, VisionResult
from .config import StateConfig


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


class PriorFeatures:
    def __init__(self,electrode_map,config:StateConfig):
        self.map=electrode_map;self.config=config
        self.extractor=DropletFeatureExtractor(electrode_map)
        self.history=deque(maxlen=2);self.last_timestamp=None
        self.polygons={r.electrode_id:np.asarray([self.map.calibration.pixel_to_mm(p) for p in r.polygon_px],np.float32) for r in self.map}

    def extract(self,packet,result,source,target,candidates):
        cfg=self.config;t=packet.timestamp_s
        if not math.isfinite(t) or (self.last_timestamp is not None and t<=self.last_timestamp):
            return Observation(error='INVALID_TIMESTAMP')
        self.last_timestamp=t
        try:result.validate(packet.image_bgr.shape)
        except (ValueError,TypeError):return Observation(error='INVALID_MASK')
        if result.mask is None or not result.detected or result.confidence<cfg.min_confidence:
            return Observation(error=result.error_code or 'NO_RELIABLE_MASK')
        # Recompute geometry from the binary mask, not a stale model-side centroid.
        mask=result.mask;area=int(np.count_nonzero(mask))
        if not cfg.min_area_px<=area<=cfg.max_area_px:return Observation(error='MASK_AREA')
        count,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        if sum(int(s[cv2.CC_STAT_AREA])>=cfg.min_area_px for s in stats[1:])!=1:
            return Observation(error='AMBIGUOUS_MASK')
        moments=cv2.moments(mask,binaryImage=True)
        centroid=(moments['m10']/moments['m00'],moments['m01']/moments['m00'])
        clean=VisionResult(mask,centroid,float(area),result.confidence,result.processing_time_ms,True)
        f=self.extractor.extract(packet,clean,source,target)
        point=f.centroid_mm
        spatial=any(cv2.pointPolygonTest(self.polygons[i],point,True)>=-cfg.position_tolerance_mm for i in set(candidates)|{source,target})
        velocity=None;predicted=None;temporal=True
        if self.history and t-self.history[-1][0]>cfg.history_max_gap_s:self.history.clear()
        if self.history:
            t1,p1=self.history[-1];dt=t-t1
            displacement=math.dist(point,p1);velocity=displacement/dt;predicted=p1
            if len(self.history)==2:
                t0,p0=self.history[0]
                predicted=tuple(p1[i]+(p1[i]-p0[i])*dt/(t1-t0) for i in (0,1))
            temporal=(displacement<=cfg.max_speed_mm_s*dt+cfg.position_tolerance_mm and
                      math.dist(point,predicted)<=cfg.prediction_tolerance_mm+cfg.max_speed_mm_s*dt)
        if spatial and temporal:self.history.append((t,point))
        region=self.map[target]
        target_center=(self.map.calibration.pixel_to_mm(region.center_px) if region.geometry_source=='calibrated' else region.center_mm)
        return Observation(True,point,float(area),f.source_coverage,f.target_coverage,
            math.dist(point,target_center),velocity,predicted,spatial,temporal)


class StateRecognizer:
    def __init__(self,config:StateConfig):self.config=config;self.reset()

    def reset(self):self.pending=None;self.count=0;self.since=None

    def recognize(self,f:Observation,t):
        cfg=self.config
        if not f.valid:self.reset();return S.UNKNOWN
        if not f.spatial_ok or not f.temporal_ok:self.reset();return S.DEVIATION
        if f.eta_target>=cfg.eta_arr and f.eta_source<=cfg.eta_release:state=S.ARRIVED
        elif f.eta_target>=cfg.eta_enter and f.eta_source>cfg.eta_release:state=S.PARTIAL
        elif f.velocity is None:self.reset();return S.UNKNOWN
        elif f.velocity<cfg.v_th_mm_s:state=S.STATIONARY
        else:state=S.MOVING
        if state!=self.pending:self.pending=state;self.count=0;self.since=t
        self.count+=1
        frames=cfg.arrival_frames if state is S.ARRIVED else cfg.consistency_frames
        duration=cfg.arrival_duration_s if state is S.ARRIVED else 0
        return state if self.count>=frames and t-self.since+1e-9>=duration else S.UNKNOWN
