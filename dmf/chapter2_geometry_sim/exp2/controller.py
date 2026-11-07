"""Mask/time/task-only controller, sharing frozen experiment1B arrival gates."""
import math
from dmf.experiment.evidence import StepContext, EvidenceWindow
from ..exp1b.gates import RawAssessor, GateRunner
from ..exp1b.spec import METHODS, GATES
from .spec import METHOD_NAMES


class ExperimentController:
    def __init__(self,method,config,run_id):
        if method not in METHOD_NAMES:raise ValueError('normal mechanism methods only')
        self.method,self.cfg,self.run_id=method,config,run_id
        self.phase='prepare';self.pending=None;self.context=None;self.epoch=0
        self.step_index=0;self.attempt=0;self.applied_s=None;self.terminal=None
        self.events=[];self.frames=[];self.arrivals=[];self.consumed_steps=set()
        self.steps=[dict(step=i,source=a,target=b,attempted=False,applied_count=0,retries=0,recoveries=0,
            arrival_s=None,decision_s=None,departure_action=None,departure_request_s=None,
            departure_applied_s=None,started_s=None,censored=True) for i,(a,b) in enumerate(zip(config.route,config.route[1:]))]
        self.assessor=None;self.gate=None;self.window=None;self._request_id=0

    def start(self,time_s=0.):
        if self.context is not None or self.pending is not None or self.events:raise ValueError('already started')
        self._request(self.cfg.route[0],'Prepare',time_s)

    def _request(self,target,action,time_s):
        if self.pending is not None or self.terminal is not None:return False
        if time_s+self.cfg.applied_delay_s>self.cfg.control_budget_s+1e-9:
            self._stop('time_budget_exhausted',time_s);return False
        if action!='Prepare':
            receive_step=self.step_index+1 if action=='Update' else self.step_index
            if self.steps[receive_step]['applied_count']>=self.cfg.max_step_applied:
                self._stop('transport_aborted',time_s);return False
        self._request_id+=1
        self.pending=dict(request_id=self._request_id,target=target,action=action,request_s=time_s,
                          origin_step=self.step_index if action!='Prepare' else None)
        self.events.append(dict(event='request',time_s=time_s,**self.pending))
        self.phase='pending';return True

    def on_applied(self,transaction,time_s):
        if self.terminal is not None:
            raise ValueError('Applied after terminal state; transaction admission/order violated')
        if self.pending is None or transaction!=self.pending:raise ValueError('unmatched Applied')
        if time_s<transaction['request_s']+self.cfg.applied_delay_s-1e-9:raise ValueError('premature Applied')
        action=transaction['action'];self.pending=None;self.applied_s=time_s;self.epoch+=1
        self.events.append(dict(event='simulated_applied',time_s=time_s,applied_s=time_s,**transaction))
        if action=='Update':
            self.steps[self.step_index]['departure_applied_s']=time_s;self.step_index+=1;self.attempt=0
        elif action in ('Retry','Resend'):self.attempt+=1
        if action!='Prepare':
            step=self.steps[self.step_index];step['applied_count']+=1;step['attempted']=True
            if step['started_s'] is None:step['started_s']=time_s
            if action=='Retry':step['retries']+=1
            if action=='Recovery':step['recoveries']+=1
        self.phase='prepare' if action=='Prepare' else 'recovering' if action=='Recovery' else 'transport'
        step=self.steps[self.step_index]
        target=step['source'] if self.phase!='transport' else step['target']
        self.context=StepContext(self.run_id,self.step_index,self.attempt,self.epoch,step['source'],target,
            clock_domain='simulation',phase=self.phase,applied_timestamp_s=time_s,applied_time_quality='simulation_exact')
        previous_assessor=self.assessor
        self.assessor=RawAssessor(self.context)
        if previous_assessor is not None:
            # Identity is stream-global; only K position history is task-local.
            self.assessor.last_id=previous_assessor.last_id
            self.assessor.last_time=previous_assessor.last_time
        self.window=EvidenceWindow(GATES['min_frames'],GATES['min_span_s'],GATES['max_gap_s'])
        self.gate=GateRunner(next(m for m in METHODS if m.name==self.method),self.context) if self.method!='A_fixed' and self.phase=='transport' else None

    def _stop(self,reason,time_s):
        if self.terminal is not None:return
        self.terminal=reason;self.phase='stopped'
        self.events.append(dict(event='Stop',time_s=time_s,reason=reason,origin_step=self.step_index))

    def _advance_step(self,time_s):
        step=self.steps[self.step_index];step['decision_s']=time_s;step['censored']=False
        if self.step_index==len(self.steps)-1:
            step['departure_action']='Complete';step['departure_request_s']=time_s
            self.events.append(dict(event='Complete',time_s=time_s,action='Complete',target=step['target'],origin_step=self.step_index))
            self.phase='complete';self.terminal='complete'
        else:
            if self._request(self.steps[self.step_index+1]['target'],'Update',time_s):
                step['departure_action']='Update';step['departure_request_s']=time_s

    def tick(self,time_s):
        if self.terminal is not None:return
        if time_s>=self.cfg.control_budget_s-1e-9:
            self._stop('time_budget_exhausted',time_s);return
        if self.pending is not None or self.applied_s is None:return
        elapsed=time_s-self.applied_s
        if self.phase=='prepare' and elapsed>=self.cfg.source_timeout_s-1e-9:
            self._stop('source_preparation_failed',time_s)
        elif self.phase=='recovering' and elapsed>=self.cfg.recovery_timeout_s-1e-9:
            self._stop('transport_aborted',time_s)
        elif self.phase=='transport':
            if self.method=='A_fixed' and elapsed>=self.cfg.fixed_wait_s-1e-9:self._advance_step(time_s)
            elif elapsed>=self.cfg.attempt_timeout_s-1e-9:
                step=self.steps[self.step_index]
                if step['retries']<self.cfg.max_retries:self._request(step['target'],'Retry',time_s)
                elif step['recoveries']<self.cfg.max_recoveries:self._request(step['source'],'Recovery',time_s)
                else:self._stop('transport_aborted',time_s)

    def observe(self,frame,features):
        if self.pending is not None or self.terminal is not None or self.context is None:return False
        raw=self.assessor.observe(frame,features)
        row=dict(frame_id=frame.frame_id,exposure_start_s=frame.exposure_start_s,available_s=frame.available_s,
            processed_at_s=frame.processed_at_s,processed_s=frame.processed_at_s,step=self.step_index,
            attempt=self.attempt,epoch=self.epoch,source=self.context.source_id,target=self.context.target_id,
            phase=self.phase,**features,**raw)
        if self.phase in ('prepare','recovering'):
            eligible=bool(raw['C0'] and raw['Q'] and features.get('rho_source',0)>=GATES['rho_target']
                and features.get('source_distance_mm',math.inf)<=GATES['target_distance_mm'])
            ready=self.window.observe(self.context,frame.frame_id,frame.exposure_start_s,eligible)
            row.update(eligible=eligible,window_count=self.window.count,window_reason=self.window.last_reason,
                window_span_s=self.window.samples[-1][0]-self.window.samples[0][0] if self.window.count else 0.)
            if ready:
                now=frame.processed_at_s if frame.processed_at_s is not None else frame.available_s
                self.events.append(dict(event='SourceReady',time_s=now,origin_step=self.step_index,phase=self.phase))
                self._request(self.steps[self.step_index]['target'],'Start' if self.phase=='prepare' else 'Resend',now)
        elif self.gate is not None:
            gate=self.gate.observe(frame,raw);row.update(gate)
            if gate['new_event'] and self.step_index not in self.consumed_steps:
                self.consumed_steps.add(self.step_index)
                event=dict(self.gate.event,step=self.step_index,attempt=self.attempt,epoch=self.epoch)
                self.arrivals.append(event);self.steps[self.step_index]['arrival_s']=event['decision_s']
                self.events.append(dict(event='ArrivalEvent',time_s=event['decision_s'],origin_step=self.step_index,**event))
                self._advance_step(event['decision_s'])
        self.frames.append(row);return True
