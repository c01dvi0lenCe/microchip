"""Saved-data audit independent of recognition classes and scoring functions."""
import csv
import hashlib
import json
import math
from pathlib import Path
import cv2
import numpy as np
from shapely.geometry import Polygon


def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def flag(value):return value is True or value=='True'


def reference_from_world(rows,target):
    start=confirmed=previous=None;intervals=[]
    for row in rows:
        t=float(row['time_s'])
        good=(t>=.54 and int(float(row['active']))==191 and
            math.hypot(float(row['x_mm'])-target[0],float(row['y_mm'])-target[1])<=.288 and float(row['speed_mm_s'])<=.192)
        if not good or (previous is not None and t-previous>.0100001):
            if start is not None:intervals.append(dict(start_s=start,end_s=t,confirmed_s=confirmed))
            start=confirmed=None
        if good:
            if start is None:start=t
            if confirmed is None and t-start>=.15-1e-9:confirmed=t
        previous=t
    if start is not None:intervals.append(dict(start_s=start,end_s=previous,confirmed_s=confirmed))
    return dict(intervals=intervals)


def manual_first_event(rows,q,w,s,k):
    samples=[];last_id=last_t=None
    for r in rows:
        i=int(r['frame_id']);t=float(r['exposure_start_s'])
        if last_id is not None and (i<=last_id or t<=last_t):
            samples=[];continue
        if last_id is not None and (i!=last_id+1 or t-last_t>.18+1e-9):samples=[]
        last_id,last_t=i,t
        eligible=all(flag(r[name]) for name,enable in [('C0',True),('G',True),('Q',q),('S',s),('K',k)] if enable)
        if not eligible:samples=[];continue
        samples.append(t)
        if not w or (len(samples)>=5 and t-samples[0]>=.25-1e-9):return float(r['processed_at_s'])
    return None


