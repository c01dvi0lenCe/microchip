from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .contracts import DropletFeatures, FramePacket, VisionResult
from .electrode_map import ElectrodeMap, ElectrodeRegion

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def polygon_mask(shape: tuple[int, int], region: ElectrodeRegion) -> np.ndarray:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for electrode mask operations")
    output = np.zeros(shape, dtype=np.uint8)
    polygon = np.rint(np.asarray(region.polygon_px, dtype=np.float32)).astype(np.int32)
    cv2.fillPoly(output, [polygon], 255)
    return output


class DropletFeatureExtractor:
    def __init__(self, electrode_map: ElectrodeMap):
        self.electrode_map = electrode_map
        self.previous_centroid_mm: Optional[tuple[float, float]] = None
        self.previous_timestamp_s: Optional[float] = None

    def reset(self) -> None:
        self.previous_centroid_mm = None
        self.previous_timestamp_s = None

    def extract(
        self,
        packet: FramePacket,
        result: VisionResult,
        source_electrode: Optional[int],
        target_electrode: Optional[int],
    ) -> DropletFeatures:
        centroid_px = result.centroid_px if result.detected else None
        centroid_mm = self.electrode_map.calibration.pixel_to_mm(centroid_px) if centroid_px is not None else None
        source_coverage = self._coverage(result.mask, source_electrode)
        target_coverage = self._coverage(result.mask, target_electrode)
        distance = None
        if centroid_mm is not None and target_electrode is not None:
            target = self.electrode_map[target_electrode].center_mm
            distance = math.hypot(centroid_mm[0] - target[0], centroid_mm[1] - target[1])

        velocity = None
        timestamp_valid = math.isfinite(packet.timestamp_s)
        if (
            centroid_mm is not None
            and timestamp_valid
            and self.previous_centroid_mm is not None
            and self.previous_timestamp_s is not None
        ):
            elapsed = packet.timestamp_s - self.previous_timestamp_s
            if elapsed > 0:
                velocity = math.hypot(
                    centroid_mm[0] - self.previous_centroid_mm[0],
                    centroid_mm[1] - self.previous_centroid_mm[1],
                ) / elapsed
        if centroid_mm is not None and timestamp_valid:
            self.previous_centroid_mm = centroid_mm
            self.previous_timestamp_s = packet.timestamp_s

        return DropletFeatures(
            centroid_px=centroid_px,
            centroid_mm=centroid_mm,
            area_px=result.area_px,
            source_coverage=source_coverage,
            target_coverage=target_coverage,
            distance_to_target_mm=distance,
            velocity_mm_s=velocity,
        )

    def _coverage(self, mask: Optional[np.ndarray], electrode_id: Optional[int]) -> Optional[float]:
        if mask is None or electrode_id is None:
            return None
        droplet_area = int(np.count_nonzero(mask))
        if droplet_area == 0:
            return 0.0
        region_mask = polygon_mask(mask.shape, self.electrode_map[electrode_id])
        intersection = int(np.count_nonzero((mask > 0) & (region_mask > 0)))
        return intersection / droplet_area
