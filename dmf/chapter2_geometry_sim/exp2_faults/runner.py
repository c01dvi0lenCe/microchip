"""Fault-only scheduler: exposure context and available-time order are separate."""
from dataclasses import replace
import heapq
import math
from pathlib import Path
from ..observation import CameraFrame
from ..exp2.controller import ExperimentController
from ..exp2.reference import IndependentReference
from ..exp2.runner import RouteRaster, TrialResult, observed_features, load_inputs
from ..exp2.world import CausalWorld
from .spec import CASES, Exp2Config, VERSION
from .world import StalledWorld
from .persistence import mask_sha256


def context_fields(context):
    names=dict(epoch='epoch',step='step_index',phase='phase',run_id='run_id',
        attempt='attempt_index',source='source_id',target='target_id',
        applied_s='applied_timestamp_s',clock_domain='clock_domain')
    return {'captured_'+name:getattr(context,attribute) if context else None
            for name,attribute in names.items()}


def run_case(case,geometry,pool,config=None,run_id=None,inputs=None):
    """Execute one predeclared deterministic case (or a shortened unit fixture)."""
    if case not in CASES:
        raise ValueError('only the ten approved fault declarations are executable')
    cfg=config or Exp2Config()
    if case.applied_delay_s is not None:
        cfg=replace(cfg,applied_delay_s=case.applied_delay_s)
    run_id=run_id or VERSION+':'+case.case_id
    world=(StalledWorld(geometry,pool,cfg,case.stall_at_s) if case.stall_at_s is not None
           else CausalWorld(geometry,pool,cfg))
    controller=ExperimentController(case.method,cfg,run_id)
    reference=IndependentReference(geometry,cfg)
    raster=RouteRaster(geometry,cfg)
    rows=[];polygons=[];captures=[];deliveries=[];queue=[];interventions=[]
    world_event_cursor=0;controller_cursor=0;stall_cursor=0;delivery_serial=0
    submitted=set()
    reference.observe(world.snapshot())
    controller.start(0.)
    if case.applied_delay_s is not None:
        interventions.append(dict(operation='applied_delay_stress',time_s=0.,
            applied_delay_s=cfg.applied_delay_s))

    def sync_control(now):
        nonlocal controller_cursor
        for event in controller.events[controller_cursor:]:
            if event['event']=='request' and event['action']=='Update':
                i=event['origin_step']
                reference.mark('request',now,cfg.route[i+1],i,'Update',event['request_id'])
            elif event['event']=='Complete':
                i=event['origin_step']
                reference.mark('request',now,cfg.route[i+1],i,'Complete')
        controller_cursor=len(controller.events)
        if controller.pending is not None and controller.pending['request_id'] not in submitted and controller.terminal is None:
            tx=controller.pending
            if tx['request_s']+cfg.applied_delay_s>min(cfg.control_budget_s,cfg.horizon_s)+1e-9:
                raise ValueError('transaction Applied exceeds declared control/observation budget')
            world.request(tx['target'],tx['action'])
            submitted.add(tx['request_id'])

    def enqueue(frame,duplicate=False):
        nonlocal delivery_serial
        uid=delivery_serial
        delivery_serial+=1
        heapq.heappush(queue,(frame.available_s,uid,frame,duplicate))
        return uid

    tick_count=int(math.ceil(cfg.horizon_s/cfg.dt_s))
    frame_count=int(math.ceil(cfg.horizon_s*cfg.camera_fps-1e-10))
    next_frame=0
    fake_mask=(raster.mask(pool.at(case.fake_phase,geometry.center(case.fake_electrode))[0])
               if case.fake_electrode is not None else None)
    for tick in range(tick_count+1):
        now=round(min(tick*cfg.dt_s,cfg.horizon_s),12)
        world.advance(now)
        if isinstance(world,StalledWorld):
            interventions.extend(dict(item) for item in world.interventions[stall_cursor:])
            stall_cursor=len(world.interventions)
        new_events=world.events[world_event_cursor:]
        world_event_cursor=len(world.events)
        for event in new_events:
            if event['event']!='simulated_applied':
                continue
            reference.observe(event['left_limit'])
            tx=controller.pending
            if tx is None:
                raise ValueError('world Applied without controller transaction')
            if tx['action']=='Update':
                i=tx['origin_step']
                reference.mark('applied',event['time_s'],cfg.route[i+1],i,'Update',tx['request_id'])
            controller.on_applied(dict(tx),event['time_s'])
        reference.observe(world.snapshot())
        rows.append(world.snapshot())
        polygons.append(dict(time_s=now,polygon_mm=list(world.polygon.exterior.coords)))
        while next_frame<frame_count and next_frame/cfg.camera_fps<=now+1e-9:
            exposure=round(next_frame/cfg.camera_fps,12)
            if abs(exposure-now)>1e-8:
                raise ValueError('camera grid must coincide with integration grid')
            source_mask=raster.mask(world.polygon)
            injected=exposure in case.fake_exposures_s
            mask=fake_mask.copy() if injected else source_mask
            source_hash=mask_sha256(source_mask)
            visible_hash=mask_sha256(mask) if injected else source_hash
            end=round(exposure+cfg.exposure_s,12)
            nominal_available=round(end+cfg.processing_delay_s,12)
            delayed=next_frame==case.delayed_frame_id
            available=round(nominal_available+(case.extra_delay_s if delayed else 0.),12)
            captured_context=controller.context
            dropped=next_frame in case.drop_frame_ids
            capture=dict(frame_id=next_frame,exposure_start_s=exposure,exposure_end_s=end,
                available_s=available,nominal_available_s=nominal_available,
                **context_fields(captured_context),mask=mask,mask_path=f'masks/{next_frame:04d}.png',
                source_mask=source_mask if injected else None,
                source_mask_path=f'unmodified_source_masks/{next_frame:04d}.png' if injected else f'masks/{next_frame:04d}.png',
                source_mask_sha256=source_hash,visible_mask_sha256=visible_hash,
                mask_injected=injected,dropped=dropped,extra_delay_s=case.extra_delay_s if delayed else 0.)
            captures.append(capture)
            if injected:
                interventions.append(dict(operation='mask_replace',time_s=exposure,frame_id=next_frame,
                    electrode_id=case.fake_electrode,fixed_pool_phase=case.fake_phase,
                    source_mask_sha256=source_hash,visible_mask_sha256=visible_hash))
            if delayed:
                interventions.append(dict(operation='delivery_delay',time_s=exposure,frame_id=next_frame,
                    original_available_s=nominal_available,available_s=available,extra_delay_s=case.extra_delay_s))
            if dropped:
                interventions.append(dict(operation='delivery_drop',time_s=exposure,frame_id=next_frame,
                    original_available_s=nominal_available,reason='DECLARED_CAMERA_DROP'))
            else:
                original=CameraFrame(next_frame,exposure,end,available,mask,captured_context)
                uid=enqueue(original)
                if next_frame==case.duplicate_frame_id:
                    duplicate_available=round(available+case.duplicate_offset_s,12)
                    duplicate=CameraFrame(next_frame,exposure,end,duplicate_available,mask,captured_context)
                    duplicate_uid=enqueue(duplicate,True)
                    interventions.append(dict(operation='delivery_duplicate',time_s=exposure,
                        frame_id=next_frame,original_delivery_uid=uid,duplicate_delivery_uid=duplicate_uid,
                        original_available_s=available,available_s=duplicate_available,
                        identity_rewritten=False,context_rebound=False))
            next_frame+=1
        sync_control(now)
        while queue and queue[0][0]<=now+1e-9 and controller.pending is None:
            _,uid,item,duplicate=heapq.heappop(queue)
            item.processed_at_s=now
            current_epoch=controller.context.epoch if controller.context else None
            common=dict(delivery_uid=uid,frame_id=item.frame_id,processed_s=now,
                exposure_start_s=item.exposure_start_s,exposure_end_s=item.exposure_end_s,
                available_s=item.available_s,duplicate_delivery=duplicate,
                **context_fields(item.context),current_epoch=current_epoch,
                visible_mask_sha256=mask_sha256(item.mask))
            if controller.terminal is not None:
                deliveries.append(dict(common,consumed=False,reason='TERMINAL_FOLLOWUP'))
                continue
            if controller.context is None:
                raise ValueError('processing without established task context')
            features=observed_features(item,raster,controller.context,cfg.route)
            consumed=controller.observe(item,features)
            if consumed:
                controller.frames[-1]['delivery_uid']=uid
                controller.frames[-1]['duplicate_delivery']=duplicate
            deliveries.append(dict(common,consumed=consumed,
                reason=controller.frames[-1]['c0_reason'] if consumed else 'NOT_CONSUMED'))
            sync_control(now)
        controller.tick(now)
        sync_control(now)
    delivered_counts={}
    for row in deliveries:
        delivered_counts[row['frame_id']]=delivered_counts.get(row['frame_id'],0)+1
    for capture in captures:
        count=delivered_counts.get(capture['frame_id'],0)
        delivered=count>0
        capture.update(delivered=delivered,delivery_count=count,
            right_censored=not delivered and not capture['dropped'],
            delivery_censor_reason='DECLARED_CAMERA_DROP' if capture['dropped'] else '' if delivered
            else 'NOT_AVAILABLE_BY_HORIZON' if capture['available_s']>cfg.horizon_s+1e-9
            else 'TRANSACTION_PENDING_AT_HORIZON')
    terminal_events=[e for e in controller.events if e['event'] in ('Complete','Stop')]
    terminal_time=terminal_events[0]['time_s'] if terminal_events else None
    terminal_rows=[r for r in rows if terminal_time is not None and r['time_s']>=terminal_time-1e-9]
    holds_last=bool(terminal_rows and world.pending is None and controller.pending is None and
        all(r['active']==terminal_rows[0]['active'] for r in terminal_rows))
    steps,metrics=reference.score(controller,rows)
    metrics.update(method=case.method,case_id=case.case_id,captures=len(captures),deliveries=len(deliveries),
        dropped_frames=sum(c['dropped'] for c in captures),queued_at_horizon=len(queue),
        horizon_s=cfg.horizon_s,control_budget_s=cfg.control_budget_s,terminal_holds_last_active=holds_last,
        pending_transaction_at_horizon=world.pending,controller_pending_at_horizon=controller.pending,
        queued_frame_ids_at_horizon=[q[2].frame_id for q in sorted(queue)],
        queued_delivery_uids_at_horizon=[q[1] for q in sorted(queue)],
        simulation=True,development_only=True,n=1)
    result=TrialResult(case.method,cfg,rows,polygons,captures,deliveries,controller.frames,
        controller.events,controller.arrivals,steps,metrics,reference.segments,reference.marks,
        raster.snapshot(),dict(inputs or {},fault_case=case.snapshot()),world.events)
    result.fault_case=case.snapshot()
    result.interventions=interventions
    return result


def run_suite(output):
    """Exactly ten fixed cases; refuse existing destination before input loading."""
    from .persistence import persist_case, write_json
    output=Path(output)
    if output.exists():
        raise FileExistsError(output)
    geometry,pool,inputs=load_inputs()
    output.mkdir(parents=True)
    summaries=[]
    for case in CASES:
        result=run_case(case,geometry,pool,inputs=inputs)
        persist_case(result,output/case.case_id)
        summaries.append(result.metrics)
    write_json(output/'mechanisms_summary.json',dict(version=VERSION,cases=summaries,
        declarations=[case.snapshot() for case in CASES],inputs=inputs,
        random_draws=0,formal=False,tuning=False,simulation=True,development_only=True))
    return summaries