def audit_development(root):
    root=Path(root);config=load(root/'config.json');manifest=load(root/'manifest.json')
    failures=[];checked_masks=checked_method_rows=0;counts=[]
    def require(ok,message):
        if not ok:failures.append(message)
    for p,digest in manifest['source_code'].items():require(sha(p)==digest,'source_hash:'+p)
    for rel,digest in manifest['artifacts'].items():require(sha(root/rel)==digest,'artifact_hash:'+rel)
    baseline=Path(manifest['source_baseline'])
    for rel,digest in load(root/'baseline_entries.json').items():require(sha(baseline/rel)==digest,'baseline_hash:'+rel)
    map_data=load(root/'map_snapshot.json')
    electrodes={e['control_id']:Polygon(e['polygon_map_mm']) for e in map_data['electrodes']}
    target=electrodes[191].centroid.coords[0]
    raster=load(root/'raster.json');lower=np.array(raster['lower_mm']);scale=raster['pixels_per_mm'];shape=raster['shape']
    xx=lower[0]+(np.arange(shape[1])+.5)/scale;yy=lower[1]+(np.arange(shape[0])+.5)/scale
    from shapely import contains_xy
    regions={n:contains_xy(electrodes[e],xx[None,:],yy[:,None]) for n,e in [('source',190),('target',191)]}
    references={}
    for kind in ('normal','slow','pause','stall'):
        folder=root/'worlds'/kind
        if (folder/'failure.json').exists():
            require(not (folder/'reference.json').exists(),'no_fabricated_reference:'+kind)
            continue
        world=read(folder/'internal_world.csv');saved=load(folder/'reference.json')
        ref=reference_from_world(world,target);references[kind]=ref
        require(len(world)==1001,'world_count:'+kind)
        require(ref['intervals']==saved['intervals'],'reference_intervals:'+kind)
        require(max(float(r['speed_mm_s']) for r in world)<=(.7 if kind=='slow' else 1.4)+1e-7,'speed_limit:'+kind)
        require(all(float(r['speed_mm_s'])<1e-9 for r in world if float(r['time_s'])<=.72+1e-9),'causal_motion:'+kind)
        if kind=='stall':require(not any(r['confirmed_s'] is not None for r in ref['intervals']),'stall_no_reference')
    planned=read(root/'planned_method_results.csv')
    require(len(planned)==96,'planned_method_denominator')
    require(len({(r['case_id'],r['method']) for r in planned})==96,'unique_plan')
    for case in config['cases']:
        name=case['name'];folder=root/'caches'/name
        if (folder/'failure.json').exists():
            records=[r for r in planned if r['case_id']==name]
            require(len(records)==6 and all(r['status']=='world_generation_failed' and flag(r['unattempted'])
                and r['reference_arrivals']=='' for r in records),'failed_case_denominators:'+name)
            counts.append(dict(case_id=name,status='world_generation_failed',raw_frames=0))
            continue
        meta=load(folder/'manifest.json')
        captures=read(folder/'captures.csv');by_id={int(r['frame_id']):r for r in captures}
        deliveries=read(folder/'deliveries.csv');raw=read(folder/'raw_observations.csv')
        require(len(captures)==200,'generated_samples:'+name)
        require(len(raw)==len(deliveries),'all_deliveries_processed:'+name)
        measures={}
        for r in captures:
            path=folder/r['mask_path'];require(sha(path)==r['mask_sha256'],'mask_hash:'+name+':'+r['frame_id'])
            mask=cv2.imdecode(np.fromfile(path,np.uint8),0)>0;ys,xs=np.nonzero(mask);checked_masks+=1
            if not len(xs):
                require(not flag(r['valid']),'empty_valid:'+name);measures[int(r['frame_id'])]=dict(valid=False);continue
            point=lower+(np.array([xs.mean(),ys.mean()])+.5)/scale
            x=dict(valid=True,x_mm=float(point[0]),y_mm=float(point[1]),
                distance_mm=math.dist(point,target),components=cv2.connectedComponents(mask.astype(np.uint8))[0]-1,
                touches_roi_border=bool(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any()))
            for region,region_mask in regions.items():
                intersection=int(np.count_nonzero(mask&region_mask))
                x['eta_'+region]=intersection/len(xs);x['rho_'+region]=intersection/int(region_mask.sum())
            for key in ('x_mm','y_mm','distance_mm','eta_source','rho_target'):
                require(abs(float(r[key])-x[key])<1e-9,'mask_feature:'+name+':'+key)
            measures[int(r['frame_id'])]=x
        history=None;high_id=high_time=None
        for r in raw:
            i=int(r['frame_id']);t=float(r['exposure_start_s']);cap=by_id[i];x=measures[i]
            duplicate=high_id is not None and (i<=high_id or t<=high_time)
            if not duplicate:high_id,high_time=i,t
            reason=('DUPLICATE_OR_REVERSED' if duplicate else 'OLD_TASK_FRAME' if cap['captured_epoch']!='1' else
                    'PRE_APPLIED_EXPOSURE' if t<.54-1e-10 else 'INVALID_MASK' if not x['valid'] else '')
            raw_speed=None;k=True
            if not reason:
                point=(x['x_mm'],x['y_mm'])
                if history is not None and 0<t-history[0]<=.18:
                    raw_speed=math.dist(point,history[1])/(t-history[0]);k=raw_speed<=19.2
                history=(t,point)
            else:history=None
            expected=dict(C0=not reason,G=x['valid'] and x['rho_target']>=.9 and x['eta_source']<=.08,
                Q=x['valid'] and x['components']==1 and not x['touches_roi_border'],
                S=x.get('distance_mm',math.inf)<=.576,K=k)
            for key,value in expected.items():require(flag(r[key])==value,'raw_gate:'+name+':'+key)
            require(r['c0_reason']==reason,'c0_reason:'+name)
            require((r['raw_speed_mm_s']=='')==(raw_speed is None),'raw_speed_null:'+name)
            if raw_speed is not None:require(abs(float(r['raw_speed_mm_s'])-raw_speed)<1e-9,'raw_speed:'+name)
        for method in config['methods']:
            frames=read(folder/(method['name']+'_frames.csv'));checked_method_rows+=len(frames)
            require(len(frames)==len(raw),'method_frame_count:'+name)
            for r,source in zip(frames,raw):
                require(all(r[key]==value for key,value in source.items()),'shared_raw_history:'+name)
                require(not any(key.startswith(('world_','reference_')) for key in r),'truth_leak_columns:'+name)
            decision=manual_first_event(raw,method['q'],method['w'],method['s'],method['k'])
            event=load(folder/(method['name']+'_event.json'))
            require((decision is None)==(event is None),'event_presence:'+name+':'+method['name'])
            if event:require(abs(event['decision_s']-decision)<1e-9,'event_time:'+name+':'+method['name'])
            require(sum(flag(r['new_event']) for r in frames)<=1,'one_time_event:'+name)
            score=next(r for r in planned if r['case_id']==name and r['method']==method['name'])
            refs=[r for r in references[case['world']]['intervals'] if r['confirmed_s'] is not None and r['confirmed_s']<=10+1e-9]
            support=next((r for r in refs if decision is not None and r['confirmed_s']-1e-9<=decision<r['end_s']-1e-9),None)
            premature=any(decision is not None and decision<r['confirmed_s']-1e-9 for r in refs)
            category='unconfirmed' if decision is None else 'supported' if support else 'premature' if premature else 'unsupported'
            require(score['category']==category,'score_category:'+name+':'+method['name'])
            require(int(score['reference_arrivals'])==len(refs),'reference_denominator:'+name)
            require(int(score['missed_references'])==len(refs)-int(support is not None),'miss_denominator:'+name)
        candidate=[r for r in raw if all(flag(r[k]) for k in ('C0','G','Q'))]
        counts.append(dict(case_id=name,raw_frames=len(raw),GQ_candidates=len(candidate),
            **{k+'_failed':sum(not flag(r[k]) for r in raw) for k in ('C0','G','Q','S','K')},
            S_extra_on_GQ=sum(not flag(r['S']) for r in candidate),K_extra_on_GQ=sum(not flag(r['K']) for r in candidate),
            S_K_joint_on_GQ=sum(not flag(r['S']) and not flag(r['K']) for r in candidate),
            mutation_frames=meta['mutated_frames'],dropped_frames=meta['dropped_frames']))
    normal=read(root/'caches/A0/captures.csv');frozen=read(baseline/'trial/observations.csv')
    require(all(a['mask_sha256']==b['mask_sha256'] for a,b in zip(normal[:120],frozen)),'normal_prefix_mask_identity')
    for method,expected in [('M1',4.4),('M2',4.65),('M3',4.65)]:
        event=load(root/f'caches/A0/{method}_event.json');require(abs(event['decision_s']-expected)<1e-9,'normal_compat:'+method)
    return dict(passed=not failures,failures=sorted(set(failures)),planned_caches=16,planned_method_records=96,
        planned_base_worlds=4,complete_base_worlds=len(references),
        complete_caches=sum(r['raw_frames']>0 for r in counts),
        unattempted_method_records=sum(flag(r['unattempted']) for r in planned),
        all_cases_executed=not manifest['failures'],research_gate='HOLD_generation_failure' if manifest['failures'] else 'MECHANISMS_ONLY',
        checked_masks=checked_masks,checked_method_frame_rows=checked_method_rows,gate_counts=counts,
        independent_of_recognizer_and_scorer=True,performance_claim=False)
