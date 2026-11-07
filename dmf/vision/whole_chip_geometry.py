"""Native-resolution whole-frame tiling and global mask geometry.

The ROI selects *observed* pixels, not an image crop: halos may read real image
pixels outside it. Callers retain ROI metadata because zeros outside the ROI
are unobserved, not evidence that no droplet exists there. Components are
frame-local observations, never persistent droplet identities.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


TILE_SIZE = 512
CORE_STRIDE = 384
HALO = 64


def _integer(value: object, name: str, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum} (not bool)")


@dataclass(frozen=True)
class Tile:
    """A uniquely owned output core in original-frame pixel coordinates."""

    core_x: int
    core_y: int
    core_w: int
    core_h: int

    def __post_init__(self) -> None:
        for name in ("core_x", "core_y"):
            _integer(getattr(self, name), name, 0)
        for name in ("core_w", "core_h"):
            _integer(getattr(self, name), name, 1)
            if getattr(self, name) > CORE_STRIDE:
                raise ValueError(f"{name} must not exceed {CORE_STRIDE}")

    @property
    def input_x(self) -> int:
        return self.core_x - HALO

    @property
    def input_y(self) -> int:
        return self.core_y - HALO


def _frame_shape(frame_shape: object) -> tuple[int, int]:
    if not isinstance(frame_shape, (tuple, list)) or len(frame_shape) != 3:
        raise ValueError("frame shape must be (height, width, 3)")
    height, width, channels = frame_shape
    _integer(height, "height", 1)
    _integer(width, "width", 1)
    if type(channels) is not int or channels != 3:
        raise ValueError("frame must have exactly three BGR channels")
    return height, width


def plan_tiles(frame_shape: tuple[int, ...], roi: tuple[int, int, int, int] | None = None) -> tuple[Tile, ...]:
    """Partition the full frame or strict (x, y, width, height) ROI, row first.

    Cores never overlap or shift back at the last edge. Their union is exactly
    the observed area; input windows overlap only to provide model context.
    """
    height, width = _frame_shape(frame_shape)
    if roi is None:
        x, y, roi_w, roi_h = 0, 0, width, height
    else:
        if not isinstance(roi, (tuple, list)) or len(roi) != 4:
            raise ValueError("ROI must be (x, y, width, height)")
        x, y, roi_w, roi_h = roi
        for name, value, minimum in (("ROI x", x, 0), ("ROI y", y, 0),
                                     ("ROI width", roi_w, 1), ("ROI height", roi_h, 1)):
            _integer(value, name, minimum)
        if x + roi_w > width or y + roi_h > height:
            raise ValueError("ROI must be entirely inside the original frame")
    return tuple(
        Tile(core_x, core_y, min(CORE_STRIDE, x + roi_w - core_x),
             min(CORE_STRIDE, y + roi_h - core_y))
        for core_y in range(y, y + roi_h, CORE_STRIDE)
        for core_x in range(x, x + roi_w, CORE_STRIDE)
    )


def _tile_inside(tile: Tile, height: int, width: int) -> None:
    if not isinstance(tile, Tile):
        raise ValueError("tile must be a Tile")
    if tile.core_x + tile.core_w > width or tile.core_y + tile.core_h > height:
        raise ValueError("tile core must be entirely inside the original frame")


def extract_tile(frame: np.ndarray, tile: Tile) -> np.ndarray:
    """Return independent 512x512 uint8 BGR input; white only beyond frame."""
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
        raise ValueError("frame must be a uint8 BGR ndarray")
    height, width = _frame_shape(frame.shape)
    _tile_inside(tile, height, width)
    left, top = max(0, tile.input_x), max(0, tile.input_y)
    right = min(width, tile.input_x + TILE_SIZE)
    bottom = min(height, tile.input_y + TILE_SIZE)
    output = np.full((TILE_SIZE, TILE_SIZE, 3), 255, dtype=np.uint8)
    dx, dy = left - tile.input_x, top - tile.input_y
    output[dy:dy + bottom - top, dx:dx + right - left] = frame[top:bottom, left:right]
    return output


def _mask_shape(mask: np.ndarray, name: str) -> None:
    if (not isinstance(mask, np.ndarray) or mask.dtype != np.uint8
            or mask.ndim != 2 or min(mask.shape) < 1):
        raise ValueError(f"{name} must be a nonempty 2D uint8 binary mask")


def _binary_mask(mask: np.ndarray, name: str) -> None:
    _mask_shape(mask, name)
    # Values 1..254 are precisely the forbidden uint8 values. Native inRange
    # avoids three NumPy boolean temporaries when validating the final mask.
    import cv2

    if cv2.countNonZero(cv2.inRange(mask, 1, 254)):
        raise ValueError(f"{name} must contain only canonical binary values 0 and 255")


def stitch_core(fullmask: np.ndarray, tilemask: np.ndarray, tile: Tile) -> None:
    """Copy only the owned center into an original-size destination.

    Call exactly once per planned tile. Caller owns an original-size uint8
    destination initialized to zero, written only through this function.
    Destination shape/dtype and the complete tile's binary values are checked;
    existing destination pixels are not rescanned per tile. This operation
    does not OR, dilate, filter, resize, assign identities, or publish partial
    results. ``components`` validates the binary completed global mask.
    """
    _mask_shape(fullmask, "fullmask")
    _binary_mask(tilemask, "tilemask")
    if tilemask.shape != (TILE_SIZE, TILE_SIZE):
        raise ValueError("tilemask must be exactly 512x512")
    if not fullmask.flags.writeable:
        raise ValueError("fullmask must be writable")
    _tile_inside(tile, *fullmask.shape)
    fullmask[tile.core_y:tile.core_y + tile.core_h,
             tile.core_x:tile.core_x + tile.core_w] = tilemask[
                 HALO:HALO + tile.core_h, HALO:HALO + tile.core_w]


def components(mask: np.ndarray) -> list[dict]:
    """Extract every 8-connected foreground domain after global stitching.

    Areas count actual foreground pixels, preserving holes and 1px objects.
    Centroids are (x, y), bounding boxes are (x, y, width, height), both in
    original-frame coordinates. IDs are meaningful only within this result.
    """
    _binary_mask(mask, "mask")
    import cv2

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        np.ascontiguousarray(mask), connectivity=8, ltype=cv2.CV_32S)
    return [
        {
            "component_id": int(label),
            "area_px": int(stats[label, cv2.CC_STAT_AREA]),
            "centroid_px": (float(centroids[label, 0]), float(centroids[label, 1])),
            "bbox_xywh": tuple(int(value) for value in stats[label, :4]),
        }
        for label in range(1, count)
    ]
