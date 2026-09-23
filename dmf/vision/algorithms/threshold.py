from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from ..contracts import FramePacket, VisionResult
from .common import clean_mask, require_opencv, result_from_mask

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True)
class ThresholdConfig:
    color_space: str = "hsv"
    lower: tuple[int, ...] = (0, 0, 0)
    upper: tuple[int, ...] = (180, 255, 120)
    invert: bool = False
    min_area_px: float = 40.0
    max_area_px: Optional[float] = None
    morphology_kernel: int = 3
    open_iterations: int = 1
    close_iterations: int = 2

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "ThresholdConfig":
        return cls(
            color_space=str(values.get("color_space", "hsv")).lower(),
            lower=tuple(int(value) for value in values.get("lower", (0, 0, 0))),
            upper=tuple(int(value) for value in values.get("upper", (180, 255, 120))),
            invert=bool(values.get("invert", False)),
            min_area_px=float(values.get("min_area_px", 40.0)),
            max_area_px=float(values["max_area_px"]) if values.get("max_area_px") is not None else None,
            morphology_kernel=int(values.get("morphology_kernel", 3)),
            open_iterations=int(values.get("open_iterations", 1)),
            close_iterations=int(values.get("close_iterations", 2)),
        )


class ThresholdSegmenter:
    name = "threshold"

    def __init__(self, config: ThresholdConfig | None = None):
        require_opencv()
        self.config = config or ThresholdConfig()
        if self.config.color_space not in {"hsv", "bgr", "gray"}:
            raise ValueError("threshold color_space must be hsv, bgr, or gray")

    def process(self, frame: FramePacket) -> VisionResult:
        started_at = time.perf_counter()
        image = frame.image_bgr
        if self.config.color_space == "hsv":
            converted = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        elif self.config.color_space == "gray":
            converted = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            converted = image
        lower, upper = self._bounds(converted)
        mask = cv2.inRange(converted, lower, upper)
        if self.config.invert:
            mask = cv2.bitwise_not(mask)
        mask = clean_mask(
            mask,
            self.config.morphology_kernel,
            self.config.open_iterations,
            self.config.close_iterations,
        )
        result = result_from_mask(mask, started_at, self.config.min_area_px, self.config.max_area_px)
        result.validate(image.shape)
        return result

    def _bounds(self, converted: np.ndarray):
        channels = 1 if converted.ndim == 2 else converted.shape[2]
        if len(self.config.lower) != channels or len(self.config.upper) != channels:
            raise ValueError(f"threshold bounds need {channels} value(s) for {self.config.color_space}")
        if channels == 1:
            return int(self.config.lower[0]), int(self.config.upper[0])
        return np.asarray(self.config.lower, dtype=np.uint8), np.asarray(self.config.upper, dtype=np.uint8)
