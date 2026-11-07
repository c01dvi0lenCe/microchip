"""One persisted190→191 normal demonstration; no strategy comparison or hardware."""
from dataclasses import dataclass,asdict
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

import cv2
import numpy as np

from dmf.experiment.evidence import StepContext
from .observation import SyntheticCamera,extract_features
from .reference import evaluate_reference
from .shadow import ShadowArrival
from .single_world import DeformingWorld


@dataclass(frozen=True)
class SingleStepConfig:
    source: int=190
    target: int=191
    diameter_mm: float=4.
    spacer_height_mm: float=.8
    duration_s: float=3.
    dt_s: float=.01
    request_s: float=.5
    applied_delay_s: float=.04
    response_delay_s: float=.18
    speed_mm_s: float=4.8
    max_stretch: float=1.55
    shape_tau_s: float=.10
    camera_fps: float=20.
    exposure_s: float=.008
    processing_delay_s: float=.04
    pixels_per_mm: float=40.
    position_noise_mm: float=0.
    seed: int=264900

    def __post_init__(self):
        if (self.source,self.target,self.seed,self.diameter_mm)!=(190,191,264900,4.):
            raise ValueError('approved one-step190→191, seed264900, equivalent diameter4mm required')
        for key,value in asdict(self).items():
            if not math.isfinite(value) or value<0:raise ValueError(f'invalid {key}')
        for key in ('duration_s','dt_s','speed_mm_s','shape_tau_s','camera_fps','pixels_per_mm','spacer_height_mm'):
            if getattr(self,key)<=0:raise ValueError(f'positive {key} required')
        if (self.request_s+self.applied_delay_s+self.response_delay_s>=self.duration_s or
                self.max_stretch<1 or self.exposure_s>=1/self.camera_fps):
            raise ValueError('invalid temporal/shape config')
        if any(abs(round(t/self.dt_s)*self.dt_s-t)>1e-9 for t in (self.duration_s,self.request_s,1/self.camera_fps)):
            raise ValueError('duration, request and camera interval must align with integration grid')


TRIAL='geometry_single_step_v1:normal:264900:190-191'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def _json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def _source_summary():
    repo=Path(__file__).resolve().parents[2]
    root=repo/'dmf'
    folder=Path(__file__).resolve().parent
    files=[folder/name for name in ('model.py','footprint.py','single_world.py','observation.py','shadow.py','reference.py','single_step.py','preflight.py')]
    files.extend([root/'experiment/evidence.py',root/'vision/design_registration.py'])
    return dict(files={str(p.relative_to(repo)):sha(p) for p in sorted(files)},
                git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip(),
                git_worktree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=repo)),
                python=platform.python_version(),numpy=np.__version__,opencv=cv2.__version__)


