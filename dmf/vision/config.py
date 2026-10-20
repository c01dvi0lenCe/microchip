from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json

from .calibration import ArrayGridCalibration
from .electrode_map import ElectrodeMap

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load vision experiment configurations")
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return payload


def load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"configuration root must be a mapping: {path}")
        return payload
    return load_yaml(path)


def resolve_path(base_dir: Path, value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base_dir / path).resolve()


def load_electrode_map(path: Path) -> ElectrodeMap:
    values = load_mapping(path)
    rows = int(values.get("rows", 20))
    cols = int(values.get("cols", 20))
    if (rows, cols) != (20, 20):
        raise ValueError("the physical electrode map must use the 20 x 20 core plus IDs 401..420")
    corners = values.get("core_corners_px")
    if not isinstance(corners, list) or len(corners) != 4:
        raise ValueError("electrode map needs four core_corners_px ordered TL, TR, BR, BL")
    calibration = ArrayGridCalibration(
        corners_px=tuple((float(point[0]), float(point[1])) for point in corners),
        rows=rows,
        cols=cols,
        pitch_mm=float(values.get("pitch_mm", 3.2)),
    )
    raw_overrides = values.get("pixel_overrides", {}) or {}
    if not isinstance(raw_overrides, Mapping):
        raise ValueError("pixel_overrides must be a mapping from electrode ID to polygon")
    invalid_ids = sorted(int(value) for value in raw_overrides if int(value) not in range(1, 421))
    if invalid_ids:
        raise ValueError(f"pixel_overrides contains invalid electrode IDs: {invalid_ids}")
    overrides = {
        int(electrode_id): tuple((float(point[0]), float(point[1])) for point in polygon)
        for electrode_id, polygon in raw_overrides.items()
    }
    return ElectrodeMap.from_calibration(calibration, overrides)


def save_electrode_map(path: Path, electrode_map: ElectrodeMap) -> None:
    overrides = {
        str(region.electrode_id): [[float(x), float(y)] for x, y in region.polygon_px]
        for region in electrode_map
        if region.geometry_source == "calibrated"
    }
    payload = {
        "rows": electrode_map.calibration.rows,
        "cols": electrode_map.calibration.cols,
        "pitch_mm": electrode_map.calibration.pitch_mm,
        "core_corners_px": [list(point) for point in electrode_map.calibration.corners_px],
        "pixel_overrides": overrides,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if yaml is None:
        raise RuntimeError("PyYAML is required to save YAML electrode maps")
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
