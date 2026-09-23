from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .contracts import DropletState
from .dataset import read_csv_rows, write_csv_rows
from .metrics import centroid_error, mask_centroid, mean_available, segmentation_metrics, state_classification_metrics
from .image_io import read_image

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def evaluate_results(
    results_path: Path,
    ground_truth_path: Path,
    output_dir: Path,
    boundary_tolerance_px: int = 2,
) -> dict[str, object]:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for evaluation")
    results = read_csv_rows(results_path)
    truth_rows = read_csv_rows(ground_truth_path)
    truth_by_key = {(row["video_id"], int(row["frame_id"])): row for row in truth_rows}
    per_frame = []
    predicted_states = []
    truth_states = []
    misses = 0
    processing_times = []
    pipeline_times = []
    for row in results:
        key = (row["video_id"], int(row["frame_id"]))
        truth = truth_by_key.get(key)
        if truth is None:
            continue
        predicted_mask = _read_optional_mask(results_path.parent, row.get("mask_path", ""))
        truth_mask = _read_required_mask(ground_truth_path.parent, truth["mask_path"])
        mask_scores = segmentation_metrics(predicted_mask, truth_mask, boundary_tolerance_px)
        predicted_centroid = _row_centroid(row)
        expected_centroid = mask_centroid(truth_mask)
        error_px = centroid_error(predicted_centroid, expected_centroid)
        detected = str(row.get("detected", "")).lower() in {"true", "1", "yes"}
        if not detected:
            misses += 1
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
        }
        per_frame.append(metric_row)
        if DropletState.parse(row.get("state_pred")) is not DropletState.UNKNOWN:
            predicted_states.append(row["state_pred"])
            truth_states.append(truth.get("state_gt", DropletState.UNKNOWN.value))

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(output_dir / "per_frame_metrics.csv", per_frame)
    mean_processing = mean_available(processing_times)
    mean_pipeline = mean_available(pipeline_times)
    summary: dict[str, object] = {
        "matched_frames": len(per_frame),
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
    if predicted_states:
        summary["state_metrics"] = state_classification_metrics(predicted_states, truth_states)
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _read_optional_mask(base_dir: Path, value: str):
    if not value:
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
