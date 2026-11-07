"""Streaming audit logs and optional images; never retain a run in memory."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import yaml
from dmf.vision.image_io import write_image
from .overlay import render_overlay
from dmf.recording import AsyncCsvLog, EVENT_FIELDS, event_row

FRAME_COLUMNS=('experiment_id','frame_id','timestamp','timestamp_source','source_electrode','target_electrode',
    'centroid_x','centroid_y','droplet_area','eta_source','eta_target','distance_to_target','velocity',
    'predicted_position','recognized_state','event_action','retry_count','command_id','command_sent',
    'command_accepted','phase','spatial_ok','temporal_ok','error','reason','pipeline_ms',
    'observation_quality','state_reason','progress_status',
    'step_index','attempt_index','epoch','capture_frame_id','device_ticks_raw',
    'receive_monotonic_ns','receive_perf_counter_ns','clock_domain','timing_quality',
    'queue_overwrites','causality','arrival_event_id','applied_receive_ns',
    'software_barrier_ns','applied_time_quality',
    'run_id','sdk_host_timestamp_raw','receive_utc_ns','relative_anchor_perf_counter_ns',
    'exposure_start_ns','exposure_clock_domain','transport_retry_total','recovery_total','communication_retries',
    'rho_target','source_intersection_px','target_intersection_px','progress_mm',
    'progress_fraction','lateral_error_mm','velocity_parallel_mm_s','target_position_ok','geometry_quality')
STEP_COLUMNS=('experiment_id','step_index','source_electrode','target_electrode','step_start_time','step_end_time',
    'transport_time','success','retry_total','recovery_total','final_state','reason',
    'attempt_index','epoch','arrival_event_id','clock_domain','communication_retry_total','applied_time_quality')
COMMAND_COLUMNS=('timestamp','command_id','action','changes','command_sent','accepted','error',
    'request_id','applied_monotonic_ns','applied_perf_counter_ns','requested_perf_counter_ns',
    'communication_retries','simulated','step_index','attempt_index','epoch','clock_domain',
    'requested_step_index','requested_attempt_index','requested_epoch','caused_by_arrival_event_id')
ARRIVAL_COLUMNS=('event_id','run_id','step_index','attempt_index','epoch','source_id','target_id',
    'first_frame_id','last_frame_id','evidence_start_s','evidence_end_s','confirmed_at_ns',
    'evidence_clock_domain','applied_receive_ns','applied_clock_domain','causality','consumed',
    'software_barrier_ns','applied_time_quality',
    'transport_retry_total','recovery_total','communication_retry_total')
LATENCY_COLUMNS=('frame_id','step_index','attempt_index','epoch','timing_quality','clock_domain',
    'receive_to_ingest_ms','receive_to_ingest_clock_domain','ingest_to_segmentation_ms',
    'segmentation_ms','features_ms','decision_ms','transaction_ms',
    'command_to_applied_ms','image_write_ms','pipeline_with_images_ms',
    'ingest_monotonic_ns','ingest_perf_counter_ns','decision_perf_counter_ns','command_submit_perf_counter_ns',
    'command_return_perf_counter_ns','segmentation_start_perf_counter_ns','segmentation_end_perf_counter_ns',
    'features_end_perf_counter_ns','timing_error')


class ExperimentLogger:
    def __init__(self,config):
        self.root=Path(config['output_dir']);self.root.mkdir(parents=True,exist_ok=True)
        if (self.root/'frames.csv').exists():raise FileExistsError('output_dir already contains a run; select a new directory')
        self.handles=[];self.writers={}
        self.electrode_log=None
        try:
            for name,columns in [('frames',FRAME_COLUMNS),('steps',STEP_COLUMNS),('commands',COMMAND_COLUMNS),
                                 ('arrivals',ARRIVAL_COLUMNS),('latencies',LATENCY_COLUMNS)]:
                handle=(self.root/(name+'.csv')).open('x',encoding='utf-8',newline='');self.handles.append(handle)
                writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();self.writers[name]=writer
            (self.root/'config_snapshot.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf8')
            self.electrode_log=AsyncCsvLog({'events':(self.root/'electrode_events.csv',EVENT_FIELDS)})
            shutil.copy2(config['electrode_map'],self.root/'electrode_map_snapshot.yaml')
            (self.root/'log_schema.json').write_text(json.dumps({
                'schema_version':2,'position_unit':'mm','software_duration_unit':'ms',
                'frame_timestamp':'source-relative for offline; host monotonic seconds for live',
                'host_duration_clock':'host_perf_counter','applied':'ACK software receive only',
                'exposure_causality':'unknown unless explicit same-domain exposure mapping is supplied',
                'pipeline_ms_scope':'ingest through command return, excludes image writes',
                'simulation_ack':'offline/dry_run acceptance is not a real APPLIED ACK'},indent=2),encoding='utf8')
            model=config['segmentation'].get('model_path')
            if model and Path(model).is_file():
                with Path(model).open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                (self.root/'model_sha256.txt').write_text(digest+'\n',encoding='ascii')
        except Exception:self.close();raise

    def write(self,table,row):
        if self.electrode_log and self.electrode_log.error:raise OSError(self.electrode_log.error)
        self.writers[table].writerow(row)
        self.flush()
    def flush(self):
        for f in self.handles:f.flush()
    def summary(self,payload):
        (self.root/'summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    def close(self):
        for f in self.handles:f.close()
        if self.electrode_log:
            self.electrode_log.close()

    def transaction_event(self,event):
        self.electrode_log.append('events',event_row(event))

    def images(self,packet,result,electrode_map,source,target,state,action,recording):
        images={}
        if recording.get('raw'):images['raw']=packet.image_bgr
        if recording.get('mask') and result.mask is not None:images['mask']=result.mask
        if recording.get('overlay'):
            images['overlay']=render_overlay(packet,result,electrode_map,source,target,state,action)
        for name,img in images.items():
            folder=self.root/name;folder.mkdir(exist_ok=True)
            if not write_image(folder/f'{packet.frame_id:06d}.png',img):raise OSError('image recording failed')
