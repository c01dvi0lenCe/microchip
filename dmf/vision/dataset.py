from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from .image_io import read_image
from .contracts import DropletState

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


DATASET_COLUMNS = ("video_id", "batch_id", "video_path", "split")
ANNOTATION_COLUMNS = (
    "video_id",
    "experiment_id",
    "batch_id",
    "frame_id",
    "timestamp_s",
    "frame_path",
    "mask_path",
    "source_electrode",
    "target_electrode",
    "state_gt",
    "lighting_condition",
    "notes",
)
VALID_SPLITS = frozenset({"train", "validation", "test"})


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv_rows(path: Path, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if fieldnames:
            with path.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=list(fieldnames)).writeheader()
        else:
            path.write_text("", encoding="utf-8")
        return
    names = list(fieldnames or rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def validate_dataset(manifest_path: Path, annotation_path: Path | None = None) -> dict[str, int]:
    manifest = read_csv_rows(manifest_path)
    _require_columns(manifest, DATASET_COLUMNS, "dataset manifest")
    video_splits: dict[str, str] = {}
    video_batches: dict[str, str] = {}
    batch_splits: dict[str, str] = {}
    for row in manifest:
        video_id = row["video_id"].strip()
        batch_id = row["batch_id"].strip()
        split = row["split"].strip().lower()
        if not video_id or not batch_id:
            raise ValueError("video_id and batch_id must be non-empty")
        if split not in VALID_SPLITS:
            raise ValueError(f"invalid split '{split}' for video {video_id}")
        if video_id in video_splits and video_splits[video_id] != split:
            raise ValueError(f"video_id {video_id} leaks across splits")
        if video_id in video_batches and video_batches[video_id] != batch_id:
            raise ValueError(f"video_id {video_id} is assigned to multiple batches")
        if batch_id in batch_splits and batch_splits[batch_id] != split:
            raise ValueError(f"batch_id {batch_id} leaks across splits")
        video_splits[video_id] = split
        video_batches[video_id] = batch_id
        batch_splits[batch_id] = split

    annotation_count = 0
    if annotation_path is not None:
        annotations = read_csv_rows(annotation_path)
        _require_columns(annotations, ANNOTATION_COLUMNS, "annotation CSV")
        seen = set()
        frame_hashes: dict[str, set[str]] = {}
        timestamps: dict[str, list[tuple[int, float]]] = {}
        for row in annotations:
            video_id = row["video_id"].strip()
            frame_id = int(row["frame_id"])
            key = (video_id, frame_id)
            if key in seen:
                raise ValueError(f"duplicate annotation for video/frame {key}")
            seen.add(key)
            if key[0] not in video_splits:
                raise ValueError(f"annotation references unknown video_id {key[0]}")
            if row["batch_id"].strip() != video_batches[video_id]:
                raise ValueError(f"annotation batch does not match manifest for video {video_id}")
            if not row["experiment_id"].strip():
                raise ValueError(f"experiment_id is empty for {key}")
            timestamp = _finite_timestamp(row["timestamp_s"], key)
            timestamps.setdefault(video_id, []).append((frame_id, timestamp))

            frame_path = _resolve_annotation_path(annotation_path, row["frame_path"])
            if not frame_path.is_file():
                raise FileNotFoundError(f"annotation frame not found: {frame_path}")
            frame = read_image(frame_path, cv2.IMREAD_COLOR) if cv2 is not None else None
            if frame is None:
                raise ValueError(f"annotation frame is not readable: {frame_path}")
            digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
            hashes = frame_hashes.setdefault(video_id, set())
            if digest in hashes:
                raise ValueError(f"duplicate frame content in video {video_id}: {frame_path}")
            hashes.add(digest)

            mask_path = Path(row["mask_path"])
            resolved = mask_path if mask_path.is_absolute() else annotation_path.parent / mask_path
            if not resolved.is_file():
                raise FileNotFoundError(f"annotation mask not found: {resolved}")
            if resolved.suffix.lower() != ".png":
                raise ValueError(f"annotation mask must be a PNG: {resolved}")
            if cv2 is None:
                raise RuntimeError("opencv-python is required to validate annotation masks")
            mask = read_image(resolved, cv2.IMREAD_GRAYSCALE)
            if mask is None:
                raise ValueError(f"annotation mask is not a readable PNG: {resolved}")
            if not set(int(value) for value in np.unique(mask)).issubset({0, 255}):
                raise ValueError(f"annotation mask must contain only 0 and 255: {resolved}")
            if mask.shape != frame.shape[:2]:
                raise ValueError(f"mask size does not match frame for {key}")
            for name in ("source_electrode", "target_electrode"):
                electrode = int(row[name])
                if electrode not in range(1, 421):
                    raise ValueError(f"{name} must be in 1..420 for {key}")
            state = DropletState.parse(row["state_gt"])
            if state is DropletState.UNKNOWN and row["state_gt"].strip().lower() != "unknown":
                raise ValueError(f"invalid state_gt for {key}: {row['state_gt']}")
        for video_id, values in timestamps.items():
            ordered = sorted(values)
            if any(following[1] <= current[1] for current, following in zip(ordered, ordered[1:])):
                raise ValueError(f"timestamps must increase with frame_id for video {video_id}")
        annotation_count = len(annotations)
    return {"videos": len(video_splits), "batches": len(batch_splits), "annotations": annotation_count}


def _require_columns(rows: Sequence[Mapping[str, str]], required: Sequence[str], label: str) -> None:
    if not rows:
        raise ValueError(f"{label} is empty")
    missing = [name for name in required if name not in rows[0]]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def _resolve_annotation_path(annotation_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else annotation_path.parent / path


def _finite_timestamp(value: str, key: tuple[str, int]) -> float:
    if not str(value).strip():
        raise ValueError(f"missing timestamp for {key}")
    timestamp = float(value)
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError(f"invalid timestamp for {key}")
    return timestamp
