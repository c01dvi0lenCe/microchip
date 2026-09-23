from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from ..layout import (
    CORNER_RESERVOIRS,
    ELECTRODE_PITCH_MM,
    GRID_COLS,
    GRID_ROWS,
    RESERVOIR_CELL_BY_ID,
    SIDE_RESERVOIR_LARGE,
    Cell,
    cell_from_electrode_id,
)
from .calibration import ArrayGridCalibration, Point


def polygon_centroid(points: Sequence[Point]) -> Point:
    if len(points) < 3:
        raise ValueError("an electrode polygon needs at least three points")
    cross_sum = 0.0
    x_sum = 0.0
    y_sum = 0.0
    for current, following in zip(points, (*points[1:], points[0])):
        cross = current[0] * following[1] - following[0] * current[1]
        cross_sum += cross
        x_sum += (current[0] + following[0]) * cross
        y_sum += (current[1] + following[1]) * cross
    if abs(cross_sum) <= 1e-9:
        return float(np.mean([point[0] for point in points])), float(np.mean([point[1] for point in points]))
    return x_sum / (3.0 * cross_sum), y_sum / (3.0 * cross_sum)


@dataclass(frozen=True)
class ElectrodeRegion:
    electrode_id: int
    row: int
    col: int
    center_px: Point
    polygon_px: tuple[Point, ...]
    center_mm: Point
    polygon_mm: tuple[Point, ...]
    geometry_source: str


class ElectrodeMap:
    def __init__(self, calibration: ArrayGridCalibration, regions: Mapping[int, ElectrodeRegion]):
        if set(regions) != set(range(1, 421)):
            missing = sorted(set(range(1, 421)) - set(regions))
            raise ValueError(f"electrode map must contain IDs 1..420; missing={missing[:5]}")
        self.calibration = calibration
        self._regions = dict(regions)

    @classmethod
    def from_calibration(
        cls,
        calibration: ArrayGridCalibration,
        pixel_overrides: Mapping[int, Sequence[Point]] | None = None,
    ) -> "ElectrodeMap":
        overrides = {int(key): tuple(value) for key, value in (pixel_overrides or {}).items()}
        regions: dict[int, ElectrodeRegion] = {}
        for electrode_id in range(1, 421):
            cell = cell_from_electrode_id(electrode_id)
            grid_polygon = _grid_polygon(cell)
            polygon_mm = tuple((x * calibration.pitch_mm, y * calibration.pitch_mm) for x, y in grid_polygon)
            if electrode_id in overrides:
                polygon_px = tuple((float(x), float(y)) for x, y in overrides[electrode_id])
                source = "calibrated"
            else:
                polygon_px = calibration.grid_polygon_to_pixel(grid_polygon)
                source = "template"
            regions[electrode_id] = ElectrodeRegion(
                electrode_id=electrode_id,
                row=cell[0],
                col=cell[1],
                center_px=polygon_centroid(polygon_px),
                polygon_px=polygon_px,
                center_mm=polygon_centroid(polygon_mm),
                polygon_mm=polygon_mm,
                geometry_source=source,
            )
        return cls(calibration, regions)

    def __len__(self) -> int:
        return len(self._regions)

    def __iter__(self):
        return iter(self._regions.values())

    def __getitem__(self, electrode_id: int) -> ElectrodeRegion:
        return self._regions[electrode_id]

    def nearest_electrode(self, point_px: Point) -> ElectrodeRegion:
        return min(
            self._regions.values(),
            key=lambda region: (region.center_px[0] - point_px[0]) ** 2 + (region.center_px[1] - point_px[1]) ** 2,
        )


def _rect(cx: float, cy: float, width: float, height: float) -> tuple[Point, ...]:
    half_w = width / 2.0
    half_h = height / 2.0
    return (
        (cx - half_w, cy - half_h),
        (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h),
        (cx - half_w, cy + half_h),
    )


def _corner_polygon(cell: Cell) -> tuple[Point, ...]:
    row, col = cell
    if row < 0 and col < 0:
        return ((-1, -1), (1, -1), (1, 0), (0, 0), (0, 1), (-1, 1))
    if row < 0:
        return (
            (GRID_COLS - 1, -1),
            (GRID_COLS + 1, -1),
            (GRID_COLS + 1, 1),
            (GRID_COLS, 1),
            (GRID_COLS, 0),
            (GRID_COLS - 1, 0),
        )
    if col < 0:
        return (
            (-1, GRID_ROWS - 1),
            (0, GRID_ROWS - 1),
            (0, GRID_ROWS),
            (1, GRID_ROWS),
            (1, GRID_ROWS + 1),
            (-1, GRID_ROWS + 1),
        )
    return (
        (GRID_COLS, GRID_ROWS - 1),
        (GRID_COLS + 1, GRID_ROWS - 1),
        (GRID_COLS + 1, GRID_ROWS + 1),
        (GRID_COLS - 1, GRID_ROWS + 1),
        (GRID_COLS - 1, GRID_ROWS),
        (GRID_COLS, GRID_ROWS),
    )


def _grid_polygon(cell: Cell) -> tuple[Point, ...]:
    row, col = cell
    if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
        return ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1))
    if cell in CORNER_RESERVOIRS:
        return _corner_polygon(cell)
    if cell not in set(RESERVOIR_CELL_BY_ID.values()):
        raise ValueError(f"unsupported electrode cell {cell}")
    if cell in SIDE_RESERVOIR_LARGE:
        scale = 1.9
        if row < 0:
            return _rect(col + 0.5, -2.0, scale, scale)
        if row >= GRID_ROWS:
            return _rect(col + 0.5, GRID_ROWS + 2.0, scale, scale)
        if col < 0:
            return _rect(-2.0, row + 0.5, scale, scale)
        return _rect(GRID_COLS + 2.0, row + 0.5, scale, scale)
    return _rect(col + 0.5, row + 0.5, 0.8, 0.8)
