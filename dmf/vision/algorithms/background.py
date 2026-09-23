from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from ..contracts import FramePacket, VisionResult
from .common import clean_mask, require_opencv, result_from_mask
from ..image_io import read_image

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True)
class BackgroundConfig:
    min_diff: int = 14
    min_area_px: float = 40.0
    max_area_px: Optional[float] = None
    morphology_kernel: int = 3
    open_iterations: int = 1
    close_iterations: int = 2

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "BackgroundConfig":
        return cls(
            min_diff=int(values.get("min_diff", 14)),
            min_area_px=float(values.get("min_area_px", 40.0)),
            max_area_px=float(values["max_area_px"]) if values.get("max_area_px") is not None else None,
            morphology_kernel=int(values.get("morphology_kernel", 3)),
            open_iterations=int(values.get("open_iterations", 1)),
            close_iterations=int(values.get("close_iterations", 2)),
        )


class BackgroundSegmenter:
    name = "background"

    def __init__(self, background_bgr: np.ndarray, config: BackgroundConfig | None = None):
        require_opencv()
        if background_bgr is None or background_bgr.size == 0:
            raise ValueError("an explicit background image is required")
        self.config = config or BackgroundConfig()
        self.background_gray = self._prepare(background_bgr)

    @staticmethod
    def _prepare(image_bgr: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def process(self, frame: FramePacket) -> VisionResult:
        started_at = time.perf_counter()
        gray = self._prepare(frame.image_bgr)
        if gray.shape != self.background_gray.shape:
            raise ValueError("background image size must match the input video")
        diff = cv2.absdiff(gray, self.background_gray)
        if int(diff.max()) <= self.config.min_diff:
            mask = np.zeros_like(diff)
        else:
            _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            mask[diff < self.config.min_diff] = 0
        mask = clean_mask(
            mask,
            self.config.morphology_kernel,
            self.config.open_iterations,
            self.config.close_iterations,
        )
        result = result_from_mask(mask, started_at, self.config.min_area_px, self.config.max_area_px)
        result.validate(frame.image_bgr.shape)
        return result


def median_background_from_images(paths: Sequence[Path]) -> np.ndarray:
    require_opencv()
    frames = []
    for path in paths:
        frame = read_image(path, cv2.IMREAD_COLOR)
        if frame is None:
            raise FileNotFoundError(f"could not read background image: {path}")
        frames.append(frame)
    if not frames:
        raise ValueError("at least one explicit background image is required")
    shapes = {frame.shape for frame in frames}
    if len(shapes) != 1:
        raise ValueError("all background images must have the same dimensions")
    return np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)


def median_background_from_video(path: Path, sample_count: int = 25) -> np.ndarray:
    """Build a background only from a dedicated blank-background video."""
    require_opencv()
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open background video: {path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    indices = [0] if total <= 0 else sorted(set(int(value) for value in np.linspace(0, total - 1, min(total, sample_count))))
    frames = []
    try:
        for frame_index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise RuntimeError(f"could not sample background frames from {path}")
    return np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)
