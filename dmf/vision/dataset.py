from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from .image_io import read_image

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


DATASET_COLUMNS = ("video_id", "batch_id", "video_path", "split")
ANNOTATION_COLUMNS = (
    "video_id",
    "batch_id",
    "frame_id",
    "timestamp_s",
    "mask_path",
    "source_electrode",
    "target_electrode",
    "state_gt",
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
        if batch_id in batch_splits and batch_splits[batch_id] != split:
            raise ValueError(f"batch_id {batch_id} leaks across splits")
        video_splits[video_id] = split
        batch_splits[batch_id] = split

    annotation_count = 0
    if annotation_path is not None:
        annotations = read_csv_rows(annotation_path)
        _require_columns(annotations, ANNOTATION_COLUMNS, "annotation CSV")
        seen = set()
        for row in annotations:
            key = (row["video_id"].strip(), int(row["frame_id"]))
            if key in seen:
                raise ValueError(f"duplicate annotation for video/frame {key}")
            seen.add(key)
            if key[0] not in video_splits:
                raise ValueError(f"annotation references unknown video_id {key[0]}")
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
        annotation_count = len(annotations)
    return {"videos": len(video_splits), "batches": len(batch_splits), "annotations": annotation_count}


def _require_columns(rows: Sequence[Mapping[str, str]], required: Sequence[str], label: str) -> None:
    if not rows:
        raise ValueError(f"{label} is empty")
    missing = [name for name in required if name not in rows[0]]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")
