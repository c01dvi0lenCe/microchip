"""Frozen, offline, same-capture semantic baselines; never a formal test.

No cameras, serial devices, network training, instance matching or GT-dependent
prediction. Native inputs remain read-only. Runtime excludes decode, scoring,
background letterbox initialization and disk output, but includes each image's
letterbox, prediction (including background gray conversion) and native restore.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys
from time import perf_counter_ns

import cv2
import numpy as np

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dmf.segmentation_research.roi_pilot import INTERNAL_PROTOCOL, validate_proposed_groups
from dmf.segmentation_research.semantic_baselines import (
    prepare_image, restore_mask, otsu_mask, background_mask,
    assert_causal_background, score_mask, candidate_target_coverage,
)


METHODS = ('otsu', 'background')
METRICS = ('dice', 'iou', 'precision', 'recall')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def _csv(path, rows, fields=None):
    rows = list(rows)
    fields = fields or list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _child(base, raw):
    if not isinstance(raw, str) or not raw.strip() or Path(raw).is_absolute():
        raise ValueError('input path must be a nonblank relative path')
    path = (base / raw).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError(f'input path escapes its frozen directory or is absent: {raw}')
    return path


def _int(value, name, minimum=0):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError(f'{name} must be an integer')
    result = int(value)
    if result < minimum:
        raise ValueError(f'{name} must be >= {minimum}')
    return result


def _read(path):
    array = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
    if array is None:
        raise ValueError(f'unreadable image: {path}')
    return array


def _checked_file(base, raw, expected, paths):
    path = _child(base, raw)
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected) or _sha(path) != expected:
        raise ValueError(f'input SHA256 mismatch: {raw}')
    paths.add(path)
    return path


def _load_samples(root, paths):
    path = root / 'G2/frozen_samples.csv'
    paths.add(path)
    split_manifest = root / 'G2/split_manifest.json'
    if split_manifest.is_file():
        paths.add(split_manifest)
        frozen = json.loads(split_manifest.read_text(encoding='utf-8'))
        if frozen.get('frozen_samples_sha256') != _sha(path):
            raise ValueError('split manifest frozen_samples_sha256 does not match CSV')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    loaded = []
    parents = {}
    for raw in rows:
        row = dict(raw)
        for flag in ('mask_reviewed', 'exclusion_reviewed', 'boundary_reviewed', 'traditional_baseline_released'):
            if row.get(flag) != 'True':
                raise ValueError(f'{flag} must be exact CSV True')
        # Unrelated state/instance/capture reviews are not silently promoted.
        for key in tuple(row):
            if key.endswith('_reviewed') or key in ('capture_group_confirmed', 'grouping_verified'):
                if row[key] not in ('True', 'False'):
                    raise ValueError(f'{key} must be exact CSV True or False')
                row[key] = row[key] == 'True'
        if row.get('split') not in ('train', 'val') or row.get('formal_test') != 'False':
            raise ValueError('only assigned internal train/val, formal_test=False are allowed')
        if row.get('split_protocol') != INTERNAL_PROTOCOL or row.get('semantic_definition') != 'all_actual_droplets':
            raise ValueError('explicit same-capture internal all_actual_droplets protocol required')
        sample_id = row.get('sample_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', sample_id):
            raise ValueError('unsafe or missing sample_id')
        digest = row.get('source_sha256', '')
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('source_sha256 must be a valid source hash')
        parent = row.get('parent_video_id', '')
        if parent in parents and parents[parent] != digest:
            raise ValueError('parent video identity has conflicting source hashes')
        parents[parent] = digest
        row['source_frame_id'] = _int(row.get('source_frame_id'), 'source_frame_id')
        if row.get('frame_id') and _int(row['frame_id'], 'frame_id') != row['source_frame_id']:
            raise ValueError('frame_id does not match original source_frame_id')
        try:
            row['timestamp_s'] = float(row['timestamp_s'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('finite nonnegative timestamp required') from exc
        if not math.isfinite(row['timestamp_s']) or row['timestamp_s'] < 0:
            raise ValueError('finite nonnegative timestamp required')
        try:
            roi = json.loads(row['roi_xywh'])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError('roi_xywh must be JSON integer coordinates') from exc
        if not isinstance(roi, list) or len(roi) != 4 or any(type(n) is not int for n in roi):
            raise ValueError('roi_xywh must contain four native integer coordinates')
        expected_roi = [_int(row.get(key), key, 0 if i < 2 else 1)
                        for i, key in enumerate(('roi_x', 'roi_y', 'roi_w', 'roi_h'))]
        if roi != expected_roi:
            raise ValueError('ROI metadata conflict')
        row['roi_xywh'] = roi
        row['proposed_split'] = row['split']
        arrays = []
        for key in ('frame_path', 'mask_path', 'exclusion_mask_path'):
            image_path = _checked_file(root / 'G2', row.get(key), row.get(key + '_sha256'), paths)
            array = _read(image_path)
            shape = (roi[3], roi[2])
            if array.dtype != np.uint8 or array.shape[:2] != shape:
                raise ValueError(f'{key} must have native ROI size and uint8 type')
            if key == 'frame_path':
                if array.ndim != 3 or array.shape[2] != 3:
                    raise ValueError('frame image must be native BGR')
            elif array.ndim != 2 or not np.isin(array, [0, 255]).all():
                raise ValueError('GT/Ignore must be native binary single-channel masks')
            arrays.append(array)
        if (_int(row.get('width'), 'width', 1), _int(row.get('height'), 'height', 1)) != tuple(roi[2:]):
            raise ValueError('native image dimensions conflict')
        score_mask(None, arrays[1], arrays[2], 'unavailable_background')
        loaded.append((row, *arrays))
    validate_proposed_groups([row for row, *_ in loaded])
    return loaded


def _references(root, loaded, paths):
    path = root / 'backgrounds/reviewed_references.json'
    paths.add(path)
    references = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(references, list):
        raise ValueError('background references must be a reviewed list')
    samples = {row['sample_id']: (row, image) for row, image, *_ in loaded}
    by_sample, images, ids = {}, {}, set()
    for reference in references:
        reference_id = reference.get('reference_id')
        if not isinstance(reference_id, str) or not reference_id or reference_id in ids:
            raise ValueError('background reference IDs must be unique')
        ids.add(reference_id)
        if type(reference.get('usable')) is not bool:
            raise ValueError('background usable must be a literal boolean')
        file = _checked_file(root / 'backgrounds', reference.get('background_path'),
                             reference.get('background_sha256'), paths)
        image = _read(file)
        roi = reference.get('roi_xywh')
        if (not isinstance(roi, list) or len(roi) != 4 or any(type(n) is not int for n in roi)
                or min(roi[:2]) < 0 or min(roi[2:]) < 1 or image.dtype != np.uint8
                or image.shape != (roi[3], roi[2], 3)):
            raise ValueError('background must be native BGR at its recorded ROI')
        images[reference_id] = image
        links = reference.get('linked_sample_ids')
        if not isinstance(links, list) or not links:
            raise ValueError('background requires linked_sample_ids')
        for sample_id in links:
            if sample_id not in samples or sample_id in by_sample:
                raise ValueError('unknown or multiply linked background sample')
            row, _ = samples[sample_id]
            if reference['usable']:
                assert_causal_background(row, reference)
            by_sample[sample_id] = reference
    return by_sample, images


def _maps(root, paths):
    path = root / 'maps/mapping_sources.json'
    if not path.is_file():
        return {}
    paths.add(path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    mapping = raw.get('videos', raw.get('mapping', raw.get('sources', raw)))
    if not isinstance(mapping, dict):
        raise ValueError('mapping_sources must map videos to copied polygons')
    result = {}
    for parent, entry in mapping.items():
        if not isinstance(entry, dict) or 'polygon_path' not in entry:
            continue
        polygon_path = _checked_file(path.parent, entry['polygon_path'], entry.get('polygon_sha256'), paths)
        if entry.get('calibration_manifest'):
            _checked_file(path.parent, entry['calibration_manifest'], entry.get('calibration_sha256'), paths)
        polygons = json.loads(polygon_path.read_text(encoding='utf-8'))
        result[parent] = {str(electrode['control_id']): electrode['polygon_native_px']
                          for electrode in polygons['electrodes']}
    return result


def _coverage(row, pred, gt, ignore, maps):
    base = dict(target_coverage_available=False, target_coverage_reason='recorded_target_or_map_unavailable',
                target_coverage_label='provisional_candidate_mapping_not_final_metrology',
                target_area_px=None, predicted_rho=None, gt_rho=None, target_coverage_absolute_error=None)
    target = row.get('task_target_electrode_recorded', '')
    polygon = maps.get(row['parent_video_id'], {}).get(str(target)) if target else None
    if polygon is not None and pred is not None:
        shifted = np.asarray(polygon, dtype=float) - np.asarray(row['roi_xywh'][:2])
        value = candidate_target_coverage(pred, gt, ignore, shifted)
        base.update(target_coverage_available=value['available'], target_coverage_reason=value['reason'],
                    target_area_px=value['target_area_px'], predicted_rho=value['predicted_rho'],
                    gt_rho=value['gt_rho'], target_coverage_absolute_error=value['absolute_error'])
    return base


def _stats(rows, method, split, **extra):
    eligible = [r for r in rows if r['eligible']]
    positive = [r for r in eligible if r['positive_gt']]
    result = dict(method=method, split=split, **extra, planned=len(rows), eligible=len(eligible),
                  unavailable=sum(not r['eligible'] for r in rows), errors=sum(r['error'] for r in eligible),
                  timed_error_calls=sum(r['timed_error_calls'] for r in eligible),
                  timed_repeat_error_rows=sum(r['timed_repeat_has_errors'] for r in eligible),
                  positive_gt_planned=sum(r['positive_gt'] for r in rows),
                  empty_gt_planned=sum(not r['positive_gt'] for r in rows),
                  positive_gt_eligible=len(positive), empty_gt_eligible=len(eligible) - len(positive),
                  image_level_misses=sum(r['image_level_miss'] for r in positive),
                  empty_predictions=sum(r['empty_mask'] for r in eligible),
                  availability=len(eligible) / len(rows) if rows else None,
                  image_level_miss_rate=sum(r['image_level_miss'] for r in positive) / len(positive) if positive else None)
    for name in METRICS:
        result['mean_' + name] = float(np.mean([r[name] for r in eligible])) if eligible else None
        result['positive_gt_mean_' + name] = float(np.mean([r[name] for r in positive])) if positive else None
    return result


def _summaries(rows):
    videos, summary = [], []
    for method in METHODS:
        for split in ('train', 'val', 'all'):
            subset = [r for r in rows if r['method'] == method and (split == 'all' or r['split'] == split)]
            total = _stats(subset, method, split)
            per_video = []
            for parent in sorted({r['parent_video_id'] for r in subset}):
                video = _stats([r for r in subset if r['parent_video_id'] == parent], method, split,
                               parent_video_id=parent)
                per_video.append(video)
                videos.append(video)
            for name in METRICS:
                values = [r['mean_' + name] for r in per_video if r['eligible']]
                total['per_video_macro_' + name] = float(np.mean(values)) if values else None
            total['per_video_macro_eligible_videos'] = sum(r['eligible'] > 0 for r in per_video)
            total['uncertainty_note'] = 'same_capture_descriptive_only_no_independent_CI'
            summary.append(total)
    return videos, summary


def _configuration(config):
    config = dict(config)
    for key, minimum in [('warmup', 0), ('repeats', 1), ('opencv_threads', 1),
                         ('blur_kernel', 1), ('close_kernel', 1), ('close_iterations', 0)]:
        if type(config.get(key)) is not int or config[key] < minimum:
            raise ValueError(f'invalid fixed configuration: {key}')
    if config['opencv_threads'] != 1:
        raise ValueError('single OpenCV thread is required')
    if any(config[k] % 2 != 1 for k in ('blur_kernel', 'close_kernel')):
        raise ValueError('blur/close kernels must be odd')
    size = config.get('common_input_hw')
    hw = [size, size] if type(size) is int else size
    if not isinstance(hw, (list, tuple)) or len(hw) != 2 or any(type(v) is not int or v < 1 for v in hw):
        raise ValueError('common_input_hw requires positive dimensions')
    threshold = config.get('background_threshold')
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not math.isfinite(threshold) or not 0 <= threshold <= 255:
        raise ValueError('background_threshold must be finite [0,255]')
    if not isinstance(config.get('hardware_label'), str) or not config['hardware_label'].strip():
        raise ValueError('recorded hardware label required')
    return config, tuple(hw)


def run(root, output, config=None):
    """Validate frozen inputs, run both methods, retain every planned sample row."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output == root or root.is_relative_to(output):
        raise ValueError('output must be a new independent directory')
    source_files = [Path(__file__).resolve(), Path(sys.modules[prepare_image.__module__].__file__).resolve(),
                    Path(sys.modules[validate_proposed_groups.__module__].__file__).resolve()]
    source_before = {str(p): _sha(p) for p in source_files}
    config_path = root / 'baseline_config.json'
    paths = {config_path}
    on_disk_config = json.loads(config_path.read_text(encoding='utf-8'))
    fixed, hw = _configuration(on_disk_config if config is None else config)
    loaded = _load_samples(root, paths)
    references, background_images = _references(root, loaded, paths)
    maps = _maps(root, paths)
    before = {path.relative_to(root).as_posix(): _sha(path) for path in sorted(paths)}
    output.mkdir(parents=True, exist_ok=False)
    _json(output / 'fixed_config.json', fixed)
    _json(output / 'input_hashes_before.json', before)
    config_digest = _sha(output / 'fixed_config.json')
    rows, timings, initialized = [], [], []
    previous_threads = cv2.getNumThreads()
    try:
        cv2.setNumThreads(1)
        if cv2.getNumThreads() != 1:
            raise RuntimeError('OpenCV failed to enforce one thread')
        background_cache = {}
        for reference in {r['reference_id']: r for r in references.values() if r['usable']}.values():
            start = perf_counter_ns()
            background_cache[reference['reference_id']] = prepare_image(background_images[reference['reference_id']], hw)[0]
            initialized.append(dict(reference_id=reference['reference_id'], duration_ns=perf_counter_ns() - start,
                                    excluded_from_frame_timing=True, operation='background_letterbox_only'))
        params = {key: fixed[key] for key in ('blur_kernel', 'close_kernel', 'close_iterations')}
        for metadata, image, gt, ignore in loaded:
            sample_id = metadata['sample_id']
            reference = references.get(sample_id)
            for method in METHODS:
                row = dict(sample_id=sample_id, parent_video_id=metadata['parent_video_id'],
                           split=metadata['split'], method=method, source_sha256=metadata['source_sha256'],
                           source_frame_id=metadata['source_frame_id'], timestamp_s=metadata['timestamp_s'],
                           native_height=gt.shape[0], native_width=gt.shape[1],
                           common_input_hw=json.dumps(hw), roi_xywh=json.dumps(metadata['roi_xywh']),
                           prediction_path='', prediction_sha256='', first_timed_prediction_sha256='',
                           reference_id=reference['reference_id'] if method == 'background' and reference else '',
                           deterministic=None, inference_error='', any_call_errors=0,
                           timed_error_calls=0, timed_repeat_has_errors=False, timed_repeat_errors='',
                           centroid_error_px=None, centroid_reason='instance_GT_not_reviewed',
                           instance_miss_rate=None, instance_metric_reason='instance_GT_not_reviewed')
                pred = None
                if method == 'background' and (reference is None or not reference['usable']):
                    row.update(score_mask(None, gt, ignore, 'unavailable_background'))
                    row['unavailable_reason'] = reference.get('review_note', 'reviewed_background_unusable') if reference else 'no_reviewed_background_reference'
                else:
                    if method == 'background':
                        assert_causal_background(metadata, reference)
                    predictions, errors, transform = [], [], None
                    for call in range(fixed['warmup'] + fixed['repeats']):
                        phase = 'warmup' if call < fixed['warmup'] else 'timed'
                        start = perf_counter_ns()
                        error, prediction = '', None
                        try:
                            prepared, transform = prepare_image(image, hw)
                            binary = (otsu_mask(prepared, **params) if method == 'otsu' else
                                      background_mask(prepared, background_cache[reference['reference_id']],
                                                      threshold=fixed['background_threshold'], **params))
                            prediction = restore_mask(binary, transform)
                        except Exception as exc:
                            error = f'{type(exc).__name__}: {exc}'
                        elapsed = perf_counter_ns() - start
                        timings.append(dict(sample_id=sample_id, parent_video_id=metadata['parent_video_id'],
                                            split=metadata['split'], method=method, phase=phase,
                                            call_index=call, duration_ns=elapsed, duration_ms=elapsed / 1e6,
                                            status='error' if error else 'ok', error=error,
                                            opencv_threads=cv2.getNumThreads()))
                        if error:
                            row['any_call_errors'] += 1
                        if phase == 'timed':
                            predictions.append(prediction)
                            errors.append(error)
                    first = predictions[0]
                    if first is not None:
                        row['first_timed_prediction_sha256'] = hashlib.sha256(first.tobytes()).hexdigest()
                    row['deterministic'] = (all(p is not None for p in predictions) and
                                             all(np.array_equal(predictions[0], p) for p in predictions[1:]))
                    # The first timed attempt alone determines the scored/saved
                    # prediction. Later failures remain explicit runtime evidence.
                    status = 'error' if errors[0] else 'ok'
                    row['inference_error'] = errors[0]
                    row['timed_error_calls'] = sum(bool(e) for e in errors)
                    row['timed_repeat_has_errors'] = any(errors)
                    row['timed_repeat_errors'] = ' | '.join(dict.fromkeys(e for e in errors if e))
                    pred = np.zeros_like(gt) if status == 'error' else first
                    row.update(score_mask(pred, gt, ignore, status))
                    if transform is not None:
                        row['letterbox_transform'] = json.dumps(transform)
                    dest = output / 'predictions' / method / f'{sample_id}.png'
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    ok, encoded = cv2.imencode('.png', pred)
                    if not ok:
                        raise RuntimeError('prediction PNG encoding failed')
                    dest.write_bytes(encoded.tobytes())
                    row['prediction_path'] = dest.relative_to(output).as_posix()
                    row['prediction_sha256'] = _sha(dest)
                row.update(_coverage(metadata, pred, gt, ignore, maps))
                rows.append(row)
    finally:
        cv2.setNumThreads(previous_threads)
    after = {path.relative_to(root).as_posix(): _sha(path) for path in sorted(paths)}
    _json(output / 'input_hashes_after.json', after)
    videos, summary = _summaries(rows)
    common_ids = {r['sample_id'] for r in rows if r['method'] == 'background' and r['eligible']}
    common = [r for r in rows if r['sample_id'] in common_ids]
    _, common_summary = _summaries(common)
    _csv(output / 'per_image.csv', rows)
    _csv(output / 'per_video.csv', videos)
    _csv(output / 'summary.csv', summary)
    _csv(output / 'common_background_subset.csv', common, list(dict.fromkeys(k for r in rows for k in r)))
    _csv(output / 'common_background_subset_summary.csv', common_summary)
    _csv(output / 'availability.csv', [dict(sample_id=r['sample_id'], split=r['split'], method=r['method'],
                                          eligible=r['eligible'], status=r['status'],
                                          unavailable_reason=r.get('unavailable_reason', '')) for r in rows])
    _csv(output / 'timings.csv', timings)
    timing_summary = []
    for method in METHODS:
        for split in ('train', 'val', 'all'):
            calls = [r['duration_ms'] for r in timings if r['method'] == method and r['phase'] == 'timed'
                     and (split == 'all' or r['split'] == split)]
            timing_summary.append(dict(method=method, split=split, timed_calls=len(calls),
                                       timed_error_calls=sum(r['status'] == 'error' for r in timings
                                                             if r['method'] == method and r['phase'] == 'timed'
                                                             and (split == 'all' or r['split'] == split)),
                                       mean_ms=float(np.mean(calls)) if calls else None,
                                       p50_ms=float(np.percentile(calls, 50)) if calls else None,
                                       p95_ms=float(np.percentile(calls, 95)) if calls else None,
                                       includes_failed_calls=True, background_initialization_excluded=True))
    _csv(output / 'timing_summary.csv', timing_summary)
    _json(output / 'background_initialization.json', initialized)
    artifact_hashes = {p.relative_to(output).as_posix(): _sha(p)
                       for p in sorted(output.rglob('*')) if p.is_file()}
    source_after = {str(p): _sha(p) for p in source_files}
    manifest = dict(scope='same_capture_internal_initial_traditional_baselines', simulation=False,
                    formal_test=False, batch_disjoint=False, independent_capture_groups=False,
                    instance_GT_reviewed=False, physical_lineage_verified=False,
                    hardware_label=fixed['hardware_label'], config_sha256=config_digest,
                    config_override=config is not None, input_hashes_before=before, input_hashes_after=after,
                    inputs_unchanged=before == after, source_code_sha256=source_before,
                    source_code_hashes_before=source_before, source_code_hashes_after=source_after,
                    source_code_unchanged=source_before == source_after,
                    output_artifact_sha256=artifact_hashes,
                    environment=dict(python=sys.version, opencv=cv2.__version__, numpy=np.__version__,
                                     platform=platform.platform(), processor=platform.processor()),
                    opencv_threads=1, previous_opencv_threads=previous_threads, planned_rows=len(rows),
                    timing_contract='image_letterbox+prediction+native_restore; background_letterbox_init_excluded; decode_score_write_excluded',
                    repeat_policy='score_and_save_first_timed_attempt_only; first_timed_error_is_eligible_empty_error; later_repeat_errors_logged_separately; not_best_of_N',
                    runtime_error_counts=dict(first_timed_error_rows=sum(r['error'] for r in rows),
                                              timed_repeat_error_rows=sum(r['timed_repeat_has_errors'] for r in rows),
                                              timed_error_calls=sum(r['timed_error_calls'] for r in rows),
                                              warmup_error_calls=sum(r['phase'] == 'warmup' and r['status'] == 'error' for r in timings),
                                              all_error_calls=sum(r['status'] == 'error' for r in timings)),
                    nondeterministic_rows=sum(r['deterministic'] is False for r in rows),
                    background_unavailable_search='fixed_frame0_pilot_not_exhaustive_past_reference_search',
                    limitations=['No formal held-out test or network comparison',
                                 'No independent-capture confidence interval or generalization claim',
                                 'Provisional map diagnostics are not final calibration/metrology',
                                 'Image-level empty-positive-GT misses are not instance/identity misses'])
    _json(output / 'manifest.json', manifest)
    if before != after:
        raise RuntimeError('frozen inputs changed during evaluation; results invalid')
    if source_before != source_after:
        raise RuntimeError('source code changed during evaluation; results invalid')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = run(args.root, args.output)
    print(json.dumps(dict(output=str(args.output.resolve()), planned_rows=manifest['planned_rows'],
                          inputs_unchanged=manifest['inputs_unchanged'], formal_test=False)))


if __name__ == '__main__':
    main()
