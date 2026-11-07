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
class FrameTiming:
    """Raw acquisition metadata. Device ticks are never assumed to be seconds.

    Exposure stamps may only be supplied by an explicitly calibrated adapter;
    ordinary SDK host-receive timestamps do not establish exposure ordering.
    """
    capture_frame_id: int | None = None
    receive_monotonic_ns: int | None = None
    receive_perf_counter_ns: int | None = None
    device_ticks_raw: int | None = None
    clock_domain: str = 'unknown'
    timing_quality: str = 'unknown'
    exposure_start_ns: int | None = None
    exposure_clock_domain: str = 'unknown'
    queue_overwrites: int = 0
    task_epoch: int | None = None
    sdk_host_timestamp_raw: int | None = None
    receive_utc_ns: int | None = None
    relative_anchor_perf_counter_ns: int | None = None

    def __post_init__(self):
        for name in ('capture_frame_id','receive_monotonic_ns','receive_perf_counter_ns',
                     'device_ticks_raw','exposure_start_ns','task_epoch','queue_overwrites',
                     'sdk_host_timestamp_raw','receive_utc_ns','relative_anchor_perf_counter_ns'):
            value=getattr(self,name)
            if value is not None and (type(value) is not int or value<0):
                raise ValueError(f'{name} must be a nonnegative integer or None')


@dataclass(frozen=True)
class FramePacket:
    video_id: str
    frame_id: int
    timestamp_s: float
    timestamp_source: str
    image_bgr: np.ndarray
    timing: FrameTiming | None = None

    @property
    def capture_identity(self) -> int:
        return self.timing.capture_frame_id if self.timing and self.timing.capture_frame_id is not None else self.frame_id

    @property
    def timestamp_clock_domain(self) -> str:
        if self.timing is not None:return self.timing.clock_domain
        if self.timestamp_source in {'video_pts','fps_fallback','container_fps_unverified'}:return 'video_relative'
        if self.timestamp_source=='host_receive_perf_counter':return 'recorded_host_relative'
        if self.timestamp_source in {'host_receive_monotonic','host_monotonic'}:return 'host_monotonic'
        return 'legacy:'+self.timestamp_source


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
    target_electrode_coverage: Optional[float] = None
    source_intersection_px: Optional[int] = None
    target_intersection_px: Optional[int] = None
    progress_mm: Optional[float] = None
    progress_fraction: Optional[float] = None
    lateral_error_mm: Optional[float] = None
    velocity_parallel_mm_s: Optional[float] = None
    geometry_quality: str = ''


@dataclass(frozen=True)
class FrameRecord:
    run_id: str
    video_id: str
    experiment_id: str
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
    lighting_condition: str
    notes: str
    processing_time_ms: float
    pipeline_time_ms: float
    retry_count: Optional[int]
    mask_path: str
    error_code: str

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)
