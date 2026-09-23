from __future__ import annotations

import math
from typing import Iterable, Optional

import numpy as np

from ..layout import cell_from_electrode_id, electrode_id
from .contracts import FramePacket, VisionResult
from .electrode_map import ElectrodeMap

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class SpatialConstraint:
    def __init__(self, electrode_map: ElectrodeMap, allowed_electrodes: Iterable[int]):
        self.electrode_map = electrode_map
        self.allowed_electrodes = frozenset(int(value) for value in allowed_electrodes)
        if not self.allowed_electrodes:
            raise ValueError("spatial constraint requires at least one allowed electrode")

    def apply(self, result: VisionResult) -> VisionResult:
        if not result.detected or result.centroid_px is None:
            return result
        if cv2 is None:
            raise RuntimeError("OpenCV is required for spatial constraints")
        point = result.centroid_px
        for electrode_id_value in self.allowed_electrodes:
            polygon = np.asarray(self.electrode_map[electrode_id_value].polygon_px, dtype=np.float32)
            if cv2.pointPolygonTest(polygon, point, False) >= 0:
                return result
        return VisionResult(None, None, None, 0.0, result.processing_time_ms, False, "SPATIAL_REJECT")


class TemporalConstraint:
    def __init__(self, electrode_map: ElectrodeMap, max_speed_mm_s: float, tolerance_mm: float):
        if max_speed_mm_s <= 0:
            raise ValueError("temporal max_speed_mm_s must be positive")
        if tolerance_mm < 0:
            raise ValueError("temporal tolerance_mm must be non-negative")
        self.electrode_map = electrode_map
        self.max_speed_mm_s = float(max_speed_mm_s)
        self.tolerance_mm = float(tolerance_mm)
        self.previous_point_mm: Optional[tuple[float, float]] = None
        self.previous_timestamp_s: Optional[float] = None

    def apply(self, packet: FramePacket, result: VisionResult) -> VisionResult:
        if not result.detected or result.centroid_px is None:
            return result
        if not math.isfinite(packet.timestamp_s):
            return VisionResult(None, None, None, 0.0, result.processing_time_ms, False, "INVALID_TIMESTAMP")
        point_mm = self.electrode_map.calibration.pixel_to_mm(result.centroid_px)
        if self.previous_point_mm is not None and self.previous_timestamp_s is not None:
            elapsed = packet.timestamp_s - self.previous_timestamp_s
            if elapsed <= 0:
                return VisionResult(None, None, None, 0.0, result.processing_time_ms, False, "INVALID_TIMESTAMP")
            distance = math.hypot(point_mm[0] - self.previous_point_mm[0], point_mm[1] - self.previous_point_mm[1])
            if distance > self.max_speed_mm_s * elapsed + self.tolerance_mm:
                return VisionResult(None, None, None, 0.0, result.processing_time_ms, False, "TEMPORAL_REJECT")
        self.previous_point_mm = point_mm
        self.previous_timestamp_s = packet.timestamp_s
        return result


def neighboring_electrode_ids(electrode_id_value: int, include_diagonal: bool = True) -> set[int]:
    row, col = cell_from_electrode_id(electrode_id_value)
    result = {electrode_id_value}
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == dc == 0 or (not include_diagonal and abs(dr) + abs(dc) > 1):
                continue
            candidate = (row + dr, col + dc)
            try:
                result.add(electrode_id(candidate[0], candidate[1]))
            except ValueError:
                continue
    return result
