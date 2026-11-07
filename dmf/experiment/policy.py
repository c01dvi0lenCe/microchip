"""Bounded local transport policy. No path search or multi-droplet scheduling."""
from dataclasses import dataclass
from dmf.vision.contracts import DropletState as S
from .config import ControlConfig
from .evidence import ProgressMonitor


@dataclass(frozen=True)
class Decision:
    action: str
    target: int | None = None
    reason: str = ''


class EventController:
    def __init__(self,route,config:ControlConfig):
        self.route=tuple(route);self.config=config;self.index=0;self.phase='confirm_source'
        self.retry_count=0;self.retry_total=0;self.recovery_total=0
        self.attempt_started=None;self.step_started=None;self.phase_started=None
        self.complete=False
        self.progress=ProgressMonitor(config.wait_s,config.attempt_timeout_s,
            config.progress_epsilon_mm,config.no_detection_timeout_s)

    @property
    def source(self):return self.route[self.index]
    @property
    def target(self):return self.route[self.index+1]

    def decide(self,state,t,source_confirmed=False,*,observation=None):
        cfg=self.config
        if self.phase_started is None:self.phase_started=t
        if self.complete or self.phase=='stopped':return Decision('Hold',reason='transport complete or stopped')
        if self.phase=='confirm_source':
            if source_confirmed:return Decision('Start',self.target,'source visually confirmed')
            if t-self.phase_started>=cfg.source_timeout_s:return Decision('Stop',reason='source confirmation timeout')
            return Decision('Hold',reason='waiting for source confirmation')
        if self.phase=='recovering':
            if source_confirmed:return Decision('Retry',self.target,'recovery confirmed')
            if t-self.phase_started>=cfg.recovery_timeout_s:return Decision('Stop',reason='local recovery timeout')
            return Decision('Hold',reason='waiting for visual recovery confirmation')
        if state is S.ARRIVED:
            return Decision('Complete',reason='final target confirmed') if self.index+2==len(self.route) else Decision('Update',self.route[self.index+2],'target visually confirmed')
        if state is S.DEVIATION:return self._recovery('deviation')
        reliable=(observation.observation_quality=='reliable' if observation is not None else state is not S.UNKNOWN)
        progress=None
        if reliable and observation is not None:
            progress=observation.progress_mm
            if progress is None and observation.distance is not None:progress=-observation.distance
        status=self.progress.observe((self.index,self.attempt_started),t,progress,reliable)
        if status in {'quality_timeout','invalid_time'}:
            return Decision('Stop',reason='observation quality timeout' if status=='quality_timeout' else 'invalid progress timestamp')
        if status in {'no_progress','attempt_expired'}:
            reason='no target progress timeout' if status=='no_progress' else 'maximum attempt timeout'
            if self.retry_count<cfg.max_retries:return Decision('Retry',self.target,reason)
            return self._recovery(reason+'; retry limit reached')
        return Decision('Hold',reason='keep current command')

    def _recovery(self,reason):
        if self.recovery_total>=self.config.max_recoveries:return Decision('Stop',reason='local recovery limit reached')
        return Decision('Recovery',self.source,reason)

    def accept(self,d:Decision,t):
        """Commit policy state only after actuator success (or explicit simulation)."""
        if d.action=='Start':
            self.phase='transport';self.attempt_started=t;self.step_started=t;self.phase_started=t
        elif d.action=='Retry':
            if self.phase=='recovering':self.retry_count=0
            else:self.retry_count+=1
            self.retry_total+=1;self.phase='transport';self.attempt_started=t;self.phase_started=t
        elif d.action=='Recovery':
            self.recovery_total+=1;self.phase='recovering';self.phase_started=t
        elif d.action=='Update':
            self.index+=1;self.retry_count=0;self.retry_total=0;self.recovery_total=0
            self.phase='transport';self.attempt_started=t;self.step_started=t;self.phase_started=t
        elif d.action=='Complete':self.complete=True;self.phase='complete'
        elif d.action=='Stop':self.phase='stopped'
        if d.action in {'Start','Retry','Update'}:
            self.progress.reset((self.index,self.attempt_started),t)
