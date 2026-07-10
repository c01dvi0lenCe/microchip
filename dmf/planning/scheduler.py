from __future__ import annotations

from typing import Iterable, Mapping, Optional

from ..layout import (
    Cell,
    GRID_COLS,
    GRID_ROWS,
    INITIAL_DROPLET_CAPACITY,
    LAYOUT_CELLS,
    MAX_PARALLEL_MULTI_DROPLETS,
    RESERVOIR_DROPLET_CAPACITY,
    electrode_id,
    in_pull_risk_zone,
    is_core_cell,
    is_reservoir_cell,
)
from .geometry import target_merge_region_map


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
