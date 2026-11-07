"""Readable saved-data audit; independent motion, Mask, gate, window, event and outcome replay."""
import argparse
import json
import math
from pathlib import Path
from collections import Counter
import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely import contains_xy
from shapely.affinity import translate
from ..exp1b_closeout.audit import rasterize
from ..exp1b_random.audit import (load,read,flag,independent_reference,manual_event,manual_windows,
    independent_score_fields,field_matches)
from ..exp1b_random.statistics import clopper_pearson
from .spec import SEEDS,SLOTS,PLAN,VERSION,load_protocol,planned_identities,validate_identities,stratum
from .freeze import sha,verify_freeze
from .draws import draw_motion,draw_observation


def _equal(actual,expected):
    if expected is None:return actual in ('',None)
    if isinstance(expected,(float,int)) and not isinstance(expected,bool):
        try:return math.isfinite(float(actual)) and abs(float(actual)-expected)<1e-9
        except (ValueError,TypeError):return False
    if isinstance(expected,bool):return actual in (expected,str(expected))
    return actual==expected


def audit_capture_chronology(captures,raw,expected_plans,require,horizon=10.):
    """Bind saved rows to independently derived captures and sorted deliveries, not their hashes."""
    require(expected_plans==sorted(expected_plans),'independent_delivery_order')
    require(len(captures)==200,'capture_identity_denominator')
    by_frame={frame_id:(processed,available) for processed,frame_id,available in expected_plans}
    for frame_id,capture in enumerate(captures):
        t=round(frame_id/20,10)
        available=by_frame[frame_id][1] if frame_id in by_frame else round(t+.048,12)
        expected=dict(frame_id=frame_id,exposure_start_s=t,exposure_end_s=t+.008,
            available_s=available,captured_epoch='1' if t>=.54-1e-10 else '')
        for key,value in expected.items():
            require(_equal(capture.get(key),value),'capture_chronology:'+key+':'+str(frame_id))
    projection=[(delivery_id,processed,frame_id,available)
        for delivery_id,(processed,frame_id,available) in enumerate(expected_plans) if processed<=horizon+1e-9]
    require(len(raw)==len(projection),'raw_delivery_projection_denominator')
    for row,(delivery_id,processed,frame_id,available) in zip(raw,projection):
        t=round(frame_id/20,10)
        expected=dict(delivery_id=delivery_id,frame_id=frame_id,exposure_start_s=t,
            exposure_end_s=t+.008,available_s=available,processed_at_s=processed)
        for key,value in expected.items():
            require(_equal(row.get(key),value),'raw_delivery_projection:'+key+':'+str(delivery_id))


def _phase(u):
    u=max(0.,min(1.,u));return 10*u**3-15*u**4+6*u**5


def _inverse(q):
    lo,hi=0.,1.
    for _ in range(70):
        mid=(lo+hi)/2
        if _phase(mid)<q:lo=mid
        else:hi=mid
    return (lo+hi)/2


