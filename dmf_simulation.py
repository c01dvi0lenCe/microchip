from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
import random
from typing import Iterable, Mapping, Optional

import numpy as np

from simulation.metrics import OperationMetrics, StepEvent
from simulation.profiles import MotionProfile, VisionNoiseProfile

try:
    import cv2
except ImportError:  # pragma: no cover - exercised only on machines without OpenCV.
    cv2 = None


GRID_ROWS = 20
GRID_COLS = 20
ELECTRODE_PITCH_MM = 3.2
BOARD_FRAME_MM = 100.0
INITIAL_DROPLET_CAPACITY = 1
RESERVOIR_DROPLET_CAPACITY = 5
MAX_PARALLEL_MULTI_DROPLETS = GRID_ROWS * GRID_COLS
CAMERA_LAYOUT_PADDING_CELLS = 5.4
DROPLET_DETECTION_RGB = (
    (24, 82, 194),
    (178, 58, 72),
    (155, 77, 202),
    (0, 123, 131),
    (199, 125, 0),
    (78, 122, 46),
    (47, 95, 154),
    (125, 79, 42),
)
DROPLET_DETECTION_TOLERANCE = 30

SIDE_RESERVOIR_COLS = (6, 13)
SIDE_RESERVOIR_ROWS = (6, 13)

CORNER_RESERVOIRS = frozenset({(-1, -1), (-1, GRID_COLS), (GRID_ROWS, -1), (GRID_ROWS, GRID_COLS)})
SIDE_RESERVOIR_SMALL = frozenset(
    {(-1, col) for col in SIDE_RESERVOIR_COLS}
    | {(GRID_ROWS, col) for col in SIDE_RESERVOIR_COLS}
    | {(row, -1) for row in SIDE_RESERVOIR_ROWS}
    | {(row, GRID_COLS) for row in SIDE_RESERVOIR_ROWS}
)
SIDE_RESERVOIR_LARGE = frozenset(
    {(-3, col) for col in SIDE_RESERVOIR_COLS}
    | {(GRID_ROWS + 2, col) for col in SIDE_RESERVOIR_COLS}
    | {(row, -3) for row in SIDE_RESERVOIR_ROWS}
    | {(row, GRID_COLS + 2) for row in SIDE_RESERVOIR_ROWS}
)
RESERVOIR_CELLS = frozenset(CORNER_RESERVOIRS | SIDE_RESERVOIR_SMALL | SIDE_RESERVOIR_LARGE)
WASTE_RESERVOIRS = CORNER_RESERVOIRS
DISPENSE_RESERVOIRS = frozenset(RESERVOIR_CELLS - WASTE_RESERVOIRS)
CORE_CELLS = frozenset((row, col) for row in range(GRID_ROWS) for col in range(GRID_COLS))
LAYOUT_CELLS = frozenset(CORE_CELLS | RESERVOIR_CELLS)
RESERVOIR_ID_BY_CELL = {
    (-1, 6): 401,
    (-3, 6): 402,
    (-1, 13): 403,
    (-3, 13): 404,
    (6, GRID_COLS): 405,
    (6, GRID_COLS + 2): 406,
    (13, GRID_COLS): 407,
    (13, GRID_COLS + 2): 408,
    (GRID_ROWS, 13): 409,
    (GRID_ROWS + 2, 13): 410,
    (GRID_ROWS, 6): 411,
    (GRID_ROWS + 2, 6): 412,
    (13, -1): 413,
    (13, -3): 414,
    (6, -1): 415,
    (6, -3): 416,
    (-1, -1): 417,
    (-1, GRID_COLS): 418,
    (GRID_ROWS, GRID_COLS): 419,
    (GRID_ROWS, -1): 420,
}
RESERVOIR_CELL_BY_ID = {eid: cell for cell, eid in RESERVOIR_ID_BY_CELL.items()}

RESERVOIR_CONNECTIONS = {
    (-3, 6): (-1, 6),
    (-3, 13): (-1, 13),
    (-1, 6): (0, 6),
    (-1, 13): (0, 13),
    (GRID_ROWS + 2, 6): (GRID_ROWS, 6),
    (GRID_ROWS + 2, 13): (GRID_ROWS, 13),
    (GRID_ROWS, 6): (GRID_ROWS - 1, 6),
    (GRID_ROWS, 13): (GRID_ROWS - 1, 13),
    (6, -3): (6, -1),
    (13, -3): (13, -1),
    (6, -1): (6, 0),
    (13, -1): (13, 0),
    (6, GRID_COLS + 2): (6, GRID_COLS),
    (13, GRID_COLS + 2): (13, GRID_COLS),
    (6, GRID_COLS): (6, GRID_COLS - 1),
    (13, GRID_COLS): (13, GRID_COLS - 1),
    (-1, -1): (0, 0),
    (-1, GRID_COLS): (0, GRID_COLS - 1),
    (GRID_ROWS, -1): (GRID_ROWS - 1, 0),
    (GRID_ROWS, GRID_COLS): (GRID_ROWS - 1, GRID_COLS - 1),
}

Cell = tuple[int, int]
GridPosition = tuple[float, float]


