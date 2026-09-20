from __future__ import annotations

import math
import random
from typing import Iterable, Optional

import numpy as np

from simulation.profiles import VisionNoiseProfile

from .layout import (
    CAMERA_LAYOUT_PADDING_CELLS,
    CORNER_RESERVOIRS,
    Cell,
    DROPLET_DETECTION_RGB,
    DROPLET_DETECTION_TOLERANCE,
    GRID_COLS,
    GRID_ROWS,
    GridPosition,
    RESERVOIR_CELLS,
    SIDE_RESERVOIR_LARGE,
    rounded_cell,
)
from .models import Detection

try:
    import cv2
except ImportError:  # pragma: no cover - exercised only without OpenCV.
    cv2 = None


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
            x0 = int(round(left + col * cell_size))
            y0 = int(round(top + row * cell_size))
            x1 = int(round(left + (col + 1) * cell_size))
            y1 = int(round(top + (row + 1) * cell_size))
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
