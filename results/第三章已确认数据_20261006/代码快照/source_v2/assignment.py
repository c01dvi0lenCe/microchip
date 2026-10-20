from __future__ import annotations

import heapq
import time
from typing import Iterable, Mapping, Optional

from ..layout import (
    Cell,
    INITIAL_DROPLET_CAPACITY,
    RESERVOIR_DROPLET_CAPACITY,
    electrode_id,
    in_pull_risk_zone,
    is_reservoir_cell,
    is_waste_reservoir_cell,
)
from ..models import FaultReplanResult, MultiDropletAssignment
from .geometry import target_merge_region_map
from .scheduler import _same_merge_region, _settled_target_risk_obstacles, schedule_assignments_with_reroute


def assign_sources_to_targets(
    sources: Iterable[Cell],
    targets: Iterable[Cell],
    planner: "AStarPlanner",
    obstacles: Iterable[Cell] = (),
    source_capacity: Optional[Mapping[Cell, int]] = None,
) -> list[tuple[Cell, Cell, list[Cell]]]:
    source_list = sorted(
        {source for source in sources if not is_waste_reservoir_cell(source)},
        key=lambda cell: electrode_id(cell[0], cell[1]),
    )
    target_list = _unique_cells(targets)
    obstacles_set = set(obstacles)
    if not source_list or not target_list:
        return []

    remaining_capacity = _source_capacity_map(source_list, source_capacity)
    if sum(remaining_capacity.values()) < len(target_list):
        return []

    assignments: list[tuple[Cell, Cell, list[Cell]]] = []
    for target in target_list:
        best: Optional[tuple[int, int, int, Cell, list[Cell]]] = None
        for source in source_list:
            if remaining_capacity.get(source, 0) <= 0:
                continue
            path = planner.plan(source, target, obstacles_set - {source, target})
            if not path:
                continue
            candidate = (
                len(path),
                -remaining_capacity.get(source, 0),
                electrode_id(source[0], source[1]),
                source,
                path,
            )
            if best is None or candidate < best:
                best = candidate
        if best is None:
            return []
        _, _, _, source, path = best
        remaining_capacity[source] -= 1
        assignments.append((source, target, path))
    return sorted(assignments, key=lambda item: (electrode_id(item[0][0], item[0][1]), -len(item[2]), item[1]))


def order_assignments_by_transport_dependencies(
    assignments: Iterable[tuple[Cell, Cell, list[Cell]]],
    merge_regions: Mapping[Cell, int],
) -> list[tuple[Cell, Cell, list[Cell]]]:
    assignment_list = list(assignments)
    count = len(assignment_list)
    if count <= 1:
        return assignment_list

    edges: list[set[int]] = [set() for _ in range(count)]
    indegree = [0] * count
    for idx, (_, own_target, path) in enumerate(assignment_list):
        for other_idx, (_, other_target, _) in enumerate(assignment_list):
            if idx == other_idx:
                continue
            if _path_needs_target_clear_before_parking(path, own_target, other_target, merge_regions):
                if other_idx not in edges[idx]:
                    edges[idx].add(other_idx)
                    indegree[other_idx] += 1

    ready = [(-len(edges[idx]), idx) for idx, degree in enumerate(indegree) if degree == 0]
    heapq.heapify(ready)
    ordered_indices: list[int] = []
    while ready:
        _, idx = heapq.heappop(ready)
        ordered_indices.append(idx)
        for other_idx in sorted(edges[idx]):
            indegree[other_idx] -= 1
            if indegree[other_idx] == 0:
                heapq.heappush(ready, (-len(edges[other_idx]), other_idx))

    if len(ordered_indices) < count:
        remaining = [idx for idx in range(count) if idx not in set(ordered_indices)]
        remaining.sort(key=lambda idx: (-len(edges[idx]), indegree[idx], -len(assignment_list[idx][2]), idx))
        ordered_indices.extend(remaining)

    return [assignment_list[idx] for idx in ordered_indices]


def _path_needs_target_clear_before_parking(
    path: list[Cell],
    own_target: Cell,
    other_target: Cell,
    merge_regions: Mapping[Cell, int],
) -> bool:
    if own_target == other_target or _same_merge_region(own_target, other_target, merge_regions):
        return False
    for cell in path[:-1]:
        if cell == other_target or in_pull_risk_zone(cell, other_target):
            return True
    return False


def _source_capacity_map(
    sources: Iterable[Cell],
    source_capacity: Optional[Mapping[Cell, int]] = None,
) -> dict[Cell, int]:
    capacity: dict[Cell, int] = {}
    for source in sources:
        if is_waste_reservoir_cell(source):
            capacity[source] = 0
            continue
        if source_capacity is not None:
            value = source_capacity.get(source, 0)
        elif is_reservoir_cell(source):
            value = RESERVOIR_DROPLET_CAPACITY
        else:
            value = INITIAL_DROPLET_CAPACITY
        capacity[source] = max(0, int(value))
    return capacity


