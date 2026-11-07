"""Saved-data audit independent of recognizer and scorer implementations."""
import argparse
import csv
import hashlib
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
from .draws import draw_motion, draw_observation


def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def flag(v): return v is True or v == 'True'
def read(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream: return list(csv.DictReader(stream))


def independent_reference(rows, target, spec, horizon, stalled, applied=.54):
    spans = []; opened = None; achieved = None; old = None; final_valid = False; final_speed = 0.
    for r in rows:
        t = float(r['time_s'])
        if t > horizon+1e-9: break
        speed = float(r['speed_mm_s']); final_speed = speed
        valid = (t >= applied-1e-10 and int(float(r['active'])) == 191 and
            math.dist((float(r['x_mm']),float(r['y_mm'])),target) <= spec['radius_mm'] and speed <= spec['max_speed_mm_s'])
        gap = old is not None and t-old > .0100001
        if opened is not None and (gap or not valid):
            spans.append(dict(start_s=opened,end_s=old if gap else t,confirmed_s=achieved,
                              terminal_inclusive=False,actual_exit=not valid)); opened = achieved = None
        if valid:
            if opened is None: opened = t
            if achieved is None and t-opened >= spec['dwell_s']-1e-9: achieved = t
        old = t; final_valid = valid
    if opened is not None:
        spans.append(dict(start_s=opened,end_s=old,confirmed_s=achieved,
                          terminal_inclusive=abs(old-horizon)<=1e-9,actual_exit=False))
    complete = [r for r in spans if r['confirmed_s'] is not None]
    status = ('completed_by_H' if complete else 'dwell_incomplete_at_H' if final_valid else
              'permanent_stall_without_reference' if stalled else 'approaching_at_H' if final_speed>1e-10 else 'no_reference_by_H')
    return dict(intervals=spans,status=status,confirmed_s=complete[0]['confirmed_s'] if complete else None)


def independent_outcome(decision, reference, horizon):
    completed = [r for r in reference['intervals'] if r['confirmed_s'] is not None and r['confirmed_s'] <= horizon+1e-9]
    for r in completed:
        if decision is not None and decision >= r['confirmed_s']-1e-9 and (decision < r['end_s']-1e-9 or
                (r.get('terminal_inclusive') and decision <= r['end_s']+1e-9)):
            return 'reference_supported'
    pending = reference['status'] in ('approaching_at_H','dwell_incomplete_at_H','no_reference_by_H')
    if decision is not None:
        if any(decision<r['confirmed_s']-1e-9 for r in completed): return 'before_reference'
        if completed: return 'outside_reference_support'
        return 'confirmation_reference_pending_at_H' if pending else 'no_reference_confirmation'
    if completed: return 'reference_not_confirmed'
    if pending: return 'no_confirmation_reference_pending_at_H'
    return 'permanent_stall_no_confirmation' if reference['status']=='permanent_stall_without_reference' else 'no_reference_no_confirmation'


def manual_event(rows, method):
    times = []; last_id = last_time = None
    for r in rows:
        index = int(r['frame_id']); t = float(r['exposure_start_s'])
        if last_id is not None and (index <= last_id or t <= last_time):
            times = []; continue
        if last_id is not None and (index != last_id+1 or t-last_time > .18+1e-9): times = []
        last_id, last_time = index, t
        eligible = all(flag(r[name]) for name, use in [('C0',True),('G',True),('Q',method['Q']),('S',method['S']),('K',method['K'])] if use)
        if not eligible: times = []; continue
        times.append(t)
        if not method['W'] or (len(times)>=5 and t-times[0]>=.25-1e-9): return float(r['processed_at_s'])
    return None


def manual_windows(rows, method):
    samples=[];last_id=last_time=None;consumed=False;logs=[]
    for row in rows:
        i=int(row['frame_id']);t=float(row['exposure_start_s']);fresh=False
        eligible=all(flag(row[k]) for k,enabled in [('C0',True),('G',True),('Q',method['Q']),('S',method['S']),('K',method['K'])] if enabled)
        reverse=last_id is not None and (i<=last_id or t<=last_time)
        if reverse:samples=[];reason='DUPLICATE_OR_REVERSED_OBSERVATION'
        else:
            gap=last_time is not None and (t-last_time>.18+1e-9 or i!=last_id+1)
            if gap:samples=[]
            last_id,last_time=i,t
            if not eligible:samples=[];reason='INELIGIBLE_OBSERVATION'
            else:
                samples.append((t,i));min_count=5 if method['W'] else 1;span=.25 if method['W'] else 0.
                while len(samples)>min_count and t-samples[1][0]>=span-1e-9:samples.pop(0)
                confirmed=len(samples)>=min_count and t-samples[0][0]>=span-1e-9
                reason='CONFIRMED' if confirmed else 'GAP_REBUILT' if gap else 'INSUFFICIENT_EVIDENCE'
                fresh=confirmed and not consumed
                consumed=consumed or confirmed
        logs.append(dict(eligible=eligible,new_event=fresh,consumed=consumed,window_count=len(samples),
            window_span_s=samples[-1][0]-samples[0][0] if samples else 0.,window_reason=reason,
            window_ids=';'.join(str(i) for _,i in samples)))
    return logs


def independent_score_fields(decision, ref, horizon, pending, attempted=True):
    completed=[r for r in ref['intervals'] if r['confirmed_s'] is not None and r['confirmed_s']<=horizon+1e-9]
    support=next((r for r in completed if decision is not None and decision>=r['confirmed_s']-1e-9
        and (decision<r['end_s']-1e-9 or (r['terminal_inclusive'] and decision<=r['end_s']+1e-9))),None)
    outcome=independent_outcome(decision,ref,horizon) if attempted else 'unattempted'
    return dict(primary_outcome=outcome,primary_outcome_count=1,planned_steps=1,
        reference_status=ref['status'],reference_arrivals=len(completed),
        reference_confirmed_s=completed[0]['confirmed_s'] if completed else None,
        missed_references_by_H=len(completed)-int(support is not None),
        supported_by_H=int(support is not None) if attempted else None,
        confirmed_by_H=int(decision is not None) if attempted else None,
        not_supported_by_H=int(decision is not None and support is None) if attempted else None,
        latency_s=decision-support['confirmed_s'] if support else None,
        signed_deviation_s=decision-completed[0]['confirmed_s'] if decision is not None and completed else None,
        decision_s=decision,pending_deliveries_at_H=pending,observation_right_censored=bool(pending),
        reference_right_censored=ref['status'] in ('dwell_incomplete_at_H','approaching_at_H','no_reference_by_H'),
        physical_wrong_advance=None,unattempted=not attempted,status='executed' if attempted else 'unattempted')


def field_matches(actual, expected):
    if expected is None:return actual in ('',None)
    if type(expected) is bool:return actual==str(expected)
    if isinstance(expected,(int,float)):
        try:return math.isfinite(float(actual)) and abs(float(actual)-expected)<1e-9
        except (TypeError,ValueError):return False
    return actual==expected


def audit_development(root):
    root = Path(root); manifest = load(root/'manifest.json'); config = load(root/'effective_config.json')
    failures = []; checked_masks = checked_frames = complete_worlds = complete_caches = 0
    def require(ok, label):
        if not ok: failures.append(label)
    for path, digest in manifest['source_code'].items(): require(sha(path)==digest,'source_hash:'+path)
    for rel, digest in manifest['artifacts'].items(): require(sha(root/rel)==digest,'artifact_hash:'+rel)
    for item in load(root/'source_inventory.json'):
        require(sha(item['source'])==item['sha256'],'protected_source:'+item['source'])
        if item['relative']: require(sha(root/item['relative'])==item['sha256'],'copy_hash:'+item['relative'])
    seeds = manifest['actual_development_seeds']; horizon = config['time']['horizon_s']
    require(set(seeds).issubset({268000,268001}) and len(set(seeds))==len(seeds),'development_seeds_only')
    require(not manifest['formal_execution_allowed'] and not config['formal_execution_allowed'],'formal_block')
    drawings = {}
    for seed in seeds:
        require(load(root/'draws'/str(seed)/'motion/draw.json')==draw_motion(seed,config),'motion_rng:'+str(seed))
        for condition in config['conditions']:
            cid = condition['id']; folder = root/'draws'/str(seed)/cid
            expected = draw_observation(seed,cid,'low' if seed==268000 else 'high',config)
            saved = load(folder/'draw.json'); arrays = np.load(folder/'raw_arrays.npz')
            require(sha(folder/'raw_arrays.npz')==saved.pop('array_file_sha256'),'raw_array_file_hash')
            require(saved=={k:v for k,v in expected.items() if k!='arrays'},'observation_rng:'+str(seed)+cid)
            for name, values in expected['arrays'].items(): require(np.array_equal(arrays[name],values),'raw_array:'+str(seed)+cid+name)
            drawings[seed,cid] = expected
    map_data = load(root/'map_snapshot.json'); electrodes = {e['control_id']:Polygon(e['polygon_map_mm']) for e in map_data['electrodes']}
    target = electrodes[191].centroid.coords[0]; source = electrodes[190].centroid.coords[0]
    axis = np.array(target)-np.array(source); length = float(np.linalg.norm(axis))
    raster = load(root/'raster.json'); lower = np.array(raster['lower_mm']); scale = raster['pixels_per_mm']; shape = raster['shape']
    xx = lower[0]+(np.arange(shape[1])+.5)/scale; yy = lower[1]+(np.arange(shape[0])+.5)/scale
    regions = {eid:contains_xy(electrodes[eid],xx[None,:],yy[:,None]) for eid in (190,191)}
    shape_source = Path(config['geometry']['shape_source'])
    old = read(shape_source/'trial/world.csv'); old_shapes = load(shape_source/'trial/world_polygons.json')
    pool = []; phases = []
    for index, r in enumerate(old):
        q = float(r['shape_phase'])
        if not phases or q != phases[-1]: phases.append(q); pool.append((index,Polygon(old_shapes[index]['polygon_mm'])))
    require(len(phases)==430,'saved_pool_430')
    worlds = {}; refs = {}; templates = {}; audit_counts = []
    for seed in seeds:
        md = draw_motion(seed,config)['parameters']
        for kind in config['design']['motion_groups']:
            folder = root/'worlds'/str(seed)/kind
            if (folder/'failure.json').exists(): continue
            rows = read(folder/'internal_world.csv'); polys = [Polygon(r['polygon_mm']) for r in load(folder/'internal_polygons.json')]
            diag = read(folder/'outline_replay_diagnostics.csv'); wm = load(folder/'world_manifest.json')
            require(len(rows)==len(polys)==len(diag)==1001,'world_ticks:'+str(seed)+kind)
            duration = 1.875*length/md['slow_peak_speed_mm_s' if kind=='slow' else 'normal_peak_speed_mm_s']
            response = .54+md['response_delay_s']
            def phase(u):
                u=max(0.,min(1.,u));return 10*u**3-15*u**4+6*u**5
            def inverse(q):
                lo,hi=0.,1.
                for _ in range(70):
                    mid=(lo+hi)/2
                    if phase(mid)<q:lo=mid
                    else:hi=mid
                return (lo+hi)/2
            pause_clock = duration*inverse(md['pause_progress']); stop_clock = duration*inverse(md['stall_progress'])
            for i,(r,p,d) in enumerate(zip(rows,polys,diag)):
                t=float(r['time_s']); clock=max(0.,t-response)
                if kind=='pause' and clock>=pause_clock:clock=max(pause_clock,clock-md['pause_duration_s'])
                if kind=='stall':clock=min(clock,stop_clock)
                q=phase(clock/duration); expected_point=np.array(source)+q*axis
                require(math.dist(expected_point,(float(r['x_mm']),float(r['y_mm'])))<1e-10,'world_motion:'+str(seed)+kind)
                require(int(r['active'])==(191 if t>=.54-1e-10 else 190),'active_electrode')
                chosen=min(range(len(phases)),key=lambda j:(abs(phases[j]-q),phases[j]))
                tick,original=pool[chosen]; center=original.centroid
                expected_poly=translate(original,expected_point[0]-center.x,expected_point[1]-center.y)
                require(int(d['source_tick'])==tick and abs(float(d['selected_phase'])-phases[chosen])<1e-12,'nearest_source')
                require(p.is_valid and not p.interiors and np.array(p.exterior.coords).shape==np.array(expected_poly.exterior.coords).shape
                    and np.allclose(p.exterior.coords,expected_poly.exterior.coords,rtol=0,atol=1e-10),'saved_translation_only')
                require(abs(p.area/original.area-1)<1e-8 and math.dist(p.centroid.coords[0],expected_point)<1e-8,'area_centroid')
                speed=math.dist((float(r['x_mm']),float(r['y_mm'])),(float(rows[i-1]['x_mm']),float(rows[i-1]['y_mm'])))/.01 if i else 0.
                require(abs(speed-float(r['speed_mm_s']))<1e-9,'finite_difference_speed')
                if speed>1e-8:require(t>response and polys[i-1].intersection(electrodes[191]).area>1e-8,'causal_overlap')
            saved_refs=load(folder/'references.json'); independent={}
            for spec in config['reference']['one_factor_sensitivity']:
                rid=spec['id']; ref=independent_reference(rows,target,spec,horizon,kind=='stall')
                require(all(saved_refs[rid][k]==ref[k] for k in ('status','intervals','confirmed_s')),'reference:'+str(seed)+kind+rid)
                independent[rid]=ref
            worlds[seed,kind]=(rows,polys,wm);refs[seed,kind]=independent;complete_worlds+=1
            if kind=='normal':templates[seed]=rasterize(polys[-1],raster)
    scores=read(root/'reference_sensitivity_results.csv');primary=read(root/'planned_method_results.csv')
    require(len(primary)==72*len(seeds) and len(scores)==504*len(seeds),'full_planned_denominators')
    identity=lambda r:(r['seed'],r['condition'],r['method'],r['reference_id'])
    expected_ids={(str(seed),c['id'],m['name'],s['id']) for seed in seeds for c in config['conditions']
        for m in config['methods'] for s in config['reference']['one_factor_sensitivity']}
    require(len({identity(r) for r in scores})==len(scores) and {identity(r) for r in scores}==expected_ids,'sensitivity_plan_identities')
    require(len({identity(r) for r in primary})==len(primary)
        and {identity(r) for r in primary}=={k for k in expected_ids if k[3]=='R0'},'primary_plan_identities')
    by_score={identity(r):r for r in scores};expected_primary=[]
    require(all(r==by_score.get(identity(r)) for r in primary),'primary_R0_correspondence')
    def check_score(record,decision,ref,pending,seed,cid,method,rid,kind,stratum,attempted=True):
        expected=dict(independent_score_fields(decision,ref,horizon,pending,attempted),seed=seed,
            seed_slot=0 if seed==268000 else 10,condition=cid,method=method,reference_id=rid,
            world_id=f'{seed}/{kind}',stratum=stratum)
        for key,value in expected.items():require(field_matches(record.get(key),value),'score_field:'+key)
        if rid=='R0':expected_primary.append(dict(seed=seed,condition=cid,method=method,primary_outcome=expected['primary_outcome']))
    for seed in seeds:
        for condition in config['conditions']:
            cid=condition['id'];kind=condition['world'];folder=root/'caches'/str(seed)/cid
            stratum='base' if condition['strata']=='base' else 'low' if seed==268000 else 'high'
            if (folder/'failure.json').exists():
                for m in config['methods']:
                    for s in config['reference']['one_factor_sensitivity']:
                        check_score(by_score.get((str(seed),cid,m['name'],s['id']),{}),None,
                            refs.get((seed,kind),{}).get(s['id'],dict(intervals=[],status='no_reference_by_H')),
                            0,seed,cid,m['name'],s['id'],kind,stratum,False)
                continue
            rows,polys,wm=worlds[seed,kind];obs=drawings[seed,cid];p=obs['parameters'];arrays=obs['arrays']
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
                if inside and cid in ('F','TF'):expected=templates[seed].copy();false.append(cap)
                if inside and cid in ('J','O'):
                    move=(2*arrays['spatial_uniform'][i]-1)*p['jitter_amplitude_mm'] if cid=='J' else p['bias_magnitude_mm']*np.array([math.cos(p['bias_angle_rad']),math.sin(p['bias_angle_rad'])])
                    dx,dy=np.rint(move*scale).astype(int);m=np.zeros_like(expected)
                    x0=max(0,dx);x1=min(m.shape[1],m.shape[1]+dx);y0=max(0,dy);y1=min(m.shape[0],m.shape[0]+dy)
                    if x1>x0 and y1>y0:m[y0:y1,x0:x1]=expected[y0-dy:y1-dy,x0-dx:x1-dx]
                    expected=m
                ys,xs=np.nonzero(expected)
                if inside and cid=='C' and len(xs):
                    require(abs(axis[0])>=abs(axis[1]) and axis[0]>0,'declared_horizontal_rear_crop')
                    expected[:,:xs.min()+int(math.floor(p['rear_cut_fraction']*(xs.max()-xs.min()+1)))]=0
                if inside and cid=='R' and len(xs):
                    y=round(float(ys.mean()));expected[y:y+p['fragment_band_pixels'],:]=0
                path=folder/cap['mask_path'];mask=cv2.imdecode(np.fromfile(path,np.uint8),0);checked_masks+=1
                require(sha(path)==cap['mask_sha256'] and np.array_equal(mask,expected),'actual_mask:'+str(seed)+cid+str(i))
                require(int(cap['changed_pixels'])==np.count_nonzero(mask!=original),'realized_changed_pixels')
                ys,xs=np.nonzero(mask);valid=bool(len(xs));features=dict(valid=valid)
                if valid:
                    point=lower+(np.array([xs.mean(),ys.mean()])+.5)/scale
                    features.update(x_mm=float(point[0]),y_mm=float(point[1]),distance_mm=math.dist(point,target),
                        components=cv2.connectedComponents((mask>0).astype(np.uint8))[0]-1,
                        touches_roi_border=bool(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any()),
                        eta_source=np.count_nonzero((mask>0)&regions[190])/len(xs),rho_target=np.count_nonzero((mask>0)&regions[191])/int(regions[191].sum()))
                    for key in ('x_mm','y_mm','distance_mm','eta_source','rho_target','components'):require(abs(float(cap[key])-features[key])<1e-9,'mask_features:'+key)
                measures[i]=features
                overlap=polys[i*5].intersection(electrodes[191]).area
                require(abs(float(cap['actual_outline_target_overlap_mm2'])-overlap)<1e-9,'actual_TF_overlap')
                drop=cid=='D' and t>=.54-1e-10 and arrays['drop_uniform'][i]<p['drop_probability']
                if drop:continue
                extra=0.
                if cid=='L' and t>=.54-1e-10 and arrays['delay_probability_and_magnitude_uniform'][i,0]<p['delay_probability']:
                    a,b=p['extra_delay_range_s'];extra=a+arrays['delay_probability_and_magnitude_uniform'][i,1]*(b-a)
                available=round(t+.048+extra,12);processed=round(math.ceil(available/.01-1e-9)*.01,10)
                expected_plans.append((processed,i,available))
            expected_plans.sort()
            require(len(deliveries)==len(expected_plans),'delivery_denominator')
            for d,(processed,i,available) in zip(deliveries,expected_plans):
                require(int(d['frame_id'])==i and abs(float(d['processed_s'])-processed)<1e-9 and abs(float(d['available_s'])-available)<1e-9,'delivery_timing')
            if cid=='TF':
                false_ticks=[round(float(c['exposure_start_s'])/.01) for c in false]
                require(len(false)==p['stall_false_frames'] and all(float(c['exposure_start_s'])>=wm['permanent_stall_started_s']+.2-1e-9 for c in false),'TF_stall_episode')
                require(all(abs(float(rows[i]['speed_mm_s']))<1e-10 for i in false_ticks)
                    and len({rows[i]['progress'] for i in false_ticks})==1 and all(r['confirmed_s'] is None for r in refs[seed,kind].values()),'TF_stationary_constant_progress_no_reference')
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
                frames=read(folder/(method['name']+'_frames.csv'));event=load(folder/(method['name']+'_event.json'));checked_frames+=len(frames)
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
                for rid,ref in refs[seed,kind].items():
                    s=by_score.get((str(seed),cid,method['name'],rid),{})
                    check_score(s,decision,ref,sum(t>horizon+1e-9 for t,_,_ in expected_plans),seed,cid,method['name'],rid,kind,stratum)
                    require(s.get('cache_sha256')==sha(folder/'captures.csv'),'score_field:cache_sha256')
                    require(field_matches(s.get('processed_frames'),len(raw)),'score_field:processed_frames')
            complete_caches+=1;audit_counts.append(dict(seed=seed,condition=cid,checked_masks=len(caps),processed=len(raw),false_frames=len(false)))
    counts=Counter((r['condition'],r['method'],r['primary_outcome']) for r in expected_primary)
    summary=dict(performance_CI_reported=False,planned_method_records=len(expected_primary),
        unique_development_seeds=len(seeds),counts_only=True,counts=[dict(condition=c,method=m,primary_outcome=o,count=n)
        for (c,m,o),n in sorted(counts.items())])
    require(load(root/'development_summary.json')==summary,'development_summary_semantics')
    return dict(passed=not failures,failures=sorted(set(failures)),actual_base_worlds=complete_worlds,
        actual_caches=complete_caches,planned_method_records=len(primary),reference_scores=len(scores),
        checked_masks=checked_masks,checked_method_frame_rows=checked_frames,cache_counts=audit_counts,
        independent_of_recognizer_and_scorer=True,formal_execution_allowed=False,performance_CI_reported=False,
        audit_code_sha256=sha(__file__))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);args=parser.parse_args()
    result=audit_development(args.output)
    (args.output/'independent_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
