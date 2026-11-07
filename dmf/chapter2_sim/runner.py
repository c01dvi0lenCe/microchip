"""Closed synthetic loop. Only this evaluator sees hidden physical truth."""
from dataclasses import dataclass
import heapq

import numpy as np

from .control import EventPolicy, Recognizer
from .geometry import SimulationMap
from .vision import FeatureExtractor, SyntheticCamera
from .world import DropletWorld


@dataclass
class TrialResult:
    metrics: dict
    frames: list
    truth: list
    events: list


def run_trial(config, scenario, seed, method):
    cfg = config
    geometry = SimulationMap(cfg)
    world = DropletWorld(cfg, geometry, scenario, seed)
    camera = SyntheticCamera(cfg, geometry, seed, scenario)
    extractor, recognizer = FeatureExtractor(cfg, geometry), Recognizer(cfg)
    policy = EventPolicy(cfg, method)
    frames, truth, events = [], [], []
    queue = []
    frame_id = 0
    last_frame_id = -1
    early = confirmed = 0
    delays = []
    physical_arrival = None
    status = 'time_limit'
    steps = len(cfg.route)-1
    common = dict(simulation=True, scenario=scenario, seed=seed, method=method)

    def send(action, target, now):
        nonlocal last_frame_id
        applied = world.command(target, now, action)
        policy.command_started(now, applied)
        recognizer.reset()
        extractor.reset()
        events.append(dict(common, event=action, time_s=now, target=target,
                           step=policy.step, epoch=policy.epoch, applied_s=applied))
        return applied

    send('Start', cfg.route[1], 0.)
    for tick in range(int(np.ceil(cfg.max_time_s/cfg.dt_s))+1):
        now = min(cfg.max_time_s, tick*cfg.dt_s)
        world.advance(now)
        source, target = cfg.route[policy.step:policy.step+2]
        if physical_arrival is None and now >= policy.applied_s and world.is_physically_settled(target):
            physical_arrival = now
            events.append(dict(common, event='TruthArrival', time_s=now, step=policy.step,
                               epoch=policy.epoch, target=target))
        truth.append(dict(common, time_s=now, step=policy.step, epoch=policy.epoch,
                          x=float(world.position[0]), y=float(world.position[1]),
                          true_speed=float(np.linalg.norm(world.velocity)), target=target,
                          physically_arrived=physical_arrival is not None))
        while frame_id/cfg.camera_fps+cfg.exposure_s <= now+1e-9:
            # Integration-grid endpoint approximation, bounded by dt_s. Exposure
            # start/end are explicit; no claim of optical motion-blur simulation.
            frame = camera.expose(frame_id, frame_id/cfg.camera_fps, world.position)
            frame_id += 1
            if frame.dropped:
                frames.append(dict(common, frame_id=frame.frame_id, exposure_s=frame.exposure_end_s,
                                   exposure_start_s=frame.exposure_start_s, available_s=frame.available_s,
                                   processing_s=None, step=policy.step, epoch=policy.epoch,
                                   valid=False, reason='CAMERA_DROPPED', state='Unknown', action='Hold'))
            else:
                heapq.heappush(queue, (frame.available_s, frame.frame_id, frame))
        decisions = []
        while queue and queue[0][0] <= now+1e-9:
            _, _, frame = heapq.heappop(queue)
            old = frame.exposure_start_s < policy.applied_s-1e-9
            duplicate = frame.frame_id <= last_frame_id
            stale = now-frame.exposure_end_s > cfg.observation_timeout_s
            reason = 'PRE_APPLIED_EXPOSURE' if old else 'OUT_OF_ORDER_FRAME' if duplicate else 'STALE_FRAME' if stale else ''
            f = dict(valid=False, reason=reason) if reason else extractor.extract(frame, target if policy.phase == 'recovering' else source,
                                                                                 source if policy.phase == 'recovering' else target)
            if reason:
                state, candidate = 'Unknown', False
                # Late frames cannot contaminate or reset a newer valid window.
                action = 'Hold'
            else:
                last_frame_id = frame.frame_id
                state, candidate = recognizer.observe(frame, f)
                action = policy.decide(now, state, candidate, f) if method != 'A' else 'Hold'
            row = dict(common, frame_id=frame.frame_id, exposure_s=frame.exposure_end_s,
                       exposure_start_s=frame.exposure_start_s, available_s=frame.available_s,
                       processing_s=now, sample_quantization_bound_s=cfg.dt_s,
                       step=policy.step, epoch=policy.epoch, source=source, target=target,
                       state=state, action=action, applied_s=policy.applied_s, **f)
            frames.append(row)
            if action != 'Hold':
                decisions.append((action, frame))
                break
        if not decisions:
            # Safety clocks continue without camera delivery. No missing frame
            # is represented as physical Deviation.
            action = policy.decide(now, 'Unknown', False, dict(valid=False))
            if action != 'Hold':
                decisions.append((action, None))
        if not decisions:
            continue
        action, frame = decisions[0]
        if action == 'Stop':
            status = 'protective_stop'
            events.append(dict(common, event='Stop', time_s=now, step=policy.step, epoch=policy.epoch))
            break
        if action == 'Update':
            is_early = physical_arrival is None
            early += int(is_early)
            confirmed += 1
            delay = None if physical_arrival is None else now-physical_arrival
            if delay is not None:
                delays.append(delay)
            final = policy.step == steps-1
            events.append(dict(common, event='Complete' if final else 'Update', time_s=now,
                               step=policy.step, epoch=policy.epoch, early=is_early,
                               true_arrival_s=physical_arrival, delay_s=delay,
                               exposure_s=None if frame is None else frame.exposure_end_s,
                               applied_s=policy.applied_s, target=target))
            if final:
                status = 'completed' if not early else 'completed_with_early_updates'
                break
            policy.advance_step()
            physical_arrival = None
            send('Start', cfg.route[policy.step+1], now)
        elif action == 'Recovery':
            send(action, source, now)
        else:
            send('Retry' if action == 'Retry' else 'Resume', target, now)
    unfinished = int(confirmed < steps)
    censored = int(bool(unfinished) and physical_arrival is not None)
    no_arrival = early + int(bool(unfinished) and physical_arrival is None)
    unattempted = max(0, steps-confirmed-unfinished)
    if unfinished:
        events.append(dict(common, event='UnconfirmedStep', time_s=now, step=policy.step,
                           epoch=policy.epoch, true_arrival_s=physical_arrival,
                           delay_censored=bool(censored)))
    metrics = dict(common, path_complete=status == 'completed' and confirmed == steps,
                   early_updates=early, transport_steps=steps, confirmed_steps=confirmed,
                   issued_updates=confirmed,
                   confirmation_delay_s=float(np.mean(delays)) if delays else None,
                   delay_observed_steps=len(delays), delay_missing_steps=steps-len(delays),
                   delay_censored_steps=censored, delay_no_arrival_steps=no_arrival,
                   delay_unattempted_steps=unattempted,
                   total_time_s=now, retries=policy.retries, recoveries=policy.recoveries,
                   status=status)
    return TrialResult(metrics, frames, truth, events)
