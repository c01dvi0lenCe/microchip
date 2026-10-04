"""Streaming audit logs and optional images; never retain a run in memory."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import yaml
from dmf.vision.image_io import write_image
from .overlay import render_overlay

FRAME_COLUMNS=('experiment_id','frame_id','timestamp','timestamp_source','source_electrode','target_electrode',
    'centroid_x','centroid_y','droplet_area','eta_source','eta_target','distance_to_target','velocity',
    'predicted_position','recognized_state','event_action','retry_count','command_id','command_sent',
    'command_accepted','phase','spatial_ok','temporal_ok','error','reason','pipeline_ms')
STEP_COLUMNS=('experiment_id','step_index','source_electrode','target_electrode','step_start_time','step_end_time',
    'transport_time','success','retry_total','recovery_total','final_state','reason')
COMMAND_COLUMNS=('timestamp','command_id','action','changes','command_sent','accepted','error')


class ExperimentLogger:
    def __init__(self,config):
        self.root=Path(config['output_dir']);self.root.mkdir(parents=True,exist_ok=True)
        if (self.root/'frames.csv').exists():raise FileExistsError('output_dir already contains a run; select a new directory')
        self.handles=[];self.writers={}
        try:
            for name,columns in [('frames',FRAME_COLUMNS),('steps',STEP_COLUMNS),('commands',COMMAND_COLUMNS)]:
                handle=(self.root/(name+'.csv')).open('x',encoding='utf-8',newline='');self.handles.append(handle)
                writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();self.writers[name]=writer
            (self.root/'config_snapshot.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf8')
            shutil.copy2(config['electrode_map'],self.root/'electrode_map_snapshot.yaml')
            model=config['segmentation'].get('model_path')
            if model and Path(model).is_file():
                with Path(model).open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                (self.root/'model_sha256.txt').write_text(digest+'\n',encoding='ascii')
        except Exception:self.close();raise

    def write(self,table,row):
        self.writers[table].writerow(row)
        self.flush()
    def flush(self):
        for f in self.handles:f.flush()
    def summary(self,payload):
        (self.root/'summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    def close(self):
        for f in self.handles:f.close()

    def images(self,packet,result,electrode_map,source,target,state,action,recording):
        images={}
        if recording.get('raw'):images['raw']=packet.image_bgr
        if recording.get('mask') and result.mask is not None:images['mask']=result.mask
        if recording.get('overlay'):
            images['overlay']=render_overlay(packet,result,electrode_map,source,target,state,action)
        for name,img in images.items():
            folder=self.root/name;folder.mkdir(exist_ok=True)
            if not write_image(folder/f'{packet.frame_id:06d}.png',img):raise OSError('image recording failed')
