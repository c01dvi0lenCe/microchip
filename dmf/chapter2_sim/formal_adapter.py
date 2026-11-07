"""Versioned pitch/simulation adapter over the unchanged formal experiment rules.

The shared algorithm's ``*_mm`` attributes are numeric compatibility aliases for
pitch (or pitch/s) here, never measurements or an asserted physical calibration.
Only explicitly pitch-labelled values may leave this simulation boundary.
"""
from dataclasses import dataclass, field, replace
import math

import cv2
import numpy as np

from dmf.experiment.config import StateConfig, ControlConfig
from dmf.experiment.evidence import (StepContext, ArrivalEvent, ArrivalEventLedger,
                                     FrameCausalityGuard, EvidenceWindow)
from dmf.experiment.perception import PriorFeatures, StateRecognizer, Observation
from dmf.experiment.policy import EventController, Decision
from dmf.vision.contracts import FramePacket, FrameTiming, VisionResult, DropletState as S
from dmf.vision.electrode_map import ElectrodeRegion, polygon_centroid, validated_polygon

METHOD_VERSIONS = {'A':'A_fixed_v1','B':'B_single_eta_v1','C':'C_formal_b1b4_v1'}
ABLATIONS = ('full','no_spatial','no_temporal','no_validity')


class _PitchCoordinates:
    """Legacy pixel_to_mm interface, explicitly returning normalized pitches."""
    coordinate_unit = 'pitch'
    physical_calibration_verified = False

    def __init__(self, lower, scale): self.lower,self.scale=lower,scale

    def pixel_to_mm(self, point):
        return tuple(np.asarray(point,dtype=float)/self.scale+self.lower)


class NormalizedMap:
    def __init__(self, geometry):
        self._initialize(geometry.polygons,geometry.lower,geometry.scale,geometry.shape,
                         geometry.metadata,getattr(geometry,'sources',{}))

    @classmethod
    def from_snapshot(cls, snapshot):
        if snapshot.get('metadata',{}).get('coordinate_unit')!='pitch':
            raise ValueError('normalized snapshot must explicitly declare pitch units')
        value=cls.__new__(cls)
        value._initialize(snapshot['polygons'],snapshot['lower'],snapshot['scale'],snapshot['shape'],
                          snapshot['metadata'],snapshot.get('sources',{}))
        return value

    def _initialize(self, polygons, lower, scale, shape, metadata, sources):
        self.lower=np.asarray(lower,dtype=float);self.scale=float(scale);self.shape=tuple(shape)
        if (self.lower.shape!=(2,) or not np.isfinite(self.lower).all() or
                not math.isfinite(self.scale) or self.scale<=0 or len(self.shape)!=2 or
                any(type(v) not in (int,np.int64,np.int32) or v<=0 for v in self.shape)):
            raise ValueError('invalid normalized raster transform')
        self.calibration=_PitchCoordinates(self.lower,self.scale)
        self.metadata=dict(metadata,coordinate_unit='pitch',clock_domain='simulation',
                           physical_calibration_verified=False,
                           legacy_numeric_aliases='*_mm=pitch; *_mm_s=pitch/s; no physical mm calibration')
        self._regions={}
        for key, points in polygons.items():
            identity=int(key);world=validated_polygon(points)
            if not 1<=identity<=420 or identity in self._regions:raise ValueError('invalid or duplicate electrode ID')
            pixel=tuple(map(tuple,(np.asarray(world)-self.lower)*self.scale))
            row,col=divmod(identity-1,20)
            self._regions[identity]=ElectrodeRegion(identity,row,col,'normalized_simulation',
                polygon_centroid(pixel),pixel,polygon_centroid(world),world,
                sources.get(identity,sources.get(str(identity),'simulation_snapshot')))
        if not self._regions:raise ValueError('normalized map requires at least one region')
        self.metadata['electrode_count']=len(self._regions)

    def __iter__(self): return iter(self._regions.values())
    def __getitem__(self, identity): return self._regions[identity]
    def __len__(self): return len(self._regions)
    def validate_frame_shape(self, shape):
        if tuple(shape[:2])!=self.shape:raise ValueError('simulation raster shape mismatch')


@dataclass(frozen=True)
class SimulationFrameTiming(FrameTiming):
    exposure_start_s: float | None = None
    exposure_end_s: float | None = None
    available_s: float | None = None


def make_frame_packet(frame, *, video_id='simulation', task_epoch=None, shape=None):
    if shape is None:
        if frame.mask is None:raise ValueError('shape is required for missing-mask frames')
        shape=frame.mask.shape
    image=np.zeros(tuple(shape[:2])+(3,),np.uint8)
    timing=SimulationFrameTiming(capture_frame_id=frame.frame_id,clock_domain='simulation',
        timing_quality='simulation_exposure',exposure_clock_domain='simulation',task_epoch=task_epoch,
        exposure_start_s=frame.exposure_start_s,exposure_end_s=frame.exposure_end_s,available_s=frame.available_s)
    return FramePacket(video_id,frame.frame_id,frame.exposure_end_s,'simulation_exposure',image,timing)


