"""One raw history shared by all orthogonal gates. No world/reference inputs."""
import math
from dmf.experiment.evidence import EvidenceWindow,ArrivalEvent,ArrivalEventLedger
from .spec import GATES


class RawAssessor:
    def __init__(self,context):
        self.context=context
        self.last_id=self.last_time=None
        self.previous=None

    def observe(self,frame,features):
        t=frame.exposure_start_s
        decision=frame.processed_at_s if frame.processed_at_s is not None else frame.available_s
        times=(t,frame.exposure_end_s,frame.available_s,decision)
        valid_times=all(isinstance(x,(int,float)) and math.isfinite(x) and x>=0 for x in times)
        valid_id=type(frame.frame_id) is int and frame.frame_id>=0
        duplicate=(valid_times and valid_id and
            ((self.last_id is not None and frame.frame_id<=self.last_id) or
             (self.last_time is not None and t<=self.last_time)))
        if valid_times and valid_id and not duplicate:
            self.last_id,self.last_time=frame.frame_id,t
        reason=('INVALID_TIME_OR_ID' if not valid_times or not valid_id else
                'INVALID_TIME_ORDER' if not t<=frame.exposure_end_s<=frame.available_s<=decision+1e-9 else
                'DUPLICATE_OR_REVERSED' if duplicate else
                'OLD_TASK_FRAME' if frame.context!=self.context else
                'PRE_APPLIED_EXPOSURE' if t<self.context.applied_timestamp_s-1e-10 else
                'INVALID_MASK' if not features.get('valid') else
                'INVALID_FEATURE' if any(not isinstance(features.get(k),(int,float)) or
                    not math.isfinite(features[k]) for k in ('x_mm','y_mm','rho_target','eta_source','distance_mm')) else '')
        g=bool(features.get('valid') and features.get('rho_target',0)>=GATES['rho_target']
               and features.get('eta_source',1)<=GATES['eta_source'])
        q=bool(features.get('valid') and features.get('components',1)==1
               and not features.get('touches_roi_border',False))
        s=bool(features.get('distance_mm',math.inf)<=GATES['target_distance_mm'])
        k=True;speed=None;previous=self.previous
        if not reason:
            point=(features['x_mm'],features['y_mm'])
            if previous is not None:
                gap=t-previous[0]
                if 0<gap<=GATES['max_gap_s']:
                    speed=math.dist(point,previous[1])/gap
                    k=speed<=GATES['max_history_speed_mm_s']
            self.previous=(t,point)
        else:self.previous=None
        return dict(C0=not reason,c0_reason=reason,G=g,Q=q,S=s,K=k,raw_speed_mm_s=speed,
            history_previous_t_s=previous[0] if previous else None,
            history_previous_x_mm=previous[1][0] if previous else None,
            history_previous_y_mm=previous[1][1] if previous else None)


class GateRunner:
    def __init__(self,spec,context):
        self.spec,self.context=spec,context
        self.window=EvidenceWindow(GATES['min_frames'] if spec.w else 1,
            GATES['min_span_s'] if spec.w else 0.,GATES['max_gap_s'])
        self.ledger=ArrivalEventLedger();self.ledger.activate(context)
        self.event=None

    def observe(self,frame,raw):
        eligible=raw['C0'] and raw['G'] and all(raw[name] for name,enabled in
            [('Q',self.spec.q),('S',self.spec.s),('K',self.spec.k)] if enabled)
        confirmed=self.window.observe(self.context,frame.frame_id,frame.exposure_start_s,eligible)
        fresh=False
        decision=frame.processed_at_s if frame.processed_at_s is not None else frame.available_s
        if confirmed:
            event=ArrivalEvent.from_window(self.context,self.window,round(decision*1e9),
                'simulation','simulation_exposure_after_applied')
            if self.ledger.consume(event):
                fresh=True
                self.event=dict(method=self.spec.name,event_id=event.event_id,decision_s=decision,
                    evidence_start_s=event.evidence_start_s,evidence_end_s=event.evidence_end_s,
                    first_frame_id=event.first_frame_id,last_frame_id=event.last_frame_id)
        return dict(method=self.spec.name,eligible=bool(eligible),new_event=fresh,
            consumed=self.event is not None,window_count=self.window.count,
            window_span_s=self.window.samples[-1][0]-self.window.samples[0][0] if self.window.count else 0.,
            window_reason=self.window.last_reason,
            window_ids=';'.join(str(r[3]) for r in self.window.samples))
