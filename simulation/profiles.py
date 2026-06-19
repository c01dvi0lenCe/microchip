from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MotionProfile:
    name: str = "ideal"
    response_delay_s: float = 0.0
    speed_scale: float = 1.0
    position_jitter_cells: float = 0.0
    stuck_probability: float = 0.0
    overshoot_probability: float = 0.0
    split_failure_probability: float = 0.0


@dataclass(frozen=True)
class VisionNoiseProfile:
    name: str = "off"
    drop_frame_rate: float = 0.0
    jitter_cells: float = 0.0
    false_detection_rate: float = 0.0
    low_contrast: float = 0.0
