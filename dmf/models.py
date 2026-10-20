from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .layout import Cell, GridPosition


@dataclass
class MultiDropletAssignment:
    droplet_id: int
    source: Cell
    target: Cell
    path: list[Cell]
    scheduled_path: list[Optional[Cell]]
    round_index: int = 1


@dataclass
class FaultReplanResult:
    assignments: list[MultiDropletAssignment]
    status: str
    reason: str = ""
    routing_time_ms: float = 0.0
    scheduling_time_ms: float = 0.0
    nominal_remaining_length: int = 0
    fault_remaining_length: int = 0


@dataclass
class Detection:
    grid_position: GridPosition
    cell: Cell
    pixel: tuple[float, float]
    confidence: float
    area_px: float
