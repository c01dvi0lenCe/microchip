from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterable, Optional

from simulation.profiles import MotionProfile

from .layout import Cell, GridPosition, rounded_cell


@dataclass
class SimulatedDroplet:
    start_cell: Cell
    speed_cells_per_sec: float = 2.5

    def __post_init__(self) -> None:
        self.position: GridPosition = (float(self.start_cell[0]), float(self.start_cell[1]))

    def reset(self, cell: Cell) -> None:
        self.start_cell = cell
        self.position = (float(cell[0]), float(cell[1]))

    def update_towards(
        self,
        target: Cell,
        dt_s: float,
        motion_profile: Optional[MotionProfile] = None,
        weak_fault_cells: Iterable[Cell] = (),
    ) -> GridPosition:
        if dt_s <= 0:
            return self.position
        profile = motion_profile or MotionProfile()
        if dt_s < profile.response_delay_s:
            return self.position
        if target in set(weak_fault_cells) or profile.stuck_probability >= 1.0:
            return self.position
        if profile.stuck_probability > 0.0 and random.random() < profile.stuck_probability:
            return self.position

        target_pos = (float(target[0]), float(target[1]))
        dr = target_pos[0] - self.position[0]
        dc = target_pos[1] - self.position[1]
        distance = math.hypot(dr, dc)
        if distance <= 1e-6:
            self.position = target_pos
            return self.position

        max_step = self.speed_cells_per_sec * max(0.0, profile.speed_scale) * dt_s
        if profile.overshoot_probability >= 1.0 or (
            profile.overshoot_probability > 0.0 and random.random() < profile.overshoot_probability
        ):
            max_step *= 1.18
        if max_step >= distance:
            self.position = target_pos
        else:
            scale = max_step / distance
            self.position = (self.position[0] + dr * scale, self.position[1] + dc * scale)
        if profile.position_jitter_cells > 0:
            jitter = profile.position_jitter_cells
            self.position = (self.position[0] + jitter, self.position[1] - jitter)
        return self.position

    @property
    def cell(self) -> Cell:
        return rounded_cell(self.position)
