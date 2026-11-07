"""Development S3 loop. Algorithms receive frames, never independent truth."""
from collections import Counter
from dataclasses import asdict,replace
import hashlib
import heapq
import json
import numpy as np
from ..geometry import SimulationMap
from ..world import DropletWorld
from ..vision import SyntheticCamera
from ..v2.observation import ObservedFrame
from ..v2.runner import TrialV2
from ..runner import TrialResult
from .adapter import S3Adapter,TransactionSlot
from .evaluation import evaluate_trial

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def flush_applications(world,now_s):
    """Expose World's scheduled boundary at now without advancing dynamics.

    World.advance integrates half-open intervals and otherwise applies an
    exactly-due command only on the next interval. Reuse its unchanged _apply
    at this boundary before notifying the controller; no RNG is consumed.
    """
    if abs(world.time-now_s)>1e-9:raise ValueError('application boundary must equal current world time')
    while world.pending and world.pending[0][0]<=now_s+1e-9:
        world._apply(*world.pending.pop(0))

def run_trial(spec,scenario,seed,method='BTQ',*,protection=None,phase_mode='end_to_end',cohort='main'):
    spec.validate_seed(seed)
    if phase_mode not in ('end_to_end','transport_only'):raise ValueError('only approved phase views')
    cfg=spec.common.environment;g=SimulationMap(cfg)
    a=S3Adapter(spec,g,method,protection=protection,run_id=f's3:{scenario}:{seed}:{method}:{protection}:{phase_mode}')
    world=DropletWorld(cfg,g,scenario,seed);camera=SyntheticCamera(cfg,g,seed,scenario)
    identity=f'{scenario}:{seed}:{method}:{a.protection}:{phase_mode}'
    r=TrialV2(identity,method,phase_mode,tuple(cfg.route))
    r.geometry=dict(g.snapshot(),lower=g.lower.tolist(),scale=g.scale,shape=[int(i) for i in g.shape])
    ext=dict(world_noise=hashlib.sha256(world.noise.tobytes()).hexdigest(),speed_factor=world.speed_factor,
             camera_errors=hashlib.sha256(camera.errors.tobytes()).hexdigest(),camera_uniform=hashlib.sha256(camera.uniform.tobytes()).hexdigest(),
             max_time_s=cfg.max_time_s,world_stream=[seed,101],camera_stream=[seed,202])
    common=dict(simulation=True,scenario=scenario,seed=seed,method=method,protection=a.protection,
                method_version=a.method_version,phase_mode=phase_mode,cohort=cohort,coordinate_unit='pitch',clock_domain='simulation')
    queue=[];pending=None;slot=TransactionSlot();fid=0;now=0.;source_s=None;stop_reason='time_budget_exhausted'
    controlled=phase_mode=='transport_only';initial_at=world.command(cfg.route[1] if controlled else cfg.route[0],0.,'Start' if controlled else 'Prepare')
    if not controlled:
        a.context=replace(a.context,applied_timestamp_s=initial_at,applied_time_quality='simulation_applied');a.ledger.activate(a.context)
    initial_done=False;applied_budget=Counter();retries=resume=recoveries=0;request_counter=0
    def event(name,**values):
        row=dict(common,event=name,time_s=now,step=a.controller.index,epoch=a.context.epoch,attempt=a.context.attempt_index,
                 phase=a.phase,source=a.source,target=a.target)
        row.update(values);r.events.append(row);return row
    event('Start' if controlled else 'Prepare',request_id='initial',activated_target=cfg.route[1] if controlled else cfg.route[0],
          applied_s=initial_at,controlled_initial_condition=controlled)
    def request(d):
        nonlocal pending,request_counter,source_s,stop_reason
        if slot.request_id is not None:raise RuntimeError('pending transaction cannot accept a second request')
        request_counter+=1;rid=f'request-{request_counter}';old_step=a.controller.index;old_phase=a.phase
        activation_step=old_step+int(d.action=='Update')
        event(d.action,request_id=rid,activated_target=d.target,reason=d.reason,
              arrival_event_id=d.arrival_event_id,attempt_applied_s=a.controller.attempt_started,
              decision_time_s=now,origin_context=asdict(a.context))
        if d.action=='Start' and source_s is None:source_s=now
        if d.action in ('Complete','Stop'):
            if not a.accept(d,now):raise RuntimeError('terminal acceptance failed')
            stop_reason=d.reason;return
        if applied_budget[activation_step]>=7:raise RuntimeError('per-step seven-Applied contract exhausted')
        applied=world.command(d.target,now,d.action)
        if not slot.reserve(rid):raise RuntimeError('transaction slot race')
        r.events[-1]['applied_s']=applied
        pending=(d,applied,rid,old_step,old_phase,activation_step)

    for tick in range(int(round(cfg.max_time_s/cfg.dt_s))+1):
        now=round(tick*cfg.dt_s,12);world.advance(now);flush_applications(world,now)
        if not initial_done and now>=initial_at-1e-9:
            if controlled:a.begin_transport(initial_at);applied_budget[0]+=1
            event('Applied',request_id='initial',action='Start' if controlled else 'Prepare',activation_step=0,
                  activated_target=cfg.route[1] if controlled else cfg.route[0],applied_s=initial_at)
            initial_done=True
        if pending and now>=pending[1]-1e-9:
            d,at,rid,origin_step,origin_phase,activation_step=pending
            if not a.accept(d,at):raise RuntimeError('simulated Applied acceptance failed')
            retries+=int(d.action=='Retry' and origin_phase!='recovering')
            resume+=int(d.action=='Retry' and origin_phase=='recovering');recoveries+=int(d.action=='Recovery')
            applied_budget[activation_step]+=1
            event('Applied',request_id=rid,action=d.action,activation_step=activation_step,request_step=origin_step,
                  origin_phase=origin_phase,activated_target=d.target,applied_s=at,step_applied_count=applied_budget[activation_step])
            if not slot.release(rid):raise RuntimeError('wrong pending request completed')
            pending=None
        r.truth.append(dict(common,time_s=now,step=a.controller.index,epoch=a.context.epoch,phase=a.phase,source=a.source,target=a.target,
             x=float(world.position[0]),y=float(world.position[1]),true_speed=float(np.linalg.norm(world.velocity)),
             world_active=world.active,world_goal_x=float(world.goal[0]),world_goal_y=float(world.goal[1]),
             world_response_at_s=world.response_at if np.isfinite(world.response_at) else None,
             world_vx=float(world.velocity[0]),world_vy=float(world.velocity[1]),pending_request=slot.request_id))
        while fid/cfg.camera_fps+cfg.exposure_s<=now+1e-9:
            t=fid/cfg.camera_fps;f=camera.expose(fid,t,world.position)
            mask_hash=hashlib.sha256(f.mask.tobytes()).hexdigest() if f.mask is not None else None
            r.captures.append(dict(frame_id=fid,exposure_start_s=t,exposure_end_s=f.exposure_end_s,available_s=f.available_s,
                capture_sample_time_s=now,capture_epoch=a.context.epoch,step=a.controller.index,dropped=f.dropped,
                confidence=1.,mask=f.mask,raw_mask_sha256=mask_hash,clock_domain='simulation'))
            wrapped=ObservedFrame(fid,t,f.exposure_end_s,f.available_s,f.mask,f.dropped,task_epoch=a.context.epoch)
            if f.dropped:
                r.frames.append(dict(common,frame_id=fid,exposure_start_s=t,exposure_s=f.exposure_end_s,available_s=f.available_s,
                    processing_s=None,step=a.controller.index,epoch=a.context.epoch,phase=a.phase,state='Unknown',action='Hold',valid=False,
                    reason='CAMERA_DROPPED',observation_quality='unavailable'))
            else:heapq.heappush(queue,(f.available_s,fid,wrapped))
            fid+=1
        if pending or not initial_done:continue
        d=None
        while queue and queue[0][0]<=now+1e-9:
            _,_,f=heapq.heappop(queue);o=a.observe(f,now);v=o.observation
            r.frames.append(dict(common,frame_id=f.frame_id,exposure_start_s=f.exposure_start_s,exposure_s=f.exposure_end_s,
                available_s=f.available_s,processing_s=now,step=a.controller.index,epoch=a.context.epoch,phase=a.phase,source=a.source,target=a.target,
                state=o.state.value,action=o.decision.action,action_reason=o.decision.reason,valid=v.valid,reason=v.error,
                observation_quality=v.observation_quality,causality=o.causality,
                x=v.centroid[0] if v.centroid else None,y=v.centroid[1] if v.centroid else None,area_px=v.area,
                eta_source=v.eta_source,eta_target=v.eta_target,rho_target=v.rho_target,distance_pitch=v.distance,
                progress_pitch=v.progress_mm,lateral_pitch=v.lateral_error_mm,velocity_pitch_s=v.velocity,
                spatial_ok=v.spatial_ok,temporal_ok=v.temporal_ok,target_position_ok=v.target_position_ok,
                state_reason=a.last_trace.get('window_reason'),arrival_window_count=a.last_trace.get('window_count'),
                applied_s=a.context.applied_timestamp_s))
            r.gates.append(dict(a.last_trace,frame_id=f.frame_id,processing_s=now,step=a.controller.index,epoch=a.context.epoch,
                                state=o.state.value,action=o.decision.action,phase=a.phase))
            if o.arrival_event:event('ArrivalEvent',event_id=o.arrival_event.event_id,evidence_start_s=o.arrival_event.evidence_start_s,
                                     evidence_end_s=o.arrival_event.evidence_end_s,context=asdict(o.arrival_event.context))
            if o.decision.action!='Hold':d=o.decision;break
        if d is None:d=a.tick(now)
        if d.action!='Hold':request(d)
        if a.controller.complete or a.phase=='stopped':break
    pending_frames=len(queue)
    while queue:
        _,_,f=heapq.heappop(queue)
        r.frames.append(dict(common,frame_id=f.frame_id,exposure_start_s=f.exposure_start_s,exposure_s=f.exposure_end_s,available_s=f.available_s,
            processing_s=None,step=a.controller.index,epoch=a.context.epoch,phase=a.phase,state='Unknown',action='Hold',valid=False,
            reason='PROCESSING_PENDING_AT_TERMINATION',observation_quality='unavailable',censored=True))
    prefix_captures=[{k:c[k] for k in ('frame_id','exposure_start_s','available_s','dropped','raw_mask_sha256')} for c in r.captures
                     if source_s is None or c['capture_sample_time_s']<=source_s+1e-9]
    prefix_frames=[{k:f.get(k) for k in ('frame_id','processing_s','state','action','valid','reason','eta_source','eta_target')}
                   for f in r.frames if (f.get('processing_s') is not None and (source_s is None or f['processing_s']<=source_s+1e-9))]
    r.metrics=dict(common,trial_id=identity,source_prepared=source_s is not None or controlled,
        source_visual_confirmed=source_s is not None,source_confirmation_s=source_s,
        source_condition='controlled_initial_condition_not_source_evidence' if controlled else 'common_P0',
        transport_started=any(e['event']=='Applied' and e.get('action')=='Start' for e in r.events),
        transport_complete=a.controller.complete,execution_time_s=now,stop_reason=stop_reason,
        retries=retries,recovery_resends=resume,recoveries=recoveries,max_step_applied=max(applied_budget.values(),default=0),
        step_applied_counts=dict(applied_budget),exogenous_hash=digest(ext),exogenous=ext,
        p0_prefix_hash=digest(dict(captures=prefix_captures,frames=prefix_frames)) if not controlled else None,
        capture_sequence_hash=digest([(c['frame_id'],c['raw_mask_sha256']) for c in r.captures]),
        captured_frames=fid,pending_frames_at_termination=pending_frames,pending_transaction_at_termination=slot.request_id,
        unknown_frames=sum(f['state']=='Unknown' for f in r.frames),missing_mask_frames=sum(c['mask'] is None for c in r.captures),
        infrastructure_invalid=False,physical_timing_validated=False)
    evaluate_trial(r,g,spec)
    r.legacy=TrialResult(r.metrics,r.frames,r.truth,r.events)
    return r
