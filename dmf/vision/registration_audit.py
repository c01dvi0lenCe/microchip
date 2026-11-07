"""Independent offline arithmetic and fail-closed final-apparatus manifest checks.

Does not call the production registration projection/fitting/scoring functions.
The optional workspace loader is used only for provenance validation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np


CONDITION_FIELDS = ('camera_model', 'camera_serial', 'lens_model', 'focal_length_mm',
                    'focus_setting', 'resolution', 'chip_height_mm', 'height_datum',
                    'cover_plate', 'mounting_id', 'roi', 'pixel_format',
                    'distortion_model_id', 'acquisition_id')


def checked_matrix(value):
    matrix = np.asarray(value, dtype=float)
    if (matrix.shape != (3, 3) or not np.isfinite(matrix).all() or
            np.linalg.matrix_rank(matrix) != 3):
        raise ValueError('finite nonsingular 3x3 matrix required')
    return matrix


def homogeneous(points, matrix):
    """Direct homogeneous arithmetic, intentionally independent of project()."""
    matrix = checked_matrix(matrix)
    xy = np.asarray(points, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all():
        raise ValueError('finite Nx2 points required')
    h = np.column_stack((xy, np.ones(len(xy)))) @ matrix.T
    if np.any(np.abs(h[:, 2]) < 1e-12):
        raise ValueError('point at projective horizon')
    result = h[:, :2] / h[:, 2:]
    if not np.isfinite(result).all(): raise ValueError('nonfinite projection')
    return result


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values): return dict(n=0, rmse=None, p95=None, maximum=None, mean=None)
    return dict(n=len(values), rmse=float(np.sqrt(np.mean(values**2))),
                p95=float(np.percentile(values, 95, method='linear')),
                maximum=float(np.max(values)), mean=float(np.mean(values)))


def correlation(x, y):
    if len(x) < 3 or np.std(x) < 1e-12 or np.std(y) < 1e-12: return None
    return float(np.corrcoef(x, y)[0, 1])


def recompute(workspace, *, core_bounds):
    matrix = checked_matrix(workspace['fit_freeze']['image_to_design_mm'])
    inverse = np.linalg.inv(matrix)
    width, height = workspace['image_size']
    image_center = np.array([(width-1)/2, (height-1)/2])
    lo = np.array(core_bounds[:2]); hi = np.array(core_bounds[2:])
    if not np.all(hi > lo): raise ValueError('positive core bounds required')
    checks = [p for p in workspace['points'] if p['role'] == 'check']
    rows = []
    for p in checks:
        if p['status'] != 'confirmed': continue
        expected = np.asarray(p['map_mm'], dtype=float)
        observed = np.asarray(p['observed_px'], dtype=float)
        predicted = homogeneous([expected], inverse)[0]
        predicted_mm = homogeneous([observed], matrix)[0]
        residual = predicted-observed
        radius_vec = observed-image_center
        radius = float(np.linalg.norm(radius_vec))
        unit = radius_vec/radius if radius > 0 else np.array([0., 0.])
        fractional = (expected-lo)/(hi-lo)
        region = ('core_center' if np.all((fractional >= .25) & (fractional <= .75))
                  else 'core_edge' if np.all((fractional >= 0) & (fractional <= 1))
                  else 'peripheral')
        rows.append(dict(point_id=p['point_id'], region=region,
            map_x_mm=float(expected[0]), map_y_mm=float(expected[1]),
            observed_u=float(observed[0]), observed_v=float(observed[1]),
            predicted_u=float(predicted[0]), predicted_v=float(predicted[1]),
            du_px=float(residual[0]), dv_px=float(residual[1]),
            error_px=float(np.linalg.norm(residual)),
            dx_design_mm=float(predicted_mm[0]-expected[0]),
            dy_design_mm=float(predicted_mm[1]-expected[1]),
            error_design_mm=float(np.linalg.norm(predicted_mm-expected)),
            radius_from_image_center_px=radius,
            radial_residual_px=float(residual @ unit),
            tangential_residual_px=float(residual @ np.array([-unit[1], unit[0]]))))
    excluded = sum(p['status'] == 'excluded' for p in checks)
    missing = len(checks)-len(rows)-excluded
    summary = dict(fit_count=sum(p['role'] == 'fit' and p['status'] == 'confirmed'
                                 for p in workspace['points']),
        check_total=len(checks), check_confirmed=len(rows), check_excluded=excluded,
        check_missing=missing, physical_mm_accuracy_verified=False,
        independent_acquisition_groups=1, rmse_px=None, p95_px=None, max_px=None,
        rmse_design_mm=None, p95_design_mm=None, max_design_mm=None)
    if not missing and rows:
        for unit in ('px', 'design_mm'):
            stats = distribution([r[f'error_{unit}'] for r in rows])
            summary.update({f'rmse_{unit}': stats['rmse'], f'p95_{unit}': stats['p95'],
                            f'max_{unit}': stats['maximum']})
    groups = {name: distribution([r['error_px'] for r in rows if r['region'] == name])
              for name in ('core_center', 'core_edge', 'peripheral')}
    trends = {}
    for feature in ('observed_u', 'observed_v', 'radius_from_image_center_px'):
        for component in ('du_px', 'dv_px', 'error_px', 'radial_residual_px'):
            trends[f'{feature}__{component}'] = correlation(
                [r[feature] for r in rows], [r[component] for r in rows])
    return dict(schema='dmf_independent_registration_audit_v1', simulation=False,
        use_scope='pre_experiment_only', summary=summary, points=rows,
        region_definition='central 50% rectangle of actual core design bounding box; rest core edge; outside peripheral',
        core_bounds_mm=list(map(float, core_bounds)), region_statistics_px=groups,
        trends_descriptive_pearson_only=trends,
        radial_origin_px=image_center.tolist(),
        radial_origin_note='image geometric center, NOT a measured optical principal point',
        residual_definition_px='inverse(H)*design - observed, u right / v down',
        residual_definition_design_mm='H*observed - design, x right / y down; NOT physical metrology',
        percentile_definition='numpy.percentile(method=linear)',
        distortion_status='not identified or excluded by 16 points; no correction estimated')


def compare_previous(result, previous, *, tolerance=1e-9):
    differences = {}
    for name in ('rmse_px', 'p95_px', 'max_px', 'rmse_design_mm', 'p95_design_mm', 'max_design_mm'):
        a, b = result['summary'][name], previous[name]
        differences[name] = abs(a-b) if a is not None and b is not None else (0 if a == b else None)
    old = {r['point_id']: r for r in previous['residuals']}
    new = {r['point_id']: r for r in result['points']}
    same_ids = set(old) == set(new)
    for name in sorted(set(old) & set(new)):
        for unit in ('px', 'design_mm'):
            differences[f'{name}_{unit}'] = abs(new[name][f'error_{unit}']-old[name][f'error_{unit}'])
    return dict(matches=same_ids and all(v is not None and v <= tolerance for v in differences.values()),
                absolute_tolerance=tolerance, same_point_ids=same_ids, absolute_differences=differences)


def audit_workspace(path, previous_path):
    from .registration_workspace import load_workspace
    from .design_registration import file_hash, load_design_map
    path = Path(path).resolve()
    w = load_workspace(path)
    design = load_design_map(path.parent/w['design_map_path'], w['design_map_sha256'])
    core = np.concatenate([e['polygon_map_mm'] for e in design['electrodes'] if e['control_id'] <= 400])
    result = recompute(w, core_bounds=[*core.min(axis=0), *core.max(axis=0)])
    previous = json.loads(Path(previous_path).read_text(encoding='utf-8'))
    result['previous_comparison'] = compare_previous(result, previous)
    result['source'] = dict(workspace=str(path), workspace_sha256=file_hash(path),
        image_sha256=w['image_sha256'], design_map_sha256=w['design_map_sha256'],
        previous_result_sha256=file_hash(previous_path))
    result['frozen_H_image_to_design_mm'] = w['fit_freeze']['image_to_design_mm']
    result['fit_points_raw'] = [p for p in w['points'] if p['role'] == 'fit']
    return result


def final_manifest_template():
    return dict(schema='dmf_final_calibration_manifest_v1', status='template_not_calibrated',
        source_scope=None, final_height_fixed=False, reviewer=None,
        conditions={key: None for key in CONDITION_FIELDS}, reference_sha256=None,
        design_map_sha256=None, image_to_design_mm=None, independently_checked=False,
        acceptance=dict(declared_before_check_review=False,
            thresholds_px={k: None for k in ('rmse_px', 'p95_px', 'max_px')},
            measured_px={k: None for k in ('rmse_px', 'p95_px', 'max_px')}))


def validate_final_binding(manifest, current_conditions, reference_sha256, design_map_sha256):
    """Offline preparation guard, NOT claimed integrated into the live control UI."""
    if (manifest.get('schema') != 'dmf_final_calibration_manifest_v1' or
            manifest.get('status') != 'accepted_final_calibration' or
            manifest.get('source_scope') != 'final_apparatus' or
            manifest.get('final_height_fixed') is not True or
            manifest.get('independently_checked') is not True or not manifest.get('reviewer')):
        raise ValueError('final apparatus, fixed height and independent review required')
    for name in CONDITION_FIELDS:
        recorded = manifest.get('conditions', {}).get(name)
        if recorded is None or recorded == '' or name not in current_conditions or recorded != current_conditions[name]:
            raise ValueError(f'missing or changed acquisition geometry: {name}')
    for key, value in [('reference_sha256', reference_sha256), ('design_map_sha256', design_map_sha256)]:
        if not re.fullmatch('[0-9a-f]{64}', str(value)) or manifest.get(key) != value:
            raise ValueError(f'calibration identity mismatch: {key}')
    checked_matrix(manifest['image_to_design_mm'])
    acceptance = manifest['acceptance']
    if acceptance.get('declared_before_check_review') is not True:
        raise ValueError('predeclared acceptance required')
    for key in ('rmse_px', 'p95_px', 'max_px'):
        limit, value = acceptance['thresholds_px'][key], acceptance['measured_px'][key]
        if (not isinstance(limit, (float, int)) or not isinstance(value, (float, int)) or
                not np.isfinite([limit, value]).all() or limit <= 0 or value < 0 or value > limit):
            raise ValueError(f'incomplete or failed acceptance: {key}')
    return True


def audit_dataset(resource_manifest, reviewed_csv, groups):
    from dmf.segmentation_research.data import load_reviewed, sha256
    videos = json.loads(Path(resource_manifest).read_text(encoding='utf-8'))['videos']
    samples = load_reviewed(reviewed_csv, groups=groups)
    rows = []
    for v in videos:
        path = Path(v['source'])
        digest = sha256(path)
        if digest != v['sha256']: raise ValueError('original video hash mismatch')
        rows.append(dict(video_id=v['video_id'], source=str(path), sha256=digest,
            width=v['width'], height=v['height'], frames=v['frames'], fps=v['fps'],
            exposure_timing_verified=v['exposure_timing_verified'],
            timing_sidecar_status=v['timing_sidecar_status']))
    return dict(schema='dmf_registration_segmentation_handoff_audit_v1', videos=rows,
        video_count=len(rows), reviewed_mask_count=len(samples),
        mask_source_video_count=len({s.parent_video_id for s in samples}),
        independent_acquisition_groups=len({s.metadata['session_id'] for s in samples}),
        split_counts={key:sum(s.split == key for s in samples) for key in ('train','val','test','unassigned')},
        state_counts={key:sum(s.metadata.get('state_gt') == key for s in samples)
                      for key in sorted({s.metadata.get('state_gt', '') for s in samples})},
        current_photo_H_valid_for_old_video=False,
        spatial_mapping_status='requires separately validated registration bound to corresponding source video and ROI',
        samples=[dict(parent_video_id=s.parent_video_id, source_frame_id=s.source_frame_id,
            source_sha256=s.source_sha256, image_sha256=s.image_sha256, mask_sha256=s.mask_sha256,
            frame_path=str(s.image_path), mask_path=str(s.mask_path),
            width=s.metadata['width'], height=s.metadata['height'],
            roi_x=s.metadata.get('roi_x'), roi_y=s.metadata.get('roi_y'),
            state_gt=s.metadata.get('state_gt'), map_version=s.metadata.get('map_version')) for s in samples])
