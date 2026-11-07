from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

import numpy as np

from .contracts import DropletState
from .config import load_electrode_map
from .dataset import read_csv_rows, write_csv_rows
from .metrics import centroid_error, mask_centroid, mean_available, segmentation_metrics, state_classification_metrics
from .image_io import read_image
from .features import polygon_mask

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def evaluate_results(
    results_path: Path,
    ground_truth_path: Path,
    output_dir: Path,
    boundary_tolerance_px: int = 2,
    electrode_map_path: Path | None = None,
) -> dict[str, object]:
    """Score every reference row using the legacy pixel-based frame-results schema.

    The caller supplies the complete reviewed reference CSV. Experiment frames
    contain mm centroids and require a separately implemented explicit adapter;
    they are deliberately not inferred or converted here. Missing predictions,
    blank masks and failed detections are empty segmentation predictions.
    """
    if cv2 is None:
        raise RuntimeError("opencv-python is required for evaluation")
    _validate_frame_schema(results_path, "prediction")
    _validate_frame_schema(ground_truth_path, "reference")
    results = read_csv_rows(results_path)
    truth_rows = read_csv_rows(ground_truth_path)
    results_by_key = _index_unique_rows(results, "prediction")
    truth_by_key = _index_unique_rows(truth_rows, "reference")
    for key in results_by_key.keys() - truth_by_key.keys():
        _read_optional_mask(results_path.parent, results_by_key[key].get("mask_path", ""))
    electrode_map = load_electrode_map(electrode_map_path) if electrode_map_path is not None else None
    per_frame = []
    predicted_states = []
    truth_states = []
    misses = 0
    processing_times = []
    pipeline_times = []
    region_mask_cache = {}
    label_map_cache = {}
    missing_rows = blank_masks = failed_detections = empty_masks = 0
    positive_gt_frames = positive_gt_misses = 0
    for key, truth in truth_by_key.items():
        prediction_missing = key not in results_by_key
        row = results_by_key.get(key, {})
        missing_rows += int(prediction_missing)
        # Resolve nonempty paths even for a failed detection: missing files are
        # broken artifacts, not legal empty predictions.
        predicted_mask = _read_optional_mask(results_path.parent, row.get("mask_path", ""))
        truth_mask = _read_required_mask(ground_truth_path.parent, truth["mask_path"])
        detected_flag = str(row.get("detected", "")).lower() in {"true", "1", "yes"}
        blank_masks += int(not prediction_missing and not str(row.get("mask_path", "")).strip())
        failed_detections += int(not prediction_missing and not detected_flag)
        empty_masks += int(predicted_mask is not None and not predicted_mask.any())
        if predicted_mask is None or not detected_flag:
            predicted_mask = np.zeros_like(truth_mask)
        detected = detected_flag and bool(predicted_mask.any())
        mask_scores = segmentation_metrics(predicted_mask, truth_mask, boundary_tolerance_px)
        predicted_centroid = _row_centroid(row) if detected else None
        expected_centroid = mask_centroid(truth_mask)
        error_px = centroid_error(predicted_centroid, expected_centroid)
        if not detected:
            misses += 1
        if truth_mask.any():
            positive_gt_frames += 1
            positive_gt_misses += int(not detected)
        processing_ms = _optional_float(row.get("processing_time_ms"))
        if processing_ms is not None:
            processing_times.append(processing_ms)
        pipeline_ms = _optional_float(row.get("pipeline_time_ms"))
        if pipeline_ms is not None:
            pipeline_times.append(pipeline_ms)
        metric_row = {
            "video_id": key[0],
            "frame_id": key[1],
            **mask_scores,
            "centroid_error_px": error_px,
            "detected": detected,
            "processing_time_ms": processing_ms,
            "pipeline_time_ms": pipeline_ms,
            "state_gt": truth.get("state_gt", DropletState.UNKNOWN.value),
            "state_pred": row.get("state_pred") or DropletState.UNKNOWN.value,
            "prediction_missing": prediction_missing,
        }
        if electrode_map is not None:
            source = int(truth["source_electrode"])
            target = int(truth["target_electrode"])
            source_gt = _coverage_for_id(truth_mask, electrode_map, source, region_mask_cache)
            target_gt = _coverage_for_id(truth_mask, electrode_map, target, region_mask_cache)
            source_pred = _coverage_for_id(predicted_mask, electrode_map, source, region_mask_cache) if predicted_mask is not None else None
            target_pred = _coverage_for_id(predicted_mask, electrode_map, target, region_mask_cache) if predicted_mask is not None else None
            assignment_gt = _assign_electrode(truth_mask, electrode_map, label_map_cache)
            assignment_pred = (
                _assign_electrode(predicted_mask, electrode_map, label_map_cache)
                if predicted_mask is not None
                else _assign_from_centroid(predicted_centroid, electrode_map)
            )
            metric_row.update(
                {
                    "source_coverage_gt": source_gt,
                    "source_coverage_pred": source_pred,
                    "source_coverage_error": abs(source_pred - source_gt) if source_pred is not None else None,
                    "target_coverage_gt": target_gt,
                    "target_coverage_pred": target_pred,
                    "target_coverage_error": abs(target_pred - target_gt) if target_pred is not None else None,
                    "electrode_assignment_gt": assignment_gt,
                    "electrode_assignment_pred": assignment_pred,
                    "electrode_assignment_correct": assignment_pred == assignment_gt if assignment_gt is not None else None,
                }
            )
        per_frame.append(metric_row)
        predicted_states.append(row.get("state_pred") or DropletState.UNKNOWN.value)
        truth_states.append(truth.get("state_gt", DropletState.UNKNOWN.value))

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(output_dir / "per_frame_metrics.csv", per_frame)
    mean_processing = mean_available(processing_times)
    mean_pipeline = mean_available(pipeline_times)
    summary: dict[str, object] = {
        "matched_frames": len(per_frame),
        "reference_frames": len(truth_rows),
        "prediction_rows": len(results),
        "prediction_rows_matched": len(results_by_key.keys() & truth_by_key.keys()),
        "unmatched_prediction_rows": len(results_by_key.keys() - truth_by_key.keys()),
        "missing_prediction_rows": missing_rows,
        "blank_prediction_masks": blank_masks,
        "detected_false_rows": failed_detections,
        "empty_prediction_masks": empty_masks,
        "detection_misses": misses,
        "segmentation_denominator": len(per_frame),
        "positive_gt_frames": positive_gt_frames,
        "positive_gt_detection_misses": positive_gt_misses,
        "positive_gt_miss_rate": positive_gt_misses / positive_gt_frames if positive_gt_frames else None,
        "unknown_prediction_count": sum(DropletState.parse(value) is DropletState.UNKNOWN for value in predicted_states),
        "centroid_error_denominator": sum(row["centroid_error_px"] is not None for row in per_frame),
        "processing_time_denominator": len(processing_times),
        "pipeline_time_denominator": len(pipeline_times),
        "miss_rate": misses / len(per_frame) if per_frame else None,
        "mean_iou": mean_available(row["iou"] for row in per_frame),
        "mean_dice": mean_available(row["dice"] for row in per_frame),
        "mean_precision": mean_available(row["precision"] for row in per_frame),
        "mean_recall": mean_available(row["recall"] for row in per_frame),
        "mean_boundary_f1": mean_available(row["boundary_f1"] for row in per_frame),
        "mean_centroid_error_px": mean_available(row["centroid_error_px"] for row in per_frame),
        "mean_processing_time_ms": mean_processing,
        "processing_fps": 1000.0 / mean_processing if mean_processing and mean_processing > 0 else None,
        "mean_pipeline_time_ms": mean_pipeline,
        "pipeline_fps": 1000.0 / mean_pipeline if mean_pipeline and mean_pipeline > 0 else None,
    }
    summary["state_metrics"] = state_classification_metrics(predicted_states, truth_states)
    if electrode_map is not None:
        summary["dmf_metrics"] = {
            "overall": _summarize_dmf(per_frame),
            "normal": _summarize_dmf(
                row for row in per_frame if DropletState.parse(row["state_gt"]) not in {DropletState.PARTIAL, DropletState.UNKNOWN}
            ),
            "partial": _summarize_dmf(
                row for row in per_frame if DropletState.parse(row["state_gt"]) is DropletState.PARTIAL
            ),
        }
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _validate_frame_schema(path, label):
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        columns = set(csv.DictReader(handle).fieldnames or [])
    _validate_frame_columns(columns, label)


