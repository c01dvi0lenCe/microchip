from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

Cell = tuple[int, int]


@dataclass(frozen=True)
class StepEvent:
    stage: str
    target_cell: Optional[Cell] = None
    detected_cell: Optional[Cell] = None
    on_cells: tuple[Cell, ...] = ()
    off_cells: tuple[Cell, ...] = ()
    duration_s: float = 0.0
    action: str = ""


@dataclass
class OperationMetrics:
    operation: str
    success: bool = False
    events: list[StepEvent] = field(default_factory=list)
    replan_count: int = 0
    dropout_count: int = 0
    stall_count: int = 0
    split_failure_count: int = 0
    electrode_switch_count: int = 0

    def record_event(self, event: StepEvent) -> None:
        self.events.append(event)
        self.electrode_switch_count += len(event.on_cells) + len(event.off_cells)

    def record_replan(self) -> None:
        self.replan_count += 1

    def record_dropout(self) -> None:
        self.dropout_count += 1

    def record_stall(self) -> None:
        self.stall_count += 1

    def record_split_failure(self) -> None:
        self.split_failure_count += 1

    @property
    def total_steps(self) -> int:
        return len(self.events)

    @property
    def average_step_time_s(self) -> float:
        timed = [event.duration_s for event in self.events if event.duration_s > 0]
        if not timed:
            return 0.0
        return sum(timed) / len(timed)

    def to_csv_row(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "success": int(self.success),
            "total_steps": self.total_steps,
            "average_step_time_s": round(self.average_step_time_s, 4),
            "replan_count": self.replan_count,
            "dropout_count": self.dropout_count,
            "stall_count": self.stall_count,
            "split_failure_count": self.split_failure_count,
            "electrode_switch_count": self.electrode_switch_count,
        }