def state_config(cfg):
    """Map frozen normalized parameters onto legacy numeric field names."""
    return StateConfig(v_th_mm_s=cfg.stationary_speed,eta_arr=cfg.arrival_coverage,
        eta_release=cfg.source_release,position_tolerance_mm=cfg.position_tolerance,
        max_speed_mm_s=cfg.speed*4,prediction_tolerance_mm=cfg.position_tolerance,
        history_max_gap_s=cfg.max_frame_gap_s,arrival_frames=cfg.arrival_frames,
        arrival_duration_s=cfg.stable_duration_s,evidence_max_gap_s=cfg.max_frame_gap_s,
        arrival_max_centroid_span_mm=cfg.stable_span,deviation_frames=cfg.deviation_frames)


def control_config(cfg):
    return ControlConfig(wait_s=cfg.no_progress_s,max_retries=cfg.max_retries,
        recovery_timeout_s=cfg.recovery_timeout_s,max_recoveries=cfg.max_recoveries,
        no_detection_timeout_s=cfg.observation_timeout_s,source_timeout_s=cfg.recovery_timeout_s,
        source_frames=cfg.arrival_frames,source_duration_s=cfg.stable_duration_s,
        attempt_timeout_s=cfg.attempt_timeout_s,progress_epsilon_mm=cfg.progress_epsilon)


@dataclass(frozen=True)
class FormalDecision(Decision):
    """Adapter-issued application capability; copies preserve origin and token."""
    origin_context: StepContext | None = None
    request_token: int = 0
    arrival_event_id: str | None = None
    issuer: object | None = field(default=None,repr=False)


@dataclass(frozen=True)
class FormalObservation:
    packet: FramePacket
    observation: Observation
    state: S
    decision: Decision
    arrival_event: ArrivalEvent | None = None
    causality: str = 'simulation_exposure_verified'


