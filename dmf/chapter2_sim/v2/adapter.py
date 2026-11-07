"""Research adapters reuse production policy/token/ledger, never mutate it."""
from dataclasses import replace
import cv2

from dmf.experiment.evidence import ArrivalEvent, EvidenceWindow
from dmf.experiment.perception import Observation, PriorFeatures, StateRecognizer
from dmf.experiment.policy import Decision
from dmf.vision.contracts import DropletState as S, VisionResult
from ..formal_adapter import FormalAdapter, FormalObservation, make_frame_packet, state_config
from .spec import method_flags
from .observation import ObservationPipeline, validate_syntax
from .arrival import ArrivalGate, window_trace


class ResearchAdapter(FormalAdapter):
    def __init__(self,spec,geometry,method='F',*,flags=None,run_id='simulation_v2'):
        if method=='C_v1_compat':raise ValueError('use the unchanged FormalAdapter for compatibility')
        self.spec,self.variant=spec,method
        self.flags=flags or method_flags(method)
        super().__init__(spec.environment,geometry,'C',run_id=run_id)
        self.method_version=f'{method}_research_v2_e0_e3_dev2'
        self.metadata.update(spec.algorithm_contract(method,self.flags),method_version=self.method_version)
        self.controller.config=replace(self.control_cfg,source_timeout_s=spec.source.timeout_s,recovery_timeout_s=spec.recovery.timeout_s)
        self.control_cfg=self.controller.config
        self.source_contract=spec.source;self.recovery_contract=spec.recovery
        self.pipeline=ObservationPipeline(self.map,self.state_cfg,spec.target,spec.quality)
        self.arrival=ArrivalGate(spec.target,self.flags)
        # Classification is reused, but target temporal evidence is exclusively
        # owned by ArrivalGate; no second hidden arrival window is permitted.
        self.transport_recognizer=StateRecognizer(replace(self.state_cfg,eta_arr=spec.target.coverage,eta_release=spec.target.source_release,
            arrival_frames=1,arrival_duration_s=0.,arrival_max_centroid_span_mm=None,arrival_max_coverage_span=None))
        self.last_trace={};self._source_stage=None
        self._setup_source_stage()

    def _setup_source_stage(self):
        if self.phase not in ('confirm_source','recovering') or self._source_stage==self.phase:return
        gate=self.spec.source if self.phase=='confirm_source' else self.spec.recovery
        cfg=replace(state_config(self.cfg),eta_arr=gate.coverage,position_tolerance_mm=gate.position_tolerance_pitch)
        self.features=PriorFeatures(self.map,cfg);self.recognizer=StateRecognizer(cfg)
        w=gate.window;self.source_window=EvidenceWindow(w.frames,w.duration_s,w.max_gap_s,w.centroid_span_pitch,w.coverage_span)
        self._source_stage=self.phase

    def begin_transport(self,applied_s):
        """Controlled transport_only initial condition, never a GT-based source decision."""
        if self.phase!='confirm_source':raise ValueError('transport initial condition already used')
        decision=self._issue(Decision('Start',self.target,'controlled transport_only initial condition'))
        if not self.accept(decision,applied_s):raise RuntimeError('controlled Start rejected')

    def _reject(self,packet,now,reason,causality):
        self.arrival.reset();self.source_window.reset();self.recognizer.reset();self.transport_recognizer.reset();self.pipeline.reset()
        self.last_trace=dict(C0_passed=False,C0_reason=reason,raw={},enabled=vars(self.flags),eligible=False,
            stage='target' if self.phase=='transport' else 'source' if self.phase=='confirm_source' else 'recovery',
            window_count=0,window_duration_s=0.,rebuild_reasons=[reason],window_reason='C0_REJECTED',rejection_reasons=[reason])
        f=Observation(error=reason)
        return FormalObservation(packet,f,S.UNKNOWN,self._decision(S.UNKNOWN,now,f),causality=causality)

    def observe(self,frame,now_s):
        now_s=self._time(now_s)
        packet=make_frame_packet(frame,video_id=getattr(frame,'stream_id',None) or self.run_id,shape=self.map.shape,task_epoch=getattr(frame,'task_epoch',None))
        if getattr(frame,'clock_domain','simulation')!='simulation':
            packet=replace(packet,timing=replace(packet.timing,clock_domain=frame.clock_domain,exposure_clock_domain=frame.clock_domain))
        assessment=self.guard.check(packet,self.context,mode='simulation')
        valid,reason=validate_syntax(frame,self.map.shape)
        if not assessment.accepted:reason=assessment.reason
        elif frame.available_s>now_s+1e-9:reason='FRAME_NOT_AVAILABLE'
        elif now_s-packet.timestamp_s>self.cfg.observation_timeout_s:reason='STALE_FRAME'
        elif valid:reason=''
        if reason:return self._reject(packet,now_s,reason,assessment.causality)
        if self.phase in ('confirm_source','recovering'):
            return self._observe_source(frame,packet,now_s,assessment.causality)
        f,raw,reasons=self.pipeline.extract(packet,frame,self.context)
        if f is None:return self._reject(packet,now_s,'NON_MONOTONE_TIMESTAMP',assessment.causality)
        trace=self.arrival.observe(self.context,packet,raw)
        trace['history_rebuild_reasons']=reasons;trace['rebuild_reasons']=sorted(set(trace['rebuild_reasons']+reasons))
        # Arrival ablations change only ArrivalGate eligibility. The common
        # state/progress/recovery inputs retain raw quality and conflicts;
        # otherwise disabling S/Q/K would also change the protection policy.
        f=replace(f,valid=raw['Q'],spatial_ok=raw['S_area'],
            temporal_ok=raw['K'],target_position_ok=raw['S_position'],
            error='' if raw['Q'] else 'QUALITY_REJECTED')
        state=self.transport_recognizer.recognize(f,packet.timestamp_s,packet.capture_identity,self.context) if self.variant=='F' else S.UNKNOWN
        if state is S.ARRIVED:state=S.UNKNOWN
        arrival=None
        if trace['confirmed']:
            state=S.ARRIVED
            if self.pending_arrival is None:
                self.pending_arrival=ArrivalEvent.from_window(self.context,self.arrival.window,None,'simulation',assessment.causality)
                arrival=self.pending_arrival
        self.last_trace=trace
        decision=self._decision(state,now_s,f)
        return FormalObservation(packet,f,state,decision,arrival,assessment.causality)

    def _observe_source(self,frame,packet,now,causality):
        self._setup_source_stage()
        result=VisionResult(frame.mask,(0.,0.),None,getattr(frame,'confidence',1.),0.,True)
        f=self.features.extract(packet,result,self.source,self.target,[])
        state=self.recognizer.recognize(f,packet.timestamp_s,packet.capture_identity,self.context)
        gate=self.spec.source if self.phase=='confirm_source' else self.spec.recovery
        position_ok=f.centroid is not None and cv2.pointPolygonTest(self.features.polygons[self.source],f.centroid,True)>=-gate.position_tolerance_pitch
        eligible=f.observation_quality=='reliable' and f.eta_source>=gate.coverage and position_ok
        trace=window_trace(self.source_window,self.context,packet.capture_identity,packet.timestamp_s,eligible,f.centroid,f.eta_source)
        trace.update(C0_passed=True,C0_reason='',raw=dict(S=f.spatial_ok,K=f.temporal_ok,Q=f.valid,eta_source=f.eta_source,eta_target=f.eta_target),
            enabled=dict(S=True,W=True,K=True,Q=True),eligible=eligible,thresholds=vars(gate),stage='source' if self.phase=='confirm_source' else 'recovery',
            rejection_reasons=[] if eligible else [f.error or ('motion_conflict' if not f.temporal_ok else 'source_coverage_or_position')])
        self.last_trace=trace
        return FormalObservation(packet,f,state,self._decision(state,now,f,trace['confirmed']),causality=causality)

    def accept(self,decision,applied_s,accepted=True):
        result=super().accept(decision,applied_s,accepted)
        if result and decision.action in ('Start','Update','Retry','Recovery'):
            self.pipeline.reset();self.arrival.reset();self.transport_recognizer.reset();self._source_stage=None
            self._setup_source_stage()
        return result
