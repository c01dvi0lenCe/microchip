"""Representative closed-loop schedules, including saved letter presets."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from dmf import (
    AStarPlanner,
    LAYOUT_CELLS,
    RESERVOIR_CONNECTIONS,
    build_multi_droplet_assignments,
    electrode_id,
)
from dmf.layout import Cell


@dataclass(frozen=True)
class ScenarioSchedule:
    name: str
    frames: list[set[int]]
    droplet_count: int
    tracks: tuple[tuple[Cell | None, ...], ...] = ()
    merge_cells: frozenset[Cell] = frozenset()


def representative_scenarios(preset_dir: Path) -> list[ScenarioSchedule]:
    move_track = ((2, 2), (2, 3), (2, 4))
    mix_a = ((2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 3), (3, 3))
    mix_b = ((4, 4), (4, 3), (3, 3), (3, 4), (4, 4), (4, 3), (3, 3))
    loop_track = ((10, 10), (10, 11), (11, 11), (11, 10), (10, 10))
    simple = [
        _track_schedule("move", (move_track,)),
        _track_schedule("mix", (mix_a, mix_b), merge_cells=frozenset({(3, 3), (3, 4), (4, 4), (4, 3)})),
        _cell_frames("split", [[(8, 8)], [(8, 7), (8, 9)]], 1),
        _track_schedule("loop", (loop_track,)),
    ]
    letters = [
        _letter_schedule(name, preset_dir / f"{name}写字母.json")
        for name in ("CSE", "ZJU", "CSC")
    ]
    return simple + letters


def _cell_frames(name: str, frames: list[list[tuple[int, int]]], droplets: int) -> ScenarioSchedule:
    return ScenarioSchedule(
        name=name,
        frames=[{electrode_id(row, col) for row, col in frame} for frame in frames],
        droplet_count=droplets,
    )


def _track_schedule(
    name: str,
    tracks: tuple[tuple[Cell | None, ...], ...],
    *,
    merge_cells: frozenset[Cell] = frozenset(),
) -> ScenarioSchedule:
    max_steps = max(len(track) for track in tracks)
    frames = []
    for step in range(max_steps):
        cells = {
            track[step] if step < len(track) else track[-1]
            for track in tracks
        }
        frames.append({electrode_id(cell[0], cell[1]) for cell in cells if cell is not None})
    return ScenarioSchedule(
        name=name,
        frames=frames,
        droplet_count=len(tracks),
        tracks=tracks,
        merge_cells=merge_cells,
    )


@lru_cache(maxsize=8)
def _letter_schedule(name: str, preset_path: Path) -> ScenarioSchedule:
    payload = json.loads(preset_path.read_text(encoding="utf-8"))
    settings = payload["settings"]
    sources = [tuple(cell) for cell in settings["loaded_reservoirs"]]
    targets = [tuple(cell) for cell in settings["target_shape_cells"]]
    obstacles = [tuple(cell) for cell in settings.get("obstacle_cells", [])]
    planner = AStarPlanner(
        rows=20,
        cols=20,
        valid_cells=LAYOUT_CELLS,
        extra_edges=RESERVOIR_CONNECTIONS,
    )
    assignments = build_multi_droplet_assignments(sources, targets, planner, obstacles)
    if len(assignments) != len(set(targets)):
        raise RuntimeError(f"{name} planning failed: {len(assignments)}/{len(set(targets))} targets")

    max_steps = max(len(assignment.scheduled_path) for assignment in assignments)
    frames: list[set[int]] = []
    for step in range(max_steps):
        active = set()
        for assignment in assignments:
            cell = (
                assignment.scheduled_path[step]
                if step < len(assignment.scheduled_path)
                else assignment.scheduled_path[-1]
            )
            if cell is not None:
                active.add(electrode_id(cell[0], cell[1]))
        frames.append(active)
    tracks = tuple(tuple(assignment.scheduled_path) for assignment in assignments)
    return ScenarioSchedule(
        name=name,
        frames=frames,
        droplet_count=len(assignments),
        tracks=tracks,
    )