def audit_world_motion(rows,manifest,parameters,kind,source,target,require,
                       horizon=10.,dt=.01,applied=.54):
    """Derive the motion clock and metadata solely from declared parameters, never saved progress."""
    axis=np.asarray(target,dtype=float)-np.asarray(source,dtype=float)
    length=float(np.linalg.norm(axis));p=parameters
    peak=p['slow_peak_speed_mm_s' if kind=='slow' else 'normal_peak_speed_mm_s']
    duration=1.875*length/peak;response=applied+p['response_delay_s']
    pause_clock=duration*_inverse(p['pause_progress']);stop_clock=duration*_inverse(p['stall_progress'])
    stall_start=math.ceil((response+stop_clock)/dt-1e-9)*dt if kind=='stall' else None
    expected_rows=[];previous=None
    for i in range(round(horizon/dt)+1):
        t=round(i*dt,10);clock=max(0.,t-response)
        if kind=='pause' and clock>=pause_clock:clock=max(pause_clock,clock-p['pause_duration_s'])
        if kind=='stall':clock=min(clock,stop_clock)
        q=_phase(clock/duration);point=np.asarray(source)+q*axis
        speed=float(np.linalg.norm(point-previous)/dt) if previous is not None else 0.
        previous=point
        expected_rows.append(dict(time_s=t,x_mm=float(point[0]),y_mm=float(point[1]),speed_mm_s=speed,
            progress=q,shape_phase=q,active=191 if t>=applied-1e-10 else 190,response_at_s=response,
            permanent_stall=kind=='stall' and t>=stall_start-1e-10))
    expected_manifest=dict(kind=kind,ticks=len(expected_rows),applied_s=applied,response_s=response,
        peak_speed_mm_s=peak,duration_s=duration,permanent_stall_started_s=stall_start,
        first_exactly_stationary_stall_tick_s=round(stall_start+dt,10) if stall_start is not None else None,
        pause_started_s=response+pause_clock if kind=='pause' else None,
        pause_duration_s=p['pause_duration_s'] if kind=='pause' else None)
    require(len(rows)==len(expected_rows),'independent_world_tick_denominator')
    for i,(actual,expected) in enumerate(zip(rows,expected_rows)):
        for key,value in expected.items():
            require(_equal(actual.get(key),value),'independent_world_row:'+key+':'+str(i))
    for key,value in expected_manifest.items():
        require(_equal(manifest.get(key),value),'independent_world_manifest:'+key)
    # These derived objects, not unchecked saved fields, drive episode/reference audit below.
    return expected_rows,expected_manifest


def _binary(row,endpoint):
    if row['status']!='executed' or not flag(row.get('reference_known','True')):return None
    return int(row['primary_outcome']==endpoint.removesuffix('_per_planned'))


def _median_interval(values,stream):
    if len(values)<5:return None,None
    import hashlib
    digest=hashlib.sha256(stream.encode('utf-8')).digest()
    seed=[930100,*[int.from_bytes(digest[i:i+4],'little') for i in range(0,16,4)]]
    rng=np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed)))
    values=np.asarray(values,dtype=float)
    boot=np.median(values[rng.integers(0,len(values),(10000,len(values)))],axis=1)
    return tuple(float(v) for v in np.quantile(boot,[.025,.975]))


