from __future__ import annotations

import math
from dataclasses import dataclass
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


def coverage_for_region(mask: np.ndarray, region: ElectrodeRegion) -> float:
    droplet_area = int(np.count_nonzero(mask))
    if droplet_area == 0:
        return 0.0
    region_mask = polygon_mask(mask.shape, region)
    intersection = int(np.count_nonzero((mask > 0) & (region_mask > 0)))
    return intersection / droplet_area


@dataclass(frozen=True)
class RegionOverlap:
    intersection_px: int
    droplet_area_px: int
    electrode_area_px: int
    eta_droplet: float | None
    rho_electrode: float | None
    valid: bool
    error: str = ''


def region_overlap(mask, region_mask, *, region_complete=True):
    if mask.ndim!=2 or region_mask.shape!=mask.shape:
        raise ValueError('droplet and region masks must have the same 2D shape')
    droplet=int(np.count_nonzero(mask));electrode=int(np.count_nonzero(region_mask))
    intersection=int(np.count_nonzero((mask>0)&(region_mask>0)))
    error=('EMPTY_DROPLET' if not droplet else 'EMPTY_ELECTRODE' if not electrode else
           'REGION_CLIPPED' if not region_complete else '')
    return RegionOverlap(intersection,droplet,electrode,
        intersection/droplet if droplet else None,
        intersection/electrode if not error else None,not error,error)


@dataclass(frozen=True)
class TransportProjection:
    progress_mm: float
    progress_fraction: float
    lateral_error_mm: float


def transport_projection(point_mm, source_mm, target_mm):
    if any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in (point_mm,source_mm,target_mm)):
        raise ValueError('projection requires finite 2D points')
    dx,dy=target_mm[0]-source_mm[0],target_mm[1]-source_mm[1]
    length=math.hypot(dx,dy)
    if length<=1e-12:raise ValueError('source and target centers must differ')
    x,y=point_mm[0]-source_mm[0],point_mm[1]-source_mm[1]
    progress=(x*dx+y*dy)/length
    return TransportProjection(progress,progress/length,(dx*y-dy*x)/length)


class DropletFeatureExtractor:
    def __init__(self, electrode_map: ElectrodeMap):
        self.electrode_map = electrode_map
        self.previous_centroid_mm: Optional[tuple[float, float]] = None
        self.previous_timestamp_s: Optional[float] = None
        self.previous_task = None
        self.region_mask_cache = {}
        self.previous_clock = None

    def reset(self) -> None:
        self.previous_centroid_mm = None
        self.previous_timestamp_s = None
        self.previous_task = None
        self.previous_clock = None

    def extract(
        self,
        packet: FramePacket,
        result: VisionResult,
        source_electrode: Optional[int],
        target_electrode: Optional[int],
    ) -> DropletFeatures:
        self.electrode_map.validate_frame_shape(packet.image_bgr.shape)
        clock=(packet.video_id,packet.timestamp_clock_domain)
        if self.previous_clock is not None and self.previous_clock!=clock:self.reset()
        self.previous_clock=clock
        centroid_px = result.centroid_px if result.detected else None
        centroid_mm = self.electrode_map.calibration.pixel_to_mm(centroid_px) if centroid_px is not None else None
        source_overlap = self._overlap(result.mask, source_electrode)
        target_overlap = self._overlap(result.mask, target_electrode)
        source_coverage = (source_overlap.eta_droplet if source_overlap.droplet_area_px else 0.) if source_overlap else None
        target_coverage = (target_overlap.eta_droplet if target_overlap.droplet_area_px else 0.) if target_overlap else None
        distance = None
        if centroid_mm is not None and target_electrode is not None:
            target = self.electrode_map[target_electrode].center_mm
            distance = math.hypot(centroid_mm[0] - target[0], centroid_mm[1] - target[1])

        projection = (transport_projection(centroid_mm,self.electrode_map[source_electrode].center_mm,
                      self.electrode_map[target_electrode].center_mm)
                      if centroid_mm is not None and source_electrode is not None and target_electrode is not None
                      and source_electrode!=target_electrode else None)
        velocity = parallel = None
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
                if projection and self.previous_task==(source_electrode,target_electrode):
                    previous=transport_projection(self.previous_centroid_mm,self.electrode_map[source_electrode].center_mm,
                        self.electrode_map[target_electrode].center_mm)
                    parallel=(projection.progress_mm-previous.progress_mm)/elapsed
        if centroid_mm is not None and timestamp_valid and (self.previous_timestamp_s is None or packet.timestamp_s>self.previous_timestamp_s):
            self.previous_centroid_mm = centroid_mm
            self.previous_timestamp_s = packet.timestamp_s
            self.previous_task = (source_electrode,target_electrode)

        return DropletFeatures(
            centroid_px=centroid_px,
            centroid_mm=centroid_mm,
            area_px=result.area_px,
            source_coverage=source_coverage,
            target_coverage=target_coverage,
            distance_to_target_mm=distance,
            velocity_mm_s=velocity,
            target_electrode_coverage=target_overlap.rho_electrode if target_overlap else None,
            source_intersection_px=source_overlap.intersection_px if source_overlap else None,
            target_intersection_px=target_overlap.intersection_px if target_overlap else None,
            progress_mm=projection.progress_mm if projection else None,
            progress_fraction=projection.progress_fraction if projection else None,
            lateral_error_mm=projection.lateral_error_mm if projection else None,
            velocity_parallel_mm_s=parallel,
            geometry_quality=';'.join(sorted({v.error for v in (source_overlap,target_overlap) if v and v.error})),
        )

    def _overlap(self, mask, electrode_id):
        if mask is None or electrode_id is None:
            return None
        key=(mask.shape,electrode_id)
        if key not in self.region_mask_cache:
            polygon=np.asarray(self.electrode_map[electrode_id].polygon_px)
            height,width=mask.shape
            complete=bool(np.all(polygon>=0) and np.all(polygon[:,0]<=width-1) and np.all(polygon[:,1]<=height-1))
            # One image shape is expected per map; don't retain an unbounded
            # sequence of resolutions if an external caller changes frames.
            if any(k[0]!=mask.shape for k in self.region_mask_cache):self.region_mask_cache.clear()
            self.region_mask_cache[key]=(polygon_mask(mask.shape,self.electrode_map[electrode_id]),complete)
        region,complete=self.region_mask_cache[key]
        return region_overlap(mask,region,region_complete=complete)
