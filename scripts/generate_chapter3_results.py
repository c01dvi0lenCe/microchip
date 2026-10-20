"""Generate reproducible Chapter 3 planning/scheduling simulation figures.

This is a presentation/export harness around the production DMF planning
functions. It does not run hardware, image processing, or physical droplets.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dmf import (  # noqa: E402
    AStarPlanner,
    LAYOUT_CELLS,
    MultiDropletAssignment,
    RESERVOIR_CONNECTIONS,
    RESERVOIR_ID_BY_CELL,
    build_multi_droplet_assignments,
    electrode_id,
    replan_multi_assignments_after_fault,
    schedule_multi_paths,
)
from dmf.layout import CORNER_RESERVOIRS, SIDE_RESERVOIR_LARGE, SIDE_RESERVOIR_SMALL  # noqa: E402


PALETTE = ["#1852C2", "#B23A48", "#7651A8", "#007B83", "#B87412", "#4E7A2E", "#2F5F9A", "#7D4F2A"]
INK = "#2A3742"
MUTED = "#687782"
GRID = "#D8DEE3"
BG = "#FFFFFF"
CANVAS_BG = "#F6F9FB"
BOARD_EDGE = "#8B9298"
OBSTACLE = "#A8ADB2"
FAULT = "#C43C39"
RESERVOIR = "#D0CECA"
RESERVOIR_EDGE = "#8D8B87"
RESERVOIR_LOADED = "#D5A46F"
RESERVOIR_LOADED_EDGE = "#92714E"
TARGET_SHAPE = "#DCE9CF"
TARGET_EDGE = "#769657"
TARGET = "#F5CA51"
WAIT = "#F4A261"
_TEXT_COMMANDS: dict[int, list[tuple[tuple[int, int], str, str, int, bool, str, str]]] = {}


class _Canvas:
    def __init__(self, image: np.ndarray):
        self.image = image

    @staticmethod
    def _point(point: tuple[float, float]) -> tuple[int, int]:
        return int(round(point[0])), int(round(point[1]))

    def rectangle(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = (int(round(value)) for value in box)
        if fill is not None:
            cv2.rectangle(self.image, (x0, y0), (x1, y1), _rgb(fill), cv2.FILLED, cv2.LINE_AA)
        if outline:
            cv2.rectangle(self.image, (x0, y0), (x1, y1), _rgb(outline), int(width), cv2.LINE_AA)

    def rounded_rectangle(self, box, radius=4, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = (int(round(value)) for value in box)
        radius = max(1, int(radius))
        if fill is not None:
            color = _rgb(fill)
            cv2.rectangle(self.image, (x0 + radius, y0), (x1 - radius, y1), color, cv2.FILLED, cv2.LINE_AA)
            cv2.rectangle(self.image, (x0, y0 + radius), (x1, y1 - radius), color, cv2.FILLED, cv2.LINE_AA)
            for center in ((x0 + radius, y0 + radius), (x1 - radius, y0 + radius), (x0 + radius, y1 - radius), (x1 - radius, y1 - radius)):
                cv2.circle(self.image, center, radius, color, cv2.FILLED, cv2.LINE_AA)
        if outline is not None:
            color = _rgb(outline)
            cv2.line(self.image, (x0 + radius, y0), (x1 - radius, y0), color, width, cv2.LINE_AA)
            cv2.line(self.image, (x0 + radius, y1), (x1 - radius, y1), color, width, cv2.LINE_AA)
            cv2.line(self.image, (x0, y0 + radius), (x0, y1 - radius), color, width, cv2.LINE_AA)
            cv2.line(self.image, (x1, y0 + radius), (x1, y1 - radius), color, width, cv2.LINE_AA)
            for center, start in (((x0 + radius, y0 + radius), 180), ((x1 - radius, y0 + radius), 270), ((x1 - radius, y1 - radius), 0), ((x0 + radius, y1 - radius), 90)):
                cv2.ellipse(self.image, center, (radius, radius), 0, start, start + 90, color, width, cv2.LINE_AA)

    def ellipse(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = (int(round(value)) for value in box)
        center = ((x0 + x1) // 2, (y0 + y1) // 2)
        axes = (max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2))
        if fill is not None:
            cv2.ellipse(self.image, center, axes, 0, 0, 360, _rgb(fill), cv2.FILLED, cv2.LINE_AA)
        if outline is not None:
            cv2.ellipse(self.image, center, axes, 0, 0, 360, _rgb(outline), int(width), cv2.LINE_AA)

    def line(self, points, fill, width=1, joint=None, style="solid"):
        if len(points) == 4 and isinstance(points[0], (int, float)):
            points = ((points[0], points[1]), (points[2], points[3]))
        coords = np.asarray([self._point(point) for point in points], dtype=np.int32)
        if len(coords) >= 2 and style == "solid":
            cv2.polylines(self.image, [coords], False, _rgb(fill), int(width), cv2.LINE_AA)
        elif len(coords) >= 2:
            color = _rgb(fill)
            dash, gap = 7, 5
            for start, end in zip(coords, coords[1:]):
                delta = end - start
                length = float(np.linalg.norm(delta))
                if length == 0:
                    continue
                unit = delta / length
                for offset in np.arange(0, length, dash + gap):
                    stop = min(length, offset + dash)
                    a = tuple(np.rint(start + unit * offset).astype(int))
                    b = tuple(np.rint(start + unit * stop).astype(int))
                    cv2.line(self.image, a, b, color, int(width), cv2.LINE_AA)

    def polygon(self, points, fill=None, outline=None, width=1):
        coords = np.asarray([self._point(point) for point in points], dtype=np.int32)
        if len(coords) < 3:
            return
        if fill is not None:
            cv2.fillPoly(self.image, [coords], _rgb(fill), cv2.LINE_AA)
        if outline is not None:
            cv2.polylines(self.image, [coords], True, _rgb(outline), int(width), cv2.LINE_AA)

    def text(self, xy, text, *, font=None, fill=INK, size=16, bold=False):
        _TEXT_COMMANDS.setdefault(id(self.image), []).append((self._point(xy), str(text), fill, int(size), bool(bold), "left", "baseline"))


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def _new_canvas(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), _rgb(BG), dtype=np.uint8)


def _save_image(image: np.ndarray, path: Path) -> None:
    commands = _TEXT_COMMANDS.pop(id(image), [])
    if commands:
        height, width = image.shape[:2]
        with rc_context({
            "font.family": "Arial",
            "mathtext.fontset": "custom",
            "mathtext.rm": "Arial",
            "mathtext.it": "Arial:italic",
            "mathtext.bf": "Arial:bold",
        }):
            figure = Figure(figsize=(width / 100, height / 100), dpi=100, frameon=False)
            figure.patch.set_alpha(0)
            axes = figure.add_axes((0, 0, 1, 1))
            axes.set_xlim(0, width)
            axes.set_ylim(height, 0)
            axes.set_axis_off()
            for (x, y), text, fill, size, bold, horizontal_alignment, vertical_alignment in commands:
                axes.text(
                    x, y + size if vertical_alignment == "baseline" else y, text,
                    color=fill, fontsize=size * 0.72,
                    fontweight="bold" if bold else "normal", va=vertical_alignment, ha=horizontal_alignment,
                    clip_on=False,
                )
            FigureCanvasAgg(figure).draw()
            rgba = np.asarray(figure.canvas.buffer_rgba(), dtype=np.float32) / 255
            alpha = rgba[:, :, 3:4]
            image[:] = np.clip(rgba[:, :, :3] * alpha + image.astype(np.float32) / 255 * (1 - alpha), 0, 1) * 255
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not ok:
        raise OSError(f"Could not write figure: {path}")
    path.write_bytes(encoded.tobytes())


def _cell_name(cell: tuple[int, int] | None) -> str:
    if cell is None:
        return "-"
    try:
        return str(electrode_id(*cell))
    except ValueError:
        return f"R{cell[0]},C{cell[1]}"


def _cell_json(cell: tuple[int, int] | None) -> list[int] | None:
    return list(cell) if cell is not None else None


def _path_length(path: Iterable[tuple[int, int] | None]) -> int:
    cells = [cell for cell in path if cell is not None]
    return sum(a != b for a, b in zip(cells, cells[1:]))


def _wait_count(path: Iterable[tuple[int, int] | None]) -> int:
    cells = list(path)
    return sum(a is not None and a == b for a, b in zip(cells, cells[1:]))


def _release_delay(path: Iterable[tuple[int, int] | None]) -> int:
    for index, cell in enumerate(path):
        if cell is not None:
            return index
    return 0


def _is_core_cell(cell: tuple[int, int] | None) -> bool:
    return cell is not None and 0 <= cell[0] < 20 and 0 <= cell[1] < 20


def _snapshot_action(
    schedule: list[tuple[int, int] | None],
    frame: int,
    target: tuple[int, int] | None = None,
) -> tuple[str, tuple[int, int] | None, tuple[int, int] | None]:
    current = schedule[min(frame, len(schedule) - 1)] if schedule else None
    following = schedule[frame + 1] if frame + 1 < len(schedule) else current
    if current is None:
        return "queued", None, None
    if not _is_core_cell(current):
        return "dispensing", current, following
    if current == target:
        return "arrived", current, current
    if frame >= len(schedule) - 1:
        return "arrived", current, current
    if following == current:
        return "wait", current, following
    if following is None or not _is_core_cell(following):
        return "arrived", current, current
    return "move", current, following


def _extend_schedule(path: list[tuple[int, int] | None], length: int) -> list[tuple[int, int] | None]:
    if not path:
        return [None] * length
    return path + [path[-1]] * max(0, length - len(path))


def _load_letter(name: str, planner: AStarPlanner) -> tuple[list[MultiDropletAssignment], set[tuple[int, int]], set[tuple[int, int]]]:
    payload = json.loads((ROOT / "presets" / f"{name}写字母.json").read_text(encoding="utf-8"))
    settings = payload["settings"]
    sources = [tuple(cell) for cell in settings["loaded_reservoirs"]]
    targets = [tuple(cell) for cell in settings["target_shape_cells"]]
    obstacles = {tuple(cell) for cell in settings.get("obstacle_cells", [])}
    assignments = build_multi_droplet_assignments(
        sources, targets, planner, obstacles, faulty_electrodes=settings.get("faulty_electrodes", [])
    )
    if len(assignments) != len(targets):
        raise RuntimeError(f"{name} 字母规划失败：{len(assignments)}/{len(targets)} 个目标已分配")
    return assignments, set(sources), set(targets)


def _schedule_conflicts(assignments: list[MultiDropletAssignment]) -> list[dict[str, object]]:
    # Replay the scheduler's own constraint predicate as an export-time assertion.
    from dmf.planning.scheduler import _multi_step_conflicts

    schedules = [assignment.scheduled_path for assignment in assignments]
    conflicts = []
    for index, (assignment, schedule) in enumerate(zip(assignments, schedules)):
        for step, cell in enumerate(schedule):
            previous = schedule[step - 1] if step else None
            if _multi_step_conflicts(
                schedules[:index], previous, cell, step, assignment.target, {}, False
            ):
                conflicts.append({"droplet_id": assignment.droplet_id, "step": step, "cell": _cell_json(cell)})
    return conflicts


def _save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _draw_text(draw: _Canvas, xy: tuple[int, int], text: str, size: int = 17, color: str = INK, bold: bool = False) -> None:
    draw.text(xy, text, fill=color, size=size, bold=bold)


def _draw_centered_text(draw: _Canvas, center: tuple[float, float], text: str, size: int, color: str, bold: bool = False) -> None:
    _TEXT_COMMANDS.setdefault(id(draw.image), []).append((
        (round(center[0]), round(center[1])), str(text), color, int(size), bool(bold), "center", "center",
    ))


def _map_panel(
    image: np.ndarray,
    bounds: tuple[int, int, int, int],
    assignments: list[MultiDropletAssignment],
    *,
    paths: str = "scheduled",
    frame: int | None = None,
    frame_by_droplet: dict[int, int] | None = None,
    sources: Iterable[tuple[int, int]] = (),
    targets: Iterable[tuple[int, int]] = (),
    obstacles: Iterable[tuple[int, int]] = (),
    faults: Iterable[tuple[int, int]] = (),
    conflict_cells: Iterable[tuple[int, int]] = (),
    action_only: bool = True,
    route_colors: dict[int, str] | None = None,
    source_colors: dict[tuple[int, int], str] | None = None,
    route_styles: dict[int, str] | None = None,
    route_overlays: Iterable[tuple[list[tuple[int, int] | None], str, str]] = (),
    show_droplet_ids: bool = True,
    title: str = "",
    show_routes: bool = True,
) -> None:
    draw = _Canvas(image)
    x0, y0, x1, y1 = bounds
    _draw_text(draw, (x0, y0), title, 23, INK, True)
    board_size = max(1, min(x1 - x0 - 12, y1 - y0 - 66))
    board_left = x0 + (x1 - x0 - board_size) / 2
    board_top = y0 + 38 + (y1 - y0 - 66 - board_size) / 2
    cell_size = board_size / (20 + 2 * 2.2)
    grid_left = board_left + (board_size - 20 * cell_size) / 2
    grid_top = board_top + (board_size - 20 * cell_size) / 2
    grid_right = grid_left + 20 * cell_size
    grid_bottom = grid_top + 20 * cell_size
    draw.rectangle(
        (board_left, board_top, board_left + board_size, board_top + board_size),
        fill=CANVAS_BG,
        outline=BOARD_EDGE,
        width=2,
    )

    def cell_rect(cell: tuple[int, int]) -> tuple[float, float, float, float]:
        row, col = cell
        return (
            grid_left + col * cell_size,
            grid_top + row * cell_size,
            grid_left + (col + 1) * cell_size,
            grid_top + (row + 1) * cell_size,
        )

    def cell_center(cell: tuple[int, int]) -> tuple[float, float]:
        if cell in RESERVOIR_ID_BY_CELL:
            if cell in CORNER_RESERVOIRS:
                polygon = corner_polygons[cell]
                points = np.asarray(
                    [(grid_left + col * cell_size, grid_top + row * cell_size) for col, row in polygon],
                    dtype=float,
                )
                center = points.mean(axis=0)
                return float(center[0]), float(center[1])
            rx0, ry0, rx1, ry1 = reservoir_rect(cell)
            return (rx0 + rx1) / 2, (ry0 + ry1) / 2
        x_a, y_a, x_b, y_b = cell_rect(cell)
        return (x_a + x_b) / 2, (y_a + y_b) / 2

    # Match the app's core grid and perimeter electrode geometry.
    for row in range(20):
        for col in range(20):
            draw.rectangle(cell_rect((row, col)), fill=BG, outline=GRID, width=1)

    corner_polygons = {
        (-1, -1): [(-1, -1), (1, -1), (1, 0), (0, 0), (0, 1), (-1, 1)],
        (-1, 20): [(19, -1), (21, -1), (21, 1), (20, 1), (20, 0), (19, 0)],
        (20, -1): [(-1, 19), (0, 19), (0, 20), (1, 20), (1, 21), (-1, 21)],
        (20, 20): [(20, 19), (21, 19), (21, 21), (19, 21), (19, 20), (20, 20)],
    }
    for cell, polygon in corner_polygons.items():
        points = [(grid_left + col * cell_size, grid_top + row * cell_size) for col, row in polygon]
        draw.polygon(points, fill=RESERVOIR, outline=RESERVOIR_EDGE, width=1)

    def reservoir_side(cell: tuple[int, int]) -> str:
        row, col = cell
        if cell in CORNER_RESERVOIRS:
            return "corner"
        if row < 0:
            return "top"
        if row >= 20:
            return "bottom"
        if col < 0:
            return "left"
        return "right"

    def reservoir_rect(cell: tuple[int, int]) -> tuple[float, float, float, float]:
        row, col = cell
        side = reservoir_side(cell)
        large = cell in SIDE_RESERVOIR_LARGE
        small_pad_size = cell_size * 0.85
        pad_size = cell_size * (1.15 if large else 0.85)
        offset = pad_size / 2 + (small_pad_size if large else 0)
        if side == "top":
            cx, cy = grid_left + (col + 0.5) * cell_size, grid_top - offset
        elif side == "bottom":
            cx, cy = grid_left + (col + 0.5) * cell_size, grid_bottom + offset
        elif side == "left":
            cx, cy = grid_left - offset, grid_top + (row + 0.5) * cell_size
        else:
            cx, cy = grid_right + offset, grid_top + (row + 0.5) * cell_size
        half = pad_size / 2
        return cx - half, cy - half, cx + half, cy + half

    for cell in RESERVOIR_ID_BY_CELL:
        if cell in CORNER_RESERVOIRS:
            continue
        draw.rectangle(reservoir_rect(cell), fill=RESERVOIR, outline=RESERVOIR_EDGE, width=1)

    target_set = set(targets)
    source_set = set(sources)
    obstacle_set = set(obstacles)
    fault_set = set(faults)
    conflict_set = set(conflict_cells)
    path_routes: list[list[tuple[int, int] | None]] = []
    for assignment in assignments:
        route_frame = frame_by_droplet.get(assignment.droplet_id, 0) if frame_by_droplet is not None else frame
        if route_frame is not None:
            end = min(route_frame + 2, len(assignment.scheduled_path)) if action_only else len(assignment.scheduled_path)
            route = list(assignment.scheduled_path[route_frame:end])
        elif paths == "static" or paths == "runtime":
            route = list(assignment.path)
        else:
            route = list(assignment.scheduled_path)
        path_routes.append(route)

    for cell in sorted(target_set):
        if cell not in RESERVOIR_ID_BY_CELL:
            draw.rectangle(cell_rect(cell), fill=TARGET_SHAPE, outline=TARGET_EDGE, width=1)
    for cell in sorted(obstacle_set):
        if cell not in RESERVOIR_ID_BY_CELL:
            draw.rectangle(cell_rect(cell), fill=OBSTACLE, outline="#343D45", width=2)
    for cell in sorted(conflict_set):
        if _is_core_cell(cell):
            rx0, ry0, rx1, ry1 = cell_rect(cell)
            draw.rectangle((rx0 + 1, ry0 + 1, rx1 - 1, ry1 - 1), fill="#F9D2D2", outline="#D35555", width=2)
    for cell in sorted(conflict_set):
        if _is_core_cell(cell):
            rx0, ry0, rx1, ry1 = cell_rect(cell)
            draw.rectangle((rx0 + 1, ry0 + 1, rx1 - 1, ry1 - 1), outline="#D35555", width=3)
    for route, color, style in route_overlays:
        overlay_cells = [cell for cell in route if _is_core_cell(cell)]
        if len(overlay_cells) > 1:
            draw.line([cell_center(cell) for cell in overlay_cells], fill=color, width=max(1, int(cell_size * 0.055)), style=style)
    if show_routes:
        for idx, route in enumerate(path_routes):
            cells: list[tuple[int, int]] = []
            for cell in route:
                if (frame is not None or frame_by_droplet is not None) and not _is_core_cell(cell):
                    continue
                if cell is not None and (not cells or cells[-1] != cell):
                    cells.append(cell)
            if len(cells) < 2:
                continue
            compressed = [cells[0]]
            previous_direction = None
            for previous, current in zip(cells, cells[1:]):
                direction = (current[0] - previous[0], current[1] - previous[1])
                direction = (0 if not direction[0] else (1 if direction[0] > 0 else -1), 0 if not direction[1] else (1 if direction[1] > 0 else -1))
                if previous_direction is not None and direction != previous_direction:
                    compressed.append(previous)
                previous_direction = direction
            compressed.append(cells[-1])
            points = [cell_center(cell) for cell in compressed]
            assignment = assignments[idx]
            color = (route_colors or {}).get(assignment.droplet_id, PALETTE[idx % len(PALETTE)])
            style = (route_styles or {}).get(assignment.droplet_id, "solid")
            width = max(2, int(cell_size * 0.075))
            if len(points) > 1:
                draw.line(points, fill=color, width=width, style=style)
                marks = list(range(4, len(cells) - 1, 5))
                final_mark = len(cells) - 2
                if final_mark >= 0 and final_mark not in marks:
                    marks.append(final_mark)
                for mark in marks:
                    (sx, sy), (tx, ty) = cell_center(cells[mark]), cell_center(cells[mark + 1])
                    dx, dy = tx - sx, ty - sy
                    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
                    ux, uy = dx / length, dy / length
                    px, py = -uy, ux
                    tip = (tx, ty)
                    base = (tx - ux * cell_size * 0.28, ty - uy * cell_size * 0.28)
                    half_width = cell_size * 0.14
                    draw.polygon([tip, (base[0] + px * half_width, base[1] + py * half_width), (base[0] - px * half_width, base[1] - py * half_width)], fill=color)

    for cell in sorted(fault_set):
        rx0, ry0, rx1, ry1 = cell_rect(cell)
        draw.rectangle((rx0 + 2, ry0 + 2, rx1 - 2, ry1 - 2), fill="#FBE9E8", outline=FAULT, width=1)
        cross_width = max(1, int(cell_size * 0.075))
        draw.line((rx0 + cell_size * 0.24, ry0 + cell_size * 0.24, rx1 - cell_size * 0.24, ry1 - cell_size * 0.24), fill=FAULT, width=cross_width)
        draw.line((rx0 + cell_size * 0.24, ry1 - cell_size * 0.24, rx1 - cell_size * 0.24, ry0 + cell_size * 0.24), fill=FAULT, width=cross_width)

    # Match the app's loaded-reservoir overlay and endpoint setup markers.
    for cell in source_set:
        if cell in RESERVOIR_ID_BY_CELL and cell not in CORNER_RESERVOIRS:
            source_edge = (source_colors or {}).get(cell, RESERVOIR_LOADED_EDGE)
            draw.rectangle(reservoir_rect(cell), fill=RESERVOIR_LOADED, outline=source_edge, width=2 if source_colors else 1)
        elif cell not in RESERVOIR_ID_BY_CELL and frame is None and frame_by_droplet is None:
            source_color = (source_colors or {}).get(cell) or next((PALETTE[i % len(PALETTE)] for i, assignment in enumerate(assignments) if assignment.source == cell), PALETTE[0])
            sx, sy = cell_center(cell)
            radius = cell_size * 0.30
            draw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius), fill=source_color, outline=source_color, width=2)
            source_assignment = next((a for a in assignments if a.source == cell), None)
            if source_assignment is not None:
                _draw_centered_text(draw, (sx, sy), str(source_assignment.droplet_id), 12, BG, True)
    for cell in (target_set if len(target_set) <= 1 else ()):
        if cell not in RESERVOIR_ID_BY_CELL:
            rx0, ry0, rx1, ry1 = cell_rect(cell)
            draw.rectangle((rx0 + 1, ry0 + 1, rx1 - 1, ry1 - 1), fill=TARGET_SHAPE, outline=TARGET_EDGE, width=1)

    if frame is not None or frame_by_droplet is not None:
        for idx, assignment in enumerate(assignments):
            schedule = assignment.scheduled_path
            if not schedule:
                continue
            droplet_frame = frame_by_droplet.get(assignment.droplet_id, 0) if frame_by_droplet is not None else frame
            if droplet_frame is None:
                continue
            cell = schedule[min(droplet_frame, len(schedule) - 1)]
            if cell is None:
                continue
            cx, cy = cell_center(cell)
            radius = max(4, cell_size * 0.34)
            color = (route_colors or {}).get(assignment.droplet_id, PALETTE[idx % len(PALETTE)])
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color, outline=color, width=3)
            if show_droplet_ids and len(assignments) > 1:
                label = str(assignment.droplet_id)
                label_size = 12
                _draw_centered_text(draw, (cx, cy), label, label_size, BG, True)
            action, _, _ = _snapshot_action(schedule, droplet_frame, assignment.target)
            following = schedule[droplet_frame + 1] if droplet_frame + 1 < len(schedule) else cell
            if action in {"move", "dispensing"} and following is not None and following != cell:
                nx, ny = cell_center(following)
                dx, dy = nx - cx, ny - cy
                length = max(1.0, (dx * dx + dy * dy) ** 0.5)
                ux, uy = dx / length, dy / length
                start = (cx + ux * radius * 1.1, cy + uy * radius * 1.1)
                tip = (cx + ux * cell_size * 0.72, cy + uy * cell_size * 0.72)
                draw.line((start, tip), fill=color, width=max(2, int(cell_size * 0.09)))
                px, py = -uy, ux
                head = cell_size * 0.17
                draw.polygon([
                    tip,
                    (tip[0] - ux * head + px * head * 0.65, tip[1] - uy * head + py * head * 0.65),
                    (tip[0] - ux * head - px * head * 0.65, tip[1] - uy * head - py * head * 0.65),
                ], fill=color)
            if action == "wait":
                _draw_text(draw, (int(cx + radius * 0.7), int(cy - radius * 1.7)), "W", 11, INK, True)

        # Keep target identity visible even when a droplet marker occupies it.
        for target in sorted(target_set):
            if _is_core_cell(target):
                rx0, ry0, rx1, ry1 = cell_rect(target)
                draw.rectangle((rx0 + 1, ry0 + 1, rx1 - 1, ry1 - 1), outline=TARGET_EDGE, width=2)


def _draw_legend(draw: _Canvas, x: int, y: int, items: list[tuple[str, str]]) -> int:
    for label, color in items:
        draw.rounded_rectangle((x, y + 2, x + 18, y + 18), radius=3, fill=color)
        _draw_text(draw, (x + 26, y), label, 15, INK)
        x += max(150, 48 + len(label) * 8)
    return y + 28


def _conflict_detail_panel(
    image: np.ndarray,
    bounds: tuple[int, int, int, int],
    assignments: list[MultiDropletAssignment],
    *,
    coordinated: bool,
    title: str,
) -> None:
    draw = _Canvas(image)
    x0, y0, x1, y1 = bounds
    _draw_text(draw, (x0, y0), title, 22, INK, True)
    visible_rows, visible_cols = 5, 5
    cell_size = min((x1 - x0 - 100) / visible_cols, (y1 - y0 - 90) / visible_rows)
    grid_width, grid_height = cell_size * visible_cols, cell_size * visible_rows
    left = x0 + (x1 - x0 - grid_width) / 2
    top = y0 + 44 + (y1 - y0 - grid_height - 44) / 2

    def center(cell: tuple[int, int]) -> tuple[float, float]:
        row, col = cell
        return left + (col + 0.5) * cell_size, top + (row + 0.5) * cell_size

    for row in range(visible_rows):
        for col in range(visible_cols):
            draw.rectangle(
                (left + col * cell_size, top + row * cell_size,
                 left + (col + 1) * cell_size, top + (row + 1) * cell_size),
                fill=BG, outline=GRID, width=1,
            )

    targets = {assignment.target for assignment in assignments}
    for target in targets:
        cx, cy = center(target)
        half = cell_size / 2
        draw.rectangle((cx - half + 2, cy - half + 2, cx + half - 2, cy + half - 2), fill=TARGET_SHAPE, outline=TARGET_EDGE, width=2)

    if not coordinated:
        for cell in ((0, 1), (0, 3)):
            cx, cy = center(cell)
            half = cell_size / 2
            draw.rectangle((cx - half + 3, cy - half + 3, cx + half - 3, cy + half - 3), fill="#F9D2D2", outline="#D35555", width=3)

    for index, assignment in enumerate(assignments):
        color = PALETTE[index]
        route = assignment.scheduled_path[:2] if coordinated else assignment.path[:2]
        cells = [cell for cell in route if _is_core_cell(cell)]
        points = [center(cell) for cell in cells]
        if len(points) > 1:
            draw.line(points, fill=color, width=3)
            for (sx, sy), (tx, ty) in zip(points, points[1:]):
                dx, dy = tx - sx, ty - sy
                length = max(1.0, (dx * dx + dy * dy) ** 0.5)
                ux, uy = dx / length, dy / length
                px, py = -uy, ux
                base_x, base_y = tx - ux * cell_size * 0.20, ty - uy * cell_size * 0.20
                half_width = cell_size * 0.10
                draw.polygon(
                    [(tx, ty), (base_x + px * half_width, base_y + py * half_width),
                     (base_x - px * half_width, base_y - py * half_width)],
                    fill=color,
                )
        if cells:
            cx, cy = center(cells[0])
            radius = cell_size * 0.19
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color, outline=BG, width=2)
            _draw_centered_text(draw, (cx, cy - radius - 20), f"$D_{{{assignment.droplet_id}}}$", 21, INK)
            if coordinated and len(cells) > 1 and cells[0] == cells[1]:
                _draw_text(draw, (int(cx + radius * 1.2), int(cy - radius)), "W", 22, INK, True)


def _draw_route_legend(
    draw: _Canvas,
    x: int,
    y: int,
    *,
    include_state: bool = False,
    runtime: bool = False,
) -> None:
    if runtime:
        items = [("Failed electrode", "fault"), ("Prior route", "prior"), ("Replanned route", "dashed")]
    else:
        items = [("Failed electrode", "fault"), ("Nominal route", "solid"), ("Replanned route", "dashed")]
    if include_state:
        items.append(("Completed / unaffected", "muted"))
    for label, kind in items:
        if kind == "fault":
            draw.line((x, y + 10, x + 16, y + 10), fill=FAULT, width=2)
            draw.line((x + 2, y + 3, x + 14, y + 17), fill=FAULT, width=2)
            draw.line((x + 2, y + 17, x + 14, y + 3), fill=FAULT, width=2)
        else:
            color = MUTED if kind in ("muted", "prior") else FAULT if kind == "dashed" else INK
            style = "dashed" if kind == "prior" else kind
            draw.line((x, y + 10, x + 20, y + 10), fill=color, width=2, style=style)
        _draw_text(draw, (x + 28, y), label, 15, INK)
        x += 42 + len(label) * 8


def _draw_length_comparison(
    draw: _Canvas,
    x: int,
    y: int,
    width: int,
    rows: list[dict[str, int | str]],
    *,
    title: str,
    baseline_label: str,
    comparison_label: str,
    row_height: int = 30,
) -> None:
    baseline_color = "#98A3AA"
    comparison_color = "#2878B5"
    _draw_text(draw, (x, y), title, 17, INK, True)
    legend_x = x + width - 440
    for label, color in ((baseline_label, baseline_color), (comparison_label, comparison_color)):
        draw.rectangle((legend_x, y + 3, legend_x + 16, y + 15), fill=color)
        _draw_text(draw, (legend_x + 22, y - 1), label, 12, MUTED)
        legend_x += 215

    plot_left = x + 170
    plot_right = x + width - 35
    plot_width = plot_right - plot_left
    max_value = max(5, max(max(int(row["baseline"]), int(row["comparison"])) for row in rows))
    axis_max = ((max_value + 4) // 5) * 5
    axis_y = y + 33
    chart_bottom = axis_y + len(rows) * row_height + 3
    for tick in range(0, axis_max + 1, 5):
        tx = plot_left + plot_width * tick / axis_max
        draw.line((tx, axis_y + 8, tx, chart_bottom), fill=GRID, width=1)
        _draw_text(draw, (int(tx - 5), axis_y - 9), str(tick), 11, MUTED)

    for index, row in enumerate(rows):
        top = axis_y + 14 + index * row_height
        _draw_text(draw, (x + 12, top - 3), str(row["label"]), 13, INK, True)
        for offset, key, color in ((0, "baseline", baseline_color), (10, "comparison", comparison_color)):
            value = int(row[key])
            bar_width = plot_width * value / axis_max
            draw.rectangle((plot_left, top + offset, plot_left + bar_width, top + offset + 7), fill=color)
            _draw_text(draw, (int(plot_left + bar_width + 6), top + offset - 4), str(value), 11, INK)


def _draw_timeline(
    image: np.ndarray,
    bounds: tuple[int, int, int, int],
    assignments: list[MultiDropletAssignment],
    title: str,
    *,
    limit: int = 36,
    action_labels: bool = False,
) -> None:
    draw = _Canvas(image)
    x0, y0, x1, y1 = bounds
    _draw_text(draw, (x0, y0), title, 23, INK, True)
    max_len = max((len(a.scheduled_path) for a in assignments), default=1)
    steps = min(max_len, limit)
    label_width = 72
    plot_x0 = x0 + label_width
    plot_y0 = y0 + 76
    plot_w = x1 - plot_x0 - 12
    row_h = max(29, min(60, (y1 - plot_y0 - 30) // max(1, len(assignments))))
    step_w = plot_w / max(1, steps)
    for step in range(steps):
        _draw_centered_text(draw, (plot_x0 + (step + 0.5) * step_w, plot_y0 - 23), f"$t_{{{step}}}$", 20, INK)
    for idx, assignment in enumerate(assignments):
        y = plot_y0 + idx * row_h
        _draw_centered_text(draw, (x0 + 23, y + row_h / 2), f"$D_{{{assignment.droplet_id}}}$", 20, INK)
        schedule = _extend_schedule(assignment.scheduled_path, steps)
        for step, cell in enumerate(schedule[:steps]):
            x = plot_x0 + step * step_w
            if cell is None:
                fill = "#E6E9EC"
                label = "-"
            else:
                previous = schedule[step - 1] if step else None
                is_wait = previous == cell and cell != assignment.target
                arrived = cell == assignment.target
                fill = WAIT if is_wait else TARGET_SHAPE if arrived else PALETTE[idx % len(PALETTE)]
                label = "W" if is_wait else "" if action_labels else _cell_name(cell)
            draw.rectangle((x + 1, y, x + step_w - 1, y + row_h - 3), fill=fill, outline=BG)
            if step_w >= 23 and label:
                _draw_centered_text(draw, (x + step_w / 2, y + row_h / 2), label, 22 if action_labels else 15, INK if cell is None or fill == WAIT else BG, True)
    if max_len > limit:
        _draw_text(draw, (plot_x0, y1 - 19), f"Showing first {limit}/{max_len} steps", 13, MUTED)


def _assignment_row(assignment: MultiDropletAssignment, **extra: object) -> dict[str, object]:
    path = list(assignment.path)
    schedule = list(assignment.scheduled_path)
    return {
        "droplet_id": assignment.droplet_id,
        "source_cell": json.dumps(_cell_json(assignment.source)),
        "source_electrode": _cell_name(assignment.source),
        "target_cell": json.dumps(_cell_json(assignment.target)),
        "target_electrode": _cell_name(assignment.target),
        "static_path_cells": json.dumps([_cell_json(c) for c in path]),
        "static_path_electrodes": " ".join(_cell_name(c) for c in path),
        "scheduled_path_cells": json.dumps([_cell_json(c) for c in schedule]),
        "scheduled_path_electrodes": " ".join(_cell_name(c) for c in schedule),
        "path_length_steps": _path_length(path),
        "wait_steps": _wait_count(schedule),
        "release_delay_steps": _release_delay(schedule),
        **extra,
    }


def _save_assignments_csv(path: Path, assignments: list[MultiDropletAssignment], **extra: object) -> None:
    rows = [_assignment_row(assignment, **extra) for assignment in assignments]
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _base_planner() -> AStarPlanner:
    return AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)


def _normal_case(
    out: Path, planner: AStarPlanner,
    preset_name: str | None = None, prefix: str = "01_normal",
) -> dict[str, object]:
    if preset_name is None:
        preset_name = "复杂瓶颈并行运输.json" if (ROOT / "presets" / "复杂瓶颈并行运输.json").exists() else "多液滴正常路径调度.json"
    sources = [(-3, 6), (-3, 13), (6, -3), (6, 22)]
    targets = [(2, 4), (6, 8), (11, 12), (16, 15)]
    obstacles = {(4, 5), (5, 5), (8, 9)}
    faults = set()
    preset_path = ROOT / "presets" / preset_name
    preset = None
    if preset_path.exists():
        preset = json.loads(preset_path.read_text(encoding="utf-8"))
        settings = preset["settings"]
        sources = sorted({tuple(c) for c in settings.get("loaded_reservoirs", []) + settings.get("initial_droplet_cells", [])}, key=lambda c: electrode_id(*c))
        targets = [tuple(c) for c in settings["target_shape_cells"]]
        obstacles = {tuple(c) for c in settings.get("obstacle_cells", [])}
        faults = {tuple(c) for c in settings.get("faulty_electrodes", [])}
    metrics: dict[str, float] = {}
    started = time.perf_counter()
    assignments = build_multi_droplet_assignments(sources, targets, planner, obstacles, faulty_electrodes=faults, planning_metrics=metrics)
    wall_ms = (time.perf_counter() - started) * 1000
    if len(assignments) != len(targets):
        raise RuntimeError("正常多液滴案例未能完成全部分配")
    conflicts = _schedule_conflicts(assignments)
    if conflicts:
        raise RuntimeError(f"用户配置的多液滴排程存在冲突：{conflicts[:3]}")
    source_colors = {source: PALETTE[i % len(PALETTE)] for i, source in enumerate(sources)}
    droplet_colors = {a.droplet_id: source_colors[a.source] for a in assignments}
    timeline = max(len(a.scheduled_path) for a in assignments)
    lengths = {a.droplet_id: _path_length(a.path) for a in assignments}
    waits = {a.droplet_id: _wait_count(a.scheduled_path) for a in assignments}
    releases = {a.droplet_id: _release_delay(a.scheduled_path) for a in assignments}
    image = _new_canvas(1880, 990)
    draw = _Canvas(image)
    _map_panel(image, (45, 40, 890, 820), assignments, paths="static", sources=sources, targets=targets, obstacles=obstacles, faults=faults, route_colors=droplet_colors, source_colors=source_colors, title="(a) Planned routes")
    _map_panel(image, (930, 40, 1775, 820), assignments, paths="scheduled", frame=timeline - 1, sources=sources, targets=targets, obstacles=obstacles, faults=faults, route_colors=droplet_colors, source_colors=source_colors, title="(b) Final occupancy")
    _draw_legend(draw, 75, 850, [("Source", RESERVOIR_LOADED), ("Target", TARGET_SHAPE), ("Obstacle", OBSTACLE)])
    _draw_text(draw, (75, 920), f"$N_d={len(assignments)},\\quad L_{{\\mathrm{{total}}}}={sum(lengths.values())},\\quad T_{{\\mathrm{{makespan}}}}={timeline-1},\\quad N_{{\\mathrm{{wait}}}}={sum(waits.values())}$", 20, INK)
    _save_image(image, out / f"{prefix}_multidroplet.png")
    _save_assignments_csv(out / f"{prefix}_assignments.csv", assignments, scenario=prefix)
    if preset is not None:
        _save_json(out / f"{prefix}_preset.json", preset)
    payload = {
        "scenario": "normal_multidroplet" if prefix == "01_normal" else "initial_multidroplet_preset",
        "simulation_only": True,
        "preset": str(preset_path.relative_to(ROOT)) if preset is not None else None,
        "preset_snapshot": f"{prefix}_preset.json" if preset is not None else None,
        "schedule_conflict_count": len(conflicts),
        "fault_cells": [_cell_json(c) for c in sorted(faults)],
        "baseline_path_fault_intersections": {
            a.droplet_id: [_cell_json(c) for c in planner.plan(a.source, a.target, obstacles) if c in faults]
            for a in assignments
        },
        "sources": [_cell_json(x) for x in sources],
        "targets": [_cell_json(x) for x in targets],
        "obstacles": [_cell_json(x) for x in sorted(obstacles)],
        "assignments": [_assignment_row(a) for a in assignments],
        "path_lengths_by_droplet": lengths,
        "total_spatial_path_length": sum(lengths.values()),
        "scheduled_makespan_steps": timeline - 1,
        "wait_steps_by_droplet": waits,
        "wait_steps_total": sum(waits.values()),
        "release_delay_steps_by_droplet": releases,
        **metrics,
        "wall_time_ms_including_setup": wall_ms,
        "final_status": "completed",
    }
    _save_json(out / f"{prefix}_multidroplet.json", payload)
    return payload


def _conflict_case(out: Path) -> dict[str, object]:
    # D2's first move enters the pull-risk neighborhood of D1. The existing
    # reservation scheduler resolves the fluidic-spacing conflict by waiting.
    paths = [[(0, 2), (0, 3), (0, 4)], [(0, 0), (0, 1), (0, 2)]]
    schedules = schedule_multi_paths(paths)
    if len(schedules) != 2:
        raise RuntimeError("冲突案例未能成功调度")
    assignments = [
        MultiDropletAssignment(i + 1, path[0], path[-1], path, schedules[i])
        for i, path in enumerate(paths)
    ]
    image = _new_canvas(1680, 960)
    draw = _Canvas(image)
    _conflict_detail_panel(image, (45, 40, 805, 650), assignments, coordinated=False, title="(a) Without coordination")
    _conflict_detail_panel(image, (850, 40, 1615, 650), assignments, coordinated=True, title="(b) Reservation-based coordination")
    _draw_timeline(image, (65, 690, 1580, 945), assignments, "(c) Scheduled actions", limit=10, action_labels=True)
    _save_image(image, out / "02_conflict_resolution.png")
    _save_assignments_csv(out / "02_conflict_assignments.csv", assignments, conflict_type="fluidic_spacing")
    payload = {
        "scenario": "fluidic_spacing_conflict_resolution",
        "simulation_only": True,
        "conflict_type": "fluidic_spacing",
        "constraint": "pull-risk neighborhood",
        "static_paths": [[_cell_json(c) for c in path] for path in paths],
        "scheduled_paths": [[_cell_json(c) for c in path] for path in schedules],
        "uncoordinated_t1_positions": [_cell_json(path[1]) for path in paths],
        "uncoordinated_t1_manhattan_separation": sum(abs(a - b) for a, b in zip(paths[0][1], paths[1][1])),
        "scheduled_t1_positions": [_cell_json(path[1]) for path in schedules],
        "wait_steps_total": sum(_wait_count(path) for path in schedules),
        "release_delay_steps": [_release_delay(path) for path in schedules],
        "scheduler_result": "scheduled_with_one_source_wait",
        "scheduler": "dmf.planning.scheduler.schedule_multi_paths",
    }
    _save_json(out / "02_conflict_resolution.json", payload)
    return payload


def _letter_case(out: Path, planner: AStarPlanner, name: str = "CSE") -> dict[str, object]:
    assignments, sources, targets = _load_letter(name, planner)
    source_colors = {
        source: PALETTE[index % len(PALETTE)]
        for index, source in enumerate(sorted(sources, key=lambda cell: electrode_id(*cell)))
    }
    droplet_colors = {a.droplet_id: source_colors[a.source] for a in assignments}
    schedule_conflicts = _schedule_conflicts(assignments)
    if schedule_conflicts:
        raise RuntimeError(f"{name} 字母排程存在电极/流体间距冲突：{schedule_conflicts[:3]}")
    timeline = max(len(a.scheduled_path) for a in assignments)
    snapshot_steps = sorted({0, round((timeline - 1) / 3), round(2 * (timeline - 1) / 3), timeline - 1})
    phase_indices = [{a.droplet_id: step for a in assignments} for step in snapshot_steps]
    image = _new_canvas(1880, 1490)
    draw = _Canvas(image)
    panel_w, panel_h = 880, 640
    positions = [(35, 45), (965, 45), (35, 715), (965, 715)]
    labels = [
        f"({letter}) t={step}"
        for letter, step in zip(("a", "b", "c", "d"), snapshot_steps)
    ]
    for panel_index, (indices, (x, y), label) in enumerate(zip(phase_indices, positions, labels)):
        _map_panel(
            image, (x, y, x + panel_w, y + panel_h), assignments,
            paths="scheduled", frame_by_droplet=indices, sources=sources, targets=targets,
            show_droplet_ids=panel_index == 0,
            title=label,
            show_routes=False,
            route_colors=droplet_colors,
            source_colors=source_colors,
        )
    paths_total = sum(_path_length(a.path) for a in assignments)
    waits = sum(_wait_count(a.scheduled_path) for a in assignments)
    summary = f"$N_d={len(assignments)},\\quad L_{{\\mathrm{{total}}}}={paths_total},\\quad T_{{\\mathrm{{makespan}}}}={timeline-1},\\quad N_{{\\mathrm{{wait}}}}={waits}$"
    _draw_text(draw, (45, 1420), summary, 18, INK)
    _save_image(image, out / f"03_letter_{name}.png")
    _save_assignments_csv(out / f"03_letter_{name}_assignments.csv", assignments, scenario=f"letter_{name}")
    payload = {
        "scenario": f"letter_{name}",
        "simulation_only": True,
        "preset": f"presets/{name}写字母.json",
        "sources": [_cell_json(c) for c in sorted(sources)],
        "targets": [_cell_json(c) for c in sorted(targets)],
        "droplet_count": len(assignments),
        "reservoir_count": len(sources),
        "color_semantics": "One fixed color per source reservoir; all droplets released from that reservoir share its color. Droplet IDs remain unique.",
        "source_color_groups": [
            {
                "source_cell": _cell_json(source),
                "source_electrode": _cell_name(source),
                "color": color,
                "droplet_ids": [a.droplet_id for a in assignments if a.source == source],
            }
            for source, color in source_colors.items()
        ],
        "total_spatial_path_length": paths_total,
        "scheduled_makespan_steps": timeline - 1,
        "wait_steps_total": waits,
        "schedule_source": "build_multi_droplet_assignments; scheduled paths are exported unchanged",
        "initial_released_droplet_count": sum(a.scheduled_path[0] is not None for a in assignments),
        "schedule_conflict_count": len(schedule_conflicts),
        "schedule_conflict_validation": "passed",
        "release_delay_steps_by_droplet": {a.droplet_id: _release_delay(a.scheduled_path) for a in assignments},
        "snapshot_global_schedule_steps": snapshot_steps,
        "snapshot_semantics": "All panels are synchronized global schedule steps. Each droplet position and its single direction arrow are read from the production reservation schedule; queued droplets are omitted.",
        "snapshot_schedule_indices_by_droplet": phase_indices,
        "snapshot_actions": [
            {
                "global_schedule_step": step,
                "droplets": [
                    {
                        "droplet_id": a.droplet_id,
                        "schedule_index": indices[a.droplet_id],
                        "action": _snapshot_action(a.scheduled_path, indices[a.droplet_id], a.target)[0],
                        "current_cell": _cell_json(_snapshot_action(a.scheduled_path, indices[a.droplet_id], a.target)[1]),
                        "next_cell": _cell_json(_snapshot_action(a.scheduled_path, indices[a.droplet_id], a.target)[2]),
                    }
                    for a in assignments
                    if a.scheduled_path[min(step, len(a.scheduled_path) - 1)] is not None
                ],
            }
            for step, indices in zip(snapshot_steps, phase_indices)
        ],
        "final_status": "completed",
        "assignments": [_assignment_row(a) for a in assignments],
    }
    _save_json(out / f"03_letter_{name}.json", payload)
    return payload


def _preplanned_fault_case_legacy(out: Path, planner: AStarPlanner) -> dict[str, object]:
    source, target, fault = (7, 3), (7, 11), (7, 7)
    nominal = planner.plan(source, target)
    rerouted = planner.plan(source, target, {fault})
    if not nominal or not rerouted or fault in rerouted:
        raise RuntimeError("预置故障绕行案例未成功")
    nominal_len = len(nominal) - 1
    reroute_len = len(rerouted) - 1
    ratio = reroute_len / nominal_len if nominal_len else 1.0
    assignments = [
        MultiDropletAssignment(1, source, target, nominal, nominal),
        MultiDropletAssignment(1, source, target, rerouted, rerouted),
    ]
    image = _new_canvas(1680, 900)
    draw = _Canvas(image)
    _draw_text(draw, (40, 25), "Known faulty electrode: static A* detour", 32, INK, True)
    _map_panel(image, (45, 80, 805, 790), assignments[:1], paths="static", sources=[source], targets=[target], title="No fault")
    _map_panel(image, (850, 80, 1615, 790), assignments[1:], paths="static", sources=[source], targets=[target], faults=[fault], title=f"Fault at electrode {_cell_name(fault)}")
    _draw_text(draw, (55, 820), f"Original length={nominal_len}  Fault-aware length={reroute_len}  Increase={reroute_len-nominal_len}  Detour ratio={ratio:.3f}  Avoided={fault not in rerouted}", 21, INK)
    _save_image(image, out / "04_preplanned_fault_detour.png")
    payload = {
        "scenario": "preplanned_fault_detour",
        "simulation_only": True,
        "trial_interpretation": "Five independent static A* route trials overlaid for comparison; not a simultaneous multi-droplet schedule.",
        "source": _cell_json(source),
        "target": _cell_json(target),
        "fault_cell": _cell_json(fault),
        "fault_electrode": _cell_name(fault),
        "nominal_path": [_cell_json(c) for c in nominal],
        "fault_aware_path": [_cell_json(c) for c in rerouted],
        "nominal_length_steps": nominal_len,
        "fault_aware_length_steps": reroute_len,
        "length_increase_steps": reroute_len - nominal_len,
        "detour_ratio": ratio,
        "avoided_fault": fault not in rerouted,
        "status": "success",
    }
    _save_json(out / "04_preplanned_fault_detour.json", payload)
    with (out / "04_preplanned_fault_paths.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case", "source", "target", "fault", "path_cells", "path_electrodes", "length_steps"])
        writer.writeheader()
        for label, path in (("no_fault", nominal), ("fault_aware", rerouted)):
            writer.writerow({"case": label, "source": _cell_name(source), "target": _cell_name(target), "fault": _cell_name(fault), "path_cells": json.dumps([_cell_json(c) for c in path]), "path_electrodes": " ".join(_cell_name(c) for c in path), "length_steps": len(path)-1})
    return payload


def _preplanned_fault_case(out: Path, planner: AStarPlanner) -> dict[str, object]:
    sources = [(2, 2), (17, 2), (3, 18), (16, 18), (9, 1)]
    targets = [(5, 17), (12, 16), (15, 4), (4, 5), (9, 18)]
    faults = {
        (5, 7), (5, 8),
        (12, 8), (12, 9), (12, 10),
        (15, 11), (15, 12), (15, 13),
        (4, 10), (4, 11), (4, 12),
        (9, 7), (9, 8), (9, 9),
    }
    nominal_assignments: list[MultiDropletAssignment] = []
    fault_assignments: list[MultiDropletAssignment] = []
    rows = []
    for droplet_id, (source, target) in enumerate(zip(sources, targets), start=1):
        nominal = planner.plan(source, target)
        rerouted = planner.plan(source, target, faults)
        if not nominal or not rerouted or any(cell in faults for cell in rerouted):
            raise RuntimeError(f"D{droplet_id} 预置故障绕行失败")
        nominal_assignments.append(MultiDropletAssignment(droplet_id, source, target, nominal, nominal))
        fault_assignments.append(MultiDropletAssignment(droplet_id, source, target, rerouted, rerouted))
        rows.append({
            "droplet_id": droplet_id,
            "source": _cell_json(source),
            "target": _cell_json(target),
            "nominal_path": [_cell_json(cell) for cell in nominal],
            "fault_aware_path": [_cell_json(cell) for cell in rerouted],
            "nominal_length_steps": len(nominal) - 1,
            "fault_aware_length_steps": len(rerouted) - 1,
            "avoided_faults": all(cell not in faults for cell in rerouted),
            "nominal_fault_intersections": [_cell_json(cell) for cell in nominal if cell in faults],
        })

    nominal_total = sum(row["nominal_length_steps"] for row in rows)
    rerouted_total = sum(row["fault_aware_length_steps"] for row in rows)
    ratio = rerouted_total / nominal_total if nominal_total else 1.0
    image = _new_canvas(1680, 1200)
    draw = _Canvas(image)
    representative_id = 5
    representative_nominal = nominal_assignments[representative_id - 1]
    representative_fault = fault_assignments[representative_id - 1]
    _map_panel(
        image, (45, 45, 805, 790), [representative_nominal], paths="static",
        sources=[representative_nominal.source], targets=[representative_nominal.target],
        title=f"(a) D{representative_id}: nominal route",
    )
    _map_panel(
        image, (850, 45, 1615, 790), [representative_fault], paths="static",
        sources=[representative_fault.source], targets=[representative_fault.target],
        faults=faults, route_styles={representative_id: "dashed"},
        title=f"(b) D{representative_id}: fault-aware route",
    )
    _draw_route_legend(draw, 55, 805)
    _draw_text(draw, (55, 833), "Single-droplet route geometry; D2-D5 are summarized below, not shown as concurrent traffic.", 13, MUTED)
    _draw_text(draw, (55, 866), f"$N_d={len(rows)},\\quad L_{{\\mathrm{{total}}}}:{nominal_total}\\rightarrow{rerouted_total},\\quad R_{{\\mathrm{{detour}}}}={ratio:.3f}$", 16, INK)
    _draw_length_comparison(
        draw, 55, 905, 1570,
        [{"label": f"D{row['droplet_id']}", "baseline": row["nominal_length_steps"], "comparison": row["fault_aware_length_steps"]} for row in rows],
        title="Per-droplet path length (electrode-to-electrode steps)",
        baseline_label="Nominal", comparison_label="Fault-aware",
        row_height=37,
    )
    _save_image(image, out / "04_preplanned_fault_detour.png")
    payload = {
        "scenario": "preplanned_fault_detour",
        "simulation_only": True,
        "droplet_count": len(rows),
        "fault_cells": [_cell_json(cell) for cell in sorted(faults)],
        "fault_electrodes": [_cell_name(cell) for cell in sorted(faults)],
        "fault_electrode_count": len(faults),
        "route_visualization": f"D{representative_id} is shown alone in the map panels to avoid implying that independently planned static A* paths are collision-safe when executed concurrently. Other trials are included in the per-droplet length comparison only.",
        "representative_droplet_id": representative_id,
        "static_routes_are_concurrent_safe": False,
        "shared_cells_between_fault_aware_static_routes": [
            {
                "droplet_a": rows[i]["droplet_id"],
                "droplet_b": rows[j]["droplet_id"],
                "cells": [_cell_json(cell) for cell in sorted(set(fault_assignments[i].path) & set(fault_assignments[j].path))],
            }
            for i in range(len(rows))
            for j in range(i + 1, len(rows))
            if set(fault_assignments[i].path) & set(fault_assignments[j].path)
        ],
        "droplets": rows,
        "nominal_total_length_steps": nominal_total,
        "fault_aware_total_length_steps": rerouted_total,
        "length_increase_steps": rerouted_total - nominal_total,
        "detour_ratio": ratio,
        "avoided_faults": True,
        "status": "success",
    }
    _save_json(out / "04_preplanned_fault_detour.json", payload)
    with (out / "04_preplanned_fault_paths.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["droplet_id", "case", "source", "target", "faults", "path_cells", "path_electrodes", "length_steps"])
        writer.writeheader()
        for row in rows:
            for label in ("nominal", "fault_aware"):
                path = row[f"{label}_path"]
                writer.writerow({
                    "droplet_id": row["droplet_id"],
                    "case": label,
                    "source": _cell_name(tuple(row["source"])),
                    "target": _cell_name(tuple(row["target"])),
                    "faults": " ".join(_cell_name(cell) for cell in sorted(faults)),
                    "path_cells": json.dumps(path),
                    "path_electrodes": " ".join(_cell_name(tuple(cell)) for cell in path),
                    "length_steps": row[f"{label}_length_steps"],
                })
    return payload


def _runtime_fault_case_legacy(out: Path, planner: AStarPlanner) -> dict[str, object]:
    sources = [(2, 1), (8, 1), (14, 1)]
    targets = [(2, 5), (8, 12), (14, 12)]
    original = build_multi_droplet_assignments(sources, targets, planner)
    if len(original) != 3:
        raise RuntimeError("运行时故障案例初始多液滴规划失败")
    fault_step = 4
    fault = (8, 7)
    current: dict[int, tuple[int, int]] = {}
    completed: set[int] = set()
    for assignment in original:
        schedule = assignment.scheduled_path
        if len(schedule) - 1 <= fault_step:
            current[assignment.droplet_id] = assignment.target
            completed.add(assignment.droplet_id)
        else:
            current[assignment.droplet_id] = schedule[fault_step]
    before = copy.deepcopy(original)
    replanned = replan_multi_assignments_after_fault(
        copy.deepcopy(original), current, completed, set(), {fault}, planner
    )
    if replanned.status != "success":
        raise RuntimeError(f"运行时故障重排失败：{replanned.status} {replanned.reason}")
    nominal_remaining = replanned.nominal_remaining_length
    fault_remaining = replanned.fault_remaining_length
    detour_ratio = fault_remaining / nominal_remaining if nominal_remaining else 1.0
    compute_ms = replanned.routing_time_ms + replanned.scheduling_time_ms

    # Panel 1: state immediately before fault. Panel 2: fault marker at t_f.
    # Panel 3: rerouted unfinished paths and fixed completed targets.
    pre_snapshot = []
    for assignment in before:
        cell = current[assignment.droplet_id]
        pre_snapshot.append(MultiDropletAssignment(assignment.droplet_id, assignment.source, assignment.target, [cell], [cell]))
    image = _new_canvas(2520, 1030)
    draw = _Canvas(image)
    _draw_text(draw, (38, 22), f"Runtime fault -> global reroute/reschedule (fault at step {fault_step})", 31, INK, True)
    _map_panel(image, (30, 80, 820, 825), before, paths="scheduled", frame=fault_step - 1, sources=sources, targets=targets, title=f"t={fault_step-1}: original next actions")
    _map_panel(image, (865, 80, 1655, 790), pre_snapshot, paths="scheduled", sources=sources, targets=targets, faults=[fault], title=f"Fault event at {_cell_name(fault)}")
    _map_panel(image, (1700, 80, 2490, 790), replanned.assignments, paths="scheduled", sources=current.values(), targets=targets, faults=[fault], title="After: completed held, unfinished rerouted")
    _draw_text(draw, (45, 830), f"Completed IDs held={sorted(completed)}  Unfinished replanned={sorted(set(current)-completed)}  Nominal remaining={nominal_remaining}  Fault route={fault_remaining}  Detour ratio={detour_ratio:.3f}  Replan compute={compute_ms:.3f} ms  Status={replanned.status}", 20, INK)
    _save_image(image, out / "05_runtime_fault_global_replan.png")
    _save_assignments_csv(out / "05_runtime_fault_before.csv", before, phase="before_fault", fault_step=fault_step)
    _save_assignments_csv(out / "05_runtime_fault_after.csv", replanned.assignments, phase="after_fault", fault_step=fault_step)
    payload = {
        "scenario": "runtime_fault_global_replan",
        "simulation_only": True,
        "fault_step": fault_step,
        "fault_cell": _cell_json(fault),
        "fault_electrode": _cell_name(fault),
        "fault_intersects_original_unfinished_route": any(
            fault in assignment.path for assignment in original if assignment.droplet_id not in completed
        ),
        "current_positions": {str(k): _cell_json(v) for k, v in current.items()},
        "completed_droplet_ids": sorted(completed),
        "unfinished_droplet_ids": sorted(set(current) - completed),
        "before": [_assignment_row(a) for a in before],
        "after": [_assignment_row(a) for a in replanned.assignments],
        "nominal_remaining_path_length": nominal_remaining,
        "fault_aware_remaining_path_length": fault_remaining,
        "detour_ratio": detour_ratio,
        "replan_compute_ms": compute_ms,
        "routing_time_ms": replanned.routing_time_ms,
        "scheduling_time_ms": replanned.scheduling_time_ms,
        "status": replanned.status,
        "completed_droplets_held_at_goal": all(
            set(a.scheduled_path) == {a.target} for a in replanned.assignments if a.droplet_id in completed
        ),
        "unfinished_replanned_from_current_positions": all(
            a.path[0] == current[a.droplet_id]
            for a in replanned.assignments if a.droplet_id not in completed
        ),
    }
    _save_json(out / "05_runtime_fault_global_replan.json", payload)
    return payload


def _runtime_fault_case(out: Path, planner: AStarPlanner) -> dict[str, object]:
    sources = [(2, 1), (6, 1), (10, 1), (15, 1)]
    targets = [(2, 5), (6, 16), (10, 16), (15, 16)]
    original = build_multi_droplet_assignments(sources, targets, planner)
    if len(original) != 4:
        raise RuntimeError("运行时故障案例初始多液滴规划失败")

    fault_step = 4
    faults = {(6, 8), (10, 8)}
    current: dict[int, tuple[int, int]] = {}
    completed: set[int] = set()
    for assignment in original:
        schedule = assignment.scheduled_path
        if len(schedule) - 1 <= fault_step:
            current[assignment.droplet_id] = assignment.target
            completed.add(assignment.droplet_id)
        else:
            current[assignment.droplet_id] = schedule[fault_step]

    before = copy.deepcopy(original)
    replanned = replan_multi_assignments_after_fault(
        copy.deepcopy(original), current, completed, set(), faults, planner
    )
    if replanned.status != "success":
        raise RuntimeError(f"运行时故障重排失败：{replanned.status} {replanned.reason}")

    nominal_remaining = replanned.nominal_remaining_length
    fault_remaining = replanned.fault_remaining_length
    detour_ratio = fault_remaining / nominal_remaining if nominal_remaining else 1.0
    compute_ms = replanned.routing_time_ms + replanned.scheduling_time_ms
    replanned_by_id = {assignment.droplet_id: assignment for assignment in replanned.assignments}
    per_droplet_lengths = []
    for assignment in original:
        droplet_id = assignment.droplet_id
        if droplet_id in completed:
            old_length = new_length = 0
            outcome = "held at target"
        else:
            position = current[droplet_id]
            old_index = assignment.path.index(position)
            old_length = len(assignment.path) - old_index - 1
            new_length = len(replanned_by_id[droplet_id].path) - 1
            outcome = "detoured" if any(fault in assignment.path[old_index + 1:] for fault in faults) else "route retained"
        per_droplet_lengths.append({
            "droplet_id": droplet_id,
            "baseline": old_length,
            "comparison": new_length,
            "outcome": outcome,
        })

    image = _new_canvas(2520, 1160)
    draw = _Canvas(image)
    muted_routes = {1: MUTED, 2: FAULT, 3: FAULT, 4: "#87939C"}
    _draw_text(draw, (38, 22), "Runtime fault replanning", 26, INK, True)
    _map_panel(
        image, (30, 80, 820, 825), before, paths="scheduled", frame=fault_step - 1,
        sources=sources, targets=targets, route_colors=muted_routes,
        action_only=False,
        title="(a) Before fault",
    )
    _map_panel(
        image, (865, 80, 1655, 825), before, paths="scheduled", frame=fault_step,
        sources=sources, targets=targets, faults=faults, route_colors=muted_routes,
        action_only=False,
        title="(b) Fault at current positions",
    )
    affected_ids = {
        assignment.droplet_id for assignment in before
        if assignment.droplet_id not in completed
        and any(fault in assignment.path[assignment.path.index(current[assignment.droplet_id]) + 1:] for fault in faults)
    }
    old_routes = [
        (assignment.scheduled_path[fault_step:], "#D7DDE1", "dashed")
        for assignment in before if assignment.droplet_id in affected_ids
    ]
    _map_panel(
        image, (1700, 80, 2490, 825), replanned.assignments, paths="scheduled", frame=0,
        sources=current.values(), targets=targets, faults=faults,
        route_colors=muted_routes, route_styles={droplet_id: "dashed" for droplet_id in affected_ids},
        route_overlays=old_routes,
        action_only=False,
        title="(c) Replanned paths",
    )
    _draw_route_legend(draw, 45, 850, include_state=True, runtime=True)
    _draw_text(draw, (45, 895), f"$N_d={len(original)},\\quad L_{{\\mathrm{{remain}}}}:{nominal_remaining}\\rightarrow{fault_remaining},\\quad R_{{\\mathrm{{detour}}}}={detour_ratio:.3f},\\quad T_{{\\mathrm{{replan}}}}={compute_ms:.3f}\\,\\mathrm{{ms}}$", 17, INK)
    _draw_length_comparison(
        draw, 45, 930, 2430,
        [{"label": f"D{row['droplet_id']} · {row['outcome']}", "baseline": row["baseline"], "comparison": row["comparison"]} for row in per_droplet_lengths],
        title="Remaining route length by droplet (at fault time)",
        baseline_label="Original plan", comparison_label="After replan",
        row_height=36,
    )
    _save_image(image, out / "05_runtime_fault_global_replan.png")
    _save_assignments_csv(out / "05_runtime_fault_before.csv", before, phase="before_fault", fault_step=fault_step)
    _save_assignments_csv(out / "05_runtime_fault_after.csv", replanned.assignments, phase="after_fault", fault_step=fault_step)
    payload = {
        "scenario": "runtime_fault_global_replan",
        "simulation_only": True,
        "droplet_count": len(original),
        "fault_step": fault_step,
        "fault_cells": [_cell_json(fault) for fault in sorted(faults)],
        "fault_electrodes": [_cell_name(fault) for fault in sorted(faults)],
        "fault_intersects_original_unfinished_route": any(
            fault in assignment.path[assignment.path.index(current[assignment.droplet_id]) + 1:]
            for fault in faults for assignment in original if assignment.droplet_id not in completed
        ),
        "per_droplet_remaining_lengths": per_droplet_lengths,
        "current_positions": {str(k): _cell_json(v) for k, v in current.items()},
        "completed_droplet_ids": sorted(completed),
        "unfinished_droplet_ids": sorted(set(current) - completed),
        "before": [_assignment_row(a) for a in before],
        "after": [_assignment_row(a) for a in replanned.assignments],
        "nominal_remaining_path_length": nominal_remaining,
        "fault_aware_remaining_path_length": fault_remaining,
        "detour_ratio": detour_ratio,
        "replan_compute_ms": compute_ms,
        "routing_time_ms": replanned.routing_time_ms,
        "scheduling_time_ms": replanned.scheduling_time_ms,
        "status": replanned.status,
        "completed_droplets_held_at_goal": all(
            set(a.scheduled_path) == {a.target} for a in replanned.assignments if a.droplet_id in completed
        ),
        "unfinished_replanned_from_current_positions": all(
            a.path[0] == current[a.droplet_id]
            for a in replanned.assignments if a.droplet_id not in completed
        ),
    }
    _save_json(out / "05_runtime_fault_global_replan.json", payload)
    return payload


def _write_index(out: Path, cases: list[dict[str, object]]) -> None:
    lines = [
        "# Chapter 3 simulation result pack",
        "",
        "Generated from the current repository's production assignment, A*, reservation scheduling, and runtime-fault replanning functions.",
        "These are deterministic/software simulation outputs, not physical droplet experiments.",
        "",
        "## Files",
        "",
        "| Figure | Scenario | Data |",
        "|---|---|---|",
        "| `01_normal_multidroplet.png` | Normal assignment -> A* -> scheduling | `01_normal_multidroplet.json`, `01_normal_assignments.csv` |",
        "| `01b_initial_multidroplet.png` | User preset: six initial droplets with an obstacle/fault map | `01b_initial_multidroplet.json`, `01b_initial_assignments.csv` |",
        "| `02_conflict_resolution.png` | Fluidic-spacing conflict, resolved with source wait | `02_conflict_resolution.json`, `02_conflict_assignments.csv` |",
        "| `03_letter_CSE.png` | CSE pattern at four schedule snapshots | `03_letter_CSE.json`, `03_letter_CSE_assignments.csv` |",
        "| `03_letter_ZJU.png` | ZJU pattern at four schedule snapshots | `03_letter_ZJU.json`, `03_letter_ZJU_assignments.csv` |",
        "| `04_preplanned_fault_detour.png` | Known fault and A* detour | `04_preplanned_fault_detour.json`, `04_preplanned_fault_paths.csv` |",
        "| `05_runtime_fault_global_replan.png` | Runtime fault -> global reroute/reschedule | `05_runtime_fault_global_replan.json`, before/after CSVs |",
        "",
        "## Important interpretation",
        "",
        "- Path length and makespan are discrete electrode/step counts, not seconds.",
        "- Figure 01 prefers presets/复杂瓶颈并行运输.json, falling back to presets/多液滴正常路径调度.json. Figure 01b uses presets/多液滴正常路径调度2.json; its preconfigured faults do not intersect the corresponding nominal paths, so it is not fault-detour evidence.",
        "- In Figure 02, red shading marks the unsafe first transition, green cells mark targets, and W marks inserted waiting. Other colored timeline blocks need no in-figure action abbreviations.",
        "- Planning/replanning times are single-run local wall-clock measurements, not statistical performance claims.",
        "- Letter snapshots use shared global schedule steps and the planner's original parallel schedules. All droplets already released at t=0 appear; arrows show each active droplet's scheduled next move.",
        "- In letter figures, each source reservoir has a fixed color shared by all droplets it releases. IDs distinguish individual droplets; colors identify their source liquid.",
        "- The simulation does not model real dispense volume, fluid shape, or voltage physics.",
        "- Runtime fault is an offline invocation of the same replan function used by the multi-droplet simulation controller; no GUI/hardware is operated.",
        "- Figure 04 shows one representative route pair; other independent fault trials appear in the per-droplet length chart. Independent static routes are not collision-safe when assumed simultaneous.",
        "- Figure 05 replans two unfinished routes around two runtime faults, holds one completed droplet, and retains one unaffected route.",
        "- Reservation scheduling can insert waits/delayed releases to satisfy vertex, edge-swap, and fluidic pull-risk constraints.",
        "- Figure encoding: red cross = failed electrode; solid = nominal route; dashed = fault-aware route; muted routes = completed or unaffected droplets.",
        "- Reservoir pads have straight borders. Routes use lines and arrows without background bands or artificial core-entry circles; filled circles denote actual droplets.",
        "",
    ]
    lines.extend(f"- `{case['scenario']}`: {case.get('final_status', case.get('status', 'see JSON'))}" for case in cases)
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    _save_json(out / "summary.json", {"simulation_only": True, "cases": cases})


def generate(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    planner = _base_planner()
    cases = [
        _normal_case(output_dir, planner),
        _conflict_case(output_dir),
        _letter_case(output_dir, planner, "CSE"),
        _letter_case(output_dir, planner, "ZJU"),
        _preplanned_fault_case(output_dir, planner),
        _runtime_fault_case(output_dir, planner),
    ]
    if (ROOT / "presets" / "多液滴正常路径调度2.json").exists():
        cases.insert(1, _normal_case(output_dir, planner, "多液滴正常路径调度2.json", "01b_initial"))
    _write_index(output_dir, cases)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results" / "chapter3_simulation_results",
        help="Output directory (default: results/chapter3_simulation_results)",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    generate(output.resolve())
    print(f"Generated Chapter 3 simulation pack: {output.resolve()}")
    print("Cases: normal multi-droplet, conflict resolution, CSE/ZJU snapshots, preplanned fault, runtime global replan")
    print("All outputs are software simulation results; no hardware was operated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
