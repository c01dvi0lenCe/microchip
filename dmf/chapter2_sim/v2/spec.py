"""Explicit phase-specific research contracts; all lengths are pitches."""
from dataclasses import asdict, dataclass, field, replace
import math

from ..config import SimConfig

METHODS=('C_v1_compat','BT','BTQ','F')
DEVELOPMENT_SEEDS=(262000,262001,262002)


@dataclass(frozen=True)
class FactorFlags:
    S: bool=True
    W: bool=True
    K: bool=True
    Q: bool=True

    def __post_init__(self):
        if any(type(v) is not bool for v in asdict(self).values()):
            raise ValueError('S/W/K/Q must be boolean; C0 is not a switch')


def method_flags(method):
    if method=='BT':return FactorFlags(S=False,K=False,Q=False)
    if method=='BTQ':return FactorFlags(S=False,K=False)
    if method=='F':return FactorFlags()
    raise ValueError('v1 compatibility has its original indivisible semantics')


@dataclass(frozen=True)
class WindowConfig:
    frames: int=5
    duration_s: float=.25
    max_gap_s: float=.18
    centroid_span_pitch: float=.11
    coverage_span: float=.15

    def __post_init__(self):
        if type(self.frames) is not int or self.frames<5:raise ValueError('research W uses at least five frames')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for k,v in asdict(self).items() if k!='frames'):
            raise ValueError('finite nonnegative window values required')
        if self.duration_s<.25 or self.max_gap_s<=0 or self.coverage_span>1:raise ValueError('invalid research evidence window')


@dataclass(frozen=True)
class TargetGateConfig:
    coverage: float=.85
    source_release: float=.08
    position_tolerance_pitch: float=.18
    window: WindowConfig=field(default_factory=WindowConfig)

    def __post_init__(self):
        if not 0<=self.source_release<self.coverage<=1:raise ValueError('invalid target eta thresholds')
        if not math.isfinite(self.position_tolerance_pitch) or self.position_tolerance_pitch<0:raise ValueError('invalid position tolerance')


@dataclass(frozen=True)
class SourceGateConfig:
    policy: str='P0_v1'
    coverage: float=.85
    position_tolerance_pitch: float=.18
    timeout_s: float=2.6
    window: WindowConfig=field(default_factory=WindowConfig)

    def __post_init__(self):
        if self.policy!='P0_v1':raise ValueError('P1 is not implemented or approved')
        if not 0<self.coverage<=1 or not math.isfinite(self.timeout_s) or self.timeout_s<=0:raise ValueError('invalid source gate')
        if not math.isfinite(self.position_tolerance_pitch) or self.position_tolerance_pitch<0:raise ValueError('invalid source tolerance')


@dataclass(frozen=True)
class QualityConfig:
    min_confidence: float=.2
    min_area_px: int=10
    max_area_px: int=100000

    def __post_init__(self):
        if not 0<=self.min_confidence<=1 or not 0<self.min_area_px<self.max_area_px:raise ValueError('invalid quality thresholds')


@dataclass(frozen=True)
class ReferenceSpec:
    radius_pitch: float=.09
    max_speed_pitch_s: float=.06
    dwell_s: float=.15
    version: str='independent_simulation_reference_v2_contiguous'

    def __post_init__(self):
        if any(not math.isfinite(v) or v<=0 for v in (self.radius_pitch,self.max_speed_pitch_s,self.dwell_s)):
            raise ValueError('invalid independent simulation reference')


@dataclass(frozen=True)
class StudySpecV2:
    environment: SimConfig=field(default_factory=SimConfig)
    source: SourceGateConfig=field(default_factory=SourceGateConfig)
    target: TargetGateConfig=field(default_factory=TargetGateConfig)
    recovery: SourceGateConfig=field(default_factory=SourceGateConfig)
    quality: QualityConfig=field(default_factory=QualityConfig)
    reference: ReferenceSpec=field(default_factory=ReferenceSpec)
    version: str='chapter2_v2_e0_e3_dev2'

    def algorithm_contract(self,method,flags=None):
        if method not in METHODS:raise ValueError('unknown research method')
        return dict(method=method,display_name='等稳定窗口覆盖率强基线' if method=='BTQ' else method,
            factors=asdict(flags or method_flags(method)) if method!='C_v1_compat' else None,
            target=asdict(self.target),source=asdict(self.source),recovery=asdict(self.recovery),quality=asdict(self.quality),
            C0_always_on=True,clock_domain='simulation',coordinate_unit='pitch',reference_not_visible_to_algorithm=True)


def load_spec(path):
    from pathlib import Path
    import yaml
    data=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if data.get('mode')!='simulation' or data.get('schema')!='chapter2_sim_v2_e0_e3':raise ValueError('explicit v2 simulation development schema required')
    if tuple(data.get('development_seeds',()))!=DEVELOPMENT_SEEDS or tuple(data.get('methods',()))!=METHODS:raise ValueError('this stage has a fixed small development plan')
    allowed={'mode','schema','development_seeds','methods','environment','source','target','recovery','quality','reference','version'}
    if set(data)-allowed:raise ValueError('unknown development configuration field')
    values={}
    env=dict(data.get('environment',{}))
    if 'route' in env:env['route']=tuple(env['route'])
    values['environment']=SimConfig(**env)
    for name,cls in (('source',SourceGateConfig),('target',TargetGateConfig),('recovery',SourceGateConfig)):
        v=dict(data.get(name,{}))
        if 'window' in v:v['window']=WindowConfig(**v['window'])
        values[name]=cls(**v)
    values['quality']=QualityConfig(**data.get('quality',{}));values['reference']=ReferenceSpec(**data.get('reference',{}))
    if 'version' in data:values['version']=data['version']
    return StudySpecV2(**values)
