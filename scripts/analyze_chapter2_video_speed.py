"""Describe video transitions without declaring arrival GT or changing a model."""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.measure_chapter2_video_speed import DEFAULT_OUT, read_csv, sha


def transition_measurement(points, start, end, fps, pitch_px, pitch_mm, endpoint_window=5):
    selected = [r for r in points if start <= int(r['frame_id']) <= end]
    if [int(r['frame_id']) for r in selected] != list(range(start, end+1)):
        raise ValueError('complete ordered measurement interval required')
    if endpoint_window < 2 or len(selected) < 2*endpoint_window+2:
        raise ValueError('nonoverlapping endpoint windows required')
    try:
        xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in selected])
        t = np.array([float(r['receive_s']) for r in selected])
    except (TypeError, ValueError) as exc:
        raise ValueError('missing detections cannot be bridged') from exc
    scales = np.array(pitch_px, dtype=float)
    if (not np.isfinite(xy).all() or not np.isfinite(t).all() or np.any(np.diff(t) <= 0)
            or not np.isfinite(scales).all() or np.any(scales <= 0)
            or not math.isfinite(pitch_mm) or pitch_mm <= 0 or not math.isfinite(fps) or fps <= 0):
        raise ValueError('finite positions and strictly increasing time required')
    xy = xy/scales
    a = np.median(xy[:endpoint_window], axis=0)
    b = np.median(xy[-endpoint_window:], axis=0)
    vector = b-a
    length = float(np.linalg.norm(vector))
    if length < .2:
        raise ValueError('endpoint displacement too small for transition description')
    progress = (xy-a)@vector/(length**2)
    indices = []
    for threshold in (.1, .9):
        candidates = np.flatnonzero((progress[:-1] < threshold) & (progress[1:] >= threshold))
        if not len(candidates):
            raise ValueError('no observed crossing bracket')
        indices.append(int(candidates[0])+1)
    lo, hi = indices
    if lo >= hi:
        raise ValueError('both crossings unresolved within one sample')
    dt_bounds = [float(t[hi-1]-t[lo]), float(t[hi]-t[lo-1])]
    if dt_bounds[0] <= 0:
        raise ValueError('time resolution insufficient')
    distance = .8*length*pitch_mm
    return dict(start_frame=start, end_frame=end, endpoint_window_frames=endpoint_window,
                endpoint_displacement_pitch=length,
                crossing_10_frame_bracket=[int(selected[lo-1]['frame_id']), int(selected[lo]['frame_id'])],
                crossing_90_frame_bracket=[int(selected[hi-1]['frame_id']), int(selected[hi]['frame_id'])],
                duration_10_90_bounds_s=dt_bounds,
                container_duration_10_90_bounds_s=[(hi-1-lo)/fps, (hi-lo+1)/fps],
                progress_distance_10_90_mm=distance,
                approx_average_progress_speed_bounds_mm_s=[distance/dt_bounds[1], distance/dt_bounds[0]],
                equivalent_one_pitch_time_bounds_s=[dt_bounds[0]/(.8*length), dt_bounds[1]/(.8*length)],
                timing_bounds_are_sampling_brackets_not_confidence_intervals=True,
                role='descriptive_transition_not_target_arrival_or_independent_trial')


def minimum_jerk_conversion(distance_mm, peak_mm_s):
    if not all(math.isfinite(v) and v > 0 for v in (distance_mm, peak_mm_s)):
        raise ValueError('positive finite distance and peak speed required')
    def inverse_q(value):
        lo, hi = 0., 1.
        for _ in range(70):
            mid = (lo+hi)/2
            q = 10*mid**3-15*mid**4+6*mid**5
            if q < value:
                lo = mid
            else:
                hi = mid
        return (lo+hi)/2
    a, b = inverse_q(.1), inverse_q(.9)
    duration = 1.875*distance_mm/peak_mm_s
    return dict(u10=a, u90=b, motion_duration_s=duration,
                duration_10_90_s=(b-a)*duration,
                mean_progress_speed_10_90_mm_s=.8*distance_mm/((b-a)*duration),
                total_mean_speed_mm_s=distance_mm/duration,
                peak_speed_mm_s=peak_mm_s)


def analyze(root, output_name='analysis_r2_same_metric'):
    root = Path(root)
    output = root/output_name
    output.mkdir(exist_ok=False)
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        if sha(root/name) != digest:
            raise ValueError('persisted measurement changed: '+name)
    if sha(ROOT/'scripts/measure_chapter2_video_speed.py') != manifest['code_sha256']:
        raise ValueError('capture measurement source differs from manifest')
    rows = read_csv(root/'draft_centroids.csv')
    fps = manifest['timing']['container_fps']
    # Visually inspected windows: two opposite monotonic directions in the fixed
    # 630–810 inspection range. They are not predeclared electrode arrival trials.
    windows = [(665,715), (715,780)]
    results = []
    for a,b in windows:
        for method in ('otsu','adaptive'):
            points = [dict(frame_id=int(r['frame_id']), receive_s=float(r['receive_s']),
                           x_px=r['x_px'] if method=='otsu' else r['adaptive_x_px'],
                           y_px=r['y_px'] if method=='otsu' else r['adaptive_y_px']) for r in rows]
            result = transition_measurement(points,a,b,fps,(118.,119.),3.2)
            results.append(dict(method=method, **result))
    (output/'transition_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    conversion = minimum_jerk_conversion(3.2, 1.4)
    factor = minimum_jerk_conversion(3.2, 1.)['mean_progress_speed_10_90_mm_s']
    observed = [v for r in results for v in r['approx_average_progress_speed_bounds_mm_s']]
    proposed = dict(status='proposed_not_applied_not_physically_calibrated',
                    model='same minimum-jerk shape; new version only if later approved',
                    nominal_peak_speed_mm_s=1.4,
                    nominal_3_2mm_motion_duration_s=conversion['motion_duration_s'],
                    nominal_average_speed_mm_s=conversion['total_mean_speed_mm_s'],
                    comparable_10_90_progress=conversion,
                    rough_peak_range_from_same_metric_mm_s=[min(observed)/factor,max(observed)/factor],
                    basis='Match same10–90% progress speed, not overall mean to peak; approximate range, not CI or fit.',
                    recommended_future_recording_duration_s=6.0,
                    supersedes='analysis/proposed_speed_not_applied.json: provisional2.0 lacked same-metric conversion',
                    old_4_8mm_s_trial_modified=False,
                    not_a_final_calibration=True)
    (output/'proposed_speed_not_applied.json').write_text(json.dumps(proposed,ensure_ascii=False,indent=2),encoding='utf-8')
    index = dict(source_manifest_sha256=sha(root/'manifest.json'),
                 analysis_source_sha256=sha(__file__), results=results,
                 selection='visual inspection of all fixed630–810 frames; descriptive only; no target IDs',
                 proposed_configuration=proposed,
                 limitation='Sampling brackets omit uncertain receive-to-exposure delay, grid scale and centroid bias.',
                 files={p.name:sha(p) for p in output.iterdir() if p.is_file()})
    (output/'analysis_manifest.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=DEFAULT_OUT)
    p.add_argument('--output-name',default='analysis_r2_same_metric')
    args = p.parse_args()
    if Path(args.output_name).name != args.output_name:
        raise ValueError('output name must be a single directory name')
    analyze(args.root,args.output_name)