def audit_statistics(root,records,config,require):
    """Separate grouping/counting and CI construction; does not call the output summarizer."""
    endpoints=('before_reference_per_planned','no_reference_confirmation_per_planned','reference_supported_per_planned')
    contrasts=(('M2','M1'),('M3','M2'),('GQ','M1'),('M2','GQ'),('M2_S','M2'),('M2_K','M2'))
    categories=('reference_supported','before_reference','no_reference_confirmation','outside_reference_support',
        'reference_not_confirmed','no_reference_no_confirmation','confirmation_reference_pending_at_H',
        'no_confirmation_reference_pending_at_H','permanent_stall_no_confirmation','unattempted')
    files={name:read(root/name) for name in ('statistics_rates.csv','paired_binary.csv','latency_summary.csv',
        'paired_latency.csv','outcomes_counts.csv')}
    indexes={}
    for name,rows in files.items():
        discriminator='contrast' if name in ('paired_binary.csv','paired_latency.csv') else 'method'
        suffix=['endpoint'] if name in ('statistics_rates.csv','paired_binary.csv') else ['primary_outcome'] if name=='outcomes_counts.csv' else []
        keys=['reference_id','condition','stratum',discriminator,*suffix]
        indexes[name]={tuple(r[k] for k in keys):r for r in rows}
        require(len(indexes[name])==len(rows),'statistics_duplicate_identity:'+name)
    visited={name:set() for name in files}
    def check(name,key,expected):
        visited[name].add(key);actual=indexes[name].get(key,{})
        require(bool(actual),'statistics_missing_identity:'+name+str(key))
        for k,v in expected.items():require(_equal(actual.get(k),v),'statistics_field:'+name+':'+k+str(key))
    for rs in config['reference']['one_factor_sensitivity']:
        rid=rs['id']
        for cond in config['conditions']:
            cid=cond['id'];allrows=[r for r in records if r['reference_id']==rid and r['condition']==cid]
            for level in (['base'] if cond['strata']=='base' else ['low','high','mixture']):
                selected=[r for r in allrows if level=='mixture' or r['stratum']==level]
                groups=['low','high'] if level=='mixture' else [level]
                common=(rid,cid,level)
                for method in config['methods']:
                    name=method['name'];rows=[r for r in selected if r['method']==name]
                    for endpoint in (*endpoints,'reference_recall'):
                        parts=[]
                        for group in groups:
                            rr=[r for r in rows if r['stratum']==group]
                            if endpoint=='reference_recall':rr=[r for r in rr if flag(r.get('reference_known','True')) and r.get('reference_arrivals') not in ('',None) and int(r['reference_arrivals'])>0]
                            values=[_binary(r,'reference_supported_per_planned' if endpoint=='reference_recall' else endpoint) for r in rr]
                            n=len(rr);u=values.count(None);k=sum(v for v in values if v is not None)
                            lo,hi=clopper_pearson(k,n,.025 if level=='mixture' else .05) if n and not u else (None,None)
                            parts.append(dict(n_planned=n,n_known=n-u,n_unknown=u,k=k,estimate=k/n if n else None,
                                ident_lower=k/n if n else None,ident_upper=(k+u)/n if n else None,ci_lower=lo,ci_upper=hi))
                        expected={k:sum(p[k] for p in parts) for k in ('n_planned','n_known','n_unknown','k')}
                        for k in ('estimate','ident_lower','ident_upper','ci_lower','ci_upper'):
                            expected[k]=sum(p[k]/len(parts) for p in parts) if all(p[k] is not None for p in parts) else None
                        check('statistics_rates.csv',(*common,name,endpoint),expected)
                    values=[float(r['latency_s']) for r in rows if _binary(r,'reference_supported_per_planned')==1]
                    lo,hi=_median_interval(values,f'{rid}/{cid}/{level}/{name}') if level!='mixture' else (None,None)
                    check('latency_summary.csv',(*common,name),dict(n_supported=len(values),median_s=float(np.median(values)) if values else None,ci_lower=lo,ci_upper=hi))
                    counts=Counter(r['primary_outcome'] for r in rows)
                    for category in categories:
                        rr=[r for r in rows if r['primary_outcome']==category]
                        check('outcomes_counts.csv',(*common,name,category),dict(count=counts[category],n_planned=len(rows),
                            observation_censored_count=sum(flag(r['observation_right_censored']) for r in rr),
                            reference_censored_count=sum(flag(r['reference_right_censored']) for r in rr),
                            reference_unknown_count=sum(not flag(r['reference_known']) for r in rr)))
                for a,b in contrasts:
                    aa={r['seed']:r for r in selected if r['method']==a};bb={r['seed']:r for r in selected if r['method']==b}
                    contrast=f'{a}_minus_{b}';require(set(aa)==set(bb),'paired_same_seed')
                    for endpoint in endpoints:
                        parts=[]
                        for group in groups:
                            pairs=[(_binary(aa[s],endpoint),_binary(bb[s],endpoint)) for s in sorted(aa,key=int) if aa[s]['stratum']==group]
                            n=len(pairs);known=[(x,y) for x,y in pairs if x is not None and y is not None]
                            plus=sum(x==1 and y==0 for x,y in known);minus=sum(x==0 and y==1 for x,y in known)
                            lo=hi=None
                            if n and len(known)==n:
                                pl,pu=clopper_pearson(plus,n,.05/(2*len(groups)));ml,mu=clopper_pearson(minus,n,.05/(2*len(groups)))
                                lo,hi=pl-mu,pu-ml
                            lower=sum((x if x is not None else 0)-(y if y is not None else 1) for x,y in pairs)
                            upper=sum((x if x is not None else 1)-(y if y is not None else 0) for x,y in pairs)
                            parts.append(dict(n_planned=n,n_known=len(known),n_unknown=n-len(known),discordant_plus=plus,
                                discordant_minus=minus,estimate=(plus-minus)/n,ident_lower=lower/n,ident_upper=upper/n,ci_lower=lo,ci_upper=hi))
                        expected={k:sum(p[k] for p in parts) for k in ('n_planned','n_known','n_unknown','discordant_plus','discordant_minus')}
                        for k in ('estimate','ident_lower','ident_upper','ci_lower','ci_upper'):
                            expected[k]=sum(p[k]/len(parts) for p in parts) if all(p[k] is not None for p in parts) else None
                        check('paired_binary.csv',(*common,contrast,endpoint),expected)
                    supported_a=[s for s,r in aa.items() if _binary(r,'reference_supported_per_planned')==1]
                    supported_b=[s for s,r in bb.items() if _binary(r,'reference_supported_per_planned')==1]
                    differences=[float(aa[s]['latency_s'])-float(bb[s]['latency_s']) for s in sorted(set(supported_a)&set(supported_b),key=int)]
                    lo,hi=_median_interval(differences,f'{rid}/{cid}/{level}/{contrast}') if level!='mixture' else (None,None)
                    key=(*common,contrast)
                    check('paired_latency.csv',key,dict(n_joint=len(differences),n_supported_a=len(supported_a),n_supported_b=len(supported_b),
                        median_difference_s=float(np.median(differences)) if differences else None,ci_lower=lo,ci_upper=hi))
                    actual=indexes['paired_latency.csv'].get(key,{})
                    require(json.loads(actual.get('raw_differences_json','[]'))==differences,'raw_paired_latency')
    for name,index in indexes.items():require(visited[name]==set(index),'statistics_extra_identity:'+name)
    summary=load(root/'statistics_summary.json')
    require(summary.get('statistics_version')==config['statistics_version'] and summary.get('planned')==PLAN
        and summary.get('no_cross_condition_grand_accuracy') is True and summary.get('no_correlated_cache_pooling') is True
        and summary.get('analysis_seed')==930100 and summary.get('bootstrap_replicates')==10000
        and summary.get('primary_categories')==list(categories),'statistics_summary_contract')


