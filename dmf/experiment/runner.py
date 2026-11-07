"""One explicit experiment loop for video, dry-run live camera, and AM hardware."""
from pathlib import Path
import json
import time
import math
import uuid
from dmf.vision.config import load_electrode_map
from dmf.vision.contracts import DropletState as S, VisionResult
from .config import load_config, StateConfig, ControlConfig
from .perception import PriorFeatures, StateRecognizer, Observation
from .policy import EventController, Decision
from .segmenter import build_segmenter
from .sources import VideoSource, LiveSource
from .actuator import AMActuator, CommandResult
from .logging import ExperimentLogger
from .evidence import (EvidenceWindow, StepContext, ArrivalEvent, ArrivalEventLedger,
                       FrameCausalityGuard)


class Confirmation:
    """Compatibility facade; source/Recovery share the arrival evidence rules."""
    def __init__(self,frames,duration,max_gap_s=.25,**stability):
        self.frames=frames;self.duration=duration
        self.window=EvidenceWindow(frames,duration,max_gap_s,**stability)
    @property
    def count(self):return self.window.count
    def reset(self):self.window.reset()
    def observe(self,ok,t,frame_id=None,context=None,centroid_mm=None,eta_target=None):
        return self.window.observe(context,frame_id,t,ok,centroid_mm,eta_target)


