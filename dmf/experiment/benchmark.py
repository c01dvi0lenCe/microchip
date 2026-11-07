"""GT-blind arrival-event baselines over one immutable mask cache."""
import csv
from dataclasses import fields, replace
import json
import math
from pathlib import Path

import cv2
import numpy as np

from dmf.vision.contracts import FramePacket, FrameTiming, VisionResult, DropletState
from .config import StateConfig, typed_config
from .evidence import StepContext, FrameCausalityGuard, ArrivalEvent, ArrivalEventLedger
from .mask_cache import load_cache
from .perception import PriorFeatures, StateRecognizer, Observation

VARIANTS = ('S1', 'S2', 'S3', 'S4', 'no_spatial', 'no_temporal', 'no_validity')


def _write_rows(path, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row)) or ['step_id', 'timestamp_s']
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, keys); writer.writeheader(); writer.writerows(rows)


def run_variant(cache_dir, variant, output_dir):
    """No reference/GT argument or evaluator import is permitted at this seam."""
    if variant not in VARIANTS: raise ValueError('unknown baseline')
    output_dir = Path(output_dir)
    if output_dir.exists(): raise FileExistsError(output_dir)
    cache = load_cache(cache_dir)
    # Lazy import keeps the cache contract independent of simulation execution.
    from dmf.chapter2_sim.formal_adapter import NormalizedMap, make_frame_packet
    from dmf.chapter2_sim.vision import SyntheticFrame
    geometry = NormalizedMap.from_snapshot(cache['map'])
    values = {k: v for k, v in cache['parameters'].items() if k in {f.name for f in fields(StateConfig)}}
    cfg = typed_config(StateConfig, values)
    if variant == 'no_temporal': cfg = replace(cfg, arrival_frames=1, arrival_duration_s=0.)
    prior = PriorFeatures(geometry, cfg, spatial_prior=variant != 'no_spatial',
                          temporal_prior=variant in {'S4', 'no_spatial', 'no_validity'},
                          quality_checks=variant in {'S4', 'no_spatial', 'no_temporal'})
    recognizer = StateRecognizer(cfg); guard = FrameCausalityGuard(); ledger = ArrivalEventLedger()
    active = None; context = None; emitted = set(); events = []; rows = []
    for row in sorted(cache['frames'], key=lambda r: (r['available_s'], r['frame_id'])):
        now = row['available_s']
        task = next((t for t in cache['tasks'] if t['start_s'] <= now < t['end_s']), None)
        report = dict(frame_id=row['frame_id'], timestamp_s=now, exposure_s=row['exposure_s'],
                      mask_available=row['mask'] is not None,
                      step_id=task['step_id'] if task else '', state='', valid=False,
                      observation_quality='missing', arrived=False, reason='OUTSIDE_TASK',
                      eta_source=None, eta_target=None, rho_target=None, distance=None,
                      progress=None, lateral_error=None, velocity=None)
        if task is None:
            rows.append(report); continue
        if task['step_id'] != active:
            active = task['step_id']; prior.reset(); recognizer.reset()
            context = StepContext(cache['input_sha256'], active, 0, active, task['source'], task['target'],
                                  clock_domain=cache['clock_domain'], applied_timestamp_s=task['applied_s'],
                                  applied_time_quality='simulation' if cache['clock_domain']=='simulation' else 'offline_replay')
            ledger.activate(context)
        mask = row['mask']; centroid = None
        if mask is not None:
            m = cv2.moments(mask, binaryImage=True)
            if m['m00']: centroid = (m['m10']/m['m00'], m['m01']/m['m00'])
        synthetic = SyntheticFrame(row['frame_id'], row.get('exposure_start_s', row['exposure_s']),
                                   row['exposure_s'], now, mask, mask is None)
        if cache['clock_domain'] == 'simulation':
            packet = make_frame_packet(synthetic, video_id=row.get('video_id', 'cache'), task_epoch=active, shape=cache['map']['shape'])
        else:
            packet = FramePacket(row.get('video_id', 'cache'), row['frame_id'], row['exposure_s'], 'video_pts',
                                 np.zeros((*cache['map']['shape'], 3), np.uint8),
                                 FrameTiming(capture_frame_id=row['frame_id'], clock_domain='video_relative', task_epoch=active))
        result = VisionResult(mask, centroid, float(np.count_nonzero(mask)) if mask is not None else None,
                              row['confidence'], max(0., (now-row['exposure_s'])*1000), centroid is not None,
                              'MISSING_MASK' if mask is None else '')
        causal = guard.check(packet, context, mode='simulation' if cache['clock_domain']=='simulation' else 'offline')
        full = variant in {'S4', 'no_spatial', 'no_temporal', 'no_validity'}
        obs = prior.extract(packet, result, task['source'], task['target'], []) if causal.accepted or not full else Observation(error=causal.reason)
        arrived = False; state = None
        if full:
            state = recognizer.recognize(obs, packet.timestamp_s, packet.capture_identity, context)
            arrived = state is DropletState.ARRIVED
            reason = recognizer.last_reason
        else:
            reason = 'SINGLE_FRAME'
            if centroid is not None:
                point = geometry.calibration.pixel_to_mm(centroid)
                if variant == 'S1':
                    arrived = math.dist(point, geometry[task['target']].center_mm) <= cache['parameters'].get('centroid_tolerance', .18)
                elif variant == 'S2':
                    arrived = (obs.eta_target is not None and obs.eta_target >= cfg.eta_arr
                               and obs.eta_source <= cfg.eta_release)
                else:
                    arrived = (obs.valid and obs.spatial_ok and obs.target_position_ok is not False
                               and obs.eta_target is not None and obs.eta_target >= cfg.eta_arr
                               and obs.eta_source <= cfg.eta_release)
        report.update(state=state.value if state else '', valid=obs.valid,
                      observation_quality=obs.observation_quality, arrived=arrived, reason=reason,
                      eta_source=obs.eta_source, eta_target=obs.eta_target, rho_target=obs.rho_target,
                      distance=obs.distance, progress=obs.progress_mm, lateral_error=obs.lateral_error_mm,
                      velocity=obs.velocity)
        if arrived and active not in emitted:
            event = None
            if full:
                event = ArrivalEvent.from_window(context, recognizer.window, None, cache['clock_domain'], causal.causality)
                if not ledger.consume(event):
                    rows.append(report); continue
            emitted.add(active)
            events.append(dict(step_id=active, timestamp_s=now, exposure_s=packet.timestamp_s,
                               action='Update', clock_domain=cache['clock_domain'],
                               event_id=event.event_id if event else f'{variant}:{active}',
                               causality=causal.causality if full else 'not_enforced_single_frame'))
        rows.append(report)
    summary = dict(schema='chapter2_arrival_baseline_v1', variant=variant,
                   method_version=f'{variant}_mask_cache_v1', input_sha256=cache['input_sha256'],
                   clock_domain=cache['clock_domain'], coordinate_unit=cache['coordinate_unit'],
                   simulation=cache['clock_domain']=='simulation', planned_steps=len(cache['tasks']),
                   frames=rows, events=events)
    output_dir.mkdir(parents=True)
    _write_rows(output_dir/'frames.csv', rows); _write_rows(output_dir/'events.csv', events)
    (output_dir/'prediction.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    return summary


def check_real_materials(*, model_path=None, human_reference_path=None, calibrated_map_path=None):
    """Report prerequisites, without substituting simulation for real validation."""
    requirements = dict(unet_model=model_path, reviewed_human_arrival_intervals=human_reference_path,
                        independently_validated_map=calibrated_map_path)
    return dict(ready=all(value and Path(value).is_file() for value in requirements.values()),
                missing=[key for key, value in requirements.items() if not value or not Path(value).is_file()],
                note='File presence only; model, annotations and calibration still require content validation.')
