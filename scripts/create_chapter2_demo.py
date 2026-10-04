"""Create reproducible synthetic video fixtures, explicitly not experimental data."""
import argparse
from pathlib import Path
import cv2
import numpy as np
import yaml


def create_demo(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    geometry={'rows':20,'cols':20,'pitch_mm':1.,'core_corners_px':[[0,0],[400,0],[400,400],[0,400]]}
    (folder/'map.yaml').write_text(yaml.safe_dump(geometry),encoding='utf8')
    normal=[(190,190,6,6)]*3+[(193,190,6,6),(195,190,6,6)]+[(200,190,12,6)]*2+[(210,190,6,6)]*3
    normal +=[(213,190,6,6),(215,190,6,6)]+[(220,190,12,6)]*2+[(230,190,6,6)]*3
    faults=[(190,190,6,6)]*9+[(215,160,6,6)]*2+[(190,190,6,6)]*3+[(215,160,6,6)]*3
    outputs=[]
    for scenario,points in [('transport',normal),('recovery',faults)]:
        video=folder/(scenario+'.avi')
        writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(400,400))
        if not writer.isOpened():raise RuntimeError('MJPG writer unavailable')
        for x,y,rx,ry in points:
            frame=np.full((400,400,3),255,np.uint8)
            cv2.ellipse(frame,(x,y),(rx,ry),0,0,360,(0,0,0),-1);writer.write(frame)
        writer.release()
        cfg={'experiment_id':'synthetic-'+scenario,'mode':'offline','synthetic_test_only':True,
            'route':[190,191,192] if scenario=='transport' else [190,191],
            'electrode_map':'map.yaml','output_dir':'output-'+scenario,'source':{'video':video.name},
            'segmentation':{'name':'threshold','parameters':{'color_space':'gray','lower':[0],'upper':[100],
                'min_area_px':3,'morphology_kernel':1}},
            'state':{'min_area_px':3,'consistency_frames':1,'arrival_frames':2,'arrival_duration_s':.1,
                'eta_arr':.7,'eta_release':.12,'v_th_mm_s':.1,'position_tolerance_mm':.05},
            'control':{'source_frames':1,'source_duration_s':0,'wait_s':1.5 if scenario=='transport' else .3,
                'max_retries':1,'max_recoveries':2},
            'recording':{'raw':False,'mask':True,'overlay':True}}
        path=folder/(scenario+'.yaml');path.write_text(yaml.safe_dump(cfg,sort_keys=False),encoding='utf8');outputs.append(path)
    return outputs


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='results/chapter2-demo')
    for output in create_demo(p.parse_args().output):print(output)
