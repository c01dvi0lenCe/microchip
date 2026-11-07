"""Common saved observation cache and realized perturbation diagnostics."""
import math
from pathlib import Path
import hashlib
import json
import cv2
import numpy as np
from ..observation import CameraFrame, extract_features
from ..single_step import write_csv


def tf_episode(permanent_stall_started_s, frames, config):
    if not math.isfinite(permanent_stall_started_s) or type(frames) is not int or frames <= 0:
        raise ValueError('Finite stall time and positive integer frame count required')
    fps = config['time']['camera_fps']
    start_frame = math.ceil((permanent_stall_started_s+config['TF_revision']['fixed_offset_s'])*fps-1e-9)
    end_frame = start_frame+frames-1
    if end_frame >= 200:
        raise ValueError('Declared entire TF episode does not fit in capture horizon; no redraw')
    return dict(start_s=round(start_frame/fps, 10), end_s=round(end_frame/fps, 10), frame_count=frames)


def perturb_mask(condition, mask, target_template, parameters, spatial, scale, axis, in_episode):
    result = mask.copy()
    if not in_episode: return result
    if condition in ('F', 'TF'): return target_template.copy()
    p = parameters
    displacement = np.zeros(2)
    if condition == 'J': displacement = (2*np.asarray(spatial)-1)*p['jitter_amplitude_mm']
    if condition == 'O': displacement = p['bias_magnitude_mm']*np.array([math.cos(p['bias_angle_rad']), math.sin(p['bias_angle_rad'])])
    if displacement.any():
        pixels = np.rint(displacement*scale).astype(int)
        result = cv2.warpAffine(result, np.array([[1., 0., pixels[0]], [0., 1., pixels[1]]]),
            result.shape[::-1], flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    ys, xs = np.nonzero(result)
    if len(xs) and condition == 'C':
        # The 190->191 axis is horizontal; retain a direction-aware rear crop.
        if abs(axis[0]) >= abs(axis[1]):
            count = int(math.floor(p['rear_cut_fraction']*(xs.max()-xs.min()+1)))
            if axis[0] >= 0: result[:, :xs.min()+count] = 0
            else: result[:, xs.max()-count+1:] = 0
        else:
            count = int(math.floor(p['rear_cut_fraction']*(ys.max()-ys.min()+1)))
            if axis[1] >= 0: result[:ys.min()+count, :] = 0
            else: result[ys.max()-count+1:, :] = 0
    if len(xs) and condition == 'R':
        start = int(round(float(ys.mean()))); result[start:start+p['fragment_band_pixels'], :] = 0
    return result


def plan_delivery(condition, frame_id, capture_s, parameters, drop_uniform, delay_uniform, applied_s, horizon=10.):
    post = capture_s >= applied_s-1e-10
    if condition == 'D' and post and drop_uniform < parameters['drop_probability']: return []
    extra = 0.
    if condition == 'L' and post and delay_uniform[0] < parameters['delay_probability']:
        low, high = parameters['extra_delay_range_s']; extra = low+delay_uniform[1]*(high-low)
    available = round(capture_s+.048+extra, 12)
    processed = round(math.ceil(available/.01-1e-9)*.01, 10)
    return [dict(frame_id=frame_id, available_s=available, processed_s=processed,
                 extra_delivery_delay_s=extra, pending_at_H=processed > horizon+1e-9,
                 old_context=False, duplicate_delivery=False)]


def _json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def create_cache(folder, world, raster, observation, config, context, target_template):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False); (folder/'masks').mkdir()
    condition = observation['condition']; p = observation['parameters']; arrays = observation['arrays']
    applied = context.applied_timestamp_s; rows = world['rows']; fps = config['time']['camera_fps']
    start = end = None; stall = world['manifest']['permanent_stall_started_s']
    if condition == 'TF':
        episode = tf_episode(stall, p['stall_false_frames'], config); start = episode['start_s']; end = episode['end_s']
    elif condition in ('J', 'O', 'C', 'R', 'F'):
        threshold = p['false_start_progress'] if condition == 'F' else p['start_progress']
        candidates = [i for i in range(200) if rows[i*5]['progress'] >= threshold]
        if not candidates: raise ValueError('Episode progress not reached; no redraw')
        start = candidates[0]/fps
        end = start+(p['false_frames']-1)/fps if condition == 'F' else start+p['duration_s']
    axis = raster.geometry.center(191)-raster.geometry.center(190)
    captures = []; deliveries = []; frames = {}; features_by_id = {}
    for frame_id in range(200):
        t = round(frame_id/fps, 10); original = raster.mask(world['polygons'][frame_id*5])
        inside = start is not None and start-1e-9 <= t <= end+1e-9
        mask = perturb_mask(condition, original, target_template, p, arrays['spatial_uniform'][frame_id], raster.scale, axis, inside)
        path = folder/'masks'/f'{frame_id:04d}.png'; path.write_bytes(cv2.imencode('.png', mask)[1].tobytes())
        plans = plan_delivery(condition, frame_id, t, p, arrays['drop_uniform'][frame_id],
            arrays['delay_probability_and_magnitude_uniform'][frame_id], applied, config['time']['horizon_s'])
        available = plans[0]['available_s'] if plans else round(t+.048, 12)
        processed = plans[0]['processed_s'] if plans else round(t+.05, 10)
        frame = CameraFrame(frame_id, t, t+.008, available, mask, context if t >= applied-1e-10 else None, processed)
        features = extract_features(frame, raster, 190, 191)
        false = inside and condition in ('F', 'TF')
        captures.append(dict(frame_id=frame_id, exposure_start_s=t, exposure_end_s=t+.008,
            available_s=available, captured_epoch=frame.context.epoch if frame.context else None,
            mask_path=path.relative_to(folder).as_posix(), mask_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            changed_pixels=int(np.count_nonzero(mask != original)), actual_area_change_px=int(np.count_nonzero(mask))-int(np.count_nonzero(original)),
            episode_active=inside, false_target=bool(false), during_permanent_stall=bool(stall is not None and t >= stall-1e-9),
            actual_outline_target_overlap_mm2=world['polygons'][frame_id*5].intersection(raster.geometry.polygons[191]).area,
            delivered=bool(plans), **features))
        frames[frame_id] = frame; features_by_id[frame_id] = features; deliveries.extend(plans)
    deliveries.sort(key=lambda d: (d['processed_s'], d['frame_id']))
    false_rows = [r for r in captures if r['false_target']]
    manifest = dict(seed=observation['seed'], condition=condition, stratum=observation['stratum'],
        draw_stratum=observation['stratum'],
        generated_masks=200, episode_start_s=start, episode_end_s=end,
        permanent_stall_started_s=stall, false_target_start_s=false_rows[0]['exposure_start_s'] if false_rows else None,
        first_exactly_stationary_stall_tick_s=world['manifest'].get('first_exactly_stationary_stall_tick_s'),
        false_target_end_s=false_rows[-1]['exposure_start_s'] if false_rows else None, actual_false_frames=len(false_rows),
        dropped_frames=200-len(deliveries), pending_deliveries_at_H=sum(d['pending_at_H'] for d in deliveries),
        mutated_frames=sum(r['changed_pixels'] > 0 for r in captures), changed_pixels=sum(r['changed_pixels'] for r in captures),
        actual_false_target_overlap_mm2=[r['actual_outline_target_overlap_mm2'] for r in false_rows],
        synthetic_stress_not_empirical=True, no_redraw=True)
    if condition == 'TF' and (len(false_rows) != p['stall_false_frames'] or not all(r['during_permanent_stall'] for r in false_rows)):
        raise ValueError('TF episode not entirely during permanent stall')
    if condition == 'TF':
        false_ticks = [round(r['exposure_start_s']/.01) for r in false_rows]
        if any(abs(rows[i]['speed_mm_s'])>1e-10 for i in false_ticks) or len({rows[i]['progress'] for i in false_ticks})!=1:
            raise ValueError('TF requires entirely stationary constant-progress WORLD during false episode')
    write_csv(folder/'captures.csv', captures); write_csv(folder/'deliveries.csv', deliveries); _json(folder/'manifest.json', manifest)
    return dict(captures=captures, deliveries=deliveries, frames=frames, features=features_by_id, manifest=manifest)
