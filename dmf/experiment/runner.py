"""One explicit experiment loop for video, dry-run live camera, and AM hardware."""
from pathlib import Path
import json
import time
import math
from dataclasses import asdict
from dmf.vision.config import load_electrode_map
from dmf.vision.contracts import DropletState as S, VisionResult
from .config import load_config, StateConfig, ControlConfig
from .perception import PriorFeatures, StateRecognizer, Observation
from .policy import EventController, Decision
from .segmenter import build_segmenter
from .sources import VideoSource, LiveSource
from .actuator import AMActuator, CommandResult
from .logging import ExperimentLogger


class Confirmation:
    def __init__(self,frames,duration):self.frames=frames;self.duration=duration;self.reset()
    def reset(self):self.count=0;self.start=None
    def observe(self,ok,t):
        if not ok:self.reset();return False
        if self.start is None:self.start=t
        self.count+=1
        return self.count>=self.frames and t-self.start+1e-9>=self.duration


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
    gate=Confirmation(ctrlcfg.source_frames,ctrlcfg.source_duration_s)
    logger=ExperimentLogger(config)
    experiment_id=str(config.get('experiment_id') or Path(config['output_dir']).name)
    source=None;actuator=None;packet=None;step_open=False;last_state=S.UNKNOWN;release_confirmed=None
    status='incomplete';reason='end of video';processed=0;last_valid=None;first_time=None;last_applied=None
    emergency_path=Path(config['emergency_stop_file']) if config.get('emergency_stop_file') else None
    emergency=lambda:bool((stop_event is not None and stop_event.is_set()) or
                          (emergency_path and emergency_path.exists()))

    def command_log(t,action,result):
        if result.command_id!='':
            logger.write('commands',{'timestamp':t,'command_id':result.command_id,'action':action,
                'changes':json.dumps(result.changes or {},sort_keys=True),'command_sent':result.sent,
                'accepted':result.accepted,'error':result.error})

    def close_step(t,success,state,why):
        nonlocal step_open
        start=controller.step_started if controller.step_started is not None else first_time
        logger.write('steps',{'experiment_id':experiment_id,'step_index':controller.index,
            'source_electrode':controller.source,'target_electrode':controller.target,
            'step_start_time':start,'step_end_time':t,'transport_time':t-start if start is not None else None,
            'success':success,'retry_total':controller.retry_total,'recovery_total':controller.recovery_total,
            'final_state':state.value,'reason':why})
        step_open=False

    try:
        if emergency():raise InterruptedError('experiment stop requested')
        segmenter=(segmenter_factory or build_segmenter)(config)
        if emergency():raise InterruptedError('experiment stop requested')
        source=(source_factory(config) if source_factory else
                VideoSource(config['source']) if mode=='offline' else LiveSource(config['source']))
        if emergency():raise InterruptedError('experiment stop requested')
        hwconfig=dict(config);hwconfig['_emergency']=emergency
        actuator=(actuator_factory or AMActuator)(mode,hwconfig)
        if mode=='experiment':command_log(time.monotonic(),'Startup release',CommandResult('ALL_OFF',True,True,changes={}))
        for packet in source:
            started=time.perf_counter();t=packet.timestamp_s
            if first_time is None:first_time=t;last_valid=t;step_open=True
            sid,tid=controller.source,controller.target;phase=controller.phase
            if emergency():raise InterruptedError('experiment stop requested')
            # Do not use a frame acquired before the electrical state was applied.
            before_apply=(mode!='offline' and last_applied is not None and t<last_applied)
            error=''
            try:result=segmenter.process(packet)
            except Exception as exc:result=VisionResult(None,None,None,0,0,False,'SEGMENTATION_ERROR');error=str(exc)
            obs=(Observation(error='PRE_ACTUATION_FRAME') if before_apply else
                 prior.extract(packet,result,sid,tid,config['candidate_electrodes']))
            state=recognizer.recognize(obs,t);last_state=state
            if obs.valid:last_valid=t
            confirmed=gate.observe(obs.valid and obs.spatial_ok and obs.temporal_ok and
                obs.eta_source>=statecfg.eta_arr and obs.eta_target<=statecfg.eta_release,t)
            decision=(Decision('Hold',reason='frame acquired before command applied') if before_apply else
                      controller.decide(state,t,source_confirmed=confirmed))
            if t-last_valid>=ctrlcfg.no_detection_timeout_s:decision=Decision('Stop',reason='no reliable droplet timeout')
            if not math.isfinite(t) or obs.error=='INVALID_TIMESTAMP':decision=Decision('Stop',reason='invalid frame timestamp')
            if mode!='offline' and time.monotonic()-t>config['source']['frame_timeout_s']:
                decision=Decision('Stop',reason='camera frame stale after processing')
            if emergency():decision=Decision('Stop',reason='emergency stop')
            if decision.action in {'Update','Complete'}:close_step(t,True,state,decision.reason)
            try:command=actuator.execute(decision)
            except Exception as exc:command=CommandResult(sent=mode=='experiment',accepted=False,error=str(exc))
            command_log(t,decision.action,command)
            applied_at=t if mode=='offline' else time.monotonic()
            if command.accepted:
                controller.accept(decision,applied_at)
                if decision.target is not None:last_applied=applied_at
                if decision.action=='Update':step_open=True
                if decision.action in {'Start','Update','Retry','Recovery'}:recognizer.reset();gate.reset()
            elif decision.action=='Update':
                logger.write('steps',{'experiment_id':experiment_id,'step_index':controller.index+1,
                    'source_electrode':tid,'target_electrode':decision.target,'step_start_time':t,
                    'step_end_time':t,'transport_time':0,'success':False,'retry_total':0,'recovery_total':0,
                    'final_state':S.UNKNOWN.value,'reason':'next step command rejected: '+command.error})
            row={'experiment_id':experiment_id,'frame_id':packet.frame_id,'timestamp':t,
                'timestamp_source':packet.timestamp_source,'source_electrode':sid,'target_electrode':tid,
                'centroid_x':obs.centroid[0] if obs.centroid else None,'centroid_y':obs.centroid[1] if obs.centroid else None,
                'droplet_area':obs.area,'eta_source':obs.eta_source,'eta_target':obs.eta_target,
                'distance_to_target':obs.distance,'velocity':obs.velocity,'predicted_position':json.dumps(obs.predicted_position),
                'recognized_state':state.value,'event_action':decision.action,'retry_count':controller.retry_count,
                'command_id':command.command_id,'command_sent':command.sent,'command_accepted':command.accepted,
                'phase':phase,'spatial_ok':obs.spatial_ok,'temporal_ok':obs.temporal_ok,
                'error':command.error or error or obs.error,'reason':decision.reason,
                'pipeline_ms':(time.perf_counter()-started)*1000}
            logger.write('frames',row);processed+=1
            # Invalid external masks are not passed to OpenCV visualization.
            if obs.error=='INVALID_MASK':result=VisionResult(None,None,None,0,0,False,obs.error)
            logger.images(packet,result,electrode_map,sid,tid,state.value,decision.action,config['recording'])
            if on_frame is not None:on_frame(row,packet,result,electrode_map)
            if not command.accepted:status='error';reason=command.error or 'command failed';break
            if decision.action=='Stop':status='stopped';reason=decision.reason;break
            if controller.complete:status='complete';reason='transport complete';break
            if emergency():status='stopped';reason='experiment stop requested';break
        if step_open:close_step(packet.timestamp_s if packet else first_time,False,last_state,reason)
    except (Exception,KeyboardInterrupt) as exc:
        status='stopped' if isinstance(exc,(KeyboardInterrupt,InterruptedError)) else 'error'
        reason=str(exc) or type(exc).__name__
        if step_open:close_step(packet.timestamp_s if packet else first_time,False,last_state,reason)
    finally:
        # Release AM output even if image recording, source capture or logging fails.
        if actuator is not None:
            try:
                release=actuator.close();command_log(packet.timestamp_s if packet else None,'Shutdown release',release)
                release_confirmed=release.accepted
                if not release.accepted:status='error';reason=reason+'; '+release.error
            except Exception as exc:status='error';reason=reason+'; shutdown: '+str(exc)
        if source is not None:
            try:source.close()
            except Exception as exc:status='error';reason=reason+'; source close: '+str(exc)
        report={'experiment_id':experiment_id,'mode':mode,'status':status,'reason':reason,'frames':processed,
            'release_confirmed':release_confirmed,
            'output_dir':config['output_dir'],'synthetic_test_only':config.get('synthetic_test_only',False)}
        try:logger.summary(report)
        finally:logger.close()
    return report
