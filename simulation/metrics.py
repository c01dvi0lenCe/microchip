from __future__ import annotations

from dataclasses import dataclass, field
import json
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
    planning_status: str = "unknown"
    faulty_electrodes: list[tuple[int, int]] = field(default_factory=list)
    path_lengths: dict[int, int] = field(default_factory=dict)
    scheduled_makespan_steps: int = 0
    wait_steps_by_droplet: dict[int, int] = field(default_factory=dict)
    release_delay_steps_by_droplet: dict[int, int] = field(default_factory=dict)
    deviation_replan_count: int = 0
    fault_global_replan_count: int = 0
    fault_replan_compute_times_ms: list[float] = field(default_factory=list)
    fault_detour_ratios: list[float | None] = field(default_factory=list)
    assignment_time_ms: float = 0.0
    routing_time_ms: float = 0.0
    scheduling_time_ms: float = 0.0
    total_planning_time_ms: float = 0.0

    def record_event(self, event: StepEvent) -> None:
        self.events.append(event)
        self.electrode_switch_count += len(event.on_cells) + len(event.off_cells)

    def record_replan(self) -> None:
        self.replan_count += 1

    def record_deviation_replan(self) -> None:
        self.replan_count += 1
        self.deviation_replan_count += 1

    def record_fault_replan(self, compute_time_ms: float, detour_ratio: float | None) -> None:
        self.replan_count += 1
        self.fault_global_replan_count += 1
        self.fault_replan_compute_times_ms.append(max(0.0, float(compute_time_ms)))
        self.fault_detour_ratios.append(detour_ratio)

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
            "planning_status": self.planning_status,
            "faulty_electrodes": json.dumps(self.faulty_electrodes),
            "path_lengths": json.dumps(self.path_lengths, sort_keys=True),
            "total_spatial_path_length": sum(self.path_lengths.values()),
            "scheduled_makespan_steps": self.scheduled_makespan_steps,
            "wait_steps_by_droplet": json.dumps(self.wait_steps_by_droplet, sort_keys=True),
            "wait_steps_total": sum(self.wait_steps_by_droplet.values()),
            "release_delay_steps_by_droplet": json.dumps(self.release_delay_steps_by_droplet, sort_keys=True),
            "deviation_replan_count": self.deviation_replan_count,
            "fault_global_replan_count": self.fault_global_replan_count,
            "fault_replan_compute_times_ms": json.dumps(self.fault_replan_compute_times_ms),
            "fault_detour_ratios": json.dumps(self.fault_detour_ratios),
            "assignment_time_ms": round(self.assignment_time_ms, 6),
            "routing_time_ms": round(self.routing_time_ms, 6),
            "scheduling_time_ms": round(self.scheduling_time_ms, 6),
            "total_planning_time_ms": round(self.total_planning_time_ms, 6),
        }
