from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np

from dmf_simulation import ELECTRODE_PITCH_MM, GRID_COLS, GRID_ROWS, Cell, clamp_cell, electrode_id

try:
    import cv2
except ImportError:  # pragma: no cover - only used on machines without OpenCV.
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

    def clamp_to_frame(self, frame_shape: tuple[int, int, int] | tuple[int, int]) -> "Roi":
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
class MotionCalibration:
    origin_px: Point
    axis_unit: Point
    step_px: float
    step_mm: float = ELECTRODE_PITCH_MM

    @classmethod
    def from_points(
        cls,
        origin_px: Point,
        axis_end_px: Point,
        step_px: Optional[float] = None,
        step_points: Optional[tuple[Point, Point]] = None,
        step_mm: float = ELECTRODE_PITCH_MM,
    ) -> "MotionCalibration":
        dx = axis_end_px[0] - origin_px[0]
        dy = axis_end_px[1] - origin_px[1]
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            raise ValueError("Motion axis points must be different")
        axis_unit = (dx / norm, dy / norm)

        if step_points is not None:
            step_px = abs(project_along_axis(step_points[1], step_points[0], axis_unit))
        if step_px is None or step_px <= 0:
            raise ValueError("A positive step_px or two step_points are required")
        return cls(origin_px=origin_px, axis_unit=axis_unit, step_px=float(step_px), step_mm=float(step_mm))

    @classmethod
    def default_for_roi(cls, roi: Roi, step_px: float, step_mm: float = ELECTRODE_PITCH_MM) -> "MotionCalibration":
        y = roi.y + roi.height / 2
        return cls.from_points((roi.x, y), (roi.x + roi.width, y), step_px=step_px, step_mm=step_mm)

    def project_px(self, point: Point) -> float:
        return project_along_axis(point, self.origin_px, self.axis_unit)

    def displacement_mm(self, point: Point) -> float:
        return self.project_px(point) / self.step_px * self.step_mm

    def virtual_step(self, point: Point) -> int:
        return int(round(self.project_px(point) / self.step_px))


