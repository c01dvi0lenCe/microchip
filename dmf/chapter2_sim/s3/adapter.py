"""Composition over frozen raw pipeline, arrival gate and EventController."""
from ..v2.adapter import ResearchAdapter
from ..v2.arrival import ArrivalGate
from dmf.experiment.policy import Decision
from dmf.vision.contracts import DropletState as S

class TransactionSlot:
    def __init__(self):self.request_id=None
    def reserve(self,request_id):
        if self.request_id is not None:return False
        self.request_id=request_id;return True
    def release(self,request_id):
        if self.request_id!=request_id:return False
        self.request_id=None;return True

class _TimerOnlyGate(ArrivalGate):
    def observe(self,*args):
        trace=super().observe(*args)
        trace['diagnostic_window_complete']=trace['confirmed'];trace['confirmed']=False
        trace['arrival_disabled_for_fixed_timer']=True
        return trace

class S3Adapter(ResearchAdapter):
    def __init__(self,spec,geometry,method='BTQ',*,protection=None,run_id='s3'):
        contract=spec.contract(method,protection)
        super().__init__(spec.common,geometry,'F',flags=contract['flags'],run_id=run_id)
        self.strategy=method;self.protection=contract['protection']
        self.variant='F' if self.protection=='P_F' else 'BTQ'
        self.method='A' if method=='A_fixed' else 'C'
        if method=='A_fixed':self.arrival=_TimerOnlyGate(spec.common.target,contract['flags'])
        self.method_version=f'{spec.version}:{method}:{self.protection}'
        self.metadata.update(method_version=self.method_version,protection=self.protection,
                             arrival_method=contract['arrival_method'],raw_protection_inputs_not_switched=True)

    def _decision(self,state,now,observation=None,source_confirmed=False):
        # Same raw Observation and common quality/progress/attempt budgets.
        # Only P_F receives non-arrival five-state labels.
        policy_state=state if self.protection=='P_F' or state is S.ARRIVED else S.UNKNOWN
        if self.strategy=='A_fixed' and self.phase=='transport':
            base=self.controller.decide(S.UNKNOWN,now,observation=observation)
            if base.action!='Hold':return self._issue(base)
            if now-self.controller.attempt_started>=self.cfg.fixed_interval_s-1e-9:
                d=(Decision('Complete',reason='fixed elapsed interval; no visual arrival event')
                   if self.controller.index+2==len(self.cfg.route) else
                   Decision('Update',self.cfg.route[self.controller.index+2],'fixed elapsed interval; no visual arrival event'))
                return self._issue(d)
            return base
        return self._issue(self.controller.decide(policy_state,now,source_confirmed,observation=observation))