def _unique_cells(cells: Iterable[Cell]) -> list[Cell]:
    ordered: list[Cell] = []
    seen: set[Cell] = set()
    for cell in cells:
        if cell in seen:
            continue
        ordered.append(cell)
        seen.add(cell)
    return ordered

def build_multi_droplet_assignments(
    sources: Iterable[Cell],
    target_shape_cells: Iterable[Cell],
    planner: "AStarPlanner",
    obstacles: Iterable[Cell] = (),
    source_capacity: Optional[Mapping[Cell, int]] = None,
    faulty_electrodes: Iterable[Cell] = (),
    planning_metrics: Optional[dict[str, float]] = None,
) -> list[MultiDropletAssignment]:
    started_ns = time.perf_counter_ns()
    timed_planner = _TimedPlanner(planner)
    obstacle_set = set(obstacles) | set(faulty_electrodes)
    source_list = sorted(
        {source for source in sources if not is_waste_reservoir_cell(source)},
        key=lambda cell: electrode_id(cell[0], cell[1]),
    )
    target_list = _unique_cells(target_shape_cells)
    if not source_list or not target_list:
        if planning_metrics is not None:
            planning_metrics.update(
                assignment_time_ms=0.0,
                routing_time_ms=0.0,
                scheduling_time_ms=0.0,
                total_planning_time_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            )
        return []

    assignment_started_ns = time.perf_counter_ns()
    routes_before_assignment = timed_planner.elapsed_ns
    raw_assignments = assign_sources_to_targets(source_list, target_list, timed_planner, obstacle_set, source_capacity)
    assignment_finished_ns = time.perf_counter_ns()
    assignment_routing_ns = timed_planner.elapsed_ns - routes_before_assignment
    assignment_logic_ns = max(0, assignment_finished_ns - assignment_started_ns - assignment_routing_ns)
    if len(raw_assignments) != len(target_list):
        if planning_metrics is not None:
            planning_metrics.update(
                assignment_time_ms=assignment_logic_ns / 1_000_000,
                routing_time_ms=assignment_routing_ns / 1_000_000,
                scheduling_time_ms=0.0,
                total_planning_time_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            )
        return []

    merge_regions = target_merge_region_map(target_list)
    raw_assignments = order_assignments_by_transport_dependencies(raw_assignments, merge_regions)
    scheduling_started_ns = time.perf_counter_ns()
    routes_before_scheduling = timed_planner.elapsed_ns
    raw_assignments, scheduled_paths, round_indices = schedule_assignments_with_reroute(
        raw_assignments,
        timed_planner,
        obstacle_set,
        merge_regions,
    )
    scheduling_finished_ns = time.perf_counter_ns()
    scheduling_routing_ns = timed_planner.elapsed_ns - routes_before_scheduling
    if len(scheduled_paths) != len(raw_assignments):
        if planning_metrics is not None:
            planning_metrics.update(
                assignment_time_ms=assignment_logic_ns / 1_000_000,
                routing_time_ms=(assignment_routing_ns + scheduling_routing_ns) / 1_000_000,
                scheduling_time_ms=max(
                    0, scheduling_finished_ns - scheduling_started_ns - scheduling_routing_ns
                ) / 1_000_000,
                total_planning_time_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            )
        return []

    assignments = [
        MultiDropletAssignment(
            droplet_id=idx,
            source=source,
            target=target,
            path=path,
            scheduled_path=scheduled_paths[idx - 1],
            round_index=round_indices[idx - 1],
        )
        for idx, (source, target, path) in enumerate(raw_assignments, start=1)
    ]
    if planning_metrics is not None:
        total_ns = time.perf_counter_ns() - started_ns
        planning_metrics.update(
            assignment_time_ms=assignment_logic_ns / 1_000_000,
            routing_time_ms=(assignment_routing_ns + scheduling_routing_ns) / 1_000_000,
            scheduling_time_ms=max(
                0, scheduling_finished_ns - scheduling_started_ns - scheduling_routing_ns
            ) / 1_000_000,
            total_planning_time_ms=total_ns / 1_000_000,
        )
    return assignments