def run_experiment(config_path,mode=None,*,source_factory=None,segmenter_factory=None,actuator_factory=None,
                   stop_event=None,on_frame=None,output_dir=None):
    config=load_config(config_path,mode);mode=config['mode']
    if output_dir is not None:config['output_dir']=str(Path(output_dir).resolve())
    print(f'MODE={mode} | AM output={"ENABLED" if mode=="experiment" else "DISABLED"}',flush=True)
    statecfg=StateConfig(**config['state']);ctrlcfg=ControlConfig(**config['control'])
    electrode_map=load_electrode_map(Path(config['electrode_map']))
    for i in config['candidate_electrodes']:
        if i>400 and electrode_map[i].geometry_source!='calibrated':raise ValueError('peripheral candidate requires calibrated polygon')
    prior=PriorFeatures(electrode_map,statecfg);recognizer=StateRecognizer(statecfg)
    controller=EventController(config['route'],ctrlcfg)
    gate=Confirmation(ctrlcfg.source_frames,ctrlcfg.source_duration_s,statecfg.evidence_max_gap_s,
        max_centroid_span_mm=statecfg.arrival_max_centroid_span_mm,
        max_coverage_span=statecfg.arrival_max_coverage_span)
    run_id=str(config.get('run_id') or uuid.uuid4().hex);config['run_id']=run_id
    logger=ExperimentLogger(config)
    experiment_id=str(config.get('experiment_id') or Path(config['output_dir']).name)
    source=None;actuator=None;packet=None;step_open=False;last_state=S.UNKNOWN;release_confirmed=None
    status='incomplete';reason='end of video';processed=0;last_valid=None;first_time=None;last_task_time=None
    evidence_epoch=0;context=None;arrival=None;attempt_index=0;queue_overwrites=0;communication_retry_total=0
    ledger=ArrivalEventLedger();frame_guard=FrameCausalityGuard();epoch_exposure_verified=True
    last_identity_source=None
    emergency_path=Path(config['emergency_stop_file']) if config.get('emergency_stop_file') else None
    emergency=lambda:bool((stop_event is not None and stop_event.is_set()) or
                          (emergency_path and emergency_path.exists()))

    def command_log(t,action,result):
        if result.command_id!='':
            logger.write('commands',{'timestamp':t,'command_id':result.command_id,'action':action,
                'changes':json.dumps(result.changes or {},sort_keys=True),'command_sent':result.sent,
                'accepted':result.accepted,'error':result.error,
                'request_id':result.request_id,'applied_monotonic_ns':result.applied_monotonic_ns,
                'applied_perf_counter_ns':result.applied_perf_counter_ns,
                'requested_perf_counter_ns':result.requested_perf_counter_ns,
                'communication_retries':result.communication_retries,'simulated':result.simulated,
                'step_index':context.step_index if context else None,
                'attempt_index':context.attempt_index if context else None,'epoch':context.epoch if context else None,
                'clock_domain':context.clock_domain if context else 'unknown',
                'requested_step_index':context.step_index+(action=='Update') if context else None,
                'requested_attempt_index':(0 if action=='Update' else context.attempt_index+(action=='Retry')) if context else None,
                'requested_epoch':context.epoch+1 if context and action in {'Start','Update','Retry','Recovery'} else None,
                'caused_by_arrival_event_id':arrival.event_id if arrival and action in {'Update','Complete'} else ''})

    def close_step(t,success,state,why):
        nonlocal step_open
        start=controller.step_started if controller.step_started is not None else first_time
        logger.write('steps',{'experiment_id':experiment_id,'step_index':controller.index,
            'source_electrode':controller.source,'target_electrode':controller.target,
            'step_start_time':start,'step_end_time':t,'transport_time':t-start if start is not None and t is not None else None,
            'success':success,'retry_total':controller.retry_total,'recovery_total':controller.recovery_total,
            'final_state':state.value,'reason':why,
            'attempt_index':context.attempt_index if context else None,'epoch':context.epoch if context else None,
            'arrival_event_id':arrival.event_id if arrival and success else '',
            'clock_domain':context.clock_domain if context else 'unknown',
            'communication_retry_total':communication_retry_total,
            'applied_time_quality':context.applied_time_quality if context else 'unavailable'})
        step_open=False

    try:
        (logger.root/'map_quality.json').write_text(json.dumps(electrode_map.quality_manifest(),
            ensure_ascii=False,indent=2),encoding='utf8')
        if emergency():raise InterruptedError('experiment stop requested')
        segmenter=(segmenter_factory or build_segmenter)(config)
        if emergency():raise InterruptedError('experiment stop requested')
        source=(source_factory(config) if source_factory else
                VideoSource(config['source']) if mode=='offline' else LiveSource(config['source']))
        if emergency():raise InterruptedError('experiment stop requested')
        hwconfig=dict(config);hwconfig['_emergency']=emergency
        hwconfig['_transaction_observer']=logger.transaction_event
        actuator=(actuator_factory or AMActuator)(mode,hwconfig)
        if mode=='experiment':command_log(time.monotonic(),'Startup release',CommandResult('ALL_OFF',True,True,changes={}))
        for packet in source:
            started=time.perf_counter();ingest_ns=time.monotonic_ns();ingest_perf_ns=time.perf_counter_ns();t=packet.timestamp_s
            if first_time is None:
                first_time=t if math.isfinite(t) else None;last_valid=t;step_open=True
                quality_manifest=electrode_map.quality_manifest()
                quality_manifest['observed_frame_size_px']=[packet.image_bgr.shape[1],packet.image_bgr.shape[0]]
                (logger.root/'map_quality.json').write_text(json.dumps(quality_manifest,ensure_ascii=False,indent=2),encoding='utf8')
            sid,tid=controller.source,controller.target;phase=controller.phase
            if context is None:
                context=StepContext(run_id,controller.index,0,0,sid,tid,
                    clock_domain=packet.timestamp_clock_domain if mode=='offline' else 'host_monotonic',phase=phase)
                ledger.activate(context)
            frame_context=context;arrival=None
            if emergency():raise InterruptedError('experiment stop requested')
            assessment=frame_guard.check(packet,context,mode=mode)
            time_origin_valid=assessment.reason not in {'CLOCK_DOMAIN_MISMATCH','STREAM_CHANGED'}
            if time_origin_valid and math.isfinite(t):
                last_task_time=t if last_task_time is None else max(last_task_time,t)
            identity_source='sdk' if packet.timing and packet.timing.capture_frame_id is not None else 'consumer'
            identity_changed=last_identity_source is not None and last_identity_source!=identity_source
            last_identity_source=identity_source
            if identity_changed or (packet.timing and packet.timing.queue_overwrites!=queue_overwrites):
                recognizer.reset();gate.reset();prior.reset()
                queue_overwrites=packet.timing.queue_overwrites if packet.timing else queue_overwrites
            if assessment.accepted and assessment.causality!='exposure_order_verified':epoch_exposure_verified=False
            error=''
            segment_started=time.perf_counter_ns()
            try:result=segmenter.process(packet)
            except Exception as exc:result=VisionResult(None,None,None,0,0,False,'SEGMENTATION_ERROR');error=str(exc)
            segment_ended=time.perf_counter_ns()
            obs=(Observation(error=assessment.reason) if not assessment.accepted else
                 prior.extract(packet,result,sid,tid,config['candidate_electrodes']))
            features_ended=time.perf_counter_ns()
            state=recognizer.recognize(obs,t,packet.capture_identity,context);last_state=state
            quality=recognizer.last_quality;state_reason=recognizer.last_reason
            if quality=='reliable':last_valid=t
            confirmed=gate.observe(obs.valid and obs.spatial_ok and obs.temporal_ok and
                obs.eta_source>=statecfg.eta_arr and obs.eta_target<=statecfg.eta_release,t,
                packet.capture_identity,context,obs.centroid,obs.eta_source)
            decision=(Decision('Hold',reason=assessment.reason) if not assessment.accepted else
                      controller.decide(state,t,source_confirmed=confirmed,observation=obs))
            if assessment.reason=='CLOCK_DOMAIN_MISMATCH':decision=Decision('Stop',reason='frame clock domain changed or unknown')
            elif assessment.reason=='STREAM_CHANGED':decision=Decision('Stop',reason='camera/video stream changed during task')
            elif t-last_valid>=ctrlcfg.no_detection_timeout_s:decision=Decision('Stop',reason='no reliable droplet timeout')
            if not math.isfinite(t) or obs.error=='INVALID_TIMESTAMP':decision=Decision('Stop',reason='invalid frame timestamp')
            if mode!='offline' and (packet.timing is None or packet.timing.clock_domain=='host_monotonic') and time.monotonic()-t>config['source']['frame_timeout_s']:
                decision=Decision('Stop',reason='camera frame stale after processing')
            if emergency():decision=Decision('Stop',reason='emergency stop')
            progress_status=controller.progress.status
            transport_retries_before=controller.retry_total;recoveries_before=controller.recovery_total
            if decision.action in {'Update','Complete'}:
                causality=('offline_replay' if mode=='offline' else
                           'exposure_order_verified' if epoch_exposure_verified else 'causality_unknown')
                arrival=ArrivalEvent.from_window(context,recognizer.window,time.monotonic_ns(),
                    packet.timestamp_clock_domain,causality)
                consumed=ledger.consume(arrival)
                logger.write('arrivals',{'event_id':arrival.event_id,'run_id':run_id,
                    'step_index':context.step_index,'attempt_index':context.attempt_index,'epoch':context.epoch,
                    'source_id':sid,'target_id':tid,'first_frame_id':arrival.first_frame_id,'last_frame_id':arrival.last_frame_id,
                    'evidence_start_s':arrival.evidence_start_s,'evidence_end_s':arrival.evidence_end_s,
                    'confirmed_at_ns':arrival.confirmed_at_ns,'evidence_clock_domain':arrival.evidence_clock_domain,
                    'applied_receive_ns':context.applied_receive_ns,'applied_clock_domain':context.clock_domain,
                    'causality':arrival.causality,'consumed':consumed,
                    'software_barrier_ns':context.software_barrier_ns,'applied_time_quality':context.applied_time_quality,
                    'transport_retry_total':controller.retry_total,'recovery_total':controller.recovery_total,
                    'communication_retry_total':communication_retry_total})
                if not consumed:decision=Decision('Hold',reason='arrival event already consumed or stale')
            if decision.action in {'Update','Complete'}:close_step(t,True,state,decision.reason)
            decision_ended=time.perf_counter_ns();command_submit_ns=time.perf_counter_ns()
            try:command=actuator.execute(decision)
            except Exception as exc:command=CommandResult(sent=mode=='experiment',accepted=False,error=str(exc))
            command_return_ns=time.perf_counter_ns()
            command_log(t,decision.action,command)
            if decision.action=='Update':communication_retry_total=0
            communication_retry_total+=command.communication_retries
            applied_at=(t if mode=='offline' else command.applied_monotonic_ns/1e9
                        if command.applied_monotonic_ns is not None else time.monotonic())
            if command.accepted:
                controller.accept(decision,applied_at)
                if decision.action=='Update':step_open=True
                if decision.action in {'Start','Update','Retry','Recovery'}:
                    evidence_epoch+=1
                    attempt_index=0 if decision.action in {'Start','Update'} else attempt_index+1 if decision.action=='Retry' else attempt_index
                    context=StepContext(run_id,controller.index,attempt_index,evidence_epoch,controller.source,controller.target,
                        applied_receive_ns=command.applied_monotonic_ns if mode=='experiment' else None,
                        clock_domain=packet.timestamp_clock_domain if mode=='offline' else 'host_monotonic',phase=controller.phase,
                        applied_timestamp_s=applied_at if mode=='offline' else None,
                        software_barrier_ns=int(applied_at*1e9) if mode!='offline' else None,
                        applied_time_quality='ack_receive' if mode=='experiment' and command.applied_monotonic_ns is not None
                            else 'command_return_estimate' if mode=='experiment' else 'simulated_acceptance')
                    ledger.activate(context);epoch_exposure_verified=True
                    recognizer.reset();gate.reset();prior.reset()
            elif decision.action=='Update':
                logger.write('steps',{'experiment_id':experiment_id,'step_index':controller.index+1,
                    'source_electrode':tid,'target_electrode':decision.target,'step_start_time':t,
                    'step_end_time':t,'transport_time':0,'success':False,'retry_total':0,'recovery_total':0,
                    'final_state':S.UNKNOWN.value,'reason':'next step command rejected: '+command.error,
                    'attempt_index':0,'epoch':evidence_epoch+1,'arrival_event_id':'',
                    'clock_domain':context.clock_domain,'communication_retry_total':communication_retry_total,
                    'applied_time_quality':'command_rejected'})
            row={'experiment_id':experiment_id,'frame_id':packet.frame_id,'timestamp':t,
                'timestamp_source':packet.timestamp_source,'source_electrode':sid,'target_electrode':tid,
                'centroid_x':obs.centroid[0] if obs.centroid else None,'centroid_y':obs.centroid[1] if obs.centroid else None,
                'droplet_area':obs.area,'eta_source':obs.eta_source,'eta_target':obs.eta_target,
                'distance_to_target':obs.distance,'velocity':obs.velocity,'predicted_position':json.dumps(obs.predicted_position),
                'recognized_state':state.value,'event_action':decision.action,'retry_count':controller.retry_count,
                'command_id':command.command_id,'command_sent':command.sent,'command_accepted':command.accepted,
                'phase':phase,'spatial_ok':obs.spatial_ok,'temporal_ok':obs.temporal_ok,
                'observation_quality':quality,'state_reason':state_reason,
                'progress_status':progress_status,
                'error':command.error or error or obs.error,'reason':decision.reason,
                'pipeline_ms':(time.perf_counter()-started)*1000,
                'step_index':frame_context.step_index,'attempt_index':frame_context.attempt_index,'epoch':frame_context.epoch,
                'capture_frame_id':packet.timing.capture_frame_id if packet.timing else None,
                'device_ticks_raw':packet.timing.device_ticks_raw if packet.timing else None,
                'receive_monotonic_ns':packet.timing.receive_monotonic_ns if packet.timing else None,
                'receive_perf_counter_ns':packet.timing.receive_perf_counter_ns if packet.timing else None,
                'clock_domain':packet.timestamp_clock_domain,
                'timing_quality':packet.timing.timing_quality if packet.timing else 'legacy_unverified',
                'queue_overwrites':queue_overwrites,'causality':assessment.causality,
                'arrival_event_id':arrival.event_id if arrival else '',
                'applied_receive_ns':frame_context.applied_receive_ns,
                'software_barrier_ns':frame_context.software_barrier_ns,'applied_time_quality':frame_context.applied_time_quality}
            row.update(run_id=run_id,sdk_host_timestamp_raw=packet.timing.sdk_host_timestamp_raw if packet.timing else None,
                receive_utc_ns=packet.timing.receive_utc_ns if packet.timing else None,
                relative_anchor_perf_counter_ns=packet.timing.relative_anchor_perf_counter_ns if packet.timing else None,
                exposure_start_ns=packet.timing.exposure_start_ns if packet.timing else None,
                exposure_clock_domain=packet.timing.exposure_clock_domain if packet.timing else 'unknown',
                transport_retry_total=transport_retries_before,recovery_total=recoveries_before,
                communication_retries=command.communication_retries)
            row.update(rho_target=obs.rho_target,source_intersection_px=obs.source_intersection_px,
                target_intersection_px=obs.target_intersection_px,progress_mm=obs.progress_mm,
                progress_fraction=obs.progress_fraction,lateral_error_mm=obs.lateral_error_mm,
                velocity_parallel_mm_s=obs.velocity_parallel_mm_s,target_position_ok=obs.target_position_ok,
                geometry_quality=obs.geometry_quality)
            logger.write('frames',row);processed+=1
            # Invalid external masks are not passed to OpenCV visualization.
            if obs.error=='INVALID_MASK':result=VisionResult(None,None,None,0,0,False,obs.error)
            image_started=time.perf_counter_ns()
            timing_error=''
            received=packet.timing.receive_perf_counter_ns if packet.timing and mode!='offline' and packet.timing.clock_domain=='host_monotonic' else None
            queue_ms=(ingest_perf_ns-received)/1e6 if received is not None and received<=ingest_perf_ns else None
            queue_clock='host_perf_counter' if queue_ms is not None else ''
            if queue_ms is None and mode!='offline' and packet.timing and packet.timing.clock_domain=='host_monotonic':
                received_mono=packet.timing.receive_monotonic_ns
                if received_mono is not None and received_mono<=ingest_ns:
                    queue_ms=(ingest_ns-received_mono)/1e6;queue_clock='host_monotonic'
            if received is not None and queue_ms is None:timing_error='receive stamp later than ingest'
            ack_ms=None
            if command.requested_perf_counter_ns is not None and command.applied_perf_counter_ns is not None:
                if command.applied_perf_counter_ns>=command.requested_perf_counter_ns:
                    ack_ms=(command.applied_perf_counter_ns-command.requested_perf_counter_ns)/1e6
                else:timing_error='APPLIED precedes request in host clock'
            try:logger.images(packet,result,electrode_map,sid,tid,state.value,decision.action,config['recording'])
            finally:
                ended=time.perf_counter_ns()
                logger.write('latencies',{'frame_id':packet.frame_id,'step_index':frame_context.step_index,
                    'attempt_index':frame_context.attempt_index,'epoch':frame_context.epoch,
                    'timing_quality':row['timing_quality'],'clock_domain':'host_perf_counter',
                    'receive_to_ingest_ms':queue_ms,'receive_to_ingest_clock_domain':queue_clock,
                    'ingest_to_segmentation_ms':(segment_started-ingest_perf_ns)/1e6,
                    'segmentation_ms':(segment_ended-segment_started)/1e6,
                    'features_ms':(features_ended-segment_ended)/1e6,'decision_ms':(decision_ended-features_ended)/1e6,
                    'transaction_ms':(command_return_ns-command_submit_ns)/1e6,'command_to_applied_ms':ack_ms,
                    'image_write_ms':(ended-image_started)/1e6,'pipeline_with_images_ms':(ended-ingest_perf_ns)/1e6,
                    'ingest_monotonic_ns':ingest_ns,'ingest_perf_counter_ns':ingest_perf_ns,
                    'decision_perf_counter_ns':decision_ended,'command_submit_perf_counter_ns':command_submit_ns,
                    'command_return_perf_counter_ns':command_return_ns,
                    'segmentation_start_perf_counter_ns':segment_started,'segmentation_end_perf_counter_ns':segment_ended,
                    'features_end_perf_counter_ns':features_ended,'timing_error':timing_error})
            if on_frame is not None:on_frame(row,packet,result,electrode_map)
            if not command.accepted:status='error';reason=command.error or 'command failed';break
            if decision.action=='Stop':status='stopped';reason=decision.reason;break
            if controller.complete:status='complete';reason='transport complete';break
            if emergency():status='stopped';reason='experiment stop requested';break
        if step_open:close_step(last_task_time,False,last_state,reason)
    except (Exception,KeyboardInterrupt) as exc:
        status='stopped' if isinstance(exc,(KeyboardInterrupt,InterruptedError)) else 'error'
        reason=str(exc) or type(exc).__name__
        if step_open:close_step(last_task_time,False,last_state,reason)
    finally:
        # Release AM output even if image recording, source capture or logging fails.
        if actuator is not None:
            try:
                release=actuator.close();command_log(last_task_time,'Shutdown release',release)
                release_confirmed=release.accepted
                if not release.accepted:status='error';reason=reason+'; '+release.error
            except Exception as exc:status='error';reason=reason+'; shutdown: '+str(exc)
        if source is not None:
            try:source.close()
            except Exception as exc:status='error';reason=reason+'; source close: '+str(exc)
        if logger.electrode_log is not None:
            logger.electrode_log.close()
            if logger.electrode_log.error:status='error';reason+='; '+logger.electrode_log.error
        report={'experiment_id':experiment_id,'run_id':run_id,'mode':mode,'status':status,'reason':reason,'frames':processed,
            'arrival_events_consumed':len(ledger.consumed_steps),'physical_timing_validated':False,
            'release_confirmed':release_confirmed,
            'output_dir':config['output_dir'],'synthetic_test_only':config.get('synthetic_test_only',False)}
        try:logger.summary(report)
        finally:logger.close()
    return report
