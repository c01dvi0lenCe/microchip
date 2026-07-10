from __future__ import annotations

import heapq
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
from ..models import MultiDropletAssignment
from .geometry import target_merge_region_map
from .scheduler import _same_merge_region, schedule_assignments_with_reroute


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
) -> list[MultiDropletAssignment]:
    source_list = sorted(
        {source for source in sources if not is_waste_reservoir_cell(source)},
        key=lambda cell: electrode_id(cell[0], cell[1]),
    )
    target_list = _unique_cells(target_shape_cells)
    if not source_list or not target_list:
        return []

    raw_assignments = assign_sources_to_targets(source_list, target_list, planner, obstacles, source_capacity)
    if len(raw_assignments) != len(target_list):
        return []

    merge_regions = target_merge_region_map(target_list)
    raw_assignments = order_assignments_by_transport_dependencies(raw_assignments, merge_regions)
    raw_assignments, scheduled_paths, round_indices = schedule_assignments_with_reroute(
        raw_assignments,
        planner,
        obstacles,
        merge_regions,
    )
    if len(scheduled_paths) != len(raw_assignments):
        return []

    return [
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