@dataclass(frozen=True)
class DropletObservation:
    frame_index: int
    time_s: float
    x_px: Optional[float]
    y_px: Optional[float]
    front_x_px: Optional[float]
    front_y_px: Optional[float]
    area_px: float
    confidence: float
    virtual_step: Optional[int]
    displacement_mm: Optional[float]
    event: str

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StepEvent:
    frame_index: int
    time_s: float
    virtual_step: int
    displacement_mm: float
    event: str

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SpeedSegment:
    start_step: int
    end_step: int
    start_time_s: float
    end_time_s: float
    duration_s: float
    distance_mm: float
    speed_mm_s: float

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ArrayGridCalibration:
    """Perspective mapping used later for real 20x20 camera feedback."""

    corners_px: tuple[Point, Point, Point, Point]
    rows: int = GRID_ROWS
    cols: int = GRID_COLS

    def __post_init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is required for array grid calibration")
        object.__setattr__(self, "_homography", self._build_homography())

    def _build_homography(self) -> np.ndarray:
        src = np.array(self.corners_px, dtype=np.float32)
        dst = np.array(
            [[0.0, 0.0], [float(self.cols), 0.0], [float(self.cols), float(self.rows)], [0.0, float(self.rows)]],
            dtype=np.float32,
        )
        homography = cv2.getPerspectiveTransform(src, dst)
        if homography is None:
            raise ValueError("Could not build perspective transform from corners")
        return homography

    def pixel_to_grid_position(self, point: Point) -> tuple[float, float]:
        src = np.array([[[point[0], point[1]]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(src, self._homography)[0][0]
        col = float(mapped[0])
        row = float(mapped[1])
        return row, col

    def pixel_to_cell(self, point: Point) -> Cell:
        row, col = self.pixel_to_grid_position(point)
        return clamp_cell((int(math.floor(row)), int(math.floor(col))), self.rows, self.cols)

    def to_json_dict(self) -> dict[str, object]:
        return {"corners_px": self.corners_px, "rows": self.rows, "cols": self.cols}


@dataclass(frozen=True)
class SwitchSuggestion:
    current_cell: Optional[Cell]
    next_cell: Optional[Cell]
    previous_cell: Optional[Cell]
    commands: tuple[str, ...]
    event: str


class PathSwitchAdvisor:
    """Debounced future interface for turning detected cells into SET commands."""

    def __init__(self, path: Sequence[Cell], stable_frames_required: int = 2):
        if not path:
            raise ValueError("Path must contain at least one cell")
        if stable_frames_required < 1:
            raise ValueError("stable_frames_required must be positive")
        self.path = list(path)
        self.stable_frames_required = stable_frames_required
        self.path_index = 0
        self.pending_cell: Optional[Cell] = None
        self.pending_count = 0
        self.active_cells: set[Cell] = set()

    def update(self, detected_cell: Optional[Cell], confidence: float = 1.0) -> SwitchSuggestion:
        previous_cell = self.path[self.path_index - 1] if self.path_index > 0 else None
        current_cell = self.path[self.path_index]
        next_cell = self.path[self.path_index + 1] if self.path_index + 1 < len(self.path) else None

        event = "ok"
        if detected_cell is None or confidence <= 0:
            event = "lost"
            return SwitchSuggestion(current_cell, next_cell, previous_cell, tuple(), event)

        if next_cell is not None and detected_cell == next_cell:
            if self.pending_cell == detected_cell:
                self.pending_count += 1
            else:
                self.pending_cell = detected_cell
                self.pending_count = 1
            if self.pending_count >= self.stable_frames_required:
                self.path_index += 1
                previous_cell = current_cell
                current_cell = self.path[self.path_index]
                next_cell = self.path[self.path_index + 1] if self.path_index + 1 < len(self.path) else None
                self.pending_cell = None
                self.pending_count = 0
                event = "advance"
            else:
                event = "debounce"
        elif detected_cell == current_cell:
            self.pending_cell = None
            self.pending_count = 0
        elif previous_cell is not None and detected_cell == previous_cell:
            event = "backtrack_hold"
        else:
            event = "off_path"

        desired = {next_cell} if next_cell is not None else {current_cell}
        commands = self._commands_for_desired(desired)
        return SwitchSuggestion(current_cell, next_cell, previous_cell, commands, event)

    def _commands_for_desired(self, desired: set[Cell]) -> tuple[str, ...]:
        commands: list[str] = []
        for cell in sorted(self.active_cells - desired):
            commands.append(f"SET:{electrode_id(cell[0], cell[1])}:0")
        for cell in sorted(desired - self.active_cells):
            commands.append(f"SET:{electrode_id(cell[0], cell[1])}:1")
        self.active_cells = set(desired)
        return tuple(commands)


class DropletVideoTracker:
    def __init__(
        self,
        calibration: MotionCalibration,
        roi: Optional[Roi] = None,
        background_gray: Optional[np.ndarray] = None,
        min_area_px: float = 40.0,
        max_area_px: Optional[float] = None,
        min_diff: int = 14,
        front_mode: str = "motion",
        min_front_motion_px: float = 2.0,
    ):
        if cv2 is None:
            raise RuntimeError("OpenCV is required for droplet video analysis")
        if front_mode not in {"motion", "axis"}:
            raise ValueError("front_mode must be 'motion' or 'axis'")
        self.calibration = calibration
        self.roi = roi
        self.background_gray = background_gray
        self.min_area_px = min_area_px
        self.max_area_px = max_area_px
        self.min_diff = min_diff
        self.front_mode = front_mode
        self.min_front_motion_px = min_front_motion_px
        self.previous_center: Optional[Point] = None
        self.previous_area: Optional[float] = None
        self.previous_front_axis: Point = calibration.axis_unit

    def observe(self, frame_bgr: np.ndarray, frame_index: int, time_s: float) -> DropletObservation:
        roi = self.roi or Roi(0, 0, frame_bgr.shape[1], frame_bgr.shape[0])
        roi = roi.clamp_to_frame(frame_bgr.shape)
        crop = roi.crop(frame_bgr)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self.background_gray is None:
            self.background_gray = gray.copy()

        bg = self._background_for_roi(gray.shape)
        diff = cv2.absdiff(gray, bg)
        mask = self._foreground_mask(diff)
        contour = self._select_contour(mask, roi)
        if contour is None:
            return DropletObservation(frame_index, time_s, None, None, None, None, 0.0, 0.0, None, None, "lost")

        area = float(cv2.contourArea(contour))
        moments = cv2.moments(contour)
        if abs(moments["m00"]) <= 1e-9:
            return DropletObservation(frame_index, time_s, None, None, None, None, area, 0.0, None, None, "lost")

        center = (moments["m10"] / moments["m00"] + roi.x, moments["m01"] / moments["m00"] + roi.y)
        contour_global = contour.astype(np.float32)
        contour_global[:, 0, 0] += roi.x
        contour_global[:, 0, 1] += roi.y
        front_axis = self._front_axis_for_center(center)
        front = front_point_along_axis(contour_global, center, front_axis)
        event = self._event_for_detection(center, area)
        self.previous_center = center
        self.previous_area = area
        confidence = confidence_from_contour(area, diff, contour, self.min_area_px)
        return DropletObservation(
            frame_index=frame_index,
            time_s=time_s,
            x_px=center[0],
            y_px=center[1],
            front_x_px=front[0],
            front_y_px=front[1],
            area_px=area,
            confidence=confidence,
            virtual_step=self.calibration.virtual_step(center),
            displacement_mm=self.calibration.displacement_mm(center),
            event=event,
        )

    def _background_for_roi(self, gray_shape: tuple[int, int]) -> np.ndarray:
        bg = self.background_gray
        if bg is None:
            raise RuntimeError("Background has not been initialized")
        if bg.shape == gray_shape:
            return bg
        if self.roi is not None and bg.ndim == 2:
            full_roi = self.roi.clamp_to_frame((bg.shape[0], bg.shape[1]))
            cropped = bg[full_roi.y : full_roi.y + full_roi.height, full_roi.x : full_roi.x + full_roi.width]
            if cropped.shape == gray_shape:
                return cropped
        return cv2.resize(bg, (gray_shape[1], gray_shape[0]))

    def _foreground_mask(self, diff: np.ndarray) -> np.ndarray:
        if float(diff.max()) <= self.min_diff:
            return np.zeros_like(diff)
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask[diff < self.min_diff] = 0
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        return mask

    def _select_contour(self, mask: np.ndarray, roi: Roi):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < self.min_area_px:
                continue
            if self.max_area_px is not None and area > self.max_area_px:
                continue
            moments = cv2.moments(contour)
            if abs(moments["m00"]) <= 1e-9:
                continue
            cx = moments["m10"] / moments["m00"] + roi.x
            cy = moments["m01"] / moments["m00"] + roi.y
            if self.previous_center is None:
                distance_score = 0.0
            else:
                distance_score = math.hypot(cx - self.previous_center[0], cy - self.previous_center[1])
            candidates.append((distance_score, -area, contour))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:2])
        return candidates[0][2]

    def _event_for_detection(self, center: Point, area: float) -> str:
        if self.previous_center is None:
            return "detected"
        if self.previous_area and area > self.previous_area * 1.8:
            return "possible_merge_or_deformation"
        jump_px = math.hypot(center[0] - self.previous_center[0], center[1] - self.previous_center[1])
        if jump_px > self.calibration.step_px * 1.5:
            return "jump"
        return "ok"

    def _front_axis_for_center(self, center: Point) -> Point:
        if self.front_mode == "axis" or self.previous_center is None:
            return self.previous_front_axis
        dx = center[0] - self.previous_center[0]
        dy = center[1] - self.previous_center[1]
        norm = math.hypot(dx, dy)
        if norm >= self.min_front_motion_px:
            self.previous_front_axis = (dx / norm, dy / norm)
        return self.previous_front_axis


def project_along_axis(point: Point, origin: Point, axis_unit: Point) -> float:
    return (point[0] - origin[0]) * axis_unit[0] + (point[1] - origin[1]) * axis_unit[1]


def front_point_along_axis(contour: np.ndarray, origin: Point, axis_unit: Point) -> Point:
    points = contour.reshape(-1, 2)
    projections = (points[:, 0] - origin[0]) * axis_unit[0] + (points[:, 1] - origin[1]) * axis_unit[1]
    idx = int(np.argmax(projections))
    return float(points[idx, 0]), float(points[idx, 1])


def confidence_from_contour(area: float, diff: np.ndarray, contour: np.ndarray, min_area: float) -> float:
    mask = np.zeros(diff.shape, dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    contrast = float(diff[mask > 0].mean()) if np.any(mask > 0) else 0.0
    area_score = min(1.0, area / max(min_area * 4.0, 1.0))
    contrast_score = min(1.0, contrast / 45.0)
    return round(max(0.0, min(1.0, 0.55 * area_score + 0.45 * contrast_score)), 4)


def build_background_from_video(video_path: Path, roi: Optional[Roi] = None, sample_count: int = 25) -> np.ndarray:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for droplet video analysis")
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        frame_indices = [0]
    else:
        frame_indices = sorted(set(int(i) for i in np.linspace(0, max(0, total - 1), min(sample_count, total))))
    frames = []
    for frame_index in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        crop = roi.crop(frame) if roi is not None else frame
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        frames.append(gray)
    cap.release()
    if not frames:
        raise RuntimeError(f"Could not sample background frames from {video_path}")
    return np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)


def analyze_video(
    video_path: Path,
    output_dir: Path,
    calibration: MotionCalibration,
    roi: Optional[Roi] = None,
    start_frame: int = 0,
    max_frames: Optional[int] = None,
    annotated_video: bool = False,
    front_mode: str = "motion",
    show_axis: bool = False,
) -> tuple[list[DropletObservation], list[StepEvent], list[SpeedSegment]]:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for droplet video analysis")
    output_dir.mkdir(parents=True, exist_ok=True)
    background = build_background_from_video(video_path, roi)
    tracker = DropletVideoTracker(calibration=calibration, roi=roi, background_gray=background, front_mode=front_mode)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    writer = None
    observations: list[DropletObservation] = []
    start_frame = max(0, int(start_frame))
    if start_frame:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_index = start_frame
    frames_read = 0

    try:
        if annotated_video:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(output_dir / "annotated_tracking.mp4"), fourcc, fps, (width, height))

        while True:
            if max_frames is not None and frames_read >= max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                break
            observation = tracker.observe(frame, frame_index, frame_index / fps)
            observations.append(observation)
            if writer is not None:
                writer.write(draw_observation_overlay(frame, observation, calibration, roi, show_axis=show_axis))
            frame_index += 1
            frames_read += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    step_events = extract_step_events(observations)
    speed_segments = summarize_speed_segments(step_events, calibration.step_mm)
    write_csv(output_dir / "droplet_tracks.csv", [item.to_csv_row() for item in observations])
    write_csv(output_dir / "step_events.csv", [item.to_csv_row() for item in step_events])
    write_csv(output_dir / "speed_validation.csv", [item.to_csv_row() for item in speed_segments])
    write_json(
        output_dir / "tracking_config.json",
        {
            "video_path": str(video_path),
            "roi": asdict(roi) if roi is not None else None,
            "calibration": asdict(calibration),
            "start_frame": start_frame,
            "max_frames": max_frames,
            "front_mode": front_mode,
            "show_axis": show_axis,
        },
    )
    return observations, step_events, speed_segments


