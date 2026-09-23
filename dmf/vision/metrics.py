from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional, Sequence

import numpy as np

from .contracts import DropletState

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def mask_centroid(mask: np.ndarray) -> Optional[tuple[float, float]]:
    ys, xs = np.nonzero(mask > 0)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def segmentation_metrics(
    predicted: Optional[np.ndarray],
    ground_truth: np.ndarray,
    boundary_tolerance_px: int = 2,
) -> dict[str, Optional[float]]:
    if predicted is None:
        return {
            "iou": None,
            "dice": None,
            "precision": None,
            "recall": None,
            "boundary_f1": None,
        }
    if predicted.shape != ground_truth.shape:
        raise ValueError("predicted and ground-truth masks must have the same shape")
    pred = predicted > 0
    truth = ground_truth > 0
    tp = int(np.count_nonzero(pred & truth))
    fp = int(np.count_nonzero(pred & ~truth))
    fn = int(np.count_nonzero(~pred & truth))
    union = tp + fp + fn
    pred_count = tp + fp
    truth_count = tp + fn
    iou = tp / union if union else 1.0
    dice = 2 * tp / (pred_count + truth_count) if pred_count + truth_count else 1.0
    precision = tp / pred_count if pred_count else (1.0 if truth_count == 0 else 0.0)
    recall = tp / truth_count if truth_count else 1.0
    return {
        "iou": iou,
        "dice": dice,
        "precision": precision,
        "recall": recall,
        "boundary_f1": boundary_f1(pred.astype(np.uint8) * 255, truth.astype(np.uint8) * 255, boundary_tolerance_px),
    }


def boundary_f1(predicted: np.ndarray, ground_truth: np.ndarray, tolerance_px: int = 2) -> float:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for boundary F1")
    if tolerance_px < 0:
        raise ValueError("boundary tolerance must be non-negative")
    kernel = np.ones((3, 3), dtype=np.uint8)
    pred_boundary = cv2.morphologyEx((predicted > 0).astype(np.uint8), cv2.MORPH_GRADIENT, kernel) > 0
    truth_boundary = cv2.morphologyEx((ground_truth > 0).astype(np.uint8), cv2.MORPH_GRADIENT, kernel) > 0
    pred_count = int(np.count_nonzero(pred_boundary))
    truth_count = int(np.count_nonzero(truth_boundary))
    if pred_count == 0 and truth_count == 0:
        return 1.0
    if pred_count == 0 or truth_count == 0:
        return 0.0
    if tolerance_px == 0:
        pred_dilated = pred_boundary
        truth_dilated = truth_boundary
    else:
        size = 2 * tolerance_px + 1
        tolerance_kernel = np.ones((size, size), dtype=np.uint8)
        pred_dilated = cv2.dilate(pred_boundary.astype(np.uint8), tolerance_kernel) > 0
        truth_dilated = cv2.dilate(truth_boundary.astype(np.uint8), tolerance_kernel) > 0
    precision = np.count_nonzero(pred_boundary & truth_dilated) / pred_count
    recall = np.count_nonzero(truth_boundary & pred_dilated) / truth_count
    return float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0


def centroid_error(predicted: Optional[tuple[float, float]], expected: Optional[tuple[float, float]]) -> Optional[float]:
    if predicted is None or expected is None:
        return None
    return float(np.hypot(predicted[0] - expected[0], predicted[1] - expected[1]))


def state_classification_metrics(
    predicted: Sequence[str],
    ground_truth: Sequence[str],
) -> dict[str, object]:
    if len(predicted) != len(ground_truth):
        raise ValueError("predicted and ground-truth state arrays must have equal length")
    labels = [state.value for state in DropletState if state is not DropletState.UNKNOWN]
    matrix = {truth: {pred: 0 for pred in labels} for truth in labels}
    for pred_value, truth_value in zip(predicted, ground_truth):
        pred = DropletState.parse(pred_value)
        truth = DropletState.parse(truth_value)
        if pred is DropletState.UNKNOWN or truth is DropletState.UNKNOWN:
            continue
        matrix[truth.value][pred.value] += 1
    per_class = {}
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[truth][label] for truth in labels if truth != label)
        fn = sum(matrix[label][pred] for pred in labels if pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1}
    macro_f1 = sum(values["f1"] for values in per_class.values()) / len(labels)
    return {"labels": labels, "confusion_matrix": matrix, "per_class": per_class, "macro_f1": macro_f1}


def mean_available(values: Iterable[Optional[float]]) -> Optional[float]:
    available = [float(value) for value in values if value is not None]
    return sum(available) / len(available) if available else None