def run_single_step(geometry,shape,config,output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    if abs(shape.area_mm2-math.pi*config.diameter_mm**2/4)>1e-8:
        raise ValueError('template/config area mismatch')
    output.mkdir(parents=True);(output/'masks').mkdir()
    world=DeformingWorld(geometry,shape,config)
    camera=SyntheticCamera(geometry,config)
    context=shadow=None
    pending=[];world_rows=[];polygons=[];observations=[];events=[]
    event_cursor=0;previous_observation=None
    ticks=round(config.duration_s/config.dt_s)
    camera_interval=round(1/config.camera_fps/config.dt_s)
    request_tick=round(config.request_s/config.dt_s)
    for tick in range(ticks+1):
        t=round(tick*config.dt_s,10)
        world.advance(t)
        if tick==request_tick:world.request(config.target)
        for event in world.events[event_cursor:]:
            events.append(dict(event,trial_id=TRIAL))
            if event['event']=='simulated_applied':
                context=StepContext(TRIAL,1,0,1,config.source,config.target,clock_domain='simulation',
                                    applied_timestamp_s=event['time_s'],applied_time_quality='simulation_exact')
                shadow=ShadowArrival(context)
        event_cursor=len(world.events)
        if tick%camera_interval==0 and tick<ticks:
            frame_id=tick//camera_interval
            frame=camera.expose(frame_id,t,world.polygon,context)
            mask_path=output/'masks'/f'{frame_id:04d}.png'
            mask_path.write_bytes(cv2.imencode('.png',frame.mask)[1].tobytes())
            pending.append((frame,mask_path))
        while pending and pending[0][0].available_s<=t+1e-9:
            frame,path=pending.pop(0);frame.processed_at_s=t
            features=extract_features(frame,camera.raster,config.source,config.target)
            row=dict(trial_id=TRIAL,frame_id=frame.frame_id,exposure_start_s=frame.exposure_start_s,
                     exposure_end_s=frame.exposure_end_s,available_s=frame.available_s,processed_at_s=t,
                     source=config.source,target=config.target,clock_domain='simulation',
                     captured_epoch=frame.context.epoch if frame.context else None,
                     mask_path=path.relative_to(output).as_posix(),mask_sha256=sha(path),**features)
            row['observed_speed_mm_s']=None
            if features['valid']:
                point=np.array([features['x_mm'],features['y_mm']])
                if previous_observation is not None:
                    old_t,old_p=previous_observation
                    gap=frame.exposure_start_s-old_t
                    if 0<gap<=.18:row['observed_speed_mm_s']=float(np.linalg.norm(point-old_p)/gap)
                previous_observation=(frame.exposure_start_s,point)
            if shadow is None:
                gate=dict(eligible=False,c0_valid=False,c0_reason='NO_APPLIED_CONTEXT',raw_coverage_gate=False,
                          single_event=False,window_event=False,window_count=0,window_span_s=0.,window_reason='NO_APPLIED_CONTEXT',
                          single_confirmed=False,window_confirmed=False,spatiotemporal_event=False,
                          spatiotemporal_confirmed=False,raw_Q=bool(features.get('valid')),
                          raw_S=features.get('distance_mm',float('inf'))<=.576,raw_K=True,
                          raw_history_speed_mm_s=None,full_window_count=0,full_window_span_s=0.)
            else:gate=shadow.observe(frame,features)
            row.update(gate)
            row['old_eta_gate']=bool(features['valid'] and features['eta_target']>=.85 and features['eta_source']<=.08)
            observations.append(row)
            for key,name in (('single_event','single_confirmation'),('window_event','window_confirmation'),('spatiotemporal_event','spatiotemporal_confirmation')):
                if gate[key]:events.append(dict(time_s=t,event=name,target=config.target,action='ShadowOnly',trial_id=TRIAL,
                                                frame_id=frame.frame_id,exposure_start_s=frame.exposure_start_s,
                                                event_id=shadow.event.event_id if key=='window_event' else
                                                'm3:'+shadow.full_event.event_id if key=='spatiotemporal_event' else 'single_first'))
        snap=world.snapshot();polygon=snap.pop('polygon_mm');world_rows.append(dict(trial_id=TRIAL,**snap))
        polygons.append(dict(time_s=t,polygon_mm=polygon))
    applied=[r['time_s'] for r in events if r['event']=='simulated_applied']
    reference=evaluate_reference(world_rows,geometry.center(config.target),config.target,applied[0])
    if reference['confirmed_s'] is not None:
        events.append(dict(time_s=reference['confirmed_s'],event='independent_reference',target=config.target,action='ScoringOnly',trial_id=TRIAL))
    events.sort(key=lambda r:r['time_s'])
    area=shape.area_mm2
    summary=dict(request_s=config.request_s,applied_s=applied[0],
                 response_start_s=world.response_at_s,
                 first_motion_tick_s=next((r['time_s'] for r in world_rows if r['speed_mm_s']>0),None),
                 center_reached_s=next((r['time_s'] for r in world_rows if r['world_status']=='at_target_center'),None),
                 reference_confirmation_s=reference['confirmed_s'],
                 single_confirmation_s=shadow.single_s if shadow else None,
                 window_confirmation_s=shadow.window_s if shadow else None,
                 spatiotemporal_confirmation_s=shadow.full_s if shadow else None,
                 max_stretch=max(r['stretch'] for r in world_rows),
                 max_geometric_area_relative_error=max(abs(r['area_mm2']/area-1) for r in world_rows),
                 max_mask_area_relative_error=max(abs(r['area_mm2']/area-1) for r in observations if r['valid']),
                 request_count=sum(r['event']=='request' for r in events),
                 applied_count=len(applied),world_ticks=len(world_rows),processed_masks=len(observations))
    write_csv(output/'world.csv',world_rows);write_csv(output/'observations.csv',observations);write_csv(output/'events.csv',events)
    _json(output/'world_polygons.json',polygons);_json(output/'reference.json',reference)
    _json(output/'raster.json',camera.raster.snapshot());_json(output/'template.json',shape.snapshot())
    (output/'map_snapshot.json').write_bytes(geometry.path.read_bytes())
    _json(output/'camera_random_offsets.json',camera.position_errors.tolist())
    manifest=dict(schema='geometry_single_step_v1',trial_id=TRIAL,mode='simulation',research_trials=1,
                  scenario='normal',clock_domain='simulation',source_preparation='controlled_initial_condition_not_P0',
                  config=asdict(config),summary=summary,source_map_sha256=geometry.sha256,
                  source_map_path=str(geometry.path),source_template_sha256=shape.source_sha256,
                  algorithm_inputs=['observed_mask','frame_identity','simulation_timestamps','task_context','electrode_map'],
                  controller='one_fixed_activation_then_hold_three_shadow_gates_do_not_control',
                  methods=dict(M1='C0+G_single_frame',M2='C0+G+Q+W',M3='C0+G+Q+W+S+K_pure_arrival_not_full_controller'),
                  candidate_gates=dict(rho_target=.90,eta_source=.08,min_frames=5,min_span_s=.25,
                                       max_gap_s=.18,target_distance_mm=.576,max_history_speed_mm_s=19.2,
                                       quality='nonempty_single_component_not_touching_ROI_border'),
                  five_state_classifier_used=False,source_code=_source_summary(),
                  model_limits=['2D area-preserving affine silhouette with minimum-jerk translation, not CFD or electrowetting force calculation',
                                '4mm is a declared equivalent-area scale, not an exact video measurement',
                                'Timing and speed are nominal simulation parameters, not hardware measurements',
                                'Spacer0.8mm recorded only; contact angle and volume not inferred',
                                'Instantaneous mask sample at exposure start; exposure blur not simulated',
                                'One n=1 mechanism example, no comparative performance evidence'])
    manifest['artifacts']={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}
    _json(output/'manifest.json',manifest)
    return manifest
