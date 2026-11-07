"""One fixed teacher command; original motion/camera models, explicit recording."""
from dataclasses import asdict
import math
import cv2
import numpy as np

from dmf.experiment.mask_cache import write_cache
from ..geometry import SimulationMap
from ..world import DropletWorld
from ..vision import SyntheticCamera
from ..formal_adapter import state_config
from .spec import CONDITIONS


class _RecordedWorld(DropletWorld):
    def __init__(self,*args):
        super().__init__(*args)
        self.applied_events=[]

    def _apply(self,applied,target,action):
        executed=self.time
        super()._apply(applied,target,action)
        self.applied_events.append(dict(scheduled_s=applied,executed_s=executed,
            target=target,action=action,world_active=self.active,response_at_s=self.response_at))


def generate_base(spec, seed, scenario):
    spec.validate_seed(seed)
    if scenario not in ('normal','failure'):raise ValueError('only declared base worlds allowed')
    cfg=spec.environment
    geometry=SimulationMap(cfg)
    world=_RecordedWorld(cfg,geometry,scenario,seed)
    tasks=[dict(step_id=0,source=190,target=191,start_s=0.,end_s=spec.duration_s,
                applied_s=cfg.ack_delay_s)]
    applied=world.command(191,0.,'Start')
    commands=[dict(request_s=0.,target=191,action='Start',applied_s=applied,simulation=True)]
    cameras={name:SyntheticCamera(cfg,geometry,seed,name) for name in ('normal','jitter','dropout')}
    observations={name:[] for name in cameras}
    truth=[];capture_samples=[];frame_id=0
    for tick in range(int(round(spec.duration_s/cfg.dt_s))+1):
        now=tick*cfg.dt_s;world.advance(now)
        truth.append(dict(time_s=now,step_id=0,epoch=0,source=190,target=191,
            world_active=world.active,applied_s=applied,
            response_at_s=world.response_at if math.isfinite(world.response_at) else None,
            phase='transport' if world.active==191 and now>=applied else 'pending',
            x=float(world.position[0]),y=float(world.position[1]),
            true_speed=float(np.linalg.norm(world.velocity)),
            sample_order='end_tick_before_next_interval_apply'))
        while frame_id/cfg.camera_fps+cfg.exposure_s<=now+1e-9:
            start=frame_id/cfg.camera_fps
            for name,camera in cameras.items():
                frame=camera.expose(frame_id,start,world.position)
                observations[name].append(dict(frame_id=frame_id,exposure_start_s=start,
                    exposure_s=frame.exposure_end_s,available_s=frame.available_s,
                    mask=frame.mask,confidence=1. if frame.mask is not None else 0.))
            capture_samples.append(dict(frame_id=frame_id,exposure_start_s=start,
                exposure_end_s=start+cfg.exposure_s,position_sample_s=now,
                quantization_s=now-start-cfg.exposure_s))
            frame_id+=1
    snapshot=geometry.snapshot()
    snapshot.update(lower=geometry.lower.tolist(),scale=geometry.scale,shape=list(map(int,geometry.shape)))
    base=dict(seed=seed,scenario=scenario,geometry=geometry,snapshot=snapshot,tasks=tasks,
              commands=commands,applied_events=world.applied_events,truth=truth,
              observations=observations,capture_samples=capture_samples,config=asdict(cfg))
    validate_teacher(base)
    return base


