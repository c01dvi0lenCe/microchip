"""Deterministic scheduler separating capture, transaction and controller state."""
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np
from ..observation import Raster, CameraFrame, extract_features
from .controller import ExperimentController
from .reference import IndependentReference
from .spec import Exp2Config, METHOD_NAMES, MAP_PATH, MAP_SHA256, VERSION
from .world import CausalWorld


class RouteRaster(Raster):
    def __init__(self,geometry,config):
        centers=np.array([geometry.center(i) for i in config.route])
        self.lower=centers.min(axis=0)-config.diameter_mm
        self.upper=centers.max(axis=0)+config.diameter_mm
        self.scale=config.pixels_per_mm
        self.shape=tuple(np.ceil((self.upper-self.lower)[::-1]*self.scale).astype(int))
        self.geometry=geometry
        self.electrodes={i:self.mask(geometry.polygons[i]) for i in config.route}


def observed_features(frame,raster,context,route):
    source=context.source_id;target=context.target_id
    if source==target:
        other=next(i for i in route if i!=source)
        values=extract_features(frame,raster,source,other)
        if values.get('valid'):
            distance=math.dist((values['x_mm'],values['y_mm']),raster.geometry.center(source))
            values.update(rho_target=values['rho_source'],eta_target=values['eta_source'],
                          distance_mm=distance,source_distance_mm=distance,
                          progress_mm=None,progress_fraction=None,lateral_mm=None)
        return values
    values=extract_features(frame,raster,source,target)
    if values.get('valid'):
        values['source_distance_mm']=math.dist((values['x_mm'],values['y_mm']),raster.geometry.center(source))
    return values


@dataclass
class TrialResult:
    method: str
    config: Exp2Config
    world: list
    polygons: list
    captures: list
    deliveries: list
    frames: list
    events: list
    arrivals: list
    steps: list
    metrics: dict
    reference_segments: list
    reference_marks: list
    raster: dict
    inputs: dict
    world_events: list