def replan_multi_assignments_after_fault(
    assignments: Iterable[MultiDropletAssignment],
    current_positions: Mapping[int, Cell],
    completed_droplet_ids: Iterable[int],
    static_obstacles: Iterable[Cell],
    faulty_electrodes: Iterable[Cell],
    planner: "AStarPlanner",
) -> FaultReplanResult:
    """Reroute every unfinished task and reschedule it around fixed completed goals."""
    assignment_list = list(assignments)
    completed = set(completed_droplet_ids)
    faults = set(faulty_electrodes)
    obstacles = set(static_obstacles) | faults
    unfinished = [item for item in assignment_list if item.droplet_id not in completed]
    if not unfinished:
        return FaultReplanResult(assignment_list, "completed")

    timed_planner = _TimedPlanner(planner)
    nominal_length = 0
    paths: list[tuple[Cell, Cell, list[Cell]]] = []
    by_id: dict[int, tuple[Cell, list[Cell]]] = {}
    completed_items = [item for item in assignment_list if item.droplet_id in completed]
    merge_regions = target_merge_region_map(item.target for item in assignment_list)
    completed_targets = [item.target for item in completed_items]
    for assignment in unfinished:
        start = current_positions.get(assignment.droplet_id)
        if start is None or start in faults or assignment.target in faults:
            return FaultReplanResult(
                assignment_list,
                "unreachable",
                f"D{assignment.droplet_id} 当前格或目标格不可用",
                nominal_remaining_length=nominal_length,
            )
        completed_risk = _settled_target_risk_obstacles(
            assignment.target,
            completed_targets,
            merge_regions,
        )
        nominal_obstacles = set(static_obstacles) | completed_risk
        nominal = planner.plan(start, assignment.target, nominal_obstacles - {start, assignment.target})
        nominal_length += max(0, len(nominal) - 1)
        safe_obstacles = obstacles | completed_risk
        route = timed_planner.plan(start, assignment.target, safe_obstacles - {start, assignment.target})
        if not route:
            return FaultReplanResult(
                assignment_list,
                "unreachable",
                f"D{assignment.droplet_id} 从 {start} 到 {assignment.target} 不可达",
                routing_time_ms=timed_planner.elapsed_ns / 1_000_000,
                nominal_remaining_length=nominal_length,
            )
        paths.append((start, assignment.target, route))
        by_id[assignment.droplet_id] = (start, route)

    max_wait_steps = 220
    horizon = sum(len(path) + 2 * max_wait_steps + 1 for _source, _target, path in paths) + 1
    fixed_holds = [[item.target] * horizon for item in completed_items]
    schedule_started_ns = time.perf_counter_ns()
    scheduled_assignments, schedules, rounds = schedule_assignments_with_reroute(
        paths,
        timed_planner,
        obstacles,
        merge_regions,
        existing_paths=fixed_holds,
        hold_start_during_delay=True,
    )
    schedule_elapsed_ns = time.perf_counter_ns() - schedule_started_ns
    routing_ns = timed_planner.elapsed_ns
    if not (len(schedules) == len(paths) == len(scheduled_assignments) == len(rounds)):
        return FaultReplanResult(
            assignment_list,
            "protective_pause",
            "剩余路径无法通过当前预约约束完成时序协调",
            routing_time_ms=routing_ns / 1_000_000,
            scheduling_time_ms=max(0, schedule_elapsed_ns - routing_ns) / 1_000_000,
            nominal_remaining_length=nominal_length,
        )

    # Validate the whole continuation before mutating any live assignment.
    expected_start_by_target = {assignment.target: by_id[assignment.droplet_id][0] for assignment in unfinished}
    identity_valid = (
        len(expected_start_by_target) == len(unfinished)
        and {target for _source, target, _path in scheduled_assignments} == set(expected_start_by_target)
        and all(
            source == expected_start_by_target[target]
            and path and path[0] == source and path[-1] == target
            and schedule and schedule[0] == source and schedule[-1] == target
            and all(cell is not None for cell in schedule)
            for (source, target, path), schedule in zip(scheduled_assignments, schedules)
        )
    )
    if not identity_valid:
        return FaultReplanResult(
            assignment_list,
            "protective_pause",
            "剩余调度未保持液滴身份、当前起点或连续占据",
            routing_time_ms=routing_ns / 1_000_000,
            scheduling_time_ms=max(0, schedule_elapsed_ns - routing_ns) / 1_000_000,
            nominal_remaining_length=nominal_length,
        )

    scheduled_by_target = {
        target: (path, schedule, round_index)
        for (_source, target, path), schedule, round_index in zip(scheduled_assignments, schedules, rounds)
    }
    timeline = max((len(schedule) for schedule in schedules), default=1)
    result_assignments: list[MultiDropletAssignment] = []
    fault_length = 0
    for assignment in assignment_list:
        if assignment.droplet_id in completed:
            assignment.scheduled_path = [assignment.target] * timeline
            result_assignments.append(assignment)
            continue
        start, _initial_route = by_id[assignment.droplet_id]
        route, schedule, round_index = scheduled_by_target[assignment.target]
        assignment.source = start
        assignment.path = route
        assignment.scheduled_path = schedule
        assignment.round_index = round_index
        fault_length += max(0, len(route) - 1)
        result_assignments.append(assignment)
    return FaultReplanResult(
        result_assignments,
        "success",
        routing_time_ms=routing_ns / 1_000_000,
        scheduling_time_ms=max(0, schedule_elapsed_ns - routing_ns) / 1_000_000,
        nominal_remaining_length=nominal_length,
        fault_remaining_length=fault_length,
    )


class _TimedPlanner:
    def __init__(self, planner):
        self._planner = planner
        self.elapsed_ns = 0

    def plan(self, start, goal, obstacles=()):
        started = time.perf_counter_ns()
        try:
            return self._planner.plan(start, goal, obstacles)
        finally:
            self.elapsed_ns += time.perf_counter_ns() - started

    def __getattr__(self, name):
        return getattr(self._planner, name)
