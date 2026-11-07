from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json
import math
import hashlib

from .calibration import ArrayGridCalibration, Roi
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
    rows = values.get("rows", 20)
    cols = values.get("cols", 20)
    if type(rows) is not int or type(cols) is not int:raise ValueError('grid dimensions must be integers')
    if (rows, cols) != (20, 20):
        raise ValueError("the physical electrode map must use the 20 x 20 core plus IDs 401..420")
    corners = values.get("core_corners_px")
    if not isinstance(corners, list) or len(corners) != 4:
        raise ValueError("electrode map needs four core_corners_px ordered TL, TR, BR, BL")
    if any(not isinstance(point,(list,tuple)) or len(point)!=2 for point in corners):
        raise ValueError('each calibration corner must contain two coordinates')
    if isinstance(values.get('pitch_mm'),bool):raise ValueError('pitch_mm is a measured/nominal number, not boolean')
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
    image_size=values.get('image_size_px')
    def size(value):
        if (not isinstance(value,(tuple,list)) or len(value)!=2 or
                any(type(v) is not int or v<=0 for v in value)):
            raise ValueError('image size must be [positive integer width, height]')
        return list(value)
    if image_size is not None:image_size=size(image_size)
    coordinates=values.get('coordinate_frame','full_frame')
    if coordinates not in {'full_frame','roi_local'}:raise ValueError('unknown map coordinate frame')
    roi_values=values.get('roi')
    if roi_values is not None:
        reference=size(values.get('reference_image_size_px'))
        roi=Roi.from_sequence(roi_values);roi.validate_for_frame((reference[1],reference[0]))
        if image_size is not None and image_size!=[roi.width,roi.height]:raise ValueError('ROI and image_size_px disagree')
        image_size=[roi.width,roi.height]
        if coordinates=='full_frame':
            calibration=calibration.for_roi(roi,(reference[1],reference[0]))
            overrides={i:tuple((x-roi.x,y-roi.y) for x,y in polygon) for i,polygon in overrides.items()}
        coordinates='roi_local'
    elif coordinates=='roi_local':raise ValueError('ROI-local map needs explicit ROI/reference image metadata')
    if image_size and coordinates=='full_frame':
        if any(x<0 or y<0 or x>image_size[0] or y>image_size[1] for x,y in calibration.corners_px):
            raise ValueError('core corners lie outside declared full image')
    residuals=[];validation_points=[]
    for point in values.get('validation_points',[]):
        local_pixel=tuple(point['pixel_px'])
        if roi_values is not None and values.get('coordinate_frame','full_frame')=='full_frame':
            local_pixel=(local_pixel[0]-roi.x,local_pixel[1]-roi.y)
        predicted=calibration.pixel_to_mm(local_pixel)
        reference=tuple(float(v) for v in point['reference_mm'])
        if len(reference)!=2 or not all(math.isfinite(v) for v in reference):raise ValueError('invalid validation reference')
        residuals.append(dict(point_id=point.get('point_id',''),location=point.get('location','unspecified'),
            independent=point.get('independent') is True,error_mm=math.dist(predicted,reference)))
        validation_points.append(dict(point,pixel_px=list(local_pixel)))
    independent=[r for r in residuals if r['independent']]
    tolerance=values.get('validation_tolerance_mm')
    if tolerance is not None and (not math.isfinite(float(tolerance)) or float(tolerance)<=0):
        raise ValueError('positive finite independent validation tolerance required')
    groups={}
    for group in ('center','edge','all'):
        rows=[r['error_mm'] for r in independent if group=='all' or r['location']==group]
        groups[group]=dict(count=len(rows),rmse_mm=math.sqrt(sum(e*e for e in rows)/len(rows)) if rows else None,
                           max_error_mm=max(rows) if rows else None)
    metadata=dict(map_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),map_path=str(path.resolve()),
        map_version=str(values.get('map_version','unversioned')),image_size_px=image_size,
        coordinate_frame=coordinates,roi=roi_values,reference_image_size_px=values.get('reference_image_size_px'),
        pitch_source=values.get('pitch_source','unspecified_nominal_not_verified'),
        valid_range=values.get('valid_range','not_independently_audited'),
        declared_calibration_confirmed=values.get('calibration_confirmed') is True,
        validation_points=validation_points,validation_residuals=residuals,independent_validation=groups,validation_tolerance_mm=tolerance,
        check_points_within_declared_tolerance=(all(r['error_mm']<=float(tolerance) for r in independent)
            if independent and tolerance is not None else None))
    return ElectrodeMap.from_calibration(calibration, overrides,metadata)


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
    for key in ('image_size_px','map_version','pitch_source','valid_range','validation_points','validation_tolerance_mm'):
        if electrode_map.metadata.get(key) is not None:payload[key]=electrode_map.metadata[key]
    if electrode_map.metadata.get('roi') is not None:
        payload.update(coordinate_frame='roi_local',roi=electrode_map.metadata['roi'],
                       reference_image_size_px=electrode_map.metadata['reference_image_size_px'])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if yaml is None:
        raise RuntimeError("PyYAML is required to save YAML electrode maps")
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