def run_trial(method,geometry,pool,config=None,run_id=None,inputs=None):
    """In-memory normal fixture. Truth objects never enter controller methods."""
    cfg=config or Exp2Config();run_id=run_id or VERSION+':'+method
    world=CausalWorld(geometry,pool,cfg);controller=ExperimentController(method,cfg,run_id)
    reference=IndependentReference(geometry,cfg);raster=RouteRaster(geometry,cfg)
    rows=[];polygons=[];captures=[];deliveries=[];queue=[];world_event_cursor=0;controller_cursor=0
    submitted=set();reference.observe(world.snapshot());controller.start(0.)

    def sync_control(now):
        nonlocal controller_cursor
        for event in controller.events[controller_cursor:]:
            if event['event']=='request' and event['action']=='Update':
                i=event['origin_step'];reference.mark('request',now,cfg.route[i+1],i,'Update',event['request_id'])
            elif event['event']=='Complete':
                i=event['origin_step'];reference.mark('request',now,cfg.route[i+1],i,'Complete')
        controller_cursor=len(controller.events)
        if controller.pending is not None and controller.pending['request_id'] not in submitted and controller.terminal is None:
            tx=controller.pending
            if tx['request_s']+cfg.applied_delay_s>min(cfg.control_budget_s,cfg.horizon_s)+1e-9:
                raise ValueError('transaction Applied exceeds declared control/observation budget')
            world.request(tx['target'],tx['action']);submitted.add(tx['request_id'])

    tick_count=int(math.ceil(cfg.horizon_s/cfg.dt_s))
    frame_count=int(math.ceil(cfg.horizon_s*cfg.camera_fps-1e-10));next_frame=0
    for tick in range(tick_count+1):
        now=round(min(tick*cfg.dt_s,cfg.horizon_s),12);world.advance(now)
        new_events=world.events[world_event_cursor:];world_event_cursor=len(world.events)
        for event in new_events:
            if event['event']!='simulated_applied':continue
            reference.observe(event['left_limit'])
            tx=controller.pending
            if tx is None:raise ValueError('world Applied without controller transaction')
            if tx['action']=='Update':
                i=tx['origin_step'];reference.mark('applied',event['time_s'],cfg.route[i+1],i,'Update',tx['request_id'])
            controller.on_applied(dict(tx),event['time_s'])
        snapshot=world.snapshot();reference.observe(snapshot)
        rows.append(snapshot);polygons.append(dict(time_s=now,polygon_mm=list(world.polygon.exterior.coords)))
        while next_frame<frame_count and next_frame/cfg.camera_fps<=now+1e-9:
            exposure=round(next_frame/cfg.camera_fps,12)
            if abs(exposure-now)>1e-8:raise ValueError('camera grid must coincide with integration grid')
            mask=raster.mask(world.polygon);end=round(exposure+cfg.exposure_s,12)
            available=round(end+cfg.processing_delay_s,12)
            captured_context=controller.context
            camera_frame=CameraFrame(next_frame,exposure,end,available,mask,captured_context)
            queue.append(camera_frame)
            captures.append(dict(frame_id=next_frame,exposure_start_s=exposure,exposure_end_s=end,
                available_s=available,captured_epoch=captured_context.epoch if captured_context else None,
                captured_step=captured_context.step_index if captured_context else None,
                captured_phase=captured_context.phase if captured_context else None,
                captured_run_id=captured_context.run_id if captured_context else None,
                captured_attempt=captured_context.attempt_index if captured_context else None,
                captured_source=captured_context.source_id if captured_context else None,
                captured_target=captured_context.target_id if captured_context else None,
                captured_applied_s=captured_context.applied_timestamp_s if captured_context else None,
                captured_clock_domain=captured_context.clock_domain if captured_context else None,
                mask=mask,mask_path=f'masks/{next_frame:04d}.png'))
            next_frame+=1
        sync_control(now)
        while queue and queue[0].available_s<=now+1e-9 and controller.pending is None:
            item=queue.pop(0);item.processed_at_s=now
            if controller.terminal is not None:
                deliveries.append(dict(frame_id=item.frame_id,processed_s=now,consumed=False,reason='TERMINAL_FOLLOWUP'))
                continue
            if controller.context is None:
                raise ValueError('processing without established task context')
            features=observed_features(item,raster,controller.context,cfg.route)
            consumed=controller.observe(item,features)
            deliveries.append(dict(frame_id=item.frame_id,processed_s=now,consumed=consumed,
                captured_epoch=item.context.epoch if item.context else None,current_epoch=controller.context.epoch,
                reason=controller.frames[-1]['c0_reason'] if consumed else 'NOT_CONSUMED'))
            sync_control(now)
        # Due exposures win ties with safety timers. Transactions require room
        # for Applied within budget, but a due final lifecycle Complete counts.
        controller.tick(now);sync_control(now)
    delivered_ids={row['frame_id'] for row in deliveries}
    for capture in captures:
        delivered=capture['frame_id'] in delivered_ids
        capture.update(delivered=delivered,right_censored=not delivered,
            delivery_censor_reason='' if delivered else 'NOT_AVAILABLE_BY_HORIZON'
            if capture['available_s']>cfg.horizon_s+1e-9 else 'TRANSACTION_PENDING_AT_HORIZON')
    terminal_events=[event for event in controller.events if event['event'] in ('Complete','Stop')]
    terminal_time=terminal_events[0]['time_s'] if terminal_events else None
    terminal_rows=[row for row in rows if terminal_time is not None and row['time_s']>=terminal_time-1e-9]
    holds_last=bool(terminal_rows and world.pending is None and controller.pending is None and
                    all(row['active']==terminal_rows[0]['active'] for row in terminal_rows))
    steps,metrics=reference.score(controller,rows)
    metrics.update(method=method,captures=len(captures),deliveries=len(deliveries),dropped_frames=0,
        queued_at_horizon=len(queue),horizon_s=cfg.horizon_s,control_budget_s=cfg.control_budget_s,
        terminal_holds_last_active=holds_last,pending_transaction_at_horizon=world.pending,
        controller_pending_at_horizon=controller.pending,
        queued_frame_ids_at_horizon=[item.frame_id for item in queue],
        simulation=True,development_only=True,n=1)
    return TrialResult(method,cfg,rows,polygons,captures,deliveries,controller.frames,controller.events,
        controller.arrivals,steps,metrics,reference.segments,reference.marks,raster.snapshot(),inputs or {},world.events)


def load_inputs():
    from ..model import DesignGeometry
    from ..exp1b_closeout.run import saved_pool
    from ..sdf_trial import OUT as SHAPE_BASE
    from .persistence import sha256
    geometry=DesignGeometry(MAP_PATH)
    if geometry.sha256!=MAP_SHA256:raise ValueError('design map hash mismatch')
    oldrows,pool,source_ticks=saved_pool()
    if len(pool.phases)!=430:raise ValueError('expected read-only 430-outline pool')
    inputs=dict(map_path=str(geometry.path),map_sha256=geometry.sha256,pool_count=len(pool.phases),
        pool_world_path=str(SHAPE_BASE/'trial/world.csv'),pool_polygons_path=str(SHAPE_BASE/'trial/world_polygons.json'),
        pool_world_sha256=sha256(SHAPE_BASE/'trial/world.csv'),
        pool_polygons_sha256=sha256(SHAPE_BASE/'trial/world_polygons.json'),pool_source_ticks=source_ticks)
    return geometry,pool,inputs


def run_mechanisms(output):
    """Exactly four normal development demonstrations; additive destination only."""
    from .persistence import persist_trial, write_json
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    geometry,pool,inputs=load_inputs();cfg=Exp2Config();output.mkdir(parents=True)
    summaries=[]
    for method in METHOD_NAMES:
        result=run_trial(method,geometry,pool,cfg,inputs=inputs)
        persist_trial(result,output/method);summaries.append(result.metrics)
    write_json(output/'mechanisms_summary.json',dict(config=cfg.snapshot(),methods=summaries,inputs=inputs))
    return summaries