def _validate_frame_columns(columns, label):
    if {"recognized_state", "centroid_x", "centroid_y", "event_action"} & columns:
        raise ValueError("experiment frames schema requires an explicit mm-to-pixel/frame-results adapter")
    if not {"video_id", "frame_id"}.issubset(columns):
        raise ValueError(f"{label} must use frame-results video_id/frame_id schema; use an explicit adapter")


def _index_unique_rows(rows, label):
    indexed = {}
    for row in rows:
        key = (row["video_id"], int(row["frame_id"]))
        if key in indexed:
            raise ValueError(f"duplicate {label} video/frame key: {key}")
        indexed[key] = row
    return indexed


def _read_optional_mask(base_dir: Path, value: str):
    if not value or not str(value).strip():
        return None
    path = Path(value)
    path = path if path.is_absolute() else base_dir / path
    if not path.is_file():
        raise FileNotFoundError(f"could not read predicted mask: {path}")
    mask = read_image(path, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(f"could not read predicted mask: {path}")
    return mask


def _read_required_mask(base_dir: Path, value: str):
    mask = _read_optional_mask(base_dir, value)
    if mask is None:
        raise FileNotFoundError(f"could not read ground-truth mask: {value}")
    return mask


def _row_centroid(row: dict[str, str]) -> Optional[tuple[float, float]]:
    x = _optional_float(row.get("centroid_u_px"))
    y = _optional_float(row.get("centroid_v_px"))
    return (x, y) if x is not None and y is not None else None


def _optional_float(value: object) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _assign_electrode(mask, electrode_map, cache) -> Optional[int]:
    if mask is None or not mask.any():
        return None
    shape = mask.shape
    label_map = cache.get(shape)
    if label_map is None:
        label_map = np.zeros(shape, dtype=np.uint16)
        for region in electrode_map:
            polygon = np.rint(np.asarray(region.polygon_px)).astype(np.int32)
            cv2.fillPoly(label_map, [polygon], region.electrode_id)
        cache[shape] = label_map
    counts = np.bincount(label_map[mask > 0], minlength=421)
    counts[0] = 0
    assigned = int(counts.argmax())
    return assigned if counts[assigned] > 0 else None


def _assign_from_centroid(centroid, electrode_map) -> Optional[int]:
    if centroid is None:
        return None
    return electrode_map.nearest_electrode(centroid).electrode_id


def _coverage_for_id(mask, electrode_map, electrode_id: int, cache) -> float:
    droplet_area = int(np.count_nonzero(mask))
    if droplet_area == 0:
        return 0.0
    key = (mask.shape, electrode_id)
    region_mask = cache.get(key)
    if region_mask is None:
        region_mask = polygon_mask(mask.shape, electrode_map[electrode_id])
        cache[key] = region_mask
    return int(np.count_nonzero((mask > 0) & (region_mask > 0))) / droplet_area


def _summarize_dmf(rows) -> dict[str, object]:
    values = list(rows)
    assignments = [row["electrode_assignment_correct"] for row in values if row.get("electrode_assignment_correct") is not None]
    return {
        "frames": len(values),
        "mean_source_coverage_error": mean_available(row.get("source_coverage_error") for row in values),
        "mean_target_coverage_error": mean_available(row.get("target_coverage_error") for row in values),
        "electrode_assignment_accuracy": sum(bool(value) for value in assignments) / len(assignments) if assignments else None,
    }