def extract_step_events(observations: Iterable[DropletObservation]) -> list[StepEvent]:
    events: list[StepEvent] = []
    last_step: Optional[int] = None
    for observation in observations:
        if observation.virtual_step is None or observation.displacement_mm is None:
            continue
        if last_step is None or observation.virtual_step != last_step:
            events.append(
                StepEvent(
                    frame_index=observation.frame_index,
                    time_s=observation.time_s,
                    virtual_step=observation.virtual_step,
                    displacement_mm=observation.displacement_mm,
                    event="step_change" if last_step is not None else "initial_step",
                )
            )
            last_step = observation.virtual_step
    return events


def summarize_speed_segments(step_events: Sequence[StepEvent], step_mm: float = ELECTRODE_PITCH_MM) -> list[SpeedSegment]:
    segments: list[SpeedSegment] = []
    for previous, current in zip(step_events, step_events[1:]):
        step_delta = current.virtual_step - previous.virtual_step
        duration = current.time_s - previous.time_s
        if duration <= 0 or step_delta == 0:
            continue
        distance = abs(step_delta) * step_mm
        segments.append(
            SpeedSegment(
                start_step=previous.virtual_step,
                end_step=current.virtual_step,
                start_time_s=previous.time_s,
                end_time_s=current.time_s,
                duration_s=duration,
                distance_mm=distance,
                speed_mm_s=distance / duration,
            )
        )
    return segments


