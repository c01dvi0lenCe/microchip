"""Descriptive Pilot evaluation; this entry cannot claim a held-out test."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import time

import cv2
import numpy as np

from dmf.vision.contracts import FramePacket
from dmf.vision.image_io import read_image, write_image
from dmf.vision.metrics import centroid_error, mask_centroid, mean_available, segmentation_metrics
from .baselines import ThresholdBaseline
from .data import freeze_samples, load_reviewed, sha256, write_csv


def score_prediction(result, gt):
    missing = result is None or result.mask is None
    predicted = np.zeros_like(gt) if missing or not result.detected else result.mask
    if predicted.shape != gt.shape or predicted.dtype != np.uint8 or not set(np.unique(predicted)).issubset({0, 255}):
        raise ValueError('invalid prediction shape or binary format')
    detected = bool(predicted.any())
    return dict(**segmentation_metrics(predicted, gt),
                centroid_error_px=centroid_error(mask_centroid(predicted), mask_centroid(gt)),
                detected=detected, prediction_missing=missing, empty_mask=not detected,
                positive_gt=bool(gt.any()), inference_error='')


def summarize_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['method']].append(row)
    output = []
    for method, values in groups.items():
        parents = sorted({r['parent_video_id'] for r in values})
        summary = dict(method=method, images=len(values), parent_videos=len(parents),
                       positive_gt_images=sum(r['positive_gt'] for r in values),
                       positive_gt_misses=sum(r['positive_gt'] and not r['detected'] for r in values),
                       empty_masks=sum(r['empty_mask'] for r in values),
                       missing_predictions=sum(r['prediction_missing'] for r in values),
                       inference_error_images=sum(bool(r['inference_error']) for r in values),
                       centroid_denominator=sum(r['centroid_error_px'] is not None for r in values),
                       mean_centroid_error_px=mean_available(r['centroid_error_px'] for r in values),
                       confidence_interval=None,
                       uncertainty_note='Descriptive selected Pilot; no independent-session CI or significance claim')
        for metric in ('dice', 'iou', 'precision', 'recall'):
            summary['mean_' + metric] = mean_available(r[metric] for r in values)
            summary['video_macro_' + metric] = mean_available(
                mean_available(r[metric] for r in values if r['parent_video_id'] == p) for p in parents)
        output.append(summary)
    return output


def _timing(values):
    return dict(mean_ms=float(np.mean(values)), p50_ms=float(np.percentile(values, 50)),
                p95_ms=float(np.percentile(values, 95)), timed_calls=len(values))


def _version():
    root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True))
    except (OSError, subprocess.CalledProcessError):
        head, dirty = 'unavailable', None
    sources = list(Path(__file__).parent.glob('*.py')) + [
        root / 'dmf/vision/metrics.py', root / 'dmf/vision/algorithms/common.py',
        root / 'dmf/vision/contracts.py', root / 'dmf/vision/image_io.py', root / 'run_segmentation_pilot.py']
    return dict(head=head, dirty=dirty,
                source_sha256={str(p.relative_to(root)): sha256(p) for p in sources if p.is_file()})


def run_pilot(reviewed, output, config, *, methods=None):
    """Methods receive images only. First timed output is scored, never best-of-N."""
    reviewed, output = Path(reviewed).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'preserve existing results: {output}')
    if config.get('data_kind') not in {'real_video', 'synthetic_fixture'}:
        raise ValueError('explicit data_kind real_video or synthetic_fixture is required')
    for key, minimum in [('warmup', 0), ('repeats', 1), ('opencv_threads', 1)]:
        if type(config.get(key)) is not int or config[key] < minimum:
            raise ValueError(f'invalid {key}')
    methods = methods if methods is not None else {
        name: ThresholdBaseline(name, config.get('parameters', {})) for name in ('otsu', 'adaptive')}
    if not methods or any(not re.fullmatch('[a-zA-Z0-9_-]+', name) for name in methods):
        raise ValueError('invalid method name')
    group_path = Path(config['source_groups_path']).resolve() if config.get('source_groups_path') else None
    samples = load_reviewed(reviewed, groups=group_path)
    input_hash = sha256(reviewed)
    group_hash = sha256(group_path) if group_path else None
    output.mkdir(parents=True)
    if group_path:
        shutil.copyfile(group_path, output / 'source_groups.json')
    frozen = freeze_samples(samples, output / 'reviewed_snapshot')
    samples = load_reviewed(frozen)
    (output / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    method_config = {name: algorithm.configuration() if hasattr(algorithm, 'configuration') else
                     {'name': name, 'test_injected_method': True} for name, algorithm in methods.items()}
    rows, timings, quality = [], [], []
    threads_before = cv2.getNumThreads()
    cv2.setNumThreads(config['opencv_threads'])
    try:
        for i, sample in enumerate(samples):
            image = read_image(sample.image_path, cv2.IMREAD_COLOR)
            gt = read_image(sample.mask_path, cv2.IMREAD_GRAYSCALE)
            packet = FramePacket(sample.parent_video_id, sample.source_frame_id, 0.,
                                 'segmentation_only_no_physical_time', image)
            quality.append(dict(sample_id=i, parent_video_id=sample.parent_video_id,
                                source_frame_id=sample.source_frame_id, width=image.shape[1],
                                height=image.shape[0], gt_area_px=int(np.count_nonzero(gt)),
                                gt_components=cv2.connectedComponents(gt)[0] - 1,
                                gt_touches_roi_border=bool(np.any(gt[0]) or np.any(gt[-1]) or
                                                           np.any(gt[:, 0]) or np.any(gt[:, -1]))))
            for name, algorithm in methods.items():
                first_result, first_error, warmup_errors = None, '', 0
                for _ in range(config['warmup']):
                    try:
                        algorithm.process(packet)
                    except Exception:
                        warmup_errors += 1
                for repeat in range(config['repeats']):
                    start, result, error = time.perf_counter_ns(), None, ''
                    try:
                        result = algorithm.process(packet)
                        result.validate(image.shape)
                    except Exception as exc:
                        result, error = None, f'{type(exc).__name__}: {exc}'
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    timings.append(dict(method=name, sample_id=i, repeat=repeat, elapsed_ms=elapsed,
                                        inference_error=error, width=image.shape[1], height=image.shape[0]))
                    if repeat == 0:
                        first_result, first_error = result, error
                scores = score_prediction(first_result, gt)
                scores['inference_error'] = first_error
                pred = first_result.mask if first_result is not None and first_result.detected else np.zeros_like(gt)
                pred_path = output / 'predictions' / name / f'sample_{i:04d}.png'
                if not write_image(pred_path, pred):
                    raise OSError(f'could not save prediction {pred_path}')
                sample_times = [t['elapsed_ms'] for t in timings if t['method'] == name and t['sample_id'] == i]
                rows.append(dict(sample_id=i, method=name, parent_video_id=sample.parent_video_id,
                                 source_frame_id=sample.source_frame_id, source_sha256=sample.source_sha256,
                                 split=sample.split, width=image.shape[1], height=image.shape[0],
                                 frame_path=str(sample.image_path.relative_to(output)),
                                 gt_mask_path=str(sample.mask_path.relative_to(output)),
                                 prediction_path=pred_path.relative_to(output).as_posix(),
                                 warmup_error_calls=warmup_errors, **scores, **_timing(sample_times)))
    finally:
        cv2.setNumThreads(threads_before)
    summary = summarize_rows(rows)
    per_video = []
    for parent in sorted({r['parent_video_id'] for r in rows}):
        per_video.extend(dict(parent_video_id=parent, **r) for r in summarize_rows(
            [r for r in rows if r['parent_video_id'] == parent]))
    for s in summary:
        times = [t['elapsed_ms'] for t in timings if t['method'] == s['method']]
        s.update(_timing(times))
        s['timed_error_calls'] = sum(bool(t['inference_error']) for t in timings if t['method'] == s['method'])
    for filename, values in [('per_image.csv', rows), ('per_video.csv', per_video),
                             ('timings.csv', timings), ('mask_quality.csv', quality), ('summary.csv', summary)]:
        write_csv(output / filename, values)
    manifest = dict(schema='dmf_segmentation_pilot_v1', created_utc=datetime.now(timezone.utc).isoformat(),
                    data_kind=config['data_kind'], simulation=config['data_kind'] == 'synthetic_fixture',
                    formal_test=False, purpose='development Pilot, no held-out generalization claim',
                    original_reviewed_csv=str(reviewed), original_reviewed_sha256=input_hash,
                    frozen_samples_sha256=sha256(frozen), config_sha256=sha256(output / 'config.json'),
                    methods=method_config, summary=summary, code_version=_version(),
                    environment=dict(python=platform.python_version(), platform=platform.platform(),
                                     processor=platform.processor(), hardware_label=config.get('hardware_label', 'unverified'),
                                     opencv=cv2.__version__, numpy=np.__version__,
                                     backend='OpenCV CPU', opencv_threads=config['opencv_threads']),
                    timing_scope='host wall, preprocessing+inference+postprocessing+result validation; excludes decode/metrics/save; all timed calls including errors',
                    scoring_rule='first timed output; not best-of-N; failures remain empty predictions',
                    source_groups_sha256=group_hash,
                    known_chip_groups=len({s.metadata['chip_id'] for s in samples}) if all(s.metadata.get('chip_id') for s in samples) else None,
                    known_session_groups=len({s.metadata['session_id'] for s in samples}) if all(s.metadata.get('session_id') for s in samples) else None,
                    independent_unit='confirmed acquisition session; videos/frames are subsamples' if group_path else 'chip/session independence unknown; videos not established independent replicates',
                    unet=dict(status='not_evaluated_no_real_weights'),
                    formal_blockers=['selected development Pilot only', 'no frozen train/val/test split',
                                     'insufficient independently acquired groups for held-out evaluation',
                                     'no trained real-data U-Net'])
    if sha256(reviewed) != input_hash:
        raise ValueError('reviewed CSV changed during evaluation; do not use this run')
    if group_path and (sha256(group_path) != group_hash or sha256(output / 'source_groups.json') != group_hash):
        raise ValueError('source group manifest changed during evaluation')
    manifest['artifacts_sha256'] = {
        p.relative_to(output).as_posix(): sha256(p) for p in output.rglob('*') if p.is_file()}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return manifest