class FormalAdapter:
    def __init__(self,cfg,geometry,method='C',ablation='full',run_id='simulation'):
        if method not in METHOD_VERSIONS or ablation not in ABLATIONS:raise ValueError('unknown formal method/ablation')
        self.cfg,self.method,self.ablation,self.run_id=cfg,method,ablation,run_id
        self.method_version=METHOD_VERSIONS[method]
        self.map=geometry if isinstance(geometry,NormalizedMap) else NormalizedMap(geometry)
        self.state_cfg=state_config(cfg);self.control_cfg=control_config(cfg)
        if ablation=='no_temporal':self.state_cfg=replace(self.state_cfg,arrival_frames=1,arrival_duration_s=0.)
        self.features=PriorFeatures(self.map,self.state_cfg,spatial_prior=ablation!='no_spatial',
            temporal_prior=ablation!='no_temporal',quality_checks=ablation!='no_validity')
        self.recognizer=StateRecognizer(self.state_cfg)
        self.controller=EventController(cfg.route,self.control_cfg)
        self.guard=FrameCausalityGuard();self.ledger=ArrivalEventLedger()
        self.source_window=EvidenceWindow(self.control_cfg.source_frames,self.control_cfg.source_duration_s,
            self.state_cfg.evidence_max_gap_s,self.state_cfg.arrival_max_centroid_span_mm,
            self.state_cfg.arrival_max_coverage_span)
        self.epoch=0;self.attempt=0;self.last_now=0.
        self._issuer=object();self._next_token=0;self._issued={};self.pending_arrival=None
        self.context=self._context(None);self.ledger.activate(self.context)
        self.metadata=dict(coordinate_unit='pitch',clock_domain='simulation',method_version=self.method_version,
            base_method=method,ablation=ablation,physical_timing_validated=False,
            acceptance_contract='adapter-issued context/token; arrival consumed only on accepted Update/Complete',
            legacy_numeric_aliases=self.map.metadata['legacy_numeric_aliases'])

    @property
    def source(self):return self.controller.source
    @property
    def target(self):return self.controller.target
    @property
    def phase(self):return self.controller.phase

    def _context(self,applied_s):
        return StepContext(self.run_id,self.controller.index,self.attempt,self.epoch,self.source,self.target,
            clock_domain='simulation',phase=self.phase,applied_timestamp_s=applied_s,
            applied_time_quality='simulation_applied' if applied_s is not None else 'simulation_initial')

    def _time(self,now):
        if not math.isfinite(now) or now<self.last_now-1e-9:raise ValueError('simulation decision clock moved backwards')
        self.last_now=max(self.last_now,now)
        return self.last_now

    def _decision(self,state,now,observation=None,source_confirmed=False):
        if self.phase=='transport' and self.method=='A':
            if now-self.controller.attempt_started>=self.cfg.fixed_interval_s:
                decision=Decision('Complete',reason='fixed interval') if self.controller.index+2==len(self.cfg.route) else Decision('Update',self.cfg.route[self.controller.index+2],'fixed interval')
                return self._issue(decision)
            state=S.UNKNOWN
        return self._issue(self.controller.decide(state,now,source_confirmed,observation=observation))

    def _issue(self,decision):
        if decision.action=='Hold':return decision
        self._next_token+=1
        event_id=(self.pending_arrival.event_id if self.pending_arrival is not None and
                  decision.action in ('Update','Complete') else None)
        issued=FormalDecision(decision.action,decision.target,decision.reason,self.context,
                              self._next_token,event_id,self._issuer)
        self._issued[issued.request_token]=issued
        return issued

    def observe(self,frame,now_s):
        now_s=self._time(now_s)
        packet=make_frame_packet(frame,video_id=self.run_id,shape=self.map.shape)
        assessment=self.guard.check(packet,self.context,mode='simulation')
        if frame.available_s>now_s+1e-9:raise ValueError('frame not available at decision time')
        if not assessment.accepted or now_s-packet.timestamp_s>self.cfg.observation_timeout_s:
            # Identity/causality failures cannot donate evidence to any window.
            self.recognizer.reset();self.source_window.reset()
            observation=Observation(error=assessment.reason or 'STALE_FRAME')
            return FormalObservation(packet,observation,S.UNKNOWN,self._decision(S.UNKNOWN,now_s,observation),causality=assessment.causality)
        mask=frame.mask;detected=mask is not None and bool(np.count_nonzero(mask))
        result=VisionResult(mask,(0.,0.) if detected else None,None,1.,0.,detected,'NO_MASK' if not detected else '')
        observation=self.features.extract(packet,result,self.source,self.target,[])
        state=self.recognizer.recognize(observation,packet.timestamp_s,packet.capture_identity,self.context)
        source_confirmed=False
        if self.phase in ('confirm_source','recovering'):
            position_ok=observation.centroid is not None and cv2.pointPolygonTest(
                self.features.polygons[self.source],observation.centroid,True)>=-self.state_cfg.position_tolerance_mm
            eligible=observation.observation_quality=='reliable' and observation.eta_source>=self.state_cfg.eta_arr and position_ok
            source_confirmed=self.source_window.observe(self.context,packet.capture_identity,packet.timestamp_s,
                eligible,observation.centroid,observation.eta_source)
        arrival=None
        if self.phase=='transport' and self.method=='C' and state is S.ARRIVED:
            if self.pending_arrival is None:
                self.pending_arrival=ArrivalEvent.from_window(self.context,self.recognizer.window,None,'simulation',assessment.causality)
                arrival=self.pending_arrival
        policy_state=state
        if self.phase=='transport' and self.method=='B':
            policy_state=S.ARRIVED if (observation.valid and observation.eta_target>=self.state_cfg.eta_arr and
                observation.eta_source<=self.state_cfg.eta_release) else S.UNKNOWN
        if self.method=='C' and state is S.ARRIVED and self.pending_arrival is None:policy_state=S.UNKNOWN
        decision=self._decision(policy_state,now_s,observation,source_confirmed)
        return FormalObservation(packet,observation,state,decision,arrival,assessment.causality)

    def tick(self,now_s):
        now_s=self._time(now_s)
        return self._decision(S.UNKNOWN,now_s,Observation(error='NO_FRESH_FRAME'))

    def accept(self,decision,applied_s,accepted=True):
        """Accept only an unchanged, unused adapter-issued request for this epoch.

        A rejected application leaves its confirmed arrival pending/retryable.
        No real hardware acknowledgement or host timestamp is implied.
        """
        if not accepted:return False
        if (not isinstance(decision,FormalDecision) or decision.issuer is not self._issuer or
                decision.origin_context!=self.context or
                self._issued.get(decision.request_token)!=decision or
                self.controller.complete or self.phase=='stopped'):
            return False
        applied_s=self._time(applied_s)
        if self.method=='C' and decision.action in ('Update','Complete'):
            if (self.pending_arrival is None or decision.arrival_event_id!=self.pending_arrival.event_id or
                    not self.ledger.consume(self.pending_arrival)):
                return False
        self._issued.clear()
        self.controller.accept(decision,applied_s)
        if decision.action in ('Start','Update','Retry','Recovery'):
            if decision.action in ('Start','Update'):self.attempt=0
            elif decision.action=='Retry':self.attempt+=1
            self.epoch+=1;self.context=self._context(applied_s);self.ledger.activate(self.context)
            self.pending_arrival=None
            self.features.reset();self.recognizer.reset();self.source_window.reset()
        return True
