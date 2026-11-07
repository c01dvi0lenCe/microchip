"""Read-only whole-chip video replay verification, not camera/closed-loop acceptance.

Checks frozen native ROI parity, audits batch equivalence, then processes 63
native video frames. No GT scoring, camera SDK, serial port or actuator output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding='utf-8')


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def write_rows(path, rows, fallback=('sample_id',)):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else list(fallback))
        writer.writeheader()
        writer.writerows(rows)


def validate_output(output, inputs):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('verification output exists; no overwrite')
    for source in inputs:
        source = Path(source).resolve()
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('output must be separate from all inputs')
    return output


def _selected_videos(inventory):
    # The original inventory records videos in acquisition order.
    videos = inventory['videos'][-2:] if 'videos' in inventory else inventory['last2']
    if len(videos) != 2:
        raise ValueError('inventory must identify two final source videos')
    result = []
    for entry in videos:
        source = entry.get('source', entry.get('path'))
        if not source:
            raise ValueError('source video path missing')
        video_id = entry.get('video_id', Path(source).stem)
        if video_id != Path(source).stem:
            raise ValueError('video ID must be the real source video name')
        if int(entry.get('frames', 30)) < 30:
            raise ValueError('source video has fewer than 30 frames')
        result.append(dict(entry, source=source, video_id=video_id))
    if result[0]['video_id'] == result[1]['video_id']:
        raise ValueError('source video IDs must be distinct')
    return result


def select_replay_frames(inventory, annotations):
    videos = _selected_videos(inventory)
    by_video = {row['video_id']: row for row in videos}
    selection = []
    for video in videos:
        for frame_id in range(30):
            selection.append(dict(video_id=video['video_id'], source=video['source'],
                                  source_sha256=video['sha256'], frame_id=frame_id,
                                  kind='consecutive', sample_id='',
                                  save_example=frame_id in (0, 29)))
    by_sample = {row['sample_id']: row for row in annotations}
    for sample_id in ('N1106_090', 'N1106_091', 'N1106_092'):
        if sample_id not in by_sample:
            raise ValueError(f'missing dark-source annotation: {sample_id}')
        row = by_sample[sample_id]
        video = by_video.get(row['parent_video_id'])
        if video is None or row['source_sha256'] != video['sha256']:
            raise ValueError(f'dark-source video/hash mismatch: {sample_id}')
        frame_id = int(row['source_frame_id'])
        if not 0 <= frame_id < int(video.get('frames', frame_id + 1)):
            raise ValueError('dark-source frame index out of range')
        selection.append(dict(video_id=video['video_id'], source=video['source'],
                              source_sha256=video['sha256'], frame_id=frame_id,
                              kind='dark_source', sample_id=sample_id, save_example=True))
    return selection


def recorded_timing(row):
    from dmf.vision.contracts import FrameTiming

    def integer(name):
        value = row.get(name, '')
        return int(value) if value != '' else None

    if row.get('timestamp_source') != 'host_receive_perf_counter':
        raise ValueError('recorded host-receive perf-counter timing required')
    timestamp = float(row['receive_relative_s'])
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError('invalid recorded relative timestamp')
    timing = FrameTiming(capture_frame_id=integer('sdk_frame_number'),
        receive_monotonic_ns=integer('host_receive_monotonic_ns'),
        receive_perf_counter_ns=integer('host_receive_perf_counter_ns'),
        receive_utc_ns=integer('host_utc_ns'),
        device_ticks_raw=integer('device_timestamp_raw'),
        sdk_host_timestamp_raw=integer('sdk_host_timestamp_raw'),
        clock_domain='recorded_host_relative',
        timing_quality='recorded_host_receive_not_exposure')
    if timing.receive_perf_counter_ns is None or timing.capture_frame_id is None:
        raise ValueError('recorded SDK/receive timing missing')
    return timing, timestamp


def assert_native_mask(mask, shape, sample_id):
    import numpy as np
    if mask is None or mask.shape != tuple(shape[:2]) or mask.dtype != np.uint8:
        raise ValueError(f'native uint8 mask geometry mismatch: {sample_id}')
    if not set(np.unique(mask)).issubset({0, 255}):
        raise ValueError(f'nonbinary mask: {sample_id}')


def assert_native_parity(predicted, reference, shape, sample_id):
    import numpy as np
    assert_native_mask(predicted, shape, sample_id)
    assert_native_mask(reference, shape, sample_id)
    different = int(np.count_nonzero(predicted != reference))
    if different:
        raise ValueError(f'frozen reference pixel mismatch: {sample_id}: {different}')
    return different


def _read_image(path, grayscale=False):
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8),
                         cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'image decode failed: {path}')
    return image


def _write_png(path, image):
    import cv2
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise OSError(f'PNG encode failed: {path}')
    path.write_bytes(encoded.tobytes())


def load_native_rois(root, expected_count=120):
    root = Path(root).resolve()
    rows = read_rows(root/'annotations.csv')
    if len(rows) != expected_count:
        raise ValueError(f'expected {expected_count} native ROIs, got {len(rows)}')
    seen = set(); images = []
    for row in rows:
        sample_id = row['sample_id']
        if (not sample_id or sample_id in seen or '/' in sample_id or '\\' in sample_id
                or sample_id in ('.', '..') or ':' in sample_id):
            raise ValueError('invalid/duplicate ROI sample ID')
        seen.add(sample_id)
        path = (root/row['frame_path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('ROI path outside source root')
        if sha256(path) != row['frame_path_sha256']:
            raise ValueError(f'ROI image hash mismatch: {sample_id}')
        image = _read_image(path)
        if image.shape[:2] != (int(row['roi_h']), int(row['roi_w'])):
            raise ValueError(f'ROI native shape mismatch: {sample_id}')
        images.append(image)
    return rows, images


def verify_roi_parity(predictor, rows, images, reference, output):
    reference = Path(reference)
    manifest = read_json(reference/'manifest.json')
    hashes = {key.replace('\\', '/'): value for key, value in manifest['output_sha256'].items()}
    records = []
    for row, image in zip(rows, images):
        sample_id = row['sample_id']
        relative = f'masks/unet/{sample_id}.png'
        path = reference/relative
        if relative not in hashes or sha256(path) != hashes[relative]:
            raise ValueError(f'frozen reference mask hash mismatch: {sample_id}')
        mask = predictor._infer([image])[0]
        cached = _read_image(path, grayscale=True)
        different = assert_native_parity(mask, cached, image.shape, sample_id)
        target = Path(output)/'roi_parity_masks'/f'{sample_id}.png'
        _write_png(target, mask)
        records.append(dict(sample_id=sample_id, different_pixels=different,
                            source_roi_sha256=row['frame_path_sha256'],
                            reference_mask_sha256=hashes[relative],
                            prediction_mask_sha256=sha256(target)))
    return records


def wait_for_result(detector, packet, timeout_s=120):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = detector.poll_result()
        if result is not None:
            if (result.packet.video_id, result.packet.frame_id) != (packet.video_id, packet.frame_id):
                raise ValueError('detection result does not match source frame')
            if result.error:
                raise RuntimeError(f'detection failed: {result.error}')
            return result
        if detector.error:
            raise RuntimeError(f'detection worker failed: {detector.error}')
        if not detector.worker.is_alive():
            raise RuntimeError('detection worker stopped without a result')
        time.sleep(.01)
    raise TimeoutError(f'full-frame inference exceeded {timeout_s}s')


def _snapshot(paths, tolerate_errors=False):
    result = {}
    for path in paths:
        key = str(Path(path).resolve())
        try:
            result[key] = sha256(path)
        except OSError as exc:
            if not tolerate_errors:
                raise
            result[key] = f'unreadable:{type(exc).__name__}'
    return result


def run_verification(package, roi_root, reference_preview, inventory_path, output,
                     device='auto', predictor_factory=None):
    import cv2
    import numpy as np
    from dmf.vision.contracts import FramePacket
    from dmf.vision.g4_model import G4UNetPredictor
    from dmf.vision.whole_chip import WholeChipDetector

    package = Path(package).resolve(); roi_root = Path(roi_root).resolve()
    reference_preview = Path(reference_preview).resolve(); inventory_path = Path(inventory_path).resolve()
    inventory = read_json(inventory_path)
    videos = _selected_videos(inventory)
    video_paths = [Path(row['source']).resolve() for row in videos]
    sidecars = [path.with_suffix('.timestamps.csv') for path in video_paths]
    output = validate_output(output, [package, roi_root, reference_preview, inventory_path,
                                     *video_paths, *sidecars])
    # Snapshot only read inputs, including the source/checkpoint hashes recorded
    # by the frozen preview. Nothing under a historical source is written.
    reference_manifest = read_json(reference_preview/'manifest.json')
    protected_paths = [inventory_path, Path(__file__).resolve(),
                       ROOT/'dmf/vision/g4_model.py', ROOT/'dmf/vision/whole_chip.py',
                       ROOT/'dmf/vision/whole_chip_geometry.py']
    for folder in (package, roi_root, reference_preview):
        protected_paths.extend(path for path in folder.rglob('*') if path.is_file())
    protected_paths.extend(video_paths + sidecars)
    protected_paths.extend(Path(path) for path in reference_manifest.get('source_sha256', {})
                           if Path(path).is_file())
    for path in reference_manifest.get('provenance', {}).get('protected_files', []):
        if not Path(path).is_file():
            raise ValueError(f'protected source checkpoint is missing: {path}')
        protected_paths.append(Path(path))
    protected = _snapshot(set(protected_paths))
    known_hashes = {str(Path(row['path']).resolve()): row['sha256']
                    for row in inventory.get('source_files', [])}
    timelines = {}
    for video, source, sidecar in zip(videos, video_paths, sidecars):
        if protected[str(source)] != video['sha256']:
            raise ValueError('source video hash mismatch')
        if str(sidecar) not in known_hashes or protected[str(sidecar)] != known_hashes[str(sidecar)]:
            raise ValueError('source timestamp sidecar hash mismatch')
        timing_rows = read_rows(sidecar)
        timeline = {}
        for row in timing_rows:
            frame_id = int(row['video_frame_index'])
            if frame_id in timeline:
                raise ValueError('duplicate recorded frame timing')
            timeline[frame_id] = row
        if len(timeline) != int(video['frames']):
            raise ValueError('source timing/video inventory frame counts differ')
        timelines[video['video_id']] = timeline
    rows, images = load_native_rois(roi_root)
    selection = select_replay_frames(inventory, rows)
    for item in selection:
        if item['frame_id'] not in timelines[item['video_id']]:
            raise ValueError('selected source frame timing missing')
    output.mkdir(parents=True)
    report = dict(schema='whole_chip_offline_replay_verification_v1', status='running',
        simulation=False, training_performed=False, gt_used=False, accuracy_evaluated=False,
        control_output=False, calibration_bound=False, physical_exposure_verified=False,
        camera_acceptance=False, closed_loop_acceptance=False,
        scope='offline native video replay only; not live camera or physical closed-loop acceptance',
        timing_scope='current PC diagnostic processing only; recorded host receive is not exposure time',
        replay_counter_scope='submission sequence; selected dark-frame gaps and video changes are not live acquisition drops',
        planned_predictions=63, planned_roi_parity_samples=120,
        input_sha256_before=protected, predictions=[], roi_parity=[], batch_audit={}, error='')
    detector = None
    try:
        predictor = predictor_factory() if predictor_factory else G4UNetPredictor(package, device=device, batch_size=4)
        report['model_manifest'] = predictor.manifest
        report['backend'] = predictor.device
        report['roi_parity'] = verify_roi_parity(predictor, rows, images, reference_preview, output)
        write_rows(output/'roi_parity.csv', report['roi_parity'])
        report['batch_audit'] = predictor.audit_batch_equivalence(images)
        if int(report['batch_audit']['samples']) != 120:
            raise ValueError('batch audit did not cover all 120 ROIs')
        if report['batch_audit']['different_pixels'] and predictor.batch_size != 1:
            raise ValueError('batch mismatch must lock batch1')
        if report['batch_audit']['selected_batch_size'] != predictor.batch_size:
            raise ValueError('batch audit selected-size mismatch')
        del images
        detector = WholeChipDetector(lambda: predictor, output/'session')
        for number, item in enumerate(selection):
            source = Path(item['source'])
            capture = cv2.VideoCapture(str(source))
            try:
                if not capture.isOpened():
                    raise OSError(f'cannot open source video: {source}')
                if not capture.set(cv2.CAP_PROP_POS_FRAMES, item['frame_id']):
                    raise OSError('cannot seek selected source frame')
                ok, image = capture.read()
                if not ok or image is None:
                    raise OSError('source frame decode failed')
                decoded_position = int(round(capture.get(cv2.CAP_PROP_POS_FRAMES))) - 1
                if decoded_position != item['frame_id']:
                    raise ValueError('decoded frame index mismatch')
            finally:
                capture.release()
            raw_timing = timelines[item['video_id']][item['frame_id']]
            timing, timestamp = recorded_timing(raw_timing)
            if image.shape[:2] != (int(raw_timing['height']), int(raw_timing['width'])):
                raise ValueError('source video/timing native geometry mismatch')
            packet = FramePacket(item['video_id'], item['frame_id'], timestamp,
                                 'host_receive_perf_counter', image, timing)
            if not detector.submit(packet):
                raise RuntimeError('detector rejected selected source frame')
            result = wait_for_result(detector, packet)
            assert_native_mask(result.mask, image.shape, item['sample_id'] or str(item['frame_id']))
            expected_tiles = math.ceil(image.shape[1]/384) * math.ceil(image.shape[0]/384)
            if result.tile_count != expected_tiles or tuple(result.roi) != (0, 0, image.shape[1], image.shape[0]):
                raise ValueError('full native frame coverage mismatch')
            stem = f'{number:03}_{item["video_id"]}_frame_{item["frame_id"]:06}'
            mask_path = output/'masks'/f'{stem}.png'
            _write_png(mask_path, result.mask)
            record = dict(index=number, video_id=item['video_id'], source=str(source),
                source_sha256=item['source_sha256'], source_frame_id=item['frame_id'],
                kind=item['kind'], sample_id=item['sample_id'], timestamp_s=timestamp,
                timestamp_source=packet.timestamp_source, timestamp_clock_domain=packet.timestamp_clock_domain,
                sdk_frame_number=timing.capture_frame_id, device_ticks_raw=timing.device_ticks_raw,
                sdk_host_timestamp_raw=timing.sdk_host_timestamp_raw,
                host_receive_monotonic_ns=timing.receive_monotonic_ns,
                host_receive_perf_counter_ns=timing.receive_perf_counter_ns, host_utc_ns=timing.receive_utc_ns,
                native_width=image.shape[1], native_height=image.shape[0],
                decoded_frame_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                mask_path=mask_path.relative_to(output).as_posix(), mask_sha256=sha256(mask_path),
                foreground_px=int(np.count_nonzero(result.mask)), components=len(result.components),
                roi=json.dumps(result.roi), tile_count=result.tile_count, backend=result.backend,
                batch_size=result.batch_size, processing_ms=result.processing_ms,
                pipeline_ms=(result.completed_perf_ns-result.submitted_perf_ns)/1e6,
                submitted_perf_ns=result.submitted_perf_ns, started_perf_ns=result.started_perf_ns,
                completed_perf_ns=result.completed_perf_ns,
                inference_queue_overwrites=detector.queue_overwrites,
                result_overwrites=detector.result_overwrites,
                source_queue_overwrites=timing.queue_overwrites,
                duplicate_frames=detector.duplicate_frames,
                delivered_sdk_number_gaps=detector.delivered_sdk_number_gaps,
                sdk_capture_skips=None,preview_queue_overwrites=detector.preview_queue_overwrites,
                sdk_resets=detector.sdk_resets, raw_timing=json.dumps(raw_timing, ensure_ascii=False),
                example_saved=item['save_example'], error='')
            if item['save_example']:
                _write_png(output/'examples'/f'{stem}_raw.png', image)
                overlay = image.copy()
                contours, _ = cv2.findContours(result.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(overlay, contours, -1, (40, 190, 20), 2)
                _write_png(output/'examples'/f'{stem}_overlay.png', overlay)
            report['predictions'].append(record)
            print(f'whole-chip replay: {number + 1}/63; {result.backend}; batch {result.batch_size}; '
                  f'{result.tile_count} tiles; {result.processing_ms:.1f} ms', flush=True)
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if detector is not None:
            detector.stop()
            # Inference and asynchronous journals must finish before return.
            detector.worker.join()
            try:
                report['session'] = read_json(output/'session/manifest.json')
            except (OSError, ValueError) as exc:
                report['session'] = dict(error=f'journal sealing failed: {exc}')
            if report['session'].get('error') or report['session'].get('log_error'):
                report['status'] = 'failed'
                report['error'] = report['error'] or 'worker/journal failed while closing'
        after = _snapshot(protected, tolerate_errors=True)
        changed = [path for path, digest in protected.items() if after[path] != digest]
        report['input_sha256_after'] = after
        report['input_changes'] = changed
        report['read_only_inputs_verified'] = not changed
        if changed:
            report['status'] = 'failed'; report['error'] = 'protected input changed'
        report['successful_predictions'] = len(report['predictions'])
        report['roi_parity_samples'] = len(report['roi_parity'])
        report['batch_mismatches'] = report['batch_audit'].get('different_pixels')
        write_rows(output/'predictions.csv', report['predictions'], ('source_frame_id',))
        write_rows(output/'source_selection.csv', selection)
        report['output_sha256'] = {path.relative_to(output).as_posix(): sha256(path)
                                  for path in output.rglob('*') if path.is_file() and path.name != 'verification.json'}
        write_json(output/'verification.json', report)
    if report['status'] != 'passed':
        raise RuntimeError(report['error'])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'roi-root', 'reference-preview', 'inventory', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    args = parser.parse_args(argv)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    report = run_verification(args.package, args.roi_root, args.reference_preview,
                              args.inventory, args.output, args.device)
    print(json.dumps({key: report[key] for key in ('status', 'successful_predictions',
                     'roi_parity_samples', 'batch_mismatches', 'backend',
                     'read_only_inputs_verified', 'camera_acceptance')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
