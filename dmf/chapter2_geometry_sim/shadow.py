"""Causal coverage gates evaluated in shadow: never send an electrode command."""
from dmf.experiment.evidence import ArrivalEvent,ArrivalEventLedger,EvidenceWindow
import math


class ShadowArrival:
    def __init__(self,context):
        self.context=context
        self.window=EvidenceWindow(5,.25,.18)
        self.ledger=ArrivalEventLedger();self.ledger.activate(context)
        self.last_id=self.last_time=None
        self.single_s=self.window_s=None
        self.event=None
        self.full_window=EvidenceWindow(5,.25,.18)
        self.full_ledger=ArrivalEventLedger();self.full_ledger.activate(context)
        self.full_s=self.full_event=None
        self.raw_previous=None

    def observe(self,frame,features):
        t=frame.exposure_start_s
        decision_t=frame.available_s if frame.processed_at_s is None else frame.processed_at_s
        duplicate=(self.last_id is not None and frame.frame_id<=self.last_id) or (self.last_time is not None and t<=self.last_time)
        if not duplicate:self.last_id,self.last_time=frame.frame_id,t
        reason=('DUPLICATE_OR_REVERSED' if duplicate else
                'OLD_TASK_FRAME' if frame.context!=self.context else
                'PRE_APPLIED_EXPOSURE' if t<self.context.applied_timestamp_s-1e-10 else
                'INVALID_MASK' if not features.get('valid') else '')
        g=bool(features.get('valid') and features.get('rho_target',0)>=.90 and features.get('eta_source',1)<=.08)
        eligible=not reason and g
        q=bool(features.get('valid') and features.get('components',1)==1 and not features.get('touches_roi_border',False))
        s=bool(features.get('distance_mm',float('inf'))<=.576)
        k=True;raw_speed=None
        if not reason and features.get('valid') and 'x_mm' in features and 'y_mm' in features:
            point=(features['x_mm'],features['y_mm'])
            if self.raw_previous is not None:
                old_t,old_point=self.raw_previous
                gap=t-old_t
                if 0<gap<=.18:
                    raw_speed=math.dist(point,old_point)/gap;k=raw_speed<=19.2
            self.raw_previous=(t,point)
        else:self.raw_previous=None
        confirmed=self.window.observe(self.context,frame.frame_id,t,eligible and q)
        full=self.full_window.observe(self.context,frame.frame_id,t,eligible and q and s and k)
        single_event=eligible and self.single_s is None
        if single_event:self.single_s=decision_t
        window_event=False
        if confirmed:
            event=ArrivalEvent.from_window(self.context,self.window,round(decision_t*1e9),'simulation','simulation_exposure_after_applied')
            if self.ledger.consume(event):
                self.event=event;self.window_s=decision_t;window_event=True
        full_event=False
        if full:
            event=ArrivalEvent.from_window(self.context,self.full_window,round(decision_t*1e9),'simulation','simulation_exposure_after_applied')
            if self.full_ledger.consume(event):
                self.full_event=event;self.full_s=decision_t;full_event=True
        span=self.window.samples[-1][0]-self.window.samples[0][0] if self.window.count else 0.
        return dict(eligible=eligible,c0_valid=not reason,c0_reason=reason,
                    raw_coverage_gate=g,single_event=single_event,window_event=window_event,
                    spatiotemporal_event=full_event,spatiotemporal_confirmed=self.full_s is not None,
                    raw_Q=q,raw_S=s,raw_K=k,raw_history_speed_mm_s=raw_speed,
                    full_window_count=self.full_window.count,
                    full_window_span_s=(self.full_window.samples[-1][0]-self.full_window.samples[0][0]) if self.full_window.count else 0.,
                    window_count=self.window.count,window_span_s=span,window_reason=self.window.last_reason,
                    single_confirmed=self.single_s is not None,window_confirmed=self.window_s is not None)
