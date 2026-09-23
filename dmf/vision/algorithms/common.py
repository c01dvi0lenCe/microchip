from __future__ import annotations

import time
from typing import Optional

import numpy as np

from ..contracts import VisionResult

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def require_opencv() -> None:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for vision algorithms")


def clean_mask(mask: np.ndarray, kernel_size: int, open_iterations: int, close_iterations: int) -> np.ndarray:
    require_opencv()
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)
    if kernel_size <= 1:
        return binary
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    if open_iterations > 0:
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=open_iterations)
    if close_iterations > 0:
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=close_iterations)
    return binary


def result_from_mask(
    mask: np.ndarray,
    started_at: float,
    min_area_px: float,
    max_area_px: Optional[float],
) -> VisionResult:
    require_opencv()
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area_px or (max_area_px is not None and area > max_area_px):
            continue
        moments = cv2.moments(contour)
        if abs(moments["m00"]) <= 1e-9:
            continue
        candidates.append((area, contour, moments))
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    if not candidates:
        return VisionResult(np.zeros(mask.shape, dtype=np.uint8), None, 0.0, 0.0, elapsed_ms, False, "NO_CANDIDATE")
    area, contour, moments = max(candidates, key=lambda item: item[0])
    selected_mask = np.zeros(mask.shape, dtype=np.uint8)
    cv2.drawContours(selected_mask, [contour], -1, 255, -1)
    centroid = (float(moments["m10"] / moments["m00"]), float(moments["m01"] / moments["m00"]))
    area_reference = max(min_area_px * 4.0, 1.0)
    confidence = min(1.0, area / area_reference)
    return VisionResult(selected_mask, centroid, area, confidence, elapsed_ms, True)
