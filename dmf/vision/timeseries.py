from __future__ import annotations

from pathlib import Path
from typing import Optional

from .dataset import read_csv_rows, write_csv_rows


TIMESERIES_COLUMNS = (
    "video_id",
    "experiment_id",
    "frame_id",
    "timestamp_s",
    "source_electrode",
    "target_electrode",
    "source_coverage",
    "target_coverage",
    "distance_to_target_mm",
    "velocity_mm_s",
    "state_pred",
    "state_gt",
)


def export_transport_timeseries(
    results_path: Path,
    output_path: Path,
    video_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> Path:
    selected = []
    for row in read_csv_rows(results_path):
        if video_id and row.get("video_id") != video_id:
            continue
        if experiment_id and row.get("experiment_id") != experiment_id:
            continue
        selected.append({name: row.get(name, "") for name in TIMESERIES_COLUMNS})
    selected.sort(key=lambda row: (row["video_id"], float(row["timestamp_s"]), int(row["frame_id"])))
    write_csv_rows(output_path, selected, TIMESERIES_COLUMNS)
    return output_path
