"""Declared assumptions; no random draws or formal execution mode."""
from dataclasses import asdict, dataclass
import math

VERSION = 'geometry_exp2_causal_development_v1'
METHOD_NAMES = ('A_fixed', 'M1', 'M2', 'M3')
MAP_PATH = 'D:/Learn/ZJU/第二章 单液滴视觉闭环/电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1/electrode_design_map.json'
MAP_SHA256 = '04ebb54420037d05849d5e4af04c18bce2bd54d9b3090e07b7e1a89dda25c437'


@dataclass(frozen=True)
class Exp2Config:
    route: tuple = (190,191,192,172)
    dt_s: float = .01
    horizon_s: float = 40.
    control_budget_s: float = 40.
    applied_delay_s: float = .04
    response_delay_s: float = .18
    vmax_mm_s: float = 1.4
    acceleration_mm_s2: float = 4.
    settle_time_s: float = .75
    velocity_tau_s: float = .25
    phase_tau_s: float = .15
    angular_rate_rad_s: float = 2*math.pi
    fixed_wait_s: float = 4.65
    source_timeout_s: float = 2.
    attempt_timeout_s: float = 10.
    recovery_timeout_s: float = 10.
    max_retries: int = 2
    max_recoveries: int = 1
    max_step_applied: int = 7
    camera_fps: float = 20.
    exposure_s: float = .008
    processing_delay_s: float = .04
    pixels_per_mm: float = 40.
    diameter_mm: float = 4.
    spacer_height_mm: float = .8
    reference_radius_mm: float = .288
    reference_speed_mm_s: float = .192
    reference_dwell_s: float = .15

    def __post_init__(self):
        for key,value in asdict(self).items():
            if key=='route':continue
            if key.startswith('max_'):
                if type(value) is not int or value < (1 if key=='max_step_applied' else 0):
                    raise ValueError('invalid budget: '+key)
            elif isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('finite positive value required: '+key)
        if (type(self.route) is not tuple or len(self.route)!=4 or
            any(type(i) is not int or not 1<=i<=400 for i in self.route)):
            raise ValueError('three planned core-electrode steps required')
        for a,b in zip(self.route,self.route[1:]):
            ar,ac=divmod(a-1,20);br,bc=divmod(b-1,20)
            if abs(ar-br)+abs(ac-bc)!=1:raise ValueError('route must be four-neighbor adjacent')
        if self.control_budget_s>self.horizon_s or self.exposure_s>=1/self.camera_fps:
            raise ValueError('invalid observation/control budget')
        if self.max_step_applied < 1+self.max_retries+2*self.max_recoveries:
            raise ValueError('Applied budget cannot cover declared protection')
        # The development runner samples truth on one fixed clock grid. Keep
        # every actuation/control boundary exact on that grid; exposure end
        # and availability intentionally remain off-grid and are ceil-delivered.
        grid_times={key:getattr(self,key) for key in (
            'horizon_s','control_budget_s','applied_delay_s','response_delay_s',
            'fixed_wait_s','source_timeout_s','attempt_timeout_s','recovery_timeout_s')}
        grid_times['camera_period_s']=1/self.camera_fps
        for key,value in grid_times.items():
            ticks=value/self.dt_s
            if not math.isclose(ticks,round(ticks),rel_tol=0.,abs_tol=1e-8):
                raise ValueError('fixed-grid scheduler requires dt-aligned '+key)

    def snapshot(self):
        return dict(version=VERSION,simulation=True,development_only=True,n=1,
            coordinate_unit='mm',clock_domain='simulation',strict_scheduler_grid=True,
            random_draws=0,formal=False,tuning=False,
            world_model='bounded_velocity_relaxation_not_old_minimum_jerk_not_CFD',
            parameters=asdict(self))
