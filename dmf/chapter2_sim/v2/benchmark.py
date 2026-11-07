"""GT-blind research arrival events over the existing immutable Mask cache."""
from dataclasses import asdict
from pathlib import Path

from dmf.experiment.mask_cache import load_cache
from dmf.experiment.evidence import FrameCausalityGuard,StepContext,ArrivalEvent,ArrivalEventLedger
from ..formal_adapter import NormalizedMap,make_frame_packet,state_config
from ..batch import _write_csv,_write_json
from .observation import ObservationPipeline,ObservedFrame,validate_syntax
from .arrival import ArrivalGate
from .spec import method_flags


def run_arrival_variant(cache_dir,method,output_dir,spec,*,flags=None):
    output=Path(output_dir)
    if output.exists():raise FileExistsError(output)
    flags=flags or method_flags(method)
    cache=load_cache(cache_dir)
    if cache['clock_domain']!='simulation':raise ValueError('v2 development benchmark only accepts explicit simulation clocks')
    expected=dict(eta_arr=spec.target.coverage,eta_release=spec.target.source_release,arrival_frames=spec.target.window.frames,
        arrival_duration_s=spec.target.window.duration_s,evidence_max_gap_s=spec.target.window.max_gap_s,
        arrival_max_centroid_span_mm=spec.target.window.centroid_span_pitch,arrival_max_coverage_span=spec.target.window.coverage_span)
    if any(cache['parameters'].get(k)!=v for k,v in expected.items()):raise ValueError('cache frozen parameters differ from shared target contract')
    geometry=NormalizedMap.from_snapshot(cache['map'])
    pipeline=ObservationPipeline(geometry,state_config(spec.environment),spec.target,spec.quality)
    arrival=ArrivalGate(spec.target,flags);guard=FrameCausalityGuard();ledger=ArrivalEventLedger()
    active=None;context=None;events=[];traces=[]
    for row in sorted(cache['frames'],key=lambda q:(q['available_s'],q['frame_id'])):
        now=row['available_s'];task=next((t for t in cache['tasks'] if t['start_s']<=now<t['end_s']),None)
        if task is None:
            traces.append(dict(frame_id=row['frame_id'],processing_s=now,C0_passed=False,C0_reason='OUTSIDE_TASK'));continue
        if task['step_id']!=active:
            active=task['step_id'];context=StepContext(cache['input_sha256'],active,0,active,task['source'],task['target'],clock_domain='simulation',
                applied_timestamp_s=task['applied_s'],applied_time_quality='simulation_applied')
            pipeline.reset();arrival.reset();ledger.activate(context)
        frame=ObservedFrame(row['frame_id'],row.get('exposure_start_s',row['exposure_s']),row['exposure_s'],now,row['mask'],
            confidence=row['confidence'],stream_id=row.get('video_id','cache'),task_epoch=active)
        packet=make_frame_packet(frame,video_id=frame.stream_id,task_epoch=active,shape=cache['map']['shape'])
        assessment=guard.check(packet,context,mode='simulation');valid,reason=validate_syntax(frame,geometry.shape)
        if not assessment.accepted or not valid or now-packet.timestamp_s>spec.environment.observation_timeout_s:
            arrival.reset();pipeline.reset();trace=dict(C0_passed=False,C0_reason=assessment.reason or reason or 'STALE_FRAME',eligible=False,window_count=0)
        else:
            f,raw,reasons=pipeline.extract(packet,frame,context)
            if f is None:
                arrival.reset();trace=dict(C0_passed=False,C0_reason='NON_MONOTONE_TIMESTAMP',eligible=False,window_count=0)
            else:
                trace=arrival.observe(context,packet,raw)
                if trace['confirmed'] and (context.run_id,context.step_index) not in ledger.consumed_steps:
                    event=ArrivalEvent.from_window(context,arrival.window,None,'simulation',assessment.causality)
                    if not ledger.consume(event):raise RuntimeError('event consumption failed')
                    events.append(dict(step_id=active,target=task['target'],timestamp_s=now,evidence_start_s=event.evidence_start_s,evidence_end_s=event.evidence_end_s,
                        first_frame_id=event.first_frame_id,last_frame_id=event.last_frame_id,event_id=event.event_id))
        trace.update(frame_id=row['frame_id'],processing_s=now,step_id=active,epoch=context.epoch)
        traces.append(trace)
    output.mkdir(parents=True)
    _write_csv(output/'events.csv',events);_write_csv(output/'gate_trace.csv',traces)
    report=dict(simulation=True,method=method,input_sha256=cache['input_sha256'],events=events,planned_steps=len(cache['tasks']),
        factors=asdict(flags),shared_target_contract=asdict(spec.target),single_frame_baselines_do_not_claim_full_states=True)
    _write_json(output/'prediction_manifest.json',report)
    return report
