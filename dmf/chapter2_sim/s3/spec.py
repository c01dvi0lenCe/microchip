"""Approved G0–G2 plan. Formal seeds deliberately have no entry point."""
from dataclasses import asdict, dataclass, field
from ..config import SCENARIOS
from ..v2.spec import StudySpecV2
from ..s2.spec import flags_for

METHODS=('A_fixed','B_single','BTQ','F_full')
SEEDS=(264000,264001,264002)
VERSION='chapter2_s3_g0_g2_dev1'

@dataclass(frozen=True)
class S3Spec:
    common: StudySpecV2=field(default_factory=StudySpecV2)
    version: str=VERSION
    def validate_seed(self,seed):
        if type(seed) is not int or seed not in SEEDS:raise ValueError('S3 G0-G2 permits only 264000–264002; formal seeds forbidden')
    def __post_init__(self):
        c=self.common.environment
        if c.route!=(190,191,192,172) or c.max_time_s!=24. or c.fixed_interval_s!=1.2:
            raise ValueError('fixed S3 route, 24s exogenous horizon and 1.2s baseline required')
        if c.max_retries!=2 or c.max_recoveries!=1:raise ValueError('approved shared Retry/Recovery budget required')
    def contract(self,method,protection=None):
        if method not in METHODS:raise ValueError('unknown S3 method')
        p=protection or ('P_F' if method=='F_full' else 'P_B')
        if p not in ('P_B','P_F'):raise ValueError('unknown protection')
        if protection and method not in ('BTQ','F_full'):raise ValueError('bridge only BTQ/F arrival')
        name={'A_fixed':'B_single_frame','B_single':'B_single_frame','BTQ':'BTQ','F_full':'F_arrival'}[method]
        return dict(method=method,protection=p,arrival_method='timer_no_visual_event' if method=='A_fixed' else name,
                    flags=flags_for(name),C0_always_on=True,source=self.common.source,
                    target=self.common.target,quality=self.common.quality,clock_domain='simulation')

def development_plan():
    plan=[]
    for scenario in SCENARIOS:
        for seed in SEEDS:
            for method in METHODS:plan.append(dict(cohort='main',scenario=scenario,seed=seed,method=method,protection=None,phase_mode='end_to_end'))
    for scenario in ('partial_stall','deviation'):
        for seed in SEEDS:
            for method,p in (('F_full','P_B'),('BTQ','P_F')):
                plan.append(dict(cohort='bridge',scenario=scenario,seed=seed,method=method,protection=p,phase_mode='end_to_end'))
    for scenario in ('jitter','dropout'):
        for seed in SEEDS:
            for method in METHODS:plan.append(dict(cohort='diagnostic',scenario=scenario,seed=seed,method=method,protection=None,phase_mode='transport_only'))
    return plan