def draw_observation_overlay(
    frame_bgr: np.ndarray,
    observation: DropletObservation,
    calibration: MotionCalibration,
    roi: Optional[Roi] = None,
    show_axis: bool = False,
) -> np.ndarray:
    frame = frame_bgr.copy()
    if roi is not None:
        cv2.rectangle(frame, (roi.x, roi.y), (roi.x + roi.width, roi.y + roi.height), (40, 180, 255), 2)
    if show_axis:
        start = (int(round(calibration.origin_px[0])), int(round(calibration.origin_px[1])))
        end = (
            int(round(calibration.origin_px[0] + calibration.axis_unit[0] * calibration.step_px * 4)),
            int(round(calibration.origin_px[1] + calibration.axis_unit[1] * calibration.step_px * 4)),
        )
        cv2.arrowedLine(frame, start, end, (90, 210, 90), 2, tipLength=0.08)
    if observation.x_px is not None and observation.y_px is not None:
        center = (int(round(observation.x_px)), int(round(observation.y_px)))
        cv2.circle(frame, center, 6, (255, 80, 40), -1)
    if observation.front_x_px is not None and observation.front_y_px is not None:
        front = (int(round(observation.front_x_px)), int(round(observation.front_y_px)))
        cv2.circle(frame, front, 5, (50, 50, 255), 2)
    label = f"f={observation.frame_index} step={observation.virtual_step} conf={observation.confidence:.2f} {observation.event}"
    cv2.putText(frame, label, (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 3, cv2.LINE_AA)
    cv2.putText(frame, label, (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (245, 245, 245), 1, cv2.LINE_AA)
    return frame


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_float_list(value: str, expected: int, name: str) -> list[float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != expected:
        raise argparse.ArgumentTypeError(f"{name} must contain {expected} comma-separated numbers")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} contains a non-numeric value") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track a DMF droplet in velocity videos and export validation CSV files.")
    parser.add_argument("--video", required=True, type=Path, help="Input video path")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for CSV/overlay outputs")
    parser.add_argument("--roi", help="Optional x,y,width,height ROI")
    parser.add_argument("--axis", help="Motion axis x1,y1,x2,y2; defaults to horizontal ROI axis")
    parser.add_argument("--step-px", type=float, help="Pixels corresponding to one 3.2 mm virtual electrode step")
    parser.add_argument("--step-points", help="Two points spanning one step: x1,y1,x2,y2")
    parser.add_argument("--step-mm", type=float, default=ELECTRODE_PITCH_MM, help="Physical distance per virtual step")
    parser.add_argument(
        "--front-mode",
        choices=("motion", "axis"),
        default="motion",
        help="How to draw the red front marker: frame-to-frame motion direction or fixed axis",
    )
    parser.add_argument("--start-frame", type=int, default=0, help="First video frame to analyze")
    parser.add_argument("--max-frames", type=int, help="Optional frame limit for quick validation")
    parser.add_argument("--annotated-video", action="store_true", help="Write annotated_tracking.mp4")
    parser.add_argument("--show-axis", action="store_true", help="Draw the fixed calibration axis in annotated video")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if cv2 is None:
        parser.error("opencv-python is required")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        parser.error(f"Could not open video: {args.video}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()

    roi = Roi.from_sequence(parse_float_list(args.roi, 4, "roi")) if args.roi else Roi(0, 0, width, height)
    if args.axis:
        axis_values = parse_float_list(args.axis, 4, "axis")
        origin = (axis_values[0], axis_values[1])
        axis_end = (axis_values[2], axis_values[3])
    else:
        origin = (roi.x, roi.y + roi.height / 2)
        axis_end = (roi.x + roi.width, roi.y + roi.height / 2)

    step_points = None
    if args.step_points:
        values = parse_float_list(args.step_points, 4, "step-points")
        step_points = ((values[0], values[1]), (values[2], values[3]))
    try:
        calibration = MotionCalibration.from_points(
            origin,
            axis_end,
            step_px=args.step_px,
            step_points=step_points,
            step_mm=args.step_mm,
        )
    except ValueError as exc:
        parser.error(str(exc))
    observations, step_events, speed_segments = analyze_video(
        args.video,
        args.output_dir,
        calibration,
        roi=roi,
        start_frame=args.start_frame,
        max_frames=args.max_frames,
        annotated_video=args.annotated_video,
        front_mode=args.front_mode,
        show_axis=args.show_axis,
    )
    print(
        f"tracked_frames={len(observations)} step_events={len(step_events)} "
        f"speed_segments={len(speed_segments)} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
