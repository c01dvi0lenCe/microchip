"""Offline design-coordinate registration; never owns camera or electrodes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .calibration import ArrayGridCalibration


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def project(points, matrix):
    return ArrayGridCalibration._transform(points, np.asarray(matrix, dtype=float))


def load_design_map(path, expected_sha256=None):
    path = Path(path)
    if expected_sha256 and file_hash(path) != expected_sha256:
        raise ValueError('design map hash mismatch')
    data = json.loads(path.read_text(encoding='utf-8'))
    electrodes = data.get('electrodes', [])
    if (data.get('schema') != 'dmf_electrode_design_map_v1' or
            data.get('coordinate_system', {}).get('unit') != 'mm' or
            data.get('electrode_count') != 420 or len(electrodes) != 420 or
            {e.get('control_id') for e in electrodes} != set(range(1, 421)) or
            data.get('binding', {}).get('confirmed') is not True):
        raise ValueError('confirmed 420-electrode design map in mm required')
    for electrode in electrodes:
        polygon = np.asarray(electrode['polygon_map_mm'], dtype=float)
        if (polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3 or
                not np.isfinite(polygon).all() or
                abs(cv2.contourArea(polygon.astype(np.float32))) < 1e-9):
            raise ValueError('invalid design polygon')
    return data


def _catalog(points):
    keys = ('point_id', 'role', 'control_id', 'vertex_index', 'map_mm')
    result = [{key: point[key] for key in keys} for point in points]
    if not result or any(p['role'] not in ('fit', 'check') for p in result):
        raise ValueError('invalid point catalog roles')
    for key in ('point_id',):
        if len({p[key] for p in result}) != len(result):
            raise ValueError('duplicate point identifier')
    if len({(p['control_id'], p['vertex_index']) for p in result}) != len(result):
        raise ValueError('duplicate design feature across roles')
    xy = np.asarray([p['map_mm'] for p in result], dtype=float)
    if xy.shape != (len(result), 2) or not np.isfinite(xy).all():
        raise ValueError('invalid map coordinates')
    distances = np.linalg.norm(xy[:, None]-xy[None, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    if np.any(distances < .01):
        raise ValueError('duplicate or indistinguishable design points')
    return result


def seal_catalog(workspace):
    workspace['catalog_sha256'] = digest(_catalog(workspace['points']))


def _validate_catalog(workspace):
    if digest(_catalog(workspace['points'])) != workspace.get('catalog_sha256'):
        raise ValueError('point catalog modified after role assignment')


def _confirmed(point):
    if point['status'] != 'confirmed':
        return False
    if (not point.get('reviewer', '').strip() or not point.get('reviewed_utc') or
            point.get('observation_method') != 'manual_native_click'):
        raise ValueError('confirmed point lacks manual review provenance')
    xy = np.asarray(point.get('observed_px'), dtype=float)
    if xy.shape != (2,) or not np.isfinite(xy).all():
        raise ValueError('invalid observed image point')
    return True


def _validate_observations(workspace):
    width, height = workspace['image_size']
    if width <= 0 or height <= 0:
        raise ValueError('invalid image dimensions')
    for point in workspace['points']:
        if point['status'] not in ('pending', 'confirmed', 'excluded'):
            raise ValueError('invalid review status')
        if point['status'] == 'excluded' and (
                not point.get('exclusion_reason', '').strip() or
                not point.get('reviewer', '').strip()):
            raise ValueError('excluded point requires reviewer and reason')
        if _confirmed(point):
            u, v = point['observed_px']
            if not (0 <= u < width and 0 <= v < height):
                raise ValueError('point outside native image')


def fit_transform(points):
    # Deliberately do not inspect ANY check observation, even for inlier selection.
    fit = [p for p in points if p['role'] == 'fit' and _confirmed(p)]
    if len(fit) < 4:
        raise ValueError('at least four reviewed fit points required')
    src = np.asarray([p['observed_px'] for p in fit], dtype=float)
    dst = np.asarray([p['map_mm'] for p in fit], dtype=float)
    for xy in (src, dst):
        if (np.linalg.matrix_rank(np.c_[xy, np.ones(len(xy))]) < 3 or
                len(np.unique(xy, axis=0)) != len(xy)):
            raise ValueError('degenerate or duplicate fit points')
    matrix, _ = cv2.findHomography(src, dst, method=0)
    if matrix is None:
        raise ValueError('degenerate homography')
    project(src, matrix)
    project(dst, np.linalg.inv(matrix))
    return matrix


def _fit_digest(workspace):
    return digest([p for p in workspace['points'] if p['role'] == 'fit'])


def freeze_fit(workspace):
    _validate_catalog(workspace)
    _validate_observations(workspace)
    fit = [p for p in workspace['points'] if p['role'] == 'fit']
    if not all(_confirmed(p) for p in fit):
        raise ValueError('all planned fit points require manual review before freeze')
    if workspace.get('fit_freeze'):
        _verify_freeze(workspace)
        return workspace['fit_freeze']
    if any(p['status'] == 'confirmed' for p in workspace['points'] if p['role'] == 'check'):
        raise ValueError('checks must be observed only after fit freeze')
    matrix = fit_transform(workspace['points'])
    workspace['fit_freeze'] = dict(fit_sha256=_fit_digest(workspace),
        catalog_sha256=workspace['catalog_sha256'], image_to_design_mm=matrix.tolist(),
        frozen_utc=datetime.now(timezone.utc).isoformat(), model='homography_no_distortion',
        check_observations_used=False)
    return workspace['fit_freeze']


def _verify_freeze(workspace):
    frozen = workspace.get('fit_freeze')
    if (not frozen or frozen.get('fit_sha256') != _fit_digest(workspace) or
            frozen.get('catalog_sha256') != workspace['catalog_sha256'] or
            frozen.get('check_observations_used') is not False):
        raise ValueError('fit freeze required, or frozen fit changed')
    matrix = np.asarray(frozen['image_to_design_mm'], dtype=float)
    if not np.allclose(matrix, fit_transform(workspace['points']), rtol=1e-9, atol=1e-9):
        raise ValueError('frozen matrix changed')
    return matrix


def record_observation(workspace, point_id, pixel, reviewer):
    _validate_catalog(workspace)
    if workspace.get('evaluation_freeze'):
        raise ValueError('evaluation is sealed; use a new declared review, not residual-driven edits')
    if not reviewer.strip():
        raise ValueError('reviewer name is required')
    point = next(p for p in workspace['points'] if p['point_id'] == point_id)
    if point['role'] == 'check':
        _verify_freeze(workspace)
    elif workspace.get('fit_freeze'):
        raise ValueError('fit is frozen; create a new review workspace to revise')
    xy = np.asarray(pixel, dtype=float)
    width, height = workspace['image_size']
    if xy.shape != (2,) or not np.isfinite(xy).all() or not (0 <= xy[0] < width and 0 <= xy[1] < height):
        raise ValueError('point outside native image')
    point.update(observed_px=xy.tolist(), status='confirmed', reviewer=reviewer.strip(),
                 observation_method='manual_native_click', exclusion_reason='',
                 reviewed_utc=datetime.now(timezone.utc).isoformat())


def evaluate_registration(workspace):
    _validate_catalog(workspace)
    _validate_observations(workspace)
    if workspace.get('evaluation_freeze') and workspace['evaluation_freeze']['checks_sha256'] != digest(
            [p for p in workspace['points'] if p['role']=='check']):
        raise ValueError('sealed check observations changed after results were exposed')
    checks = [p for p in workspace['points'] if p['role'] == 'check']
    confirmed = [p for p in checks if _confirmed(p)]
    excluded = [p for p in checks if p['status'] == 'excluded']
    result = dict(status='pending_fit', check_total=len(checks),
        check_confirmed=len(confirmed), check_excluded=len(excluded),
        check_missing=len(checks)-len(confirmed)-len(excluded),
        physical_mm_accuracy_verified=False, independent_acquisition_groups=1,
        metrics_scope='held-out manually reviewed design-coordinate consistency, not physical metrology',
        percentile_definition='numpy.percentile(method=linear)', residuals=[],
        rmse_px=None, p95_px=None, max_px=None, rmse_design_mm=None,
        p95_design_mm=None, max_design_mm=None, checks_outside_fit_hull=None)
    if not workspace.get('fit_freeze'):
        return result
    matrix = _verify_freeze(workspace)
    result.update(status='pending_checks', image_to_design_mm=matrix.tolist(),
                  design_mm_to_image=np.linalg.inv(matrix).tolist())
    if result['check_missing'] or not confirmed:
        return result
    observed = np.array([p['observed_px'] for p in confirmed])
    expected = np.array([p['map_mm'] for p in confirmed])
    predicted_px = np.array(project(expected, np.linalg.inv(matrix)))
    predicted_mm = np.array(project(observed, matrix))
    error_px = np.linalg.norm(predicted_px-observed, axis=1)
    error_mm = np.linalg.norm(predicted_mm-expected, axis=1)
    fit = [p for p in workspace['points'] if p['role'] == 'fit']
    hull = cv2.convexHull(np.array([p['map_mm'] for p in fit], dtype=np.float32))
    outside = [cv2.pointPolygonTest(hull, tuple(map(float, p)), False) < 0 for p in expected]
    result.update(status=('checked_design_consistency' if len(confirmed) >= 12 and
                         len(fit) >= 8 and not excluded else 'checked_descriptive_only'),
                  checks_outside_fit_hull=sum(outside))
    for unit, errors in [('px', error_px), ('design_mm', error_mm)]:
        result.update({f'rmse_{unit}': float(np.sqrt(np.mean(errors**2))),
                       f'p95_{unit}': float(np.percentile(errors, 95, method='linear')),
                       f'max_{unit}': float(max(errors))})
    result['residuals'] = [dict(point_id=p['point_id'], error_px=float(ep),
        error_design_mm=float(em), outside_fit_hull=bool(out))
        for p, ep, em, out in zip(confirmed, error_px, error_mm, outside)]
    return result


def seal_evaluation(workspace):
    """Lock observations before exposing the first complete check-point result."""
    result=evaluate_registration(workspace)
    if result['rmse_px'] is None:
        raise ValueError('complete check review required before evaluation seal')
    workspace['evaluation_freeze']=dict(
        checks_sha256=digest([p for p in workspace['points'] if p['role']=='check']),
        sealed_utc=datetime.now(timezone.utc).isoformat())
