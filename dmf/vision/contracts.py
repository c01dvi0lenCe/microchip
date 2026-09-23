from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Optional, Protocol

import numpy as np


Point = tuple[float, float]


class DropletState(str, Enum):
    STATIONARY = "Stationary"
    MOVING = "Moving"
    PARTIAL = "Partial"
    ARRIVED = "Arrived"
    DEVIATION = "Deviation"
    UNKNOWN = "Unknown"

    @classmethod
    def parse(cls, value: object) -> "DropletState":
        text = str(value or "").strip().lower()
        for state in cls:
            if text == state.value.lower():
                return state
        return cls.UNKNOWN


@dataclass(frozen=True)
class FramePacket:
    video_id: str
    frame_id: int
    timestamp_s: float
    timestamp_source: str
    image_bgr: np.ndarray


@dataclass
class VisionResult:
    mask: Optional[np.ndarray]
    centroid_px: Optional[Point]
    area_px: Optional[float]
    confidence: float
    processing_time_ms: float
    detected: bool
    error_code: str = ""

    def validate(self, frame_shape: tuple[int, ...]) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.processing_time_ms < 0:
            raise ValueError("processing_time_ms must be non-negative")
        if self.mask is not None:
            if self.mask.shape != frame_shape[:2]:
                raise ValueError("mask must have the same height and width as the source frame")
            values = np.unique(self.mask)
            if not set(int(value) for value in values).issubset({0, 255}):
                raise ValueError("mask must be binary with values 0 and 255")
        if self.detected and self.centroid_px is None:
            raise ValueError("a detected result must include centroid_px")


class VisionAlgorithm(Protocol):
    name: str

    def process(self, frame: FramePacket) -> VisionResult:
        ...


@dataclass(frozen=True)
class DropletFeatures:
    centroid_px: Optional[Point]
    centroid_mm: Optional[Point]
    area_px: Optional[float]
    source_coverage: Optional[float]
    target_coverage: Optional[float]
    distance_to_target_mm: Optional[float]
    velocity_mm_s: Optional[float]


@dataclass(frozen=True)
class FrameRecord:
    run_id: str
    video_id: str
    batch_id: str
    split: str
    frame_id: int
    timestamp_s: float
    timestamp_source: str
    algorithm: str
    detected: bool
    centroid_u_px: Optional[float]
    centroid_v_px: Optional[float]
    centroid_x_mm: Optional[float]
    centroid_y_mm: Optional[float]
    area_px: Optional[float]
    confidence: float
    source_electrode: Optional[int]
    target_electrode: Optional[int]
    source_coverage: Optional[float]
    target_coverage: Optional[float]
    distance_to_target_mm: Optional[float]
    velocity_mm_s: Optional[float]
    state_pred: str
    state_gt: str
    processing_time_ms: float
    pipeline_time_ms: float
    retry_count: Optional[int]
    mask_path: str
    error_code: str

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)
