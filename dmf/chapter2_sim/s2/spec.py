"""Frozen development contracts, separate from legacy v1/v2 registries."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import yaml

from ..v2.spec import FactorFlags, StudySpecV2
from ..formal_adapter import state_config

METHODS = ('B_single_frame','BTQ','BTQ+S','BTQ+K','F_arrival')
DIAGNOSTICS = ('BQ_single_frame',)
SEEDS = (262000,262001,262002)
CONDITIONS = ('A_normal','B_flash_short','B_flash_window','C_jump_short',
              'C_jump_persistent','D_tail_false','D_tail_true_cost',
              'E_lowconf_false','E_lowconf_true','E_highconf_false',
              'F_jitter','F_dropout','F_gap')
NORMAL_BASE = frozenset(('A_normal','D_tail_true_cost','E_lowconf_true',
                        'F_jitter','F_dropout','F_gap'))
MODEL_GENERATED = frozenset(('A_normal','F_jitter','F_dropout'))


def flags_for(method, *, diagnostic=False):
    values = {'B_single_frame':(False,False,False,False),
              'BTQ':(False,True,False,True),'BTQ+S':(True,True,False,True),
              'BTQ+K':(False,True,True,True),'F_arrival':(True,True,True,True)}
    if diagnostic:values['BQ_single_frame']=(False,False,False,True)
    if method not in values:raise ValueError('unknown or unapproved S2 method: '+method)
    return FactorFlags(*values[method])


@dataclass(frozen=True)
class StudySpecS2:
    common: StudySpecV2 = field(default_factory=StudySpecV2)
    version: str = 'chapter2_s2_single_task_dev1'
    duration_s: float = 4.
    followup_s: float = 1.

    @property
    def study_phase(self):return 'development'

    @property
    def environment(self):return self.common.environment
    @property
    def target(self):return self.common.target
    @property
    def quality(self):return self.common.quality
    @property
    def reference(self):return self.common.reference

    def validate_seed(self, seed):
        if type(seed) is not int or seed not in SEEDS:
            raise ValueError('S2 development only: confirmatory seeds are not authorized')

    def shared_contract(self, method):
        flags_for(method)
        return dict(target=asdict(self.target),quality=asdict(self.quality),
                    clock_domain='simulation',coordinate_unit='pitch',C0_always_on=True,
                    K_history='C0_parsable_not_gate_filtered',
                    max_speed_pitch_s=state_config(self.environment).max_speed_mm_s,
                    prediction_tolerance_pitch=self.environment.position_tolerance)


def load_spec(path):
    data=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    expected=dict(schema='chapter2_s2_development_v1',mode='simulation',
                  development_seeds=list(SEEDS),methods=list(METHODS),
                  conditions=list(CONDITIONS),duration_s=4.,followup_s=1.)
    if data!=expected:raise ValueError('S2 development contract differs; no implicit scans or overrides')
    return StudySpecS2()
