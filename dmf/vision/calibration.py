from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..layout import ELECTRODE_PITCH_MM, GRID_COLS, GRID_ROWS, Cell, clamp_cell

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


Point = tuple[float, float]


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_sequence(cls, values: Sequence[float | int]) -> "Roi":
        if len(values) != 4:
            raise ValueError("ROI must be x,y,width,height")
        x, y, width, height = (int(round(float(value))) for value in values)
        if width <= 0 or height <= 0:
            raise ValueError("ROI width and height must be positive")
        return cls(x, y, width, height)

    def clamp_to_frame(self, frame_shape: tuple[int, ...]) -> "Roi":
        frame_h, frame_w = frame_shape[:2]
        x0 = max(0, min(frame_w - 1, self.x))
        y0 = max(0, min(frame_h - 1, self.y))
        x1 = max(x0 + 1, min(frame_w, self.x + self.width))
        y1 = max(y0 + 1, min(frame_h, self.y + self.height))
        return Roi(x0, y0, x1 - x0, y1 - y0)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        clipped = self.clamp_to_frame(frame.shape)
        return frame[clipped.y : clipped.y + clipped.height, clipped.x : clipped.x + clipped.width]


@dataclass(frozen=True)
class ArrayGridCalibration:
    """Perspective mapping between image pixels and the 20 x 20 core grid."""

    corners_px: tuple[Point, Point, Point, Point]
    rows: int = GRID_ROWS
    cols: int = GRID_COLS
    pitch_mm: float = ELECTRODE_PITCH_MM

    def __post_init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is required for array grid calibration")
        if len(self.corners_px) != 4:
            raise ValueError("corners_px must be TL, TR, BR, BL")
        src = np.asarray(self.corners_px, dtype=np.float32)
        dst = np.asarray(
            [[0.0, 0.0], [float(self.cols), 0.0], [float(self.cols), float(self.rows)], [0.0, float(self.rows)]],
            dtype=np.float32,
        )
        pixel_to_grid = cv2.getPerspectiveTransform(src, dst)
        grid_to_pixel = cv2.getPerspectiveTransform(dst, src)
        if pixel_to_grid is None or grid_to_pixel is None:
            raise ValueError("could not build perspective transform from corners")
        object.__setattr__(self, "_pixel_to_grid", pixel_to_grid)
        object.__setattr__(self, "_grid_to_pixel", grid_to_pixel)

    @staticmethod
    def _transform(points: Sequence[Point], matrix: np.ndarray) -> tuple[Point, ...]:
        source = np.asarray([[list(point) for point in points]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(source, matrix)[0]
        return tuple((float(point[0]), float(point[1])) for point in mapped)

    def pixel_to_grid_position(self, point: Point) -> tuple[float, float]:
        col, row = self._transform([point], self._pixel_to_grid)[0]
        return row, col

    def grid_to_pixel(self, point: Point) -> Point:
        return self._transform([point], self._grid_to_pixel)[0]

    def grid_polygon_to_pixel(self, polygon: Sequence[Point]) -> tuple[Point, ...]:
        return self._transform(polygon, self._grid_to_pixel)

    def pixel_to_mm(self, point: Point) -> Point:
        row, col = self.pixel_to_grid_position(point)
        return col * self.pitch_mm, row * self.pitch_mm

    def mm_to_pixel(self, point: Point) -> Point:
        return self.grid_to_pixel((point[0] / self.pitch_mm, point[1] / self.pitch_mm))

    def pixel_to_cell(self, point: Point) -> Cell:
        row, col = self.pixel_to_grid_position(point)
        return clamp_cell((int(math.floor(row)), int(math.floor(col))), self.rows, self.cols)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "corners_px": self.corners_px,
            "rows": self.rows,
            "cols": self.cols,
            "pitch_mm": self.pitch_mm,
        }