def validate_teacher(base):
    tasks=base['tasks'];truth=base['truth'];commands=base['commands'];applied=base['applied_events']
    if len(tasks)!=1 or len(commands)!=1 or len(applied)!=1:raise ValueError('single teacher transaction required')
    task=tasks[0];event=applied[0];cfg=base['config'];dt=cfg['dt_s']
    if (task['source'],task['target'],task['step_id'])!=(190,191,0):raise ValueError('unexpected fixed task')
    if commands[0]['target']!=191 or event['target']!=191:raise ValueError('teacher target mismatch')
    if abs(event['scheduled_s']-task['applied_s'])>1e-9 or abs(event['executed_s']-task['applied_s'])>1e-9:
        raise ValueError('scheduled and executed Applied differ')
    if abs(event['response_at_s']-(task['applied_s']+cfg['response_delay_s']))>1e-9:
        raise ValueError('response delay mismatch')
    if abs(truth[0]['time_s']-task['start_s'])>1e-9 or abs(truth[-1]['time_s']-task['end_s'])>1e-9:
        raise ValueError('incomplete teacher followup')
    for i,row in enumerate(truth):
        if (row['step_id'],row['source'],row['target'])!=(0,190,191):raise ValueError('truth task mismatch')
        if i and abs(row['time_s']-truth[i-1]['time_s']-dt)>1e-9:raise ValueError('truth time discontinuity')
        if row['time_s']>task['applied_s']+1e-9 and row['world_active']!=191:
            raise ValueError('active target changed during fixed task')
    for rows in base['observations'].values():
        for r in rows:
            if not r['exposure_start_s']<=r['exposure_s']<=r['available_s']:
                raise ValueError('camera time disorder')
    return dict(consistent=True,planned_steps=1,command_count=1,applied_s=task['applied_s'],
                response_at_s=event['response_at_s'],task_end_s=task['end_s'],
                source_preparation='not_performed_controlled_initial_state',
                exposure_position_quantization_bound_s=dt)


def observation_variant(frames, snapshot, condition, spec):
    """Stress transforms see only observations/map/time, never world/reference."""
    if condition not in CONDITIONS:raise ValueError('unknown S2 condition')
    shape=tuple(snapshot['shape']);scale=snapshot['scale'];lower=np.array(snapshot['lower'])
    target=np.mean(np.array(snapshot['polygons']['191']),axis=0)
    source=np.mean(np.array(snapshot['polygons']['190']),axis=0)
    def circle(point,radius):
        mask=np.zeros(shape,np.uint8)
        cv2.circle(mask,tuple(np.rint((point-lower)*scale).astype(int)),int(round(radius*scale)),255,-1)
        return mask
    def tail():
        # Exact original probe pixels on the unchanged 164x212 route ROI.
        if shape!=(164,212):raise ValueError('tail fixture requires the frozen original ROI')
        mask=np.zeros(shape,np.uint8)
        mask[84:129,83:85]=255;mask[145:148,0:3]=255;mask[155:157,0:3]=255
        return mask
    output=[]
    for old in frames:
        row=dict(old);row['mask']=None if old['mask'] is None else old['mask'].copy()
        t=row['exposure_start_s']
        if row['mask'] is not None:
            if condition.startswith('B_flash'):
                end=.9 if condition=='B_flash_short' else 1.1
                row['mask']=circle(target,.26 if .8-1e-9<=t<=end+1e-9 else .65)
            elif condition.startswith('C_jump'):
                end=1.1 if condition=='C_jump_short' else 1.4
                row['mask']=circle(target if .8-1e-9<=t<=end+1e-9 else source,.26)
            elif condition.startswith('D_tail'):row['mask']=tail()
            elif condition in ('E_lowconf_false','E_highconf_false'):row['mask']=circle(target,.26)
            if condition.startswith('E_lowconf'):row['confidence']=.1
        if condition=='F_gap' and .80-1e-9<=t<1.05-1e-9:
            row['mask']=None;row['confidence']=0.
        output.append(row)
    return output


def freeze_input(base, frames, output, spec):
    params=asdict(state_config(spec.environment));w=spec.target.window
    params.update(eta_arr=spec.target.coverage,eta_release=spec.target.source_release,
        arrival_frames=w.frames,arrival_duration_s=w.duration_s,evidence_max_gap_s=w.max_gap_s,
        arrival_max_centroid_span_mm=w.centroid_span_pitch,arrival_max_coverage_span=w.coverage_span,
        centroid_tolerance=spec.target.position_tolerance_pitch)
    return write_cache(output,map_snapshot=base['snapshot'],tasks=base['tasks'],parameters=params,
                       frames=frames,clock_domain='simulation',coordinate_unit='pitch')
