from __future__ import annotations

import heapq
from typing import Iterable, Optional

from ..layout import Cell, GRID_COLS, GRID_ROWS


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
