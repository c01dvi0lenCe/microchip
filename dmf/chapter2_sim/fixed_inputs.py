"""Teacher-forced synthetic inputs and separately stored physical references."""
from dataclasses import asdict
import json
from pathlib import Path

from .geometry import SimulationMap
from .vision import SyntheticCamera
from .world import DropletWorld
from .formal_adapter import state_config
from dmf.experiment.mask_cache import write_cache


def generate_fixed_input(cfg, scenario, seed, output, *, step_duration_s=4.):
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    if step_duration_s <= cfg.ack_delay_s: raise ValueError('step window too short')
    steps = len(cfg.route)-1
    if steps*step_duration_s > cfg.max_time_s: raise ValueError('task schedule exceeds simulated horizon')
    geometry = SimulationMap(cfg); world = DropletWorld(cfg, geometry, scenario, seed)
    camera = SyntheticCamera(cfg, geometry, seed, scenario)
    tasks = [dict(step_id=i, source=cfg.route[i], target=cfg.route[i+1],
                  start_s=i*step_duration_s, end_s=(i+1)*step_duration_s,
                  applied_s=i*step_duration_s+cfg.ack_delay_s) for i in range(steps)]
    frames = []; truth = []; arrival = {}; commanded = set(); frame_id = 0
    horizon = steps*step_duration_s
    for tick in range(int(round(horizon/cfg.dt_s))+1):
        now = min(horizon, tick*cfg.dt_s)
        world.advance(now)
        index = min(int(now/step_duration_s), steps-1)
        task = tasks[index]
        if index not in commanded:
            world.command(task['target'], now, 'Start'); commanded.add(index)
        if now >= task['applied_s'] and index not in arrival and world.is_physically_settled(task['target']):
            arrival[index] = now
        truth.append(dict(time_s=now, step_id=index, x=float(world.position[0]), y=float(world.position[1]),
                          true_speed=float((world.velocity@world.velocity)**.5),
                          physically_arrived=index in arrival))
        while frame_id/cfg.camera_fps+cfg.exposure_s <= now+1e-9:
            frame = camera.expose(frame_id, frame_id/cfg.camera_fps, world.position); frame_id += 1
            frames.append(dict(frame_id=frame.frame_id, exposure_start_s=frame.exposure_start_s,
                               exposure_s=frame.exposure_end_s, available_s=frame.available_s,
                               mask=frame.mask, confidence=1. if frame.mask is not None else 0.))
    snapshot = geometry.snapshot()
    snapshot.update(lower=geometry.lower.tolist(), scale=geometry.scale, shape=[int(v) for v in geometry.shape])
    params = asdict(state_config(cfg)); params['centroid_tolerance'] = cfg.position_tolerance
    cache = write_cache(output/'inputs', map_snapshot=snapshot, tasks=tasks, parameters=params,
                        frames=frames, clock_domain='simulation', coordinate_unit='pitch')
    evaluation = output/'evaluation'; evaluation.mkdir()
    trial_id = f'{scenario}:{seed}'
    refs = []
    for task in tasks:
        t = arrival.get(task['step_id'])
        refs.append(dict(trial_id=trial_id, task_id='teacher_forced_route', step_id=task['step_id'],
                         input_sha256=cache['input_sha256'],
                         clock_domain='simulation', simulation=True, annotation_source='simulation_physics',
                         provenance='independent physical basin, true speed and dwell; integration-grid interval',
                         status='arrived' if t is not None else 'not_arrived',
                         observation_start_s=task['start_s'], observation_end_s=task['end_s'],
                         arrival_lower_s=max(task['applied_s'], t-cfg.dt_s) if t is not None else None,
                         arrival_upper_s=t))
    manifest = [dict(trial_id=trial_id, task_id='teacher_forced_route', clock_domain='simulation',
                     input_sha256=cache['input_sha256'], simulation=True, eligible=True,
                     step_ids=[t['step_id'] for t in tasks])]
    def save(name, value):
        (evaluation/name).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    save('references.json', refs); save('trial_manifest.json', manifest)
    save('truth.json', truth)
    save('generation.json', dict(simulation=True, scenario=scenario, seed=seed, config=asdict(cfg),
                                 step_duration_s=step_duration_s, input_sha256=cache['input_sha256'],
                                 sample_quantization_bound_s=cfg.dt_s))
    return dict(input_sha256=cache['input_sha256'], trial_id=trial_id, planned_steps=steps,
                n_frames=len(frames))
