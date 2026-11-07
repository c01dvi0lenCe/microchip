"""Instrumented research loop over unchanged World/Camera and production policy.

The compatible branch preserves the exact v1 call order and legacy row view.
Additional tick/Mask/gate records do not consume any random numbers.
"""
from dataclasses import asdict,dataclass,field,replace
import heapq
import numpy as np

from ..formal_adapter import FormalAdapter
from ..geometry import SimulationMap
from ..runner import TrialResult
from ..vision import SyntheticCamera
from ..world import DropletWorld
from .adapter import ResearchAdapter
from .observation import ObservedFrame
from .spec import METHODS,DEVELOPMENT_SEEDS


@dataclass
class TrialV2:
    trial_id: str
    method: str
    phase_mode: str
    route: tuple
    metrics: dict=field(default_factory=dict)
    frames: list=field(default_factory=list)
    truth: list=field(default_factory=list)
    events: list=field(default_factory=list)
    captures: list=field(default_factory=list)
    gates: list=field(default_factory=list)
    references: list=field(default_factory=list)
    steps: list=field(default_factory=list)
    event_evaluation: list=field(default_factory=list)
    geometry: dict=field(default_factory=dict)
    legacy: TrialResult | None=None


def run_trial_v2(spec,scenario,seed,method='F',*,phase_mode='end_to_end',flags=None):
    if method not in METHODS:raise ValueError('unknown v2 method')
    if seed not in DEVELOPMENT_SEEDS and not (method=='C_v1_compat' and seed in range(261000,261020)):
        raise ValueError('only declared development seeds or historical compatibility seeds allowed')
    if phase_mode not in ('end_to_end','source_only','transport_only'):raise ValueError('invalid phase view')
    if method=='C_v1_compat' and (phase_mode!='end_to_end' or flags is not None):raise ValueError('v1 compatibility cannot change phase or switches')
    cfg=spec.environment;geometry=SimulationMap(cfg);world=DropletWorld(cfg,geometry,scenario,seed);camera=SyntheticCamera(cfg,geometry,seed,scenario)
    compat=method=='C_v1_compat';base_method='C' if compat else method
    run_id=f'{scenario}:{seed}:C:full' if compat else f'{scenario}:{seed}:{method}:{phase_mode}:{flags or "full"}'
    adapter=(FormalAdapter(cfg,geometry,'C','full',run_id=run_id) if compat else ResearchAdapter(spec,geometry,method,flags=flags,run_id=run_id))
    common=dict(simulation=True,scenario=scenario,seed=seed,method=base_method,base_method=base_method,method_version=adapter.method_version,
                ablation='full',coordinate_unit='pitch',clock_domain='simulation')
    result=TrialV2(run_id,method,phase_mode,tuple(cfg.route))
    result.geometry=dict(geometry.snapshot(),lower=geometry.lower.tolist(),scale=geometry.scale,shape=[int(v) for v in geometry.shape])
    frames=[];truth=[];events=[];queue=[];pending=None;frame_id=0
    arrivals={};confirmations={};delays=[];early=0;retry_total=0;recovery_total=0;recovery_resends=0
    preparation_s=None;source_confirmed_s=None;status='time_limit';now=0.
    transport_initial=phase_mode=='transport_only'
    initial_applied=world.command(cfg.route[1] if transport_initial else cfg.route[0],0.,'Start' if transport_initial else 'Prepare')
    initial_application_logged=False
    if not transport_initial:
        adapter.context=replace(adapter.context,applied_timestamp_s=initial_applied,applied_time_quality='simulation_applied');adapter.ledger.activate(adapter.context)
    events.append(dict(common,event='Start' if transport_initial else 'Prepare',time_s=0.,applied_s=initial_applied,step=0,epoch=0,
                       target=cfg.route[1] if transport_initial else cfg.route[0],accepted=False,request_id=0,applied_receive_ns=None))

    def log_event(event,**values):
        row=dict(common,event=event,time_s=now,step=adapter.controller.index,epoch=adapter.context.epoch,
                 phase=adapter.phase,source=adapter.source,target=adapter.target,**values)
        events.append(row);return row

    def request(decision):
        nonlocal pending,early,status
        step=adapter.controller.index;request_id=len(events)+1;applied=None
        if decision.action not in ('Complete','Stop'):applied=world.command(decision.target,now,decision.action)
        if decision.action in ('Update','Complete'):
            arrival=arrivals.get(step);is_early=arrival is None;early+=int(is_early)
            delay=None if arrival is None else now-arrival
            if delay is not None:delays.append(delay)
            confirmations[step]=dict(time_s=now,true_arrival_s=arrival,early=is_early)
            log_event(decision.action,early=is_early,true_arrival_s=arrival,delay_s=delay,decision_time_s=now,applied_receive_ns=None,
                      request_id=request_id,activated_target=decision.target,applied_s=applied,accepted=decision.action=='Complete')
        if decision.action in ('Complete','Stop'):
            if not adapter.accept(decision,now):raise RuntimeError('terminal command acceptance rejected')
            if decision.action=='Stop':status='protective_stop';log_event('Stop',reason=decision.reason)
            else:status='completed' if not early else 'completed_with_early_updates'
            return
        if decision.action!='Update':log_event(decision.action,reason=decision.reason,decision_time_s=now,applied_s=applied,accepted=False,
            request_id=request_id,applied_receive_ns=None,activated_target=decision.target)
        pending=(decision,applied,request_id,step,adapter.phase)

    for tick in range(int(np.ceil(cfg.max_time_s/cfg.dt_s))+1):
        now=min(cfg.max_time_s,tick*cfg.dt_s);world.advance(now)
        if not initial_application_logged and initial_applied<=now:
            if transport_initial:adapter.begin_transport(initial_applied)
            log_event('Applied',action='Start' if transport_initial else 'Prepare',applied_s=initial_applied,accepted=True,request_id=0,applied_receive_ns=None)
            initial_application_logged=True
        if pending and pending[1]<=now+1e-9:
            decision,applied,request_id,old_step,old_phase=pending
            if not adapter.accept(decision,applied):raise RuntimeError('simulated application rejected')
            retry_total+=int(decision.action=='Retry' and old_phase!='recovering');recovery_resends+=int(decision.action=='Retry' and old_phase=='recovering')
            recovery_total+=int(decision.action=='Recovery')
            if decision.action=='Start' and preparation_s is None:preparation_s=applied
            log_event('Applied',action=decision.action,applied_s=applied,accepted=True,request_id=request_id,request_step=old_step,applied_receive_ns=None)
            pending=None
        step=adapter.controller.index
        if adapter.phase=='transport' and adapter.context.applied_timestamp_s is not None:
            if step not in arrivals and now>=adapter.context.applied_timestamp_s and world.is_physically_settled(adapter.target):
                arrivals[step]=now;log_event('TruthArrival',true_arrival_s=now)
        row=dict(common,time_s=now,step=step,epoch=adapter.context.epoch,phase=adapter.phase,x=float(world.position[0]),y=float(world.position[1]),
            true_speed=float(np.linalg.norm(world.velocity)),target=adapter.target,physically_settled_now=world.is_physically_settled(adapter.target),
            physically_arrived=step in arrivals,true_arrival_s=arrivals.get(step))
        truth.append(row)
        result.truth.append(dict(row,source=adapter.source,world_active=world.active,world_goal_x=float(world.goal[0]),world_goal_y=float(world.goal[1]),
            world_response_at_s=world.response_at if np.isfinite(world.response_at) else None,world_vx=float(world.velocity[0]),world_vy=float(world.velocity[1])))
        while frame_id/cfg.camera_fps+cfg.exposure_s<=now+1e-9:
            frame=camera.expose(frame_id,frame_id/cfg.camera_fps,world.position);frame_id+=1
            result.captures.append(dict(frame_id=frame.frame_id,exposure_start_s=frame.exposure_start_s,exposure_end_s=frame.exposure_end_s,
                available_s=frame.available_s,capture_sample_time_s=now,capture_epoch=adapter.context.epoch,step=step,dropped=frame.dropped,
                confidence=1.,mask=frame.mask,clock_domain='simulation'))
            if not compat:frame=ObservedFrame(frame.frame_id,frame.exposure_start_s,frame.exposure_end_s,frame.available_s,frame.mask,frame.dropped,task_epoch=adapter.context.epoch)
            if frame.dropped:
                frames.append(dict(common,frame_id=frame.frame_id,exposure_s=frame.exposure_end_s,exposure_start_s=frame.exposure_start_s,
                    available_s=frame.available_s,processing_s=None,step=step,epoch=adapter.context.epoch,valid=False,reason='CAMERA_DROPPED',state='Unknown',action='Hold'))
            else:heapq.heappush(queue,(frame.available_s,frame.frame_id,frame))
        if pending or (transport_initial and not initial_application_logged):continue
        decision=None
        while queue and queue[0][0]<=now+1e-9:
            _,_,frame=heapq.heappop(queue);outcome=adapter.observe(frame,now);f=outcome.observation
            frames.append(dict(common,frame_id=frame.frame_id,exposure_s=frame.exposure_end_s,exposure_start_s=frame.exposure_start_s,
                available_s=frame.available_s,processing_s=now,sample_quantization_bound_s=cfg.dt_s,step=adapter.controller.index,epoch=adapter.context.epoch,
                phase=adapter.phase,source=adapter.source,target=adapter.target,state=outcome.state.value,action=outcome.decision.action,action_reason=outcome.decision.reason,
                valid=f.valid,reason=f.error,observation_quality=f.observation_quality,
                state_reason=(adapter.transport_recognizer.last_reason if not compat and adapter.phase=='transport' and outcome.state.value!='Unknown' else
                              (','.join(adapter.last_trace.get('rejection_reasons',[])) or adapter.last_trace.get('window_reason','')) if not compat and adapter.phase=='transport' else adapter.recognizer.last_reason),
                x=None if f.centroid is None else f.centroid[0],y=None if f.centroid is None else f.centroid[1],area_px=f.area,eta_source=f.eta_source,eta_target=f.eta_target,
                rho_target=f.rho_target,distance_pitch=f.distance,progress_pitch=f.progress_mm,progress_fraction=f.progress_fraction,lateral_pitch=f.lateral_error_mm,
                velocity_pitch_s=f.velocity,velocity_parallel_pitch_s=f.velocity_parallel_mm_s,spatial_ok=f.spatial_ok,temporal_ok=f.temporal_ok,
                target_position_ok=f.target_position_ok,applied_s=adapter.context.applied_timestamp_s,causality=outcome.causality,
                arrival_window_count=adapter.arrival.window.count if not compat and adapter.phase=='transport' else adapter.recognizer.count))
            trace=(dict(adapter.last_trace) if not compat else dict(stage='source' if adapter.phase=='confirm_source' else 'recovery' if adapter.phase=='recovering' else 'target',
                window_count=adapter.source_window.count if adapter.phase!='transport' else adapter.recognizer.count,window_reason=adapter.source_window.last_reason if adapter.phase!='transport' else adapter.recognizer.last_reason,
                legacy_gate_semantics=True))
            trace.update(frame_id=frame.frame_id,processing_s=now,exposure_end_s=frame.exposure_end_s,step=adapter.controller.index,epoch=adapter.context.epoch,
                         attempt=adapter.context.attempt_index,source=adapter.source,target=adapter.target,state=outcome.state.value,action=outcome.decision.action)
            result.gates.append(trace)
            if outcome.arrival_event:
                event=outcome.arrival_event
                log_event('ArrivalEvent',event_id=event.event_id,decision_time_s=now,evidence_start_s=event.evidence_start_s,evidence_end_s=event.evidence_end_s,
                    first_frame_id=event.first_frame_id,last_frame_id=event.last_frame_id,confirmed_at_ns=None,context=asdict(event.context))
            if outcome.decision.action=='Start' and source_confirmed_s is None:source_confirmed_s=now
            if phase_mode=='source_only' and outcome.decision.action=='Start':
                status='source_prepared';log_event('SourcePrepared',source_confirmation_s=now);break
            if outcome.decision.action!='Hold':decision=outcome.decision;break
        if status=='source_prepared':break
        if decision is None:
            tick_decision=adapter.tick(now)
            if tick_decision.action!='Hold':decision=tick_decision
        if decision is not None:request(decision)
        if adapter.controller.complete or adapter.phase=='stopped':break
    pending_frames=len(queue)
    while queue:
        _,_,frame=heapq.heappop(queue)
        frames.append(dict(common,frame_id=frame.frame_id,exposure_s=frame.exposure_end_s,exposure_start_s=frame.exposure_start_s,available_s=frame.available_s,
            processing_s=None,step=adapter.controller.index,epoch=adapter.context.epoch,valid=False,reason='PROCESSING_PENDING_AT_TERMINATION',state='Unknown',action='Hold',observation_quality='unavailable',censored=True))
    steps=len(cfg.route)-1;confirmed=len(confirmations);attempted=adapter.controller.index+int(preparation_s is not None)
    unconfirmed=[i for i in range(attempted) if i not in confirmations];censored=sum(i in arrivals for i in unconfirmed)
    no_arrival=sum(i not in arrivals for i in unconfirmed)+early
    for step in range(steps):
        if step not in confirmations:events.append(dict(common,event='UnconfirmedStep' if step<attempted else 'UnattemptedStep',time_s=now,step=step,target=cfg.route[step+1],true_arrival_s=arrivals.get(step),delay_censored=step in arrivals))
    legacy_metrics=dict(common,path_complete=status=='completed' and confirmed==steps,status=status,early_updates=early,transport_steps=steps,
        confirmed_steps=confirmed,issued_updates=confirmed,reference_arrived_steps=len(arrivals),correct_confirmed_steps=confirmed-early,
        confirmation_delay_s=float(np.mean(delays)) if delays else None,delay_observed_steps=len(delays),delay_missing_steps=steps-len(delays),delay_censored_steps=censored,
        delay_no_arrival_steps=no_arrival,delay_unattempted_steps=steps-attempted,total_time_s=now,execution_time_s=now,completion_time_s=now if status=='completed' else None,
        preparation_time_s=preparation_s,transport_execution_time_s=None if preparation_s is None else now-preparation_s,retries=retry_total,recoveries=recovery_total,
        recovery_resends=recovery_resends,communication_retries=0,physical_timing_validated=False,captured_frames=frame_id,pending_frames_at_termination=pending_frames,
        legacy_numeric_aliases=adapter.metadata['legacy_numeric_aliases'])
    result.legacy=TrialResult(legacy_metrics,frames,truth,events)
    result.frames=frames;result.events=events
    prepared=source_confirmed_s is not None or transport_initial
    terminal=('source_prepared' if status=='source_prepared' else 'source_not_prepared' if not prepared else
              'transport_complete' if adapter.controller.complete else 'time_limit' if status=='time_limit' else 'transport_stopped')
    result.metrics=dict(legacy_metrics,method=method,phase_mode=phase_mode,terminal_outcome=terminal,prepared=prepared,source_visual_confirmed=source_confirmed_s is not None,
        source_confirmation_s=source_confirmed_s,preparation_status='controlled_initial_condition' if transport_initial else 'visual_confirmed' if prepared else 'not_prepared',
        unknown_frames=sum(f['state']=='Unknown' for f in frames),missing_mask_frames=sum(c['mask'] is None for c in result.captures),
        transport_started=transport_initial or preparation_s is not None)
    from .reference import derive_reference
    from .evaluation import evaluate_trial
    result.references=derive_reference(result.truth,geometry,spec.reference,cfg.dt_s,steps)
    scored=evaluate_trial(result);result.steps=scored.pop('steps');result.event_evaluation=scored.pop('event_evaluation');result.metrics.update(scored)
    return result
