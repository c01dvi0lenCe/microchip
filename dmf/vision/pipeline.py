from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from ..layout import electrode_id
from .algorithms import create_algorithm
from .config import load_electrode_map, load_yaml, resolve_path
from .constraints import SpatialConstraint, TemporalConstraint, neighboring_electrode_ids
from .contracts import DropletState, FramePacket, FrameRecord
from .dataset import read_csv_rows, write_csv_rows
from .features import DropletFeatureExtractor
from .image_io import write_image
from .timebase import VideoTimestampResolver

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


RESULT_COLUMNS = tuple(FrameRecord.__dataclass_fields__.keys())


def run_baseline(config_path: Path) -> tuple[Path, Path]:
    if cv2 is None:
        raise RuntimeError("opencv-python is required to run the offline vision pipeline")
    config_path = config_path.resolve()
    config = load_yaml(config_path)
    base_dir = config_path.parent
    video_config = _mapping(config, "video")
    algorithm_config = _mapping(config, "algorithm")

    video_path = resolve_path(base_dir, _required(video_config, "path"))
    map_path = resolve_path(base_dir, _required(config, "electrode_map"))
    output_dir = resolve_path(base_dir, _required(config, "output_dir"))
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_dir = output_dir / "masks"
    mask_dir.mkdir(parents=True, exist_ok=True)

    video_id = str(_required(video_config, "video_id"))
    batch_id = str(_required(video_config, "batch_id"))
    split = str(_required(video_config, "split"))
    algorithm_name = str(_required(algorithm_config, "name"))
    parameters = algorithm_config.get("parameters", {}) or {}
    if not isinstance(parameters, Mapping):
        raise ValueError("algorithm.parameters must be a mapping")

    electrode_map = load_electrode_map(map_path)
    algorithm = create_algorithm(algorithm_name, parameters, base_dir)
    extractor = DropletFeatureExtractor(electrode_map)
    annotation_path = config.get("ground_truth_csv")
    annotations = _load_annotations(resolve_path(base_dir, annotation_path), video_id) if annotation_path else {}
    default_source = _optional_int(config.get("source_electrode"))
    default_target = _optional_int(config.get("target_electrode"))
    _require_calibrated_peripheral(electrode_map, default_source)
    _require_calibrated_peripheral(electrode_map, default_target)
    spatial, temporal = _build_constraints(config.get("constraints", {}), electrode_map, default_source, default_target)

    run_id = str(config.get("run_id") or _make_run_id(video_id, algorithm.name, config))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = float(video_config.get("fps_fallback") or 0.0)
    if fps <= 0:
        cap.release()
        raise ValueError("video has no FPS metadata; video.fps_fallback must be supplied")
    start_frame = max(0, int(video_config.get("start_frame", 0)))
    max_frames = _optional_int(video_config.get("max_frames"))
    if start_frame:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    records: list[dict[str, object]] = []
    timestamps = VideoTimestampResolver(fps)
    frame_id = start_frame
    processed = 0
    try:
        while max_frames is None or processed < max_frames:
            ok, image = cap.read()
            if not ok:
                break
            timestamp_s, timestamp_source = timestamps.resolve(frame_id, cap.get(cv2.CAP_PROP_POS_MSEC))
            packet = FramePacket(video_id, frame_id, timestamp_s, timestamp_source, image)
            pipeline_started = time.perf_counter()
            result = algorithm.process(packet)
            if spatial is not None:
                result = spatial.apply(result)
            if temporal is not None:
                result = temporal.apply(packet, result)

            annotation = annotations.get(frame_id, {})
            source = _optional_int(annotation.get("source_electrode")) or default_source
            target = _optional_int(annotation.get("target_electrode")) or default_target
            _require_calibrated_peripheral(electrode_map, source)
            _require_calibrated_peripheral(electrode_map, target)
            features = extractor.extract(packet, result, source, target)
            pipeline_ms = (time.perf_counter() - pipeline_started) * 1000.0
            mask_path = ""
            if result.mask is not None:
                relative_mask = Path("masks") / f"frame_{frame_id:06d}.png"
                if not write_image(output_dir / relative_mask, result.mask):
                    raise RuntimeError(f"could not write mask for frame {frame_id}")
                mask_path = relative_mask.as_posix()
            centroid_px = features.centroid_px or (None, None)
            centroid_mm = features.centroid_mm or (None, None)
            record = FrameRecord(
                run_id=run_id,
                video_id=video_id,
                batch_id=batch_id,
                split=split,
                frame_id=frame_id,
                timestamp_s=timestamp_s,
                timestamp_source=timestamp_source,
                algorithm=algorithm.name,
                detected=result.detected,
                centroid_u_px=centroid_px[0],
                centroid_v_px=centroid_px[1],
                centroid_x_mm=centroid_mm[0],
                centroid_y_mm=centroid_mm[1],
                area_px=features.area_px,
                confidence=result.confidence,
                source_electrode=source,
                target_electrode=target,
                source_coverage=features.source_coverage,
                target_coverage=features.target_coverage,
                distance_to_target_mm=features.distance_to_target_mm,
                velocity_mm_s=features.velocity_mm_s,
                state_pred=DropletState.UNKNOWN.value,
                state_gt=DropletState.parse(annotation.get("state_gt")).value,
                processing_time_ms=result.processing_time_ms,
                pipeline_time_ms=pipeline_ms,
                retry_count=_optional_int(annotation.get("retry_count")),
                mask_path=mask_path,
                error_code=result.error_code,
            )
            records.append(record.to_csv_row())
            frame_id += 1
            processed += 1
    finally:
        cap.release()

    results_path = output_dir / "frame_results.csv"
    manifest_path = output_dir / "run_manifest.json"
    write_csv_rows(results_path, records, RESULT_COLUMNS)
    manifest = {
        "schema": "dmf_vision_run",
        "version": 1,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "algorithm": algorithm.name,
        "algorithm_version": 1,
        "video_path": str(video_path),
        "electrode_map_path": str(map_path),
        "frames_processed": len(records),
        "config": config,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return results_path, manifest_path


def _build_constraints(values: object, electrode_map, source: Optional[int], target: Optional[int]):
    if values is None:
        values = {}
    if not isinstance(values, Mapping):
        raise ValueError("constraints must be a mapping")
    spatial_values = values.get("spatial", {}) or {}
    temporal_values = values.get("temporal", {}) or {}
    spatial = None
    temporal = None
    if spatial_values.get("enabled", False):
        allowed = {int(value) for value in spatial_values.get("allowed_electrodes", [])}
        if not allowed:
            for value in (source, target):
                if value is not None:
                    allowed.update(neighboring_electrode_ids(value, bool(spatial_values.get("include_diagonal", True))))
        spatial = SpatialConstraint(electrode_map, allowed)
    if temporal_values.get("enabled", False):
        if "max_speed_mm_s" not in temporal_values or "tolerance_mm" not in temporal_values:
            raise ValueError("enabled temporal constraint requires max_speed_mm_s and tolerance_mm")
        temporal = TemporalConstraint(
            electrode_map,
            float(temporal_values["max_speed_mm_s"]),
            float(temporal_values["tolerance_mm"]),
        )
    return spatial, temporal


def _load_annotations(path: Path, video_id: str) -> dict[int, dict[str, str]]:
    result = {}
    for row in read_csv_rows(path):
        if row.get("video_id", "").strip() != video_id:
            continue
        frame_id = int(row["frame_id"])
        if frame_id in result:
            raise ValueError(f"duplicate ground truth for {video_id} frame {frame_id}")
        result[frame_id] = row
    return result


def _mapping(values: Mapping[str, object], key: str) -> Mapping[str, object]:
    result = values.get(key)
    if not isinstance(result, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return result


def _required(values: Mapping[str, object], key: str) -> object:
    value = values.get(key)
    if value is None or value == "":
        raise ValueError(f"missing required configuration value: {key}")
    return value


def _optional_int(value: object) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _make_run_id(video_id: str, algorithm: str, config: Mapping[str, object]) -> str:
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{video_id}-{algorithm}-{timestamp}-{digest}"


def _require_calibrated_peripheral(electrode_map, electrode_id_value: Optional[int]) -> None:
    if electrode_id_value is None:
        return
    region = electrode_map[electrode_id_value]
    if electrode_id_value > 400 and region.geometry_source != "calibrated":
        raise ValueError(
            f"peripheral electrode {electrode_id_value} requires a measured pixel_overrides polygon"
        )
