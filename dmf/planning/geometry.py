from __future__ import annotations

from typing import Iterable

from ..layout import Cell, GRID_COLS, GRID_ROWS, are_touching, is_core_cell


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
