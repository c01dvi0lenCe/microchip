"""Read-only video timing and draft centroid measurement; never arrival GT.

No simulation/control imports. Unknown device ticks remain raw. The fixed ROI
and approximate grid scale are inherited from the reviewed segmentation Pilot.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHAPTER = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
PILOT = CHAPTER/'真实分割研究/2026-10-21_第一阶段与Pilot_v1'
SNAPSHOT = CHAPTER/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot'
DEFAULT_OUT = CHAPTER/'真实分割研究/2026-10-28_视频时间与迁移速度核查_v1'
VIDEO_ID = 'camera_20261014_112318_257662'


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def audit_timing(rows, fps, frame_count):
    if not math.isfinite(fps) or fps <= 0 or len(rows) != frame_count or len(rows) < 2:
        raise ValueError('positive fps and complete timestamp index required')
    ids = [int(r['video_frame_index']) for r in rows]
    times = np.array([float(r['receive_relative_s']) for r in rows])
    sdk = np.array([int(r['sdk_frame_number']) for r in rows], dtype=np.int64)
    if ids != list(range(frame_count)) or not np.isfinite(times).all():
        raise ValueError('invalid video frame index or receive time')
    if np.any(np.diff(times) <= 0) or np.any(np.diff(sdk) <= 0):
        raise ValueError('non-increasing time or SDK identity')
    elapsed = float(times[-1]-times[0])
    container_elapsed = (frame_count-1)/fps
    return dict(saved_frames=frame_count, container_fps=fps,
                container_first_to_last_s=container_elapsed,
                host_receive_duration_s=elapsed,
                host_receive_saved_fps=(frame_count-1)/elapsed,
                playback_speedup_vs_receive=elapsed/container_elapsed,
                receive_interval_p50_s=float(np.median(np.diff(times))),
                receive_interval_p95_s=float(np.percentile(np.diff(times), 95)),
                sdk_missing_between_saved_frames=int(np.sum(np.diff(sdk)-1)),
                timestamp_source='host_receive_perf_counter',
                exposure_timing_verified=False, device_tick_unit='unknown_not_converted')


def interval_measurement(points, start, end, fps, pitch_px, pitch_mm):
    by_frame = {int(r['frame_id']): r for r in points}
    if start >= end or start not in by_frame or end not in by_frame:
        raise ValueError('ordered existing endpoints required')
    a, b = by_frame[start], by_frame[end]
    try:
        values = [float(a[k]) for k in ('receive_s', 'x_px', 'y_px')]
        values += [float(b[k]) for k in ('receive_s', 'x_px', 'y_px')]
    except (TypeError, ValueError) as exc:
        raise ValueError('valid endpoint detections required') from exc
    if not all(math.isfinite(v) for v in values) or min(*pitch_px, pitch_mm, fps) <= 0:
        raise ValueError('finite detections and positive scales required')
    dt = values[3]-values[0]
    if dt <= 0:
        raise ValueError('positive elapsed receive time required')
    dx = (values[4]-values[1])/pitch_px[0]
    dy = (values[5]-values[2])/pitch_px[1]
    displacement = math.hypot(dx, dy)
    return dict(start_frame=start, end_frame=end, receive_duration_s=dt,
                container_duration_s=(end-start)/fps, displacement_pitch=displacement,
                approximate_displacement_mm=displacement*pitch_mm,
                approx_chord_speed_mm_s=displacement*pitch_mm/dt,
                equivalent_one_pitch_time_s=dt/displacement if displacement else None,
                measurement_status='rough_unreviewed_centroid_not_arrival_gt')


def save_csv(path, rows):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_image(path, image):
    cv2.imencode('.png', image)[1].tofile(str(path))


def measure(output):
    from dmf.segmentation_research.baselines import ThresholdBaseline
    from dmf.vision.contracts import FramePacket

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    inventory = read_csv(PILOT/'video_inventory.csv')
    hash_checks = []
    for entry in inventory:
        actual = sha(entry['source'])
        if actual != entry['sha256']:
            raise ValueError('source video hash mismatch: '+entry['video_id'])
        hash_checks.append(dict(video_id=entry['video_id'], path=entry['source'],
                                sha256=actual, matches_previous_inventory=True))
    video = next(v for v in inventory if v['video_id'] == VIDEO_ID)
    source = Path(video['source'])
    sidecar = source.with_suffix('.timestamps.csv')
    times = read_csv(sidecar)
    cap = cv2.VideoCapture(str(source))
    fps, count = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    timing = audit_timing(times, fps, count)
    start, end = 630, 810
    roi = (1566, 2760, 570, 336)
    x, y, w, h = roi
    algorithms = {name: ThresholdBaseline(name) for name in ('otsu', 'adaptive')}
    for name in ('frames', 'masks_otsu', 'masks_adaptive'):
        (output/name).mkdir()
    reviewed = {int(r['source_frame_id']): r for r in read_csv(SNAPSHOT/'samples.csv')
                if r['parent_video_id'] == VIDEO_ID}
    quality, rows, previews = [], [], []
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    try:
        for frame_id in range(start, end+1):
            ok, image = cap.read()
            if not ok:
                raise ValueError(f'cannot decode frame {frame_id}')
            crop = image[y:y+h, x:x+w].copy()
            if crop.shape != (h, w, 3):
                raise ValueError('ROI outside image domain')
            save_image(output/'frames'/f'{frame_id:04d}.png', crop)
            receive = float(times[frame_id]['receive_relative_s'])
            packet = FramePacket(VIDEO_ID, frame_id, receive, 'host_receive_perf_counter', crop)
            results = {name: algo.process(packet) for name, algo in algorithms.items()}
            result = results['otsu']
            cx, cy = result.centroid_px if result.detected else (None, None)
            acx, acy = results['adaptive'].centroid_px if results['adaptive'].detected else (None, None)
            row = dict(frame_id=frame_id, receive_s=receive, container_s=frame_id/fps,
                       sdk_frame_number=times[frame_id]['sdk_frame_number'],
                       detected=result.detected, x_px=cx, y_px=cy, area_px=result.area_px,
                       adaptive_detected=results['adaptive'].detected,
                       adaptive_x_px=acx, adaptive_y_px=acy, mask_reviewed=False,
                       coordinate_domain='roi_local_px', roi_x=x, roi_y=y)
            rows.append(row)
            for name, res in results.items():
                mask = res.mask if res.mask is not None else np.zeros((h, w), np.uint8)
                save_image(output/f'masks_{name}'/f'{frame_id:04d}.png', mask)
            if frame_id in reviewed:
                r = reviewed[frame_id]
                p = SNAPSHOT/r['mask_path']
                if sha(p) != r['mask_path_sha256']:
                    raise ValueError('reviewed mask changed')
                gt = cv2.imdecode(np.fromfile(p, np.uint8), 0)
                ys, xs = np.nonzero(gt)
                for name, res in results.items():
                    error = math.dist(res.centroid_px, (float(xs.mean()), float(ys.mean()))) if res.detected else None
                    quality.append(dict(frame_id=frame_id, method=name,
                                        reviewed_centroid_error_px=error,
                                        role='selected_pilot_sanity_check_not_formal_evaluation'))
            if frame_id % 10 == 0 or frame_id == end:
                panel = crop.copy()
                contours, _ = cv2.findContours((result.mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(panel, contours, -1, (170, 220, 0), 2)
                if result.detected:
                    cv2.drawMarker(panel, (round(cx), round(cy)), (255, 255, 255), cv2.MARKER_CROSS, 14, 2)
                panel = cv2.copyMakeBorder(panel, 34, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255,255,255))
                cv2.putText(panel, f'Frame {frame_id} | receive {receive:.2f} s', (10,24), cv2.FONT_HERSHEY_SIMPLEX, .65, (40,40,40), 1, cv2.LINE_AA)
                previews.append(panel)
    finally:
        cap.release()
    save_csv(output/'draft_centroids.csv', rows)
    save_csv(output/'reviewed_mask_sanity.csv', quality)
    # A raw-image inspection sheet, not a scientific performance figure.
    while len(previews) % 3:
        previews.append(np.full_like(previews[0], 255))
    sheet = np.vstack([np.hstack(previews[i:i+3]) for i in range(0,len(previews),3)])
    save_image(output/'draft_tracking_contact_sheet.png', sheet)
    manifest = dict(schema='video_speed_readonly_check_v1', simulation=False,
                    source_video=str(source), source_sha256=sha(source),
                    timestamps_path=str(sidecar), timestamps_sha256=sha(sidecar),
                    all_video_hash_checks=hash_checks, timing=timing,
                    frame_window=[start,end], roi_xywh=roi, coordinate_domain='roi_local_px',
                    approximate_grid_pitch_px=[118.,119.], nominal_design_pitch_mm=3.2,
                    homography_used=False, physical_calibration_verified=False,
                    draft_algorithms={name: algo.configuration() for name,algo in algorithms.items()},
                    frames=len(rows), missing_otsu=sum(not r['detected'] for r in rows),
                    automated_masks_are_reviewed_gt=False, arrival_gt_created=False,
                    simulation_parameters_modified=False,
                    code_sha256=sha(__file__),
                    limits=['Host receive time is not exposure time.',
                            'Grid scale is extrapolated and not a validated video registration.',
                            'Automatic masks are draft measurement, not manual GT.',
                            'No verified electrode IDs or activation-response latency.',
                            'One acquisition group; not a population speed distribution.'])
    manifest['files'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(timing=timing, frames=len(rows), missing=manifest['missing_otsu']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    measure(parser.parse_args().output)
