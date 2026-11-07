"""All simulation dimensions are normalized electrode pitches, not measured mm."""
from dataclasses import dataclass, fields
import math
from pathlib import Path

import yaml

SCENARIOS = ('normal', 'delayed', 'partial_stall', 'jitter', 'dropout', 'deviation', 'failure')


@dataclass(frozen=True)
class SimConfig:
    route: tuple = (190, 191, 192, 172)
    map_path: str | None = None
    dt_s: float = .01
    max_time_s: float = 24.
    speed: float = 1.5
    response_delay_s: float = .18
    ack_delay_s: float = .04
    process_noise: float = .003
    camera_fps: float = 20.
    exposure_s: float = .008
    processing_delay_s: float = .04
    processing_jitter_s: float = .015
    position_noise: float = .018
    mask_radius: float = .26
    mask_radius_noise: float = .015
    drop_probability: float = .03
    pixels_per_pitch: int = 48
    fixed_interval_s: float = 1.2
    arrival_coverage: float = .85
    source_release: float = .08
    position_tolerance: float = .18
    corridor_width: float = .48
    arrival_frames: int = 5
    stable_duration_s: float = .25
    max_frame_gap_s: float = .18
    stable_span: float = .11
    stationary_speed: float = .12
    deviation_frames: int = 3
    attempt_timeout_s: float = 2.6
    no_progress_s: float = 1.4
    progress_epsilon: float = .04
    max_retries: int = 2
    max_recoveries: int = 1
    recovery_timeout_s: float = 2.6
    observation_timeout_s: float = 1.8
    # Independent hidden physical reference. Never changed by controller scans.
    truth_radius: float = .09
    truth_max_speed: float = .06
    truth_dwell_s: float = .15

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(field.default) is int and type(value) is not int:
                raise ValueError(f'{field.name} must be an integer, not a boolean or fraction')
            if type(field.default) in (float, int):
                if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                    raise ValueError(f'{field.name} must be finite and nonnegative')
        if self.dt_s <= 0 or self.camera_fps <= 0 or self.speed <= 0 or self.mask_radius <= 0:
            raise ValueError('dt/fps/speed/radius must be positive')
        if self.exposure_s > 1 / self.camera_fps or self.dt_s > 1 / self.camera_fps:
            raise ValueError('exposure and integration dt must fit a camera period')
        if self.arrival_frames < 5 or self.stable_duration_s < .25:
            raise ValueError('C confirmation requires >=5 frames and >=0.25s')
        if not 0 < self.arrival_coverage <= 1 or not 0 <= self.drop_probability <= 1:
            raise ValueError('coverage/probability outside range')
        if self.pixels_per_pitch < 16 or self.max_time_s <= 0:
            raise ValueError('invalid resolution or time limit')
        if len(self.route) < 2 or any(type(i) is not int or not 1 <= i <= 400 for i in self.route):
            raise ValueError('route needs core electrode IDs')
        for a, b in zip(self.route, self.route[1:]):
            ra, ca = divmod(a - 1, 20)
            rb, cb = divmod(b - 1, 20)
            if abs(ra-rb) + abs(ca-cb) != 1:
                raise ValueError('only manually supplied adjacent single-droplet routes')


def load_config(path):
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('mode') != 'simulation':
        raise ValueError('configuration must explicitly set mode: simulation')
    values = dict(data.get('simulation', {}))
    if 'route' in values:
        values['route'] = tuple(values['route'])
    if values.get('map_path'):
        values['map_path'] = str((path.parent / values['map_path']).resolve())
    return SimConfig(**values)