def audit_formal(root):
    root=Path(root).resolve();failures=[]
    def require(ok,label):
        if not ok:failures.append(label)
    manifest=load(root/'manifest.json');config=load(root/'effective_config.json')
    require(config==load_protocol(),'frozen_effective_protocol')
    require(manifest.get('version')==VERSION and manifest.get('actual_formal_seeds')==list(SEEDS)
        and manifest.get('planned')==PLAN and manifest.get('formal_batch_count')==1,'formal_plan_manifest')
    verify_freeze(root/'provenance/freeze.json',config=config,check_unused=False)
    for path,digest in manifest['source_code'].items():require(sha(path)==digest,'source_hash:'+path)
    for relative,digest in manifest['artifacts'].items():require(sha(root/relative)==digest,'artifact_hash:'+relative)
    for item in load(root/'source_inventory.json'):
        require(sha(item['source'])==item['sha256'] and sha(root/item['relative'])==item['sha256'],'snapshot:'+item['source'])
    horizon=config['time']['horizon_s'];drawings={};checked_masks=checked_frames=0
    for seed in SEEDS:
        motion=draw_motion(seed,config)
        for kind in config['design']['motion_groups']:
            require(load(root/'draws'/str(seed)/'motion'/kind/'draw.json')==motion,'motion_rng:'+str(seed)+kind)
        for condition in config['conditions']:
            cid=condition['id'];folder=root/'draws'/str(seed)/cid
            expected=draw_observation(seed,cid,'low' if SLOTS[seed]<10 else 'high',config)
            saved=load(folder/'draw.json')
            require(sha(folder/'raw_arrays.npz')==saved.pop('array_file_sha256'),'raw_array_file_hash')
            require(saved=={k:v for k,v in expected.items() if k!='arrays'},'observation_rng:'+str(seed)+cid)
            with np.load(folder/'raw_arrays.npz') as arrays:
                require(set(arrays.files)==set(expected['arrays']),'draw_array_names')
                for name,values in expected['arrays'].items():require(np.array_equal(arrays[name],values),'draw_array:'+str(seed)+cid+name)
            drawings[seed,cid]=expected
    require(load(root/'draws_complete.json')==dict(motion_world_identities=80,unique_motion_streams=20,
        observation_stream_sets=240,all_persisted_before_any_algorithm=True),'all_draws_persisted')
    data=load(root/'map_snapshot.json');electrodes={e['control_id']:Polygon(e['polygon_map_mm']) for e in data['electrodes']}
    target=electrodes[191].centroid.coords[0];source=electrodes[190].centroid.coords[0]
    axis=np.array(target)-np.array(source);length=float(np.linalg.norm(axis))
    raster=load(root/'raster.json');lower=np.array(raster['lower_mm']);scale=raster['pixels_per_mm'];shape=raster['shape']
    xx=lower[0]+(np.arange(shape[1])+.5)/scale;yy=lower[1]+(np.arange(shape[0])+.5)/scale
    regions={eid:contains_xy(electrodes[eid],xx[None,:],yy[:,None]) for eid in (190,191)}
    shape_source=Path(config['geometry']['shape_source']);old=read(shape_source/'trial/world.csv')
    shapes=load(shape_source/'trial/world_polygons.json');pool=[];phases=[]
    for index,row in enumerate(old):
        q=float(row['shape_phase'])
        if not phases or q!=phases[-1]:phases.append(q);pool.append((index,Polygon(shapes[index]['polygon_mm'])))
    require(len(phases)==430,'saved_pool_430')
    template_index=min(range(len(phases)),key=lambda j:(abs(phases[j]-1.),phases[j]))
    original=pool[template_index][1];center=original.centroid
    template=rasterize(translate(original,target[0]-center.x,target[1]-center.y),raster)
    worlds={};refs={};complete_caches=0;cache_counts=[]
    for seed in SEEDS:
        md=draw_motion(seed,config)['parameters']
        for kind in config['design']['motion_groups']:
            folder=root/'worlds'/str(seed)/kind
            if (folder/'failure.json').exists():continue
            rows=read(folder/'internal_world.csv');polys=[Polygon(r['polygon_mm']) for r in load(folder/'internal_polygons.json')]
            diagnostics=read(folder/'outline_replay_diagnostics.csv');wm=load(folder/'world_manifest.json')
            require(len(rows)==len(polys)==len(diagnostics)==1001,'world_ticks:'+str(seed)+kind)
            independent_rows,independent_metadata=audit_world_motion(rows,wm,md,kind,source,target,require,
                horizon=horizon,dt=config['time']['dt_s'],applied=.54)
            require(_equal(wm.get('request_s'),.5),'world_request_time')
            response=independent_metadata['response_s']
            for i,(row,polygon,diagnostic) in enumerate(zip(rows,polys,diagnostics)):
                t=independent_rows[i]['time_s'];q=independent_rows[i]['progress'];point=np.array(source)+q*axis
                require(abs(t-i*.01)<1e-9 and math.dist(point,(float(row['x_mm']),float(row['y_mm'])))<1e-10,'world_motion:'+str(seed)+kind)
                require(int(row['active'])==(191 if t>=.54-1e-10 else 190),'active_electrode')
                chosen=min(range(len(phases)),key=lambda j:(abs(phases[j]-q),phases[j]));tick,original=pool[chosen];center=original.centroid
                expected=translate(original,point[0]-center.x,point[1]-center.y)
                require(int(diagnostic['source_tick'])==tick and abs(float(diagnostic['selected_phase'])-phases[chosen])<1e-12,'nearest_source')
                require(polygon.is_valid and not polygon.interiors and np.array(polygon.exterior.coords).shape==np.array(expected.exterior.coords).shape
                    and np.allclose(polygon.exterior.coords,expected.exterior.coords,rtol=0,atol=1e-10),'translation_only')
                require(abs(polygon.area/original.area-1)<1e-8 and math.dist(polygon.centroid.coords[0],point)<1e-8,'area_centroid')
                speed=math.dist((float(row['x_mm']),float(row['y_mm'])),(float(rows[i-1]['x_mm']),float(rows[i-1]['y_mm'])))/.01 if i else 0.
                require(abs(speed-float(row['speed_mm_s']))<1e-9,'finite_difference_speed')
                if speed>1e-8:require(t>response and polys[i-1].intersection(electrodes[191]).area>1e-8,'causal_overlap')
            saved_refs=load(folder/'references.json');independent={}
            for spec in config['reference']['one_factor_sensitivity']:
                rid=spec['id'];reference=independent_reference(independent_rows,target,spec,horizon,kind=='stall')
                require(all(saved_refs[rid][k]==reference[k] for k in ('status','intervals','confirmed_s')),'reference:'+str(seed)+kind+rid)
                independent[rid]=reference
            worlds[seed,kind]=(independent_rows,polys,independent_metadata);refs[seed,kind]=independent
    scores=read(root/'reference_sensitivity_results.csv');primary=read(root/'planned_method_results.csv')
    validate_identities(scores,planned_identities(config));validate_identities(primary,planned_identities(config,primary=True))
    identity=lambda r:(r['seed'],r['condition'],r['method'],r['reference_id'])
    by_score={identity(r):r for r in scores}
    require(all(r==by_score.get(identity(r)) for r in primary),'primary_R0_correspondence')
    def check_fields(record,decision,reference,pending,seed,condition,method,rid,attempted=True):
        known=reference is not None
        reference=reference or dict(intervals=[],status='no_reference_by_H')
        expected=independent_score_fields(decision,reference,horizon,pending,attempted)
        expected.update(seed=seed,seed_slot=SLOTS[seed],condition=condition['id'],method=method,reference_id=rid,
            world_id=f"{seed}/{condition['world']}",stratum=stratum(seed,condition),reference_known=known)
        if not attempted:expected['missed_references_by_H']=None
        if not known:expected.update(reference_status='unknown_world_generation_failed',reference_arrivals=None,
            reference_confirmed_s=None,reference_right_censored=False)
        for key,value in expected.items():require(field_matches(record.get(key),value),'score_field:'+key+str(seed)+condition['id']+method+rid)
    for seed in SEEDS:
        for condition in config['conditions']:
            cid=condition['id'];kind=condition['world'];folder=root/'caches'/str(seed)/cid
            if (folder/'failure.json').exists():
                for method in config['methods']:
                    for spec in config['reference']['one_factor_sensitivity']:
                        rid=spec['id'];record=by_score.get((str(seed),cid,method['name'],rid),{})
                        check_fields(record,None,refs.get((seed,kind),{}).get(rid),0,seed,condition,method['name'],rid,False)
                continue
            rows,polys,wm=worlds[seed,kind];observation=drawings[seed,cid];p=observation['parameters'];arrays=observation['arrays']
            caps=read(folder/'captures.csv');deliveries=read(folder/'deliveries.csv');raw=read(folder/'raw_observations.csv');meta=load(folder/'manifest.json')
            require(len(caps)==200,'capture_count');measures={};expected_plans=[];false=[]
            if cid=='TF':
                start=math.ceil((wm['permanent_stall_started_s']+.2)*20-1e-9)/20;end=start+(p['stall_false_frames']-1)/20
            elif cid in ('J','O','C','R','F'):
                threshold=p['false_start_progress' if cid=='F' else 'start_progress']
                start=next(i/20 for i in range(200) if float(rows[i*5]['progress'])>=threshold)
                end=start+(p['false_frames']-1)/20 if cid=='F' else start+p['duration_s']
            else:start=end=None
            for cap in caps:
                i=int(cap['frame_id']);t=i/20;original=rasterize(polys[i*5],raster);expected=original.copy()
                inside=start is not None and start-1e-9<=t<=end+1e-9
                if inside and cid in ('F','TF'):expected=template.copy();false.append(cap)
                if inside and cid in ('J','O'):
                    move=(2*arrays['spatial_uniform'][i]-1)*p['jitter_amplitude_mm'] if cid=='J' else p['bias_magnitude_mm']*np.array([math.cos(p['bias_angle_rad']),math.sin(p['bias_angle_rad'])])
                    dx,dy=np.rint(move*scale).astype(int);m=np.zeros_like(expected)
                    x0=max(0,dx);x1=min(m.shape[1],m.shape[1]+dx);y0=max(0,dy);y1=min(m.shape[0],m.shape[0]+dy)
                    if x1>x0 and y1>y0:m[y0:y1,x0:x1]=expected[y0-dy:y1-dy,x0-dx:x1-dx]
                    expected=m
                ys,xs=np.nonzero(expected)
                if inside and cid=='C' and len(xs):
                    require(abs(axis[0])>=abs(axis[1]) and axis[0]>0,'horizontal_rear_crop')
                    expected[:,:xs.min()+int(math.floor(p['rear_cut_fraction']*(xs.max()-xs.min()+1)))]=0
                if inside and cid=='R' and len(xs):
                    y=round(float(ys.mean()));expected[y:y+p['fragment_band_pixels'],:]=0
                path=folder/cap['mask_path'];mask=cv2.imdecode(np.fromfile(path,np.uint8),0);checked_masks+=1
                require(sha(path)==cap['mask_sha256'] and np.array_equal(mask,expected),'actual_mask:'+str(seed)+cid+str(i))
                require(int(cap['changed_pixels'])==np.count_nonzero(mask!=original),'realized_changed_pixels')
                require(int(cap['actual_area_change_px'])==np.count_nonzero(mask)-np.count_nonzero(original),'realized_area_change')
                ys,xs=np.nonzero(mask);valid=bool(len(xs));features=dict(valid=valid)
                if valid:
                    point=lower+(np.array([xs.mean(),ys.mean()])+.5)/scale
                    features.update(x_mm=float(point[0]),y_mm=float(point[1]),distance_mm=math.dist(point,target),
                        components=cv2.connectedComponents((mask>0).astype(np.uint8))[0]-1,
                        touches_roi_border=bool(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any()),
                        eta_source=np.count_nonzero((mask>0)&regions[190])/len(xs),rho_target=np.count_nonzero((mask>0)&regions[191])/int(regions[191].sum()))
                    for key in ('x_mm','y_mm','distance_mm','eta_source','rho_target','components'):
                        require(abs(float(cap[key])-features[key])<1e-9,'mask_features:'+key)
                measures[i]=features
                require(abs(float(cap['actual_outline_target_overlap_mm2'])-polys[i*5].intersection(electrodes[191]).area)<1e-9,'actual_overlap')
                require(flag(cap['episode_active'])==inside and flag(cap['false_target'])==(inside and cid in ('F','TF')),'episode_flags')
                drop=cid=='D' and t>=.54-1e-10 and arrays['drop_uniform'][i]<p['drop_probability']
                require(flag(cap['delivered'])==(not drop),'delivery_flag')
                if drop:continue
                extra=0.
                if cid=='L' and t>=.54-1e-10 and arrays['delay_probability_and_magnitude_uniform'][i,0]<p['delay_probability']:
                    a,b=p['extra_delay_range_s'];extra=a+arrays['delay_probability_and_magnitude_uniform'][i,1]*(b-a)
                available=round(t+.048+extra,12);processed=round(math.ceil(available/.01-1e-9)*.01,10)
                expected_plans.append((processed,i,available))
            expected_plans.sort();require(len(deliveries)==len(expected_plans),'delivery_denominator')
            for d,(processed,i,available) in zip(deliveries,expected_plans):
                require(int(d['frame_id'])==i and abs(float(d['processed_s'])-processed)<1e-9
                    and abs(float(d['available_s'])-available)<1e-9 and flag(d['pending_at_H'])==(processed>horizon+1e-9),'delivery_timing')
            audit_capture_chronology(caps,raw,expected_plans,require,horizon)
            pending=sum(t>horizon+1e-9 for t,_,_ in expected_plans)
            require(meta['pending_deliveries_at_H']==pending and meta['common_raw_history_sha256']==sha(folder/'raw_observations.csv'),'cache_manifest')
            if cid=='TF':
                ticks=[round(float(c['exposure_start_s'])/.01) for c in false]
                require(len(false)==p['stall_false_frames'] and all(float(c['exposure_start_s'])>=wm['permanent_stall_started_s']+.2-1e-9 for c in false),'TF_stall_episode')
                require(all(abs(float(rows[i]['speed_mm_s']))<1e-10 for i in ticks)
                    and len({rows[i]['progress'] for i in ticks})==1 and all(r['confirmed_s'] is None for r in refs[seed,kind].values()),'TF_stationary_no_reference')
            high_id=high_t=None;history=None
            for r in raw:
                i=int(r['frame_id']);t=float(r['exposure_start_s']);f=measures[i]
                duplicate=high_id is not None and (i<=high_id or t<=high_t)
                if not duplicate:high_id,high_t=i,t
                reason='DUPLICATE_OR_REVERSED' if duplicate else 'OLD_TASK_FRAME' if caps[i]['captured_epoch']!='1' else 'PRE_APPLIED_EXPOSURE' if t<.54-1e-10 else 'INVALID_MASK' if not f['valid'] else ''
                previous=history;speed=None;k=True
                if reason:history=None
                else:
                    point=(f['x_mm'],f['y_mm'])
                    if previous and 0<t-previous[0]<=.18:speed=math.dist(point,previous[1])/(t-previous[0]);k=speed<=19.2
                    history=(t,point)
                expected=dict(C0=not reason,G=f['valid'] and f['rho_target']>=.9 and f['eta_source']<=.08,
                    Q=f['valid'] and f['components']==1 and not f['touches_roi_border'],S=f.get('distance_mm',math.inf)<=.576,K=k)
                require(all(flag(r[key])==value for key,value in expected.items()) and r['c0_reason']==reason,'raw_gates')
                require((r['raw_speed_mm_s']=='')==(speed is None) and (speed is None or abs(float(r['raw_speed_mm_s'])-speed)<1e-9),'raw_speed')
            require(len(raw)==sum(t<=horizon+1e-9 for t,_,_ in expected_plans),'H_inclusive_processing')
            for method in config['methods']:
                name=method['name'];frames=read(folder/(name+'_frames.csv'));event=load(folder/(name+'_event.json'));checked_frames+=len(frames)
                require(len(frames)==len(raw) and all(all(f[k]==v for k,v in r.items()) for f,r in zip(frames,raw)),'common_raw_history')
                require(not any(k.startswith(('world_','reference_','permanent_')) for r in frames for k in r),'no_truth_columns')
                decision=manual_event(raw,method)
                require((event is None)==(decision is None) and (event is None or abs(event['decision_s']-decision)<1e-9),'independent_event')
                require(sum(flag(f['new_event']) for f in frames)==int(event is not None),'single_consumption')
                for actual,expected in zip(frames,manual_windows(raw,method)):
                    require(all(flag(actual[k])==expected[k] for k in ('eligible','new_event','consumed'))
                        and int(actual['window_count'])==expected['window_count'] and actual['window_ids']==expected['window_ids']
                        and abs(float(actual['window_span_s'])-expected['window_span_s'])<1e-9
                        and actual['window_reason']==expected['window_reason'],'independent_window_log')
                for rid,reference in refs[seed,kind].items():
                    record=by_score.get((str(seed),cid,name,rid),{})
                    check_fields(record,decision,reference,pending,seed,condition,name,rid)
                    require(record.get('cache_sha256')==sha(folder/'captures.csv'),'score_cache_hash')
                    require(field_matches(record.get('processed_frames'),len(raw)),'score_processed_frames')
            complete_caches+=1;cache_counts.append(dict(seed=seed,condition=cid,checked_masks=len(caps),processed=len(raw),false_frames=len(false)))
    audit_statistics(root,scores,config,require)
    require(checked_masks==200*complete_caches,'all_actual_masks_audited')
    require(manifest.get('actual_base_worlds')==len(worlds) and manifest.get('actual_caches')==complete_caches,'actual_counts')
    return dict(passed=not failures,failures=sorted(set(failures)),actual_base_worlds=len(worlds),actual_caches=complete_caches,
        planned_method_records=len(primary),reference_scores=len(scores),checked_masks=checked_masks,
        checked_method_frame_rows=checked_frames,cache_counts=cache_counts,
        independent_of_recognizer_and_scorer=True,independent_statistics_recalculation=True,audit_code_sha256=sha(__file__))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);args=parser.parse_args()
    result=audit_formal(args.output)
    (args.output/'independent_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
