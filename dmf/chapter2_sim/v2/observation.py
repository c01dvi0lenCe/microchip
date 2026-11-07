"""Algorithm-visible observations only. No imports from world or scoring."""
from collections import deque
from dataclasses import dataclass
import math

import cv2
import numpy as np

from dmf.vision.contracts import VisionResult
from dmf.vision.features import DropletFeatureExtractor, transport_projection
from dmf.experiment.perception import Observation


@dataclass(frozen=True)
class ObservedFrame:
    frame_id: int
    exposure_start_s: float
    exposure_end_s: float
    available_s: float
    mask: np.ndarray | None
    dropped: bool=False
    confidence: float=1.
    stream_id: str | None=None
    task_epoch: int | None=None
    clock_domain: str='simulation'


def validate_syntax(frame,shape):
    mask=frame.mask
    if mask is None:return False,'NO_MASK'
    if not isinstance(mask,np.ndarray) or mask.dtype!=np.uint8 or mask.ndim!=2 or mask.shape!=tuple(shape):return False,'INVALID_MASK_SHAPE_OR_TYPE'
    if not np.isin(mask,(0,255)).all():return False,'NON_BINARY_MASK'
    if not np.count_nonzero(mask):return False,'EMPTY_MASK'
    confidence=getattr(frame,'confidence',1.)
    if type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:return False,'INVALID_CONFIDENCE_METADATA'
    return True,''


class ObservationPipeline:
    """Raw S/K/Q evaluated once from C0-valid frames, before any switches.

    K history deliberately samples every parsable C0-valid frame, including
    low-Q and spatial-conflict frames. This v2 research rule is explicit and
    different from v1's gate-filtered history. Switches cannot change history.
    """
    def __init__(self,electrode_map,state_cfg,target,quality):
        self.map,self.cfg,self.target,self.quality=electrode_map,state_cfg,target,quality
        self.extractor=DropletFeatureExtractor(electrode_map)
        self.polygons={r.electrode_id:np.asarray(r.polygon_mm,np.float32) for r in electrode_map}
        self.history=deque(maxlen=2);self.last_time=None;self.last_frame=None;self.context=None

    def reset(self):
        self.history.clear();self.extractor.reset();self.context=None

    def extract(self,packet,frame,context):
        t=packet.timestamp_s;identity=packet.capture_identity
        if self.last_time is not None and t<=self.last_time:return None,{},['non_monotone_timestamp']
        reasons=[]
        if context!=self.context:reasons.append('context_change')
        if self.history and t-self.history[-1][0]>self.target.window.max_gap_s+1e-9:reasons.append('long_gap')
        if self.last_frame is not None and identity!=self.last_frame+1:reasons.append('missing_id')
        if reasons:self.history.clear();self.extractor.reset()
        self.context=context;self.last_time=t;self.last_frame=identity
        mask=frame.mask;area=int(np.count_nonzero(mask));mom=cv2.moments(mask,binaryImage=True)
        pixel=(mom['m10']/mom['m00'],mom['m01']/mom['m00'])
        confidence=float(getattr(frame,'confidence',1.))
        result=VisionResult(mask,pixel,float(area),confidence,0.,True)
        f=self.extractor.extract(packet,result,context.source_id,context.target_id)
        point=f.centroid_mm;cfg=self.cfg;q=self.quality
        spatial_area=any(cv2.pointPolygonTest(self.polygons[i],point,True)>=-self.target.position_tolerance_pitch for i in (context.source_id,context.target_id))
        target_position=cv2.pointPolygonTest(self.polygons[context.target_id],point,True)>=-self.target.position_tolerance_pitch
        count,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        components=sum(int(s[cv2.CC_STAT_AREA])>=q.min_area_px for s in stats[1:])
        quality=confidence>=q.min_confidence and q.min_area_px<=area<=q.max_area_px and components==1
        temporal=True;predicted=None;velocity=None;parallel=None;displacement=residual=None
        if self.history:
            t1,p1=self.history[-1];dt=t-t1
            displacement=math.dist(point,p1);velocity=displacement/dt;predicted=p1
            previous=transport_projection(p1,self.map[context.source_id].center_mm,self.map[context.target_id].center_mm)
            parallel=(f.progress_mm-previous.progress_mm)/dt
            if len(self.history)==2:
                t0,p0=self.history[0];predicted=tuple(p1[j]+(p1[j]-p0[j])*dt/(t1-t0) for j in (0,1))
            residual=math.dist(point,predicted)
            temporal=(displacement<=cfg.max_speed_mm_s*dt+cfg.position_tolerance_mm and residual<=cfg.prediction_tolerance_mm+cfg.max_speed_mm_s*dt)
        self.history.append((t,point))
        raw=dict(S=bool(spatial_area and target_position),S_area=bool(spatial_area),S_position=bool(target_position),K=bool(temporal),Q=bool(quality),
            confidence=confidence,area_px=area,significant_components=components,centroid=tuple(point),eta_source=f.source_coverage,eta_target=f.target_coverage,
            rho_target=f.target_electrode_coverage,distance_pitch=f.distance_to_target_mm,progress_pitch=f.progress_mm,progress_fraction=f.progress_fraction,
            lateral_pitch=f.lateral_error_mm,velocity_pitch_s=velocity,velocity_parallel_pitch_s=parallel,prediction_residual_pitch=residual,
            history_sampling='C0_parsable_not_gate_filtered')
        observation=Observation(valid=True,centroid=point,area=float(area),eta_source=f.source_coverage,eta_target=f.target_coverage,
            distance=f.distance_to_target_mm,velocity=velocity,predicted_position=predicted,spatial_ok=bool(spatial_area),temporal_ok=bool(temporal),
            rho_target=f.target_electrode_coverage,source_intersection_px=f.source_intersection_px,target_intersection_px=f.target_intersection_px,
            progress_mm=f.progress_mm,progress_fraction=f.progress_fraction,lateral_error_mm=f.lateral_error_mm,velocity_parallel_mm_s=parallel,
            target_position_ok=bool(target_position),geometry_quality=f.geometry_quality)
        return observation,raw,reasons