def electrode_id(row: int, col: int, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> int:
    cell = (row, col)
    if cell in RESERVOIR_ID_BY_CELL:
        return RESERVOIR_ID_BY_CELL[cell]
    if row < 0 or row >= rows or col < 0 or col >= cols:
        raise ValueError(f"Invalid electrode cell ({row}, {col})")
    return row * cols + col + 1


def cell_from_electrode_id(eid: int, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> Cell:
    if eid in RESERVOIR_CELL_BY_ID:
        return RESERVOIR_CELL_BY_ID[eid]
    if eid < 1 or eid > rows * cols:
        raise ValueError(f"Invalid electrode id {eid}")
    idx = eid - 1
    return idx // cols, idx % cols


def cell_center_mm(cell: Cell, pitch_mm: float = ELECTRODE_PITCH_MM) -> tuple[float, float]:
    row, col = cell
    return (col + 0.5) * pitch_mm, (row + 0.5) * pitch_mm


def clamp_cell(cell: Cell, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> Cell:
    row, col = cell
    return max(0, min(rows - 1, row)), max(0, min(cols - 1, col))


def rounded_cell(position: GridPosition, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> Cell:
    candidate = (int(round(position[0])), int(round(position[1])))
    if candidate in LAYOUT_CELLS:
        return candidate
    return clamp_cell(candidate, rows, cols)


def is_reservoir_cell(cell: Cell) -> bool:
    return cell in RESERVOIR_CELLS


def is_waste_reservoir_cell(cell: Cell) -> bool:
    return cell in WASTE_RESERVOIRS


def is_dispense_reservoir_cell(cell: Cell) -> bool:
    return cell in DISPENSE_RESERVOIRS


def is_core_cell(cell: Cell, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> bool:
    row, col = cell
    return 0 <= row < rows and 0 <= col < cols


def are_touching(a: Cell, b: Cell) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 1


def in_pull_risk_zone(a: Cell, b: Cell) -> bool:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1


def grid_polyline_cells(points: Iterable[Cell], rows: int = GRID_ROWS, cols: int = GRID_COLS) -> list[Cell]:
    clean_points = [point for point in points if is_core_cell(point, rows, cols)]
    if not clean_points:
        return []

    cells: list[Cell] = [clean_points[0]]
    for start, end in zip(clean_points, clean_points[1:]):
        row, col = start
        end_row, end_col = end
        row_step = 1 if end_row >= row else -1
        for next_row in range(row + row_step, end_row + row_step, row_step):
            candidate = (next_row, col)
            if candidate != cells[-1]:
                cells.append(candidate)
        col_step = 1 if end_col >= col else -1
        for next_col in range(col + col_step, end_col + col_step, col_step):
            candidate = (end_row, next_col)
            if candidate != cells[-1]:
                cells.append(candidate)
    return cells


def sample_non_adjacent_targets(shape_cells: Iterable[Cell], count: int) -> list[Cell]:
    if count <= 0:
        return []

    ordered_cells: list[Cell] = []
    seen: set[Cell] = set()
    for cell in shape_cells:
        if cell in seen:
            continue
        ordered_cells.append(cell)
        seen.add(cell)

    if not ordered_cells:
        return []
    if count == 1:
        return [ordered_cells[len(ordered_cells) // 2]]

    desired_indices = [
        round(i * (len(ordered_cells) - 1) / (count - 1))
        for i in range(count)
    ]
    selected: list[Cell] = []
    selected_indices: set[int] = set()
    for desired in desired_indices:
        search_order = sorted(range(len(ordered_cells)), key=lambda idx: (abs(idx - desired), idx))
        for idx in search_order:
            cell = ordered_cells[idx]
            if idx in selected_indices:
                continue
            if any(are_touching(cell, chosen) for chosen in selected):
                continue
            selected.append(cell)
            selected_indices.add(idx)
            break

    if len(selected) == count:
        return selected

    selected = []
    for cell in ordered_cells:
        if any(are_touching(cell, chosen) for chosen in selected):
            continue
        selected.append(cell)
        if len(selected) == count:
            return selected
    return []


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


def target_merge_region_map(cells: Iterable[Cell]) -> dict[Cell, int]:
    remaining = set(cells)
    regions: dict[Cell, int] = {}
    region_id = 0
    while remaining:
        region_id += 1
        start = remaining.pop()
        regions[start] = region_id
        stack = [start]
        while stack:
            row, col = stack.pop()
            for nxt in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if nxt not in remaining:
                    continue
                remaining.remove(nxt)
                regions[nxt] = region_id
                stack.append(nxt)
    return regions


def target_proximity_region_map(cells: Iterable[Cell], max_gap: int = 2) -> dict[Cell, int]:
    remaining = set(cells)
    regions: dict[Cell, int] = {}
    region_id = 0
    while remaining:
        region_id += 1
        start = remaining.pop()
        regions[start] = region_id
        stack = [start]
        while stack:
            row, col = stack.pop()
            linked = [
                cell
                for cell in remaining
                if max(abs(cell[0] - row), abs(cell[1] - col)) <= max_gap
            ]
            for cell in linked:
                remaining.remove(cell)
                regions[cell] = region_id
                stack.append(cell)
    return regions


def schedule_multi_paths(
    paths: Iterable[list[Cell]],
    max_wait_steps: int = 220,
    existing_paths: Iterable[list[Optional[Cell]]] = (),
    min_start_delay: int = 0,
    merge_cells: Iterable[Cell] = (),
    merge_regions: Optional[Mapping[Cell, int]] = None,
    allow_settled_goal_adjacency: bool = False,
) -> list[list[Optional[Cell]]]:
    scheduled_paths: list[list[Optional[Cell]]] = [list(path) for path in existing_paths]
    new_schedules: list[list[Optional[Cell]]] = []
    region_map = dict(merge_regions) if merge_regions is not None else target_merge_region_map(merge_cells)
    for path in paths:
        if not path:
            return []
        scheduled = _schedule_one_multi_path(
            path,
            scheduled_paths,
            max_wait_steps,
            min_start_delay,
            region_map,
            allow_settled_goal_adjacency=allow_settled_goal_adjacency,
        )
        if not scheduled:
            return []
        scheduled_paths.append(scheduled)
        new_schedules.append(scheduled)
    return new_schedules


def _schedule_one_multi_path(
    path: list[Cell],
    existing_paths: list[list[Optional[Cell]]],
    max_wait_steps: int,
    min_start_delay: int = 0,
    merge_regions: Optional[Mapping[Cell, int]] = None,
    allow_settled_goal_adjacency: bool = False,
) -> list[Optional[Cell]]:
    own_goal = path[-1]
    region_map = dict(merge_regions or {})
    for start_delay in range(min_start_delay, min_start_delay + max_wait_steps + 1):
        scheduled: list[Optional[Cell]] = [None] * start_delay
        path_index = 0
        wait_steps = 0
        failed = False
        while path_index < len(path):
            step = len(scheduled)
            previous_cell = scheduled[-1] if scheduled else None
            candidate_cell = path[path_index]
            if _multi_step_conflicts(
                existing_paths,
                previous_cell,
                candidate_cell,
                step,
                own_goal,
                region_map,
                allow_settled_goal_adjacency=allow_settled_goal_adjacency,
            ):
                if previous_cell is None:
                    failed = True
                    break
                if _multi_step_conflicts(
                    existing_paths,
                    previous_cell,
                    previous_cell,
                    step,
                    own_goal,
                    region_map,
                    allow_settled_goal_adjacency=allow_settled_goal_adjacency,
                ):
                    failed = True
                    break
                scheduled.append(previous_cell)
                wait_steps += 1
                if wait_steps > max_wait_steps:
                    failed = True
                    break
                continue
            scheduled.append(candidate_cell)
            path_index += 1
        if not failed:
            return scheduled
    return []


def schedule_multi_paths_by_contamination_groups(
    paths: Iterable[list[Cell]],
    group_ids: Iterable[int],
    max_parallel: int = 4,
    max_wait_steps: int = 220,
    merge_cells: Iterable[Cell] = (),
    merge_regions: Optional[Mapping[Cell, int]] = None,
    allow_settled_goal_adjacency: bool = False,
) -> tuple[list[list[Optional[Cell]]], list[int]]:
    path_list = list(paths)
    group_list = list(group_ids)
    if not path_list:
        return [], []
    if len(path_list) != len(group_list):
        return [], []

    max_parallel = max(1, min(max_parallel, len(path_list)))
    region_map = dict(merge_regions) if merge_regions is not None else target_merge_region_map(merge_cells)
    combined: list[list[Optional[Cell]]] = []
    scheduled_by_index: list[Optional[list[Optional[Cell]]]] = [None] * len(path_list)
    round_indices: list[int] = [1] * len(path_list)
    group_state: dict[int, dict[str, int]] = {}

    for idx, (path, group_id) in enumerate(zip(path_list, group_list)):
        state = group_state.setdefault(
            group_id,
            {"round": 1, "count": 0, "start": 0, "end": 0},
        )
        if state["count"] >= max_parallel:
            state["round"] += 1
            state["count"] = 0
            state["start"] = state["end"]

        scheduled = _schedule_one_multi_path(
            path,
            combined,
            max_wait_steps=max_wait_steps,
            min_start_delay=state["start"],
            merge_regions=region_map,
            allow_settled_goal_adjacency=allow_settled_goal_adjacency,
        )
        if not scheduled:
            return [], []

        combined.append(scheduled)
        scheduled_by_index[idx] = scheduled
        round_indices[idx] = state["round"]
        state["count"] += 1
        state["end"] = max(state["end"], len(scheduled))

    if any(schedule is None for schedule in scheduled_by_index):
        return [], []
    return [schedule for schedule in scheduled_by_index if schedule is not None], round_indices


def schedule_multi_paths_in_rounds(
    paths: Iterable[list[Cell]],
    max_parallel: int = 4,
    max_wait_steps: int = 220,
    merge_cells: Iterable[Cell] = (),
    allow_settled_goal_adjacency: bool = False,
) -> tuple[list[list[Optional[Cell]]], list[int]]:
    path_list = list(paths)
    merge_regions = target_merge_region_map(merge_cells)
    group_ids = [merge_regions.get(path[-1], idx + 1) for idx, path in enumerate(path_list)]
    return schedule_multi_paths_by_contamination_groups(
        path_list,
        group_ids,
        max_parallel=max_parallel,
        max_wait_steps=max_wait_steps,
        merge_regions=merge_regions,
        allow_settled_goal_adjacency=allow_settled_goal_adjacency,
    )


def schedule_assignments_with_reroute(
    assignments: Iterable[tuple[Cell, Cell, list[Cell]]],
    planner: "AStarPlanner",
    obstacles: Iterable[Cell],
    merge_regions: Mapping[Cell, int],
    max_parallel: int = MAX_PARALLEL_MULTI_DROPLETS,
    max_wait_steps: int = 80,
) -> tuple[list[tuple[Cell, Cell, list[Cell]]], list[list[Optional[Cell]]], list[int]]:
    assignment_list = list(assignments)
    if not assignment_list:
        return [], [], []

    result = _schedule_assignments_with_reroute_core(
        assignment_list,
        planner,
        obstacles,
        merge_regions,
        max_parallel,
        max_wait_steps,
    )
    if result[0]:
        return result

    return _schedule_assignments_in_fill_batches(
        assignment_list,
        planner,
        obstacles,
        merge_regions,
        max_parallel,
        max_wait_steps,
    )


def _schedule_assignments_in_fill_batches(
    assignments: Iterable[tuple[Cell, Cell, list[Cell]]],
    planner: "AStarPlanner",
    obstacles: Iterable[Cell],
    merge_regions: Mapping[Cell, int],
    max_parallel: int,
    max_wait_steps: int,
) -> tuple[list[tuple[Cell, Cell, list[Cell]]], list[list[Optional[Cell]]], list[int]]:
    assignment_list = list(assignments)
    if not assignment_list:
        return [], [], []

    max_parallel = max(1, max_parallel)
    max_wait_steps = max(max_wait_steps, 220)
    base_obstacles = set(obstacles)
    pending_targets = [target for _source, target, _path in assignment_list]
    source_capacity: dict[Cell, int] = {}
    for source, _target, _path in assignment_list:
        if is_reservoir_cell(source):
            source_capacity[source] = RESERVOIR_DROPLET_CAPACITY
        else:
            source_capacity[source] = source_capacity.get(source, 0) + INITIAL_DROPLET_CAPACITY
    sources = sorted(source_capacity, key=lambda cell: electrode_id(cell[0], cell[1]))
    combined: list[list[Optional[Cell]]] = []
    scheduled_assignments: list[tuple[Cell, Cell, list[Cell]]] = []
    scheduled_paths: list[list[Optional[Cell]]] = []
    round_indices: list[int] = []
    settled_targets: list[Cell] = []
    round_index = 1

    while pending_targets:
        round_start = max((len(schedule) for schedule in combined), default=0)
        scheduled_this_round = 0

        while pending_targets and scheduled_this_round < max_parallel:
            best: Optional[tuple[int, int, int, int, int, Cell, Cell, list[Cell], list[Optional[Cell]]]] = None
            for target_index, target in enumerate(pending_targets):
                safe_obstacles = base_obstacles | _settled_target_risk_obstacles(
                    target,
                    settled_targets,
                    merge_regions,
                )
                for source in sources:
                    if source_capacity.get(source, 0) <= 0:
                        continue
                    path = planner.plan(source, target, safe_obstacles - {source, target})
                    if not path:
                        continue
                    scheduled = _schedule_one_multi_path(
                        path,
                        combined,
                        max_wait_steps=max_wait_steps,
                        min_start_delay=round_start,
                        merge_regions=merge_regions,
                        allow_settled_goal_adjacency=True,
                    )
                    if not scheduled:
                        continue
                    first_active_step = next(
                        (step for step, cell in enumerate(scheduled) if cell is not None),
                        len(scheduled),
                    )
                    candidate = (
                        -_target_fill_priority(target),
                        first_active_step,
                        len(path),
                        target_index,
                        -source_capacity.get(source, 0),
                        electrode_id(source[0], source[1]),
                        source,
                        target,
                        path,
                        scheduled,
                    )
                    if best is None or candidate < best:
                        best = candidate

            if best is None:
                break

            _fill_priority, _first_active_step, _path_len, target_index, _priority, _eid, source, target, path, scheduled = best
            pending_targets.pop(target_index)
            source_capacity[source] -= 1
            combined.append(scheduled)
            scheduled_assignments.append((source, target, path))
            scheduled_paths.append(scheduled)
            round_indices.append(round_index)
            settled_targets.append(target)
            scheduled_this_round += 1

        if scheduled_this_round == 0:
            return [], [], []
        round_index += 1

    if len(scheduled_paths) != len(assignment_list):
        return [], [], []
    return scheduled_assignments, scheduled_paths, round_indices


def _target_fill_priority(target: Cell) -> int:
    row, col = target
    if not is_core_cell(target):
        return 0
    edge_depth = min(row, col, GRID_ROWS - 1 - row, GRID_COLS - 1 - col)
    center_bias = (GRID_ROWS - abs(2 * row - (GRID_ROWS - 1))) + (GRID_COLS - abs(2 * col - (GRID_COLS - 1)))
    return edge_depth * 100 + center_bias


def _schedule_assignments_with_reroute_core(
    assignments: Iterable[tuple[Cell, Cell, list[Cell]]],
    planner: "AStarPlanner",
    obstacles: Iterable[Cell],
    merge_regions: Mapping[Cell, int],
    max_parallel: int,
    max_wait_steps: int,
) -> tuple[list[tuple[Cell, Cell, list[Cell]]], list[list[Optional[Cell]]], list[int]]:
    assignment_list = list(assignments)
    if not assignment_list:
        return [], [], []

    max_repairs = max(1, min(len(assignment_list) * 2, len(assignment_list) * len(assignment_list)))
    seen_orders: set[tuple[tuple[Cell, Cell], ...]] = set()
    for _ in range(max_repairs + 1):
        order_signature = tuple((source, target) for source, target, _path in assignment_list)
        if order_signature in seen_orders:
            return [], [], []
        seen_orders.add(order_signature)
        scheduled_assignments, scheduled_paths, round_indices, failed_index, blocker_index = _try_schedule_assignment_order(
            assignment_list,
            planner,
            obstacles,
            merge_regions,
            max_parallel,
            max_wait_steps,
        )
        if failed_index is None:
            return scheduled_assignments, scheduled_paths, round_indices
        if blocker_index is None or blocker_index >= failed_index:
            return [], [], []
        blocked_assignment = assignment_list.pop(failed_index)
        assignment_list.insert(blocker_index, blocked_assignment)

    return [], [], []


def _try_schedule_assignment_order(
    assignment_list: list[tuple[Cell, Cell, list[Cell]]],
    planner: "AStarPlanner",
    obstacles: Iterable[Cell],
    merge_regions: Mapping[Cell, int],
    max_parallel: int,
    max_wait_steps: int,
) -> tuple[
    list[tuple[Cell, Cell, list[Cell]]],
    list[list[Optional[Cell]]],
    list[int],
    Optional[int],
    Optional[int],
]:
    combined: list[list[Optional[Cell]]] = []
    scheduled_assignments: list[tuple[Cell, Cell, list[Cell]]] = []
    scheduled_paths: list[list[Optional[Cell]]] = []
    round_indices: list[int] = []
    scheduled_targets: list[Cell] = []
    group_state: dict[int, dict[str, int]] = {}
    base_obstacles = set(obstacles)

    for idx, (source, target, path) in enumerate(assignment_list):
        group_id = merge_regions.get(target, idx + 1)
        state = group_state.setdefault(
            group_id,
            {"round": 1, "count": 0, "start": 0, "end": 0},
        )
        if state["count"] >= max_parallel:
            state["round"] += 1
            state["count"] = 0
            state["start"] = state["end"]

        scheduled = _schedule_one_multi_path(
            path,
            combined,
            max_wait_steps=max_wait_steps,
            min_start_delay=state["start"],
            merge_regions=merge_regions,
            allow_settled_goal_adjacency=True,
        )
        if not scheduled:
            reroute_obstacles = base_obstacles | _settled_target_risk_obstacles(
                target,
                scheduled_targets,
                merge_regions,
            )
            rerouted_path = planner.plan(source, target, reroute_obstacles - {source, target})
            if rerouted_path and rerouted_path != path:
                path = rerouted_path
                scheduled = _schedule_one_multi_path(
                    path,
                    combined,
                    max_wait_steps=max_wait_steps,
                    min_start_delay=state["start"],
                    merge_regions=merge_regions,
                    allow_settled_goal_adjacency=True,
                )
        if not scheduled:
            blocker_index = _first_target_blocker_index(path, target, scheduled_assignments, merge_regions)
            return [], [], [], idx, blocker_index

        combined.append(scheduled)
        scheduled_assignments.append((source, target, path))
        scheduled_paths.append(scheduled)
        round_indices.append(state["round"])
        scheduled_targets.append(target)
        state["count"] += 1
        state["end"] = max(state["end"], len(scheduled))

    return scheduled_assignments, scheduled_paths, round_indices, None, None


def _first_target_blocker_index(
    path: list[Cell],
    target: Cell,
    scheduled_assignments: Iterable[tuple[Cell, Cell, list[Cell]]],
    merge_regions: Mapping[Cell, int],
) -> Optional[int]:
    for idx, (_, settled_target, _) in enumerate(scheduled_assignments):
        if _same_merge_region(target, settled_target, merge_regions):
            continue
        for cell in path[:-1]:
            if cell == settled_target or in_pull_risk_zone(cell, settled_target):
                return idx
    return None


def _settled_target_risk_obstacles(
    target: Cell,
    settled_targets: Iterable[Cell],
    merge_regions: Mapping[Cell, int],
) -> set[Cell]:
    obstacles: set[Cell] = set()
    for settled_target in settled_targets:
        if _same_merge_region(target, settled_target, merge_regions):
            continue
        row, col = settled_target
        for row_delta in (-1, 0, 1):
            for col_delta in (-1, 0, 1):
                cell = (row + row_delta, col + col_delta)
                if cell in LAYOUT_CELLS:
                    obstacles.add(cell)
    obstacles.discard(target)
    return obstacles


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


def _multi_step_conflicts(
    existing_paths: Iterable[list[Optional[Cell]]],
    previous_cell: Optional[Cell],
    candidate_cell: Optional[Cell],
    step: int,
    own_goal: Cell,
    merge_regions: Mapping[Cell, int],
    allow_settled_goal_adjacency: bool = False,
) -> bool:
    if candidate_cell is None:
        return False
    current_is_moving = previous_cell is not None and candidate_cell != previous_cell
    existing_path_list = list(existing_paths)
    if candidate_cell == own_goal and _settled_goal_would_block_future_transport(
        existing_path_list,
        candidate_cell,
        step,
        merge_regions,
        allow_settled_goal_adjacency,
    ):
        return True
    for existing in existing_path_list:
        other_now = existing[step] if step < len(existing) else existing[-1]
        if step <= 0:
            other_prev = None
        elif step - 1 < len(existing):
            other_prev = existing[step - 1]
        else:
            other_prev = existing[-1]
        other_goal = next((cell for cell in reversed(existing) if cell is not None), None)
        if other_now is None:
            continue
        other_is_moving = other_prev is not None and other_now != other_prev
        if candidate_cell == other_now:
            return True
        if (
            current_is_moving
            and other_prev is not None
            and in_pull_risk_zone(candidate_cell, other_prev)
            and not _can_share_settled_goal_risk(
                candidate_cell,
                own_goal,
                other_prev,
                other_goal,
                merge_regions,
                allow_settled_goal_adjacency,
            )
        ):
            return True
        if (
            other_is_moving
            and previous_cell is not None
            and in_pull_risk_zone(other_now, previous_cell)
            and not _can_share_settled_goal_risk(
                previous_cell,
                own_goal,
                other_now,
                other_goal,
                merge_regions,
                allow_settled_goal_adjacency,
            )
        ):
            return True
        if in_pull_risk_zone(candidate_cell, other_now):
            if not _can_share_settled_goal_risk(
                candidate_cell,
                own_goal,
                other_now,
                other_goal,
                merge_regions,
                allow_settled_goal_adjacency,
            ):
                return True
        if previous_cell is not None and other_prev is not None and previous_cell == other_now and candidate_cell == other_prev:
            return True
    return False


def _can_share_settled_goal_risk(
    candidate_cell: Cell,
    own_goal: Cell,
    other_cell: Cell,
    other_goal: Optional[Cell],
    merge_regions: Mapping[Cell, int],
    allow_settled_goal_adjacency: bool,
) -> bool:
    if not allow_settled_goal_adjacency:
        return False
    if other_goal is None or other_cell != other_goal:
        return False
    return _same_merge_region(own_goal, other_cell, merge_regions)


def _same_merge_region(a: Cell, b: Cell, merge_regions: Mapping[Cell, int]) -> bool:
    region = merge_regions.get(a)
    return region is not None and region == merge_regions.get(b)


def _settled_goal_would_block_future_transport(
    existing_paths: Iterable[list[Optional[Cell]]],
    settled_goal: Cell,
    settle_step: int,
    merge_regions: Mapping[Cell, int],
    allow_settled_goal_adjacency: bool,
) -> bool:
    for existing in existing_paths:
        other_goal = next((cell for cell in reversed(existing) if cell is not None), None)
        for future_step in range(settle_step + 1, len(existing)):
            other_now = existing[future_step]
            if other_now is None:
                continue
            if other_now == settled_goal:
                return True
            if not in_pull_risk_zone(settled_goal, other_now):
                continue
            if _can_share_settled_goal_risk(
                settled_goal,
                settled_goal,
                other_now,
                other_goal,
                merge_regions,
                allow_settled_goal_adjacency,
            ):
                continue
            return True
    return False


class AStarPlanner:
    def __init__(
        self,
        rows: int = GRID_ROWS,
        cols: int = GRID_COLS,
        valid_cells: Optional[Iterable[Cell]] = None,
        extra_edges: Optional[dict[Cell, Cell]] = None,
    ):
        self.rows = rows
        self.cols = cols
        self.valid_cells = set(valid_cells) if valid_cells is not None else None
        self.extra_edges: dict[Cell, set[Cell]] = {}
        if extra_edges:
            for a, b in extra_edges.items():
                self.extra_edges.setdefault(a, set()).add(b)
                self.extra_edges.setdefault(b, set()).add(a)

    def plan(self, start: Cell, goal: Cell, obstacles: Iterable[Cell] = ()) -> list[Cell]:
        obstacles_set = set(obstacles)
        if not self._in_bounds(start) or not self._in_bounds(goal):
            return []
        if start in obstacles_set or goal in obstacles_set:
            return []
        if start == goal:
            return [start]

        frontier: list[tuple[int, int, Cell]] = []
        heapq.heappush(frontier, (0, 0, start))
        came_from: dict[Cell, Optional[Cell]] = {start: None}
        cost_so_far: dict[Cell, int] = {start: 0}
        push_order = 0

        while frontier:
            _, _, current = heapq.heappop(frontier)
            if current == goal:
                break

            for nxt in self._neighbors(current):
                if nxt in obstacles_set:
                    continue
                new_cost = cost_so_far[current] + 1
                if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                    cost_so_far[nxt] = new_cost
                    priority = new_cost + self._heuristic(nxt, goal)
                    push_order += 1
                    heapq.heappush(frontier, (priority, push_order, nxt))
                    came_from[nxt] = current

        if goal not in came_from:
            return []

        path = [goal]
        current = goal
        while came_from[current] is not None:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def _in_bounds(self, cell: Cell) -> bool:
        if self.valid_cells is not None:
            return cell in self.valid_cells
        row, col = cell
        return 0 <= row < self.rows and 0 <= col < self.cols

    def _neighbors(self, cell: Cell) -> list[Cell]:
        row, col = cell
        candidates = ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1))
        neighbors = [c for c in candidates if self._in_bounds(c)]
        neighbors.extend(c for c in self.extra_edges.get(cell, set()) if self._in_bounds(c))
        return neighbors

    @staticmethod
    def _heuristic(a: Cell, b: Cell) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])


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


@dataclass
class MultiDropletAssignment:
    droplet_id: int
    source: Cell
    target: Cell
    path: list[Cell]
    scheduled_path: list[Optional[Cell]]
    round_index: int = 1


@dataclass
class Detection:
    grid_position: GridPosition
    cell: Cell
    pixel: tuple[float, float]
    confidence: float
    area_px: float


class SimulatedCamera:
    def __init__(
        self,
        rows: int = GRID_ROWS,
        cols: int = GRID_COLS,
        frame_size: tuple[int, int] = (720, 720),
        margin_px: int = 18,
    ):
        self.rows = rows
        self.cols = cols
        self.frame_size = frame_size
        self.margin_px = margin_px

    def render(
        self,
        droplet_position: GridPosition,
        obstacles: Iterable[Cell] = (),
        path: Iterable[Cell] = (),
        active_cells: Iterable[Cell] = (),
        loaded_reservoirs: Iterable[Cell] = (),
        target_shape_cells: Iterable[Cell] = (),
        target_cells: Iterable[Cell] = (),
        start_cell: Optional[Cell] = None,
        goal_cell: Optional[Cell] = None,
        hide_droplet: bool = False,
        droplet_positions: Optional[Iterable[GridPosition]] = None,
        droplet_colors: Optional[Iterable[tuple[int, int, int]]] = None,
        droplet_shapes: Optional[Iterable[str]] = None,
        noise_profile: Optional[VisionNoiseProfile] = None,
    ) -> np.ndarray:
        width, height = self.frame_size
        frame = np.full((height, width, 3), (255, 255, 255), dtype=np.uint8)
        cell_size = self.cell_size_px
        left, top = self.grid_origin_px
        grid_w_px = cell_size * self.cols
        grid_h_px = cell_size * self.rows

        self._fill_cells(frame, RESERVOIR_CELLS, (182, 91, 77), outline_color=(125, 51, 43))
        self._fill_cells(frame, loaded_reservoirs, (230, 143, 69), outline_color=(147, 82, 29))
        self._fill_cells(frame, target_shape_cells, (231, 221, 255))
        self._fill_cells(frame, path, (226, 239, 255))
        self._fill_cells(frame, target_cells, (248, 208, 89))
        self._fill_cells(frame, active_cells, (151, 216, 189))
        self._fill_cells(frame, obstacles, (89, 100, 110))

        if start_cell is not None:
            self._fill_cells(frame, [start_cell], (156, 219, 207))
        if goal_cell is not None:
            self._fill_cells(frame, [goal_cell], (242, 185, 185))

        line_color = (190, 201, 211)
        left_i = int(round(left))
        top_i = int(round(top))
        right_i = int(round(left + grid_w_px))
        bottom_i = int(round(top + grid_h_px))
        if cv2 is not None:
            for i in range(self.cols + 1):
                x = int(round(left + i * cell_size))
                cv2.line(frame, (x, top_i), (x, bottom_i), line_color, 1)
            for i in range(self.rows + 1):
                y = int(round(top + i * cell_size))
                cv2.line(frame, (left_i, y), (right_i, y), line_color, 1)
        else:
            for i in range(self.cols + 1):
                x = int(round(left + i * cell_size))
                frame[top_i : bottom_i + 1, x : x + 1] = line_color
            for i in range(self.rows + 1):
                y = int(round(top + i * cell_size))
                frame[y : y + 1, left_i : right_i + 1] = line_color

        profile = noise_profile or VisionNoiseProfile()
        if profile.drop_frame_rate >= 1.0:
            hide_droplet = True
        elif profile.drop_frame_rate > 0.0 and random.random() < profile.drop_frame_rate:
            hide_droplet = True

        if not hide_droplet:
            positions = list(droplet_positions) if droplet_positions is not None else [droplet_position]
            colors = list(droplet_colors) if droplet_colors is not None else [(24, 82, 194)]
            shapes = list(droplet_shapes) if droplet_shapes is not None else ["circle"]
            if not colors:
                colors = [(24, 82, 194)]
            if not shapes:
                shapes = ["circle"]
            radius = max(6, int(round(cell_size * 0.36)))
            for idx, pos in enumerate(positions):
                row, col = pos
                if profile.jitter_cells > 0:
                    row += profile.jitter_cells
                    col -= profile.jitter_cells
                color = colors[idx % len(colors)]
                if profile.low_contrast > 0:
                    mix = max(0.0, min(1.0, profile.low_contrast))
                    color = tuple(int(channel * (1.0 - mix) + 245 * mix) for channel in color)
                outline = tuple(max(0, int(channel * 0.45)) for channel in color)
                center = self.grid_position_to_pixel((row, col))
                shape = shapes[idx % len(shapes)]
                if cv2 is not None:
                    if shape == "horizontal_ellipse":
                        axes = (max(radius, int(round(cell_size * 0.48))), max(4, int(round(cell_size * 0.27))))
                        cv2.ellipse(frame, center, axes, 0, 0, 360, color, -1)
                        cv2.ellipse(frame, center, axes, 0, 0, 360, outline, 2)
                    else:
                        cv2.circle(frame, center, radius, color, -1)
                        cv2.circle(frame, center, radius, outline, 2)
                else:
                    if shape == "horizontal_ellipse":
                        self._draw_ellipse(
                            frame,
                            center,
                            max(radius, int(round(cell_size * 0.48))),
                            max(4, int(round(cell_size * 0.27))),
                            color,
                        )
                    else:
                        self._draw_circle(frame, center, radius, color)
            if profile.false_detection_rate >= 1.0 or (
                profile.false_detection_rate > 0.0 and random.random() < profile.false_detection_rate
            ):
                false_center = self.grid_position_to_pixel((self.rows * 0.5, self.cols * 0.5))
                false_color = (24, 82, 194)
                if cv2 is not None:
                    cv2.circle(frame, false_center, radius, false_color, -1)
                else:
                    self._draw_circle(frame, false_center, radius, false_color)

        return frame

    @property
    def cell_size_px(self) -> float:
        width, height = self.frame_size
        usable_w = width - 2 * self.margin_px
        usable_h = height - 2 * self.margin_px
        span_cols = self.cols + 2 * CAMERA_LAYOUT_PADDING_CELLS
        span_rows = self.rows + 2 * CAMERA_LAYOUT_PADDING_CELLS
        return min(usable_w / span_cols, usable_h / span_rows)

    @property
    def grid_origin_px(self) -> tuple[float, float]:
        width, height = self.frame_size
        cell_size = self.cell_size_px
        full_w = cell_size * (self.cols + 2 * CAMERA_LAYOUT_PADDING_CELLS)
        full_h = cell_size * (self.rows + 2 * CAMERA_LAYOUT_PADDING_CELLS)
        outer_left = (width - full_w) / 2
        outer_top = (height - full_h) / 2
        return outer_left + CAMERA_LAYOUT_PADDING_CELLS * cell_size, outer_top + CAMERA_LAYOUT_PADDING_CELLS * cell_size

    def grid_position_to_pixel(self, position: GridPosition) -> tuple[int, int]:
        row, col = position
        left, top = self.grid_origin_px
        x = left + (col + 0.5) * self.cell_size_px
        y = top + (row + 0.5) * self.cell_size_px
        return int(round(x)), int(round(y))

    def pixel_to_grid_position(self, x: float, y: float) -> GridPosition:
        left, top = self.grid_origin_px
        col = (x - left) / self.cell_size_px - 0.5
        row = (y - top) / self.cell_size_px - 0.5
        return row, col

    def _fill_cells(
        self,
        frame: np.ndarray,
        cells: Iterable[Cell],
        color: tuple[int, int, int],
        outline_color: Optional[tuple[int, int, int]] = None,
    ) -> None:
        for cell in cells:
            if cell in CORNER_RESERVOIRS:
                self._fill_corner_reservoir(frame, cell, color, outline_color)
                continue
            bbox = self._cell_bbox_px(cell)
            if bbox is None:
                continue
            self._fill_rect_px(frame, bbox, color, outline_color)

    def _fill_rect_px(
        self,
        frame: np.ndarray,
        bbox: tuple[float, float, float, float],
        color: tuple[int, int, int],
        outline_color: Optional[tuple[int, int, int]] = None,
    ) -> None:
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = (int(round(value)) for value in bbox)
        x0 = max(0, min(width, x0))
        x1 = max(0, min(width, x1))
        y0 = max(0, min(height, y0))
        y1 = max(0, min(height, y1))
        if x1 <= x0 or y1 <= y0:
            return
        frame[y0:y1, x0:x1] = color
        if outline_color is None:
            return
        if cv2 is not None:
            cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), outline_color, 1)
        else:
            frame[y0:y0 + 1, x0:x1] = outline_color
            frame[y1 - 1:y1, x0:x1] = outline_color
            frame[y0:y1, x0:x0 + 1] = outline_color
            frame[y0:y1, x1 - 1:x1] = outline_color

    def _fill_reservoir_connectors(self, frame: np.ndarray, color: tuple[int, int, int]) -> None:
        for cell in RESERVOIR_CELLS:
            bbox = self._reservoir_connector_bbox_px(cell)
            if bbox is not None:
                self._fill_rect_px(frame, bbox, color)

    def _reservoir_side(self, cell: Cell) -> str:
        row, col = cell
        if cell in CORNER_RESERVOIRS:
            if row < 0 and col < 0:
                return "top_left"
            if row < 0:
                return "top_right"
            if col < 0:
                return "bottom_left"
            return "bottom_right"
        if row < 0:
            return "top"
        if row >= self.rows:
            return "bottom"
        if col < 0:
            return "left"
        if col >= self.cols:
            return "right"
        return "core"

    def _reservoir_connector_bbox_px(self, cell: Cell) -> Optional[tuple[float, float, float, float]]:
        return None

    def _fill_corner_reservoir(
        self,
        frame: np.ndarray,
        cell: Cell,
        color: tuple[int, int, int],
        outline_color: Optional[tuple[int, int, int]] = None,
    ) -> None:
        for rect in self._corner_reservoir_rects_px(cell):
            self._fill_rect_px(frame, rect, color, outline_color)

    def _corner_reservoir_rects_px(self, cell: Cell) -> list[tuple[float, float, float, float]]:
        left, top = self.grid_origin_px
        cell_size = self.cell_size_px
        side = self._reservoir_side(cell)
        def rect_at(row: int, col: int) -> tuple[float, float, float, float]:
            return (
                left + col * cell_size,
                top + row * cell_size,
                left + (col + 1) * cell_size,
                top + (row + 1) * cell_size,
            )
        if side == "top_left":
            return [rect_at(row, col) for row, col in ((-1, -1), (-1, 0), (0, -1))]
        if side == "top_right":
            return [rect_at(row, col) for row, col in ((-1, self.cols - 1), (-1, self.cols), (0, self.cols))]
        if side == "bottom_left":
            return [rect_at(row, col) for row, col in ((self.rows - 1, -1), (self.rows, -1), (self.rows, 0))]
        return [
            rect_at(row, col)
            for row, col in (
                (self.rows - 1, self.cols),
                (self.rows, self.cols - 1),
                (self.rows, self.cols),
            )
        ]

    def _cell_bbox_px(self, cell: Cell) -> Optional[tuple[int, int, int, int]]:
        left, top = self.grid_origin_px
        row, col = cell
        cell_size = self.cell_size_px
        if 0 <= row < self.rows and 0 <= col < self.cols:
            x0 = int(round(left + col * cell_size)) + 1
            y0 = int(round(top + row * cell_size)) + 1
            x1 = int(round(left + (col + 1) * cell_size)) - 1
            y1 = int(round(top + (row + 1) * cell_size)) - 1
            return x0, y0, x1, y1
        if cell not in RESERVOIR_CELLS:
            return None
        if cell in CORNER_RESERVOIRS:
            return None
        scale = 1.9 if cell in SIDE_RESERVOIR_LARGE or cell in CORNER_RESERVOIRS else 0.8
        cx = left + (col + 0.5) * cell_size
        cy = top + (row + 0.5) * cell_size
        if cell in SIDE_RESERVOIR_LARGE:
            side = self._reservoir_side(cell)
            if side == "top":
                cy = top - 2.0 * cell_size
            elif side == "bottom":
                cy = top + (self.rows + 2.0) * cell_size
            elif side == "left":
                cx = left - 2.0 * cell_size
            elif side == "right":
                cx = left + (self.cols + 2.0) * cell_size
        half = cell_size * scale / 2
        return (
            int(round(cx - half)),
            int(round(cy - half)),
            int(round(cx + half)),
            int(round(cy + half)),
        )

    @staticmethod
    def _draw_circle(frame: np.ndarray, center: tuple[int, int], radius: int, color: tuple[int, int, int]) -> None:
        yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
        mask = (xx - center[0]) ** 2 + (yy - center[1]) ** 2 <= radius**2
        frame[mask] = color

    @staticmethod
    def _draw_ellipse(
        frame: np.ndarray,
        center: tuple[int, int],
        radius_x: int,
        radius_y: int,
        color: tuple[int, int, int],
    ) -> None:
        yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
        mask = ((xx - center[0]) / max(1, radius_x)) ** 2 + ((yy - center[1]) / max(1, radius_y)) ** 2 <= 1
        frame[mask] = color


class DropletDetector:
    def __init__(self, camera: SimulatedCamera):
        self.camera = camera

    def detect(self, frame_rgb: np.ndarray) -> Optional[Detection]:
        detections = self.detect_all(frame_rgb)
        return detections[0] if detections else None

    def detect_all(self, frame_rgb: np.ndarray) -> list[Detection]:
        if cv2 is not None:
            mask = self._droplet_color_mask(frame_rgb).astype(np.uint8) * 255
            kernel = np.ones((3, 3), dtype=np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return []

            detections = []
            for contour in contours:
                area = float(cv2.contourArea(contour))
                if area < 30:
                    continue
                perimeter = float(cv2.arcLength(contour, True))
                if perimeter <= 0:
                    continue
                circularity = 4.0 * math.pi * area / (perimeter * perimeter)
                if circularity < 0.62:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if h == 0 or w == 0:
                    continue
                aspect = w / h
                if not 0.45 <= aspect <= 2.25:
                    continue
                moments = cv2.moments(contour)
                if moments["m00"] == 0:
                    continue
                x = moments["m10"] / moments["m00"]
                y = moments["m01"] / moments["m00"]
                detections.append(self._build_detection(x, y, area))
            detections.sort(key=lambda det: det.area_px, reverse=True)
            return detections

        red = frame_rgb[:, :, 0]
        green = frame_rgb[:, :, 1]
        blue = frame_rgb[:, :, 2]
        blue_mask = (blue > 140) & (red < 80) & (green < 140)
        magenta_mask = (red > 120) & (green < 85) & (blue > 50)
        mask = blue_mask | magenta_mask | self._droplet_color_mask(frame_rgb)
        ys, xs = np.nonzero(mask)
        if len(xs) < 30:
            return []
        return [self._build_detection(float(xs.mean()), float(ys.mean()), float(len(xs)))]

    @staticmethod
    def _droplet_color_mask(frame_rgb: np.ndarray) -> np.ndarray:
        frame = frame_rgb.astype(np.int32)
        mask = np.zeros(frame.shape[:2], dtype=bool)
        for color in DROPLET_DETECTION_RGB:
            diff = frame - np.array(color, dtype=np.int32)
            distance = np.sqrt(np.sum(diff * diff, axis=2))
            mask |= distance <= DROPLET_DETECTION_TOLERANCE
        return mask

    def _build_detection(self, x: float, y: float, area: float) -> Detection:
        grid_position = self.camera.pixel_to_grid_position(x, y)
        cell = rounded_cell(grid_position, self.camera.rows, self.camera.cols)
        confidence = min(1.0, area / 700.0)
        return Detection(grid_position=grid_position, cell=cell, pixel=(x, y), confidence=confidence, area_px=area)


def detection_in_cell(detection: Detection, target: Cell, tolerance_cells: float = 0.35) -> bool:
    row, col = detection.grid_position
    return math.hypot(row - target[0], col - target[1]) <= tolerance_cells
