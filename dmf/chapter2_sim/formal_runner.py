"""Action-dependent, versioned formal trial; truth stays outside the adapter."""
from dataclasses import asdict, replace
import heapq

import numpy as np

from .formal_adapter import FormalAdapter
from .geometry import SimulationMap
from .runner import TrialResult
from .vision import SyntheticCamera
from .world import DropletWorld


def run_formal_trial(cfg,scenario,seed,method='C',ablation='full'):
    geometry=SimulationMap(cfg)
    world=DropletWorld(cfg,geometry,scenario,seed)
    camera=SyntheticCamera(cfg,geometry,seed,scenario)
    adapter=FormalAdapter(cfg,geometry,method,ablation,run_id=f'{scenario}:{seed}:{method}:{ablation}')
    common=dict(simulation=True,scenario=scenario,seed=seed,method=method,base_method=method,
        method_version=adapter.method_version,ablation=ablation,coordinate_unit='pitch',clock_domain='simulation')
    frames=[];truth=[];events=[];queue=[];pending=None;frame_id=0
    arrivals={};confirmations={};delays=[];early=0;retry_total=0;recovery_total=0;recovery_resends=0
    preparation_s=None;status='time_limit';now=0.
    initial_applied=world.command(cfg.route[0],0.,'Prepare')
    initial_application_logged=False
    adapter.context=replace(adapter.context,applied_timestamp_s=initial_applied,applied_time_quality='simulation_applied')
    adapter.ledger.activate(adapter.context)
    events.append(dict(common,event='Prepare',time_s=0.,applied_s=initial_applied,step=0,epoch=0,target=cfg.route[0],
                       accepted=False,request_id=0,applied_receive_ns=None))

    def log_event(event,**values):
        row=dict(common,event=event,time_s=now,step=adapter.controller.index,epoch=adapter.context.epoch,
                 phase=adapter.phase,source=adapter.source,target=adapter.target,**values)
        events.append(row)
        return row

    def request(decision):
        nonlocal pending,early,status
        step=adapter.controller.index
        request_id=len(events)+1
        applied=None
        if decision.action not in ('Complete','Stop'):
            applied=world.command(decision.target,now,decision.action)
        if decision.action in ('Update','Complete'):
            arrival=arrivals.get(step);is_early=arrival is None
            early+=int(is_early)
            delay=None if arrival is None else now-arrival
            if delay is not None:delays.append(delay)
            confirmations[step]=dict(time_s=now,true_arrival_s=arrival,early=is_early)
            log_event(decision.action,early=is_early,true_arrival_s=arrival,delay_s=delay,
                      decision_time_s=now,applied_receive_ns=None,request_id=request_id,
                      activated_target=decision.target,applied_s=applied,accepted=decision.action=='Complete')
        if decision.action in ('Complete','Stop'):
            adapter.accept(decision,now)
            if decision.action=='Stop':
                status='protective_stop';log_event('Stop',reason=decision.reason)
            else:status='completed' if not early else 'completed_with_early_updates'
            return
        if decision.action!='Update':
            log_event(decision.action,reason=decision.reason,decision_time_s=now,
                      applied_s=applied,accepted=False,request_id=request_id,applied_receive_ns=None,
                      activated_target=decision.target)
        pending=(decision,applied,request_id,step,adapter.phase)

    for tick in range(int(np.ceil(cfg.max_time_s/cfg.dt_s))+1):
        now=min(cfg.max_time_s,tick*cfg.dt_s)
        world.advance(now)
        if not initial_application_logged and initial_applied<=now:
            log_event('Applied',action='Prepare',applied_s=initial_applied,accepted=True,
                      request_id=0,applied_receive_ns=None)
            initial_application_logged=True
        if pending and pending[1]<=now+1e-9:
            decision,applied,request_id,old_step,old_phase=pending
            adapter.accept(decision,applied)
            retry_total+=int(decision.action=='Retry' and old_phase!='recovering')
            recovery_resends+=int(decision.action=='Retry' and old_phase=='recovering')
            recovery_total+=int(decision.action=='Recovery')
            if decision.action=='Start' and preparation_s is None:preparation_s=applied
            log_event('Applied',action=decision.action,applied_s=applied,accepted=True,
                      request_id=request_id,request_step=old_step,applied_receive_ns=None)
            pending=None
        step=adapter.controller.index
        if adapter.phase=='transport' and adapter.context.applied_timestamp_s is not None:
            if step not in arrivals and now>=adapter.context.applied_timestamp_s and world.is_physically_settled(adapter.target):
                arrivals[step]=now
                log_event('TruthArrival',true_arrival_s=now)
        truth.append(dict(common,time_s=now,step=step,epoch=adapter.context.epoch,phase=adapter.phase,
            x=float(world.position[0]),y=float(world.position[1]),true_speed=float(np.linalg.norm(world.velocity)),
            target=adapter.target,physically_settled_now=world.is_physically_settled(adapter.target),
            physically_arrived=step in arrivals,true_arrival_s=arrivals.get(step)))
        while frame_id/cfg.camera_fps+cfg.exposure_s<=now+1e-9:
            frame=camera.expose(frame_id,frame_id/cfg.camera_fps,world.position);frame_id+=1
            if frame.dropped:
                frames.append(dict(common,frame_id=frame.frame_id,exposure_s=frame.exposure_end_s,
                    exposure_start_s=frame.exposure_start_s,available_s=frame.available_s,processing_s=None,
                    step=step,epoch=adapter.context.epoch,valid=False,reason='CAMERA_DROPPED',state='Unknown',action='Hold'))
            else:heapq.heappush(queue,(frame.available_s,frame.frame_id,frame))
        if pending:continue
        decision=None
        while queue and queue[0][0]<=now+1e-9:
            _,_,frame=heapq.heappop(queue)
            outcome=adapter.observe(frame,now)
            f=outcome.observation
            frames.append(dict(common,frame_id=frame.frame_id,exposure_s=frame.exposure_end_s,
                exposure_start_s=frame.exposure_start_s,available_s=frame.available_s,processing_s=now,
                sample_quantization_bound_s=cfg.dt_s,step=adapter.controller.index,epoch=adapter.context.epoch,
                phase=adapter.phase,source=adapter.source,target=adapter.target,state=outcome.state.value,
                action=outcome.decision.action,action_reason=outcome.decision.reason,valid=f.valid,reason=f.error,
                observation_quality=f.observation_quality,state_reason=adapter.recognizer.last_reason,
                x=None if f.centroid is None else f.centroid[0],y=None if f.centroid is None else f.centroid[1],
                area_px=f.area,eta_source=f.eta_source,eta_target=f.eta_target,rho_target=f.rho_target,
                distance_pitch=f.distance,progress_pitch=f.progress_mm,progress_fraction=f.progress_fraction,
                lateral_pitch=f.lateral_error_mm,velocity_pitch_s=f.velocity,
                velocity_parallel_pitch_s=f.velocity_parallel_mm_s,spatial_ok=f.spatial_ok,temporal_ok=f.temporal_ok,
                target_position_ok=f.target_position_ok,applied_s=adapter.context.applied_timestamp_s,
                causality=outcome.causality,arrival_window_count=adapter.recognizer.count))
            if outcome.arrival_event:
                event=outcome.arrival_event
                log_event('ArrivalEvent',event_id=event.event_id,decision_time_s=now,
                    evidence_start_s=event.evidence_start_s,evidence_end_s=event.evidence_end_s,
                    first_frame_id=event.first_frame_id,last_frame_id=event.last_frame_id,
                    confirmed_at_ns=None,context=asdict(event.context))
            if outcome.decision.action!='Hold':decision=outcome.decision;break
        if decision is None:
            tick_decision=adapter.tick(now)
            if tick_decision.action!='Hold':decision=tick_decision
        if decision is not None:request(decision)
        if adapter.controller.complete or adapter.phase=='stopped':break

    pending_frames=len(queue)
    while queue:
        _,_,frame=heapq.heappop(queue)
        frames.append(dict(common,frame_id=frame.frame_id,exposure_s=frame.exposure_end_s,
            exposure_start_s=frame.exposure_start_s,available_s=frame.available_s,processing_s=None,
            step=adapter.controller.index,epoch=adapter.context.epoch,valid=False,
            reason='PROCESSING_PENDING_AT_TERMINATION',state='Unknown',action='Hold',
            observation_quality='unavailable',censored=True))
    steps=len(cfg.route)-1
    confirmed=len(confirmations);attempted=adapter.controller.index+int(preparation_s is not None)
    unconfirmed=[i for i in range(attempted) if i not in confirmations]
    censored=sum(i in arrivals for i in unconfirmed)
    no_arrival=sum(i not in arrivals for i in unconfirmed)+early
    for step in range(steps):
        if step not in confirmations:
            events.append(dict(common,event='UnconfirmedStep' if step<attempted else 'UnattemptedStep',
                time_s=now,step=step,target=cfg.route[step+1],true_arrival_s=arrivals.get(step),
                delay_censored=step in arrivals))
    metrics=dict(common,path_complete=status=='completed' and confirmed==steps,status=status,
        early_updates=early,transport_steps=steps,confirmed_steps=confirmed,issued_updates=confirmed,
        reference_arrived_steps=len(arrivals),correct_confirmed_steps=confirmed-early,
        confirmation_delay_s=float(np.mean(delays)) if delays else None,delay_observed_steps=len(delays),
        delay_missing_steps=steps-len(delays),delay_censored_steps=censored,delay_no_arrival_steps=no_arrival,
        delay_unattempted_steps=steps-attempted,total_time_s=now,execution_time_s=now,
        completion_time_s=now if status=='completed' else None,preparation_time_s=preparation_s,
        transport_execution_time_s=None if preparation_s is None else now-preparation_s,
        retries=retry_total,recoveries=recovery_total,recovery_resends=recovery_resends,
        communication_retries=0,physical_timing_validated=False,
        captured_frames=frame_id,pending_frames_at_termination=pending_frames,
        legacy_numeric_aliases=adapter.metadata['legacy_numeric_aliases'])
    return TrialResult(metrics,frames,truth,events)
