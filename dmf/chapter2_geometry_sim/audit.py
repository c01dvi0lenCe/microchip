"""Independent persisted-data audit: does not import world, gates or runner."""
import csv
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def audit_trial(root):
    root=Path(root)
    m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    failures=[]
    def check(ok,label):
        if not ok:failures.append(label)
    for name,value in m['artifacts'].items():
        p=root/name
        check(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==value,f'artifact_hash:{name}')
    world=read_rows(root/'world.csv');obs=read_rows(root/'observations.csv');events=read_rows(root/'events.csv')
    shapes=json.loads((root/'world_polygons.json').read_text(encoding='utf-8'))
    raster=json.loads((root/'raster.json').read_text(encoding='utf-8'))
    design=json.loads((root/'map_snapshot.json').read_text(encoding='utf-8'))
    by_id={e['control_id']:Polygon(e['polygon_map_mm']) for e in design['electrodes']}
    check(len(by_id)==420 and set(by_id)==set(range(1,421)),'420_map_identity')
    check(hashlib.sha256((root/'map_snapshot.json').read_bytes()).hexdigest()==m['source_map_sha256'],'source_map_hash')
    check(hashlib.sha256(Path(m['source_map_path']).read_bytes()).hexdigest()==m['source_map_sha256'],'original_map_unchanged')
    requests=[r for r in events if r['event']=='request'];applied=[r for r in events if r['event']=='simulated_applied']
    check(len(requests)==1 and requests[0]['target']=='191' and abs(float(requests[0]['time_s'])-.5)<1e-9,'one_request_191_at_0.5')
    check(len(applied)==1 and applied[0]['target']=='191' and abs(float(applied[0]['time_s'])-.54)<1e-9,'one_simulated_applied_191_at_0.54')
    check(not any(r.get('target')=='192' for r in events),'no_192')
    check(len(world)==301 and len(shapes)==301 and len(obs)==60,'full_tick_and_frame_counts')
    check(len({r['frame_id'] for r in obs})==len(obs),'unique_frames')
    geometric_area_error=0.;movement_before_response=False
    for i,(row,shape) in enumerate(zip(world,shapes)):
        t=float(row['time_s']);p=Polygon(shape['polygon_mm'])
        check(abs(t-shape['time_s'])<1e-9,'polygon_tick_identity')
        geometric_area_error=max(geometric_area_error,abs(p.area/(4*math.pi)-1))
        check(abs(p.centroid.x-float(row['x_mm']))<1e-8 and abs(p.centroid.y-float(row['y_mm']))<1e-8,'polygon_centroid')
        if i:
            old=world[i-1];dt=t-float(old['time_s'])
            step=math.hypot(float(row['x_mm'])-float(old['x_mm']),float(row['y_mm'])-float(old['y_mm']))
            check(dt>0 and step<=4.8*dt+1e-8,'finite_speed_and_monotone_time')
            movement_before_response|=t<=.72+1e-9 and step>1e-8
            if step>1e-8:
                check(Polygon(shapes[i-1]['polygon_mm']).intersection(by_id[int(row['active'])]).area>0,'motion_requires_overlap')
    check(not movement_before_response,'no_motion_before_response')
    check(geometric_area_error<=.005,'area_preservation')
    lower=np.array(raster['lower_mm']);scale=float(raster['pixels_per_mm']);height,width=raster['shape']
    x=lower[0]+(np.arange(width)+.5)/scale;y=lower[1]+(np.arange(height)+.5)/scale
    regions={eid:contains_xy(by_id[eid],x[None,:],y[:,None]) for eid in (190,191)}
    source=np.array(by_id[190].centroid.coords[0]);target=np.array(by_id[191].centroid.coords[0]);u=(target-source)/np.linalg.norm(target-source)
    max_mask_error=0.;single_time=window_time=full_time=None;suffix=[];full_suffix=[];last_id=last_t=None;history=None
    expected_single=[];expected_window=[]
    for row in obs:
        mask=cv2.imdecode(np.frombuffer((root/row['mask_path']).read_bytes(),np.uint8),0)>0
        ys,xs=np.nonzero(mask);n=len(xs)
        check(n>0,'nonempty_observed_mask')
        point=lower+(np.array([xs.mean(),ys.mean()])+.5)/scale
        values=dict(area_mm2=n/scale**2,x_mm=point[0],y_mm=point[1],distance_mm=np.linalg.norm(point-target),progress_mm=(point-source)@u)
        for name,eid in (('source',190),('target',191)):
            a=np.count_nonzero(mask&regions[eid]);values[f'eta_{name}']=a/n;values[f'rho_{name}']=a/regions[eid].sum()
        for name,value in values.items():check(abs(float(row[name])-value)<1e-8,f'Mask_feature:{name}:frame{row["frame_id"]}')
        max_mask_error=max(max_mask_error,abs(values['area_mm2']/(4*math.pi)-1))
        t=float(row['exposure_start_s']);fid=int(row['frame_id']);processed=float(row['processed_at_s'])
        check(processed+1e-9>=float(row['available_s'])>=float(row['exposure_end_s'])>=t,'exposure_available_processing_order')
        valid=row['captured_epoch']=='1' and t>=.54-1e-9
        if last_id is not None and (fid<=last_id or t<=last_t):valid=False
        eligible=valid and values['rho_target']>=.9 and values['eta_source']<=.08
        check((row['eligible']=='True')==eligible,f'causal_gate:frame{fid}')
        quality=cv2.connectedComponents(mask.astype(np.uint8))[0]==2 and not (mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any())
        spatial=values['distance_mm']<=.576
        historical=True
        if valid:
            if history is not None and 0<t-history[0]<=.18:
                historical=float(np.linalg.norm(point-history[1]))/(t-history[0])<=19.2
            history=(t,point)
        else:history=None
        check((row['raw_S']=='True')==spatial,f'spatial_gate:frame{fid}')
        check((row['raw_K']=='True')==historical,f'history_gate:frame{fid}')
        if last_id is not None and (fid!=last_id+1 or t-last_t>.18+1e-9):suffix=[];full_suffix=[]
        if eligible:
            if single_time is None:single_time=processed;expected_single.append(fid)
        if eligible and quality:suffix.append(t)
        else:suffix=[]
        if eligible and quality and spatial and historical:full_suffix.append(t)
        else:full_suffix=[]
        if window_time is None and len(suffix)>=5 and suffix[-1]-suffix[0]>=.25-1e-9:
            window_time=processed;expected_window.append(fid)
        if full_time is None and len(full_suffix)>=5 and full_suffix[-1]-full_suffix[0]>=.25-1e-9:full_time=processed
        last_id,last_t=fid,t
    check(max_mask_error<=.02,'Mask_area_error_under_2_percent')
    for event_name,expected in (('single_confirmation',single_time),('window_confirmation',window_time),('spatiotemporal_confirmation',full_time)):
        actual=[r for r in events if r['event']==event_name]
        check((expected is None and not actual) or (expected is not None and len(actual)==1 and abs(float(actual[0]['time_s'])-expected)<1e-9),f'independent_{event_name}')
    # Reference is recalculated here without importing the reference implementation.
    reference_start=reference_time=None
    for row in world:
        t=float(row['time_s']);distance=math.hypot(float(row['x_mm'])-target[0],float(row['y_mm'])-target[1])
        valid=t>=.54 and int(row['active'])==191 and distance<=.288 and float(row['speed_mm_s'])<=.192
        if not valid:reference_start=None
        elif reference_start is None:reference_start=t
        if valid and reference_time is None and t-reference_start>=.15-1e-9:reference_time=t
    r=json.loads((root/'reference.json').read_text(encoding='utf-8'))
    check(r['confirmed_s']==reference_time,'independent_reference_recalculation')
    return dict(passed=not failures,failures=failures,trial_id=m['trial_id'],world_ticks=len(world),masks=len(obs),
                geometric_area_relative_error=geometric_area_error,mask_area_relative_error=max_mask_error,
                single_confirmation_s=single_time,window_confirmation_s=window_time,reference_confirmation_s=reference_time,
                spatiotemporal_confirmation_s=full_time,
                scope='one_normal_mechanism_trial_no_performance_claim')
