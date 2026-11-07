"""Independent saved-data checks; never run a controller, World or scorer."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon


def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def read(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def flag(value): return value is True or value == 'True'
def cap(v, bound):
    norm=float(np.linalg.norm(v))
    return v*min(1.,bound/norm) if norm else v


def reference_intervals(rows, centers, config):
    """Reconstruct dwell from position/speed and REAL active changes only."""
    spans=[];active=None;begin=None;opened=None;previous=None
    def good(row,target):
        return (math.dist((float(row['x_mm']),float(row['y_mm'])),centers[target])<=config['reference_radius_mm']+1e-10
                and float(row['speed_mm_s'])<=config['reference_speed_mm_s']+1e-10)
    def sample(row,target):
        nonlocal begin,opened
        t=float(row['time_s'])
        if good(row,target):
            if begin is None:begin=t
            if opened is None and t-begin>=config['reference_dwell_s']-1e-9:
                opened=dict(target=target,start_s=t,end_s=None,left_limit_end=False);spans.append(opened)
        else:
            if opened is not None:opened['end_s']=t
            begin=opened=None
    for row in rows:
        t=float(row['time_s']);target=int(row['active'])
        if previous is not None and (t<=previous or t-previous>config['dt_s']+1e-8):
            raise ValueError('nonconsecutive independent reference ticks')
        if active is not None and target!=active:
            sample(row,active)
            if opened is not None:
                opened['end_s']=t;opened['left_limit_end']=True
            begin=opened=None
        active=target;sample(row,target);previous=t
    if opened is not None:
        opened['end_s']=previous;opened['horizon_inclusive']=True
    return spans


def support_at(spans,target,time_s,left_limit=False):
    return any(s['target']==target and s['start_s']<=time_s+1e-9 and
        (time_s<s['end_s']-1e-9 or abs(time_s-s['end_s'])<=1e-9 and
         (s.get('horizon_inclusive',False) or left_limit and s['left_limit_end'])) for s in spans)


def rebuild_windows(rows,method):
    result=[];context=None;samples=[];last_id=last_time=None;consumed=False
    for row in rows:
        key=(row['epoch'],row['phase'])
        if key!=context:
            context=key;samples=[];last_id=last_time=None;consumed=False
        phase=row['phase'];transport=phase=='transport';fid=int(row['frame_id']);t=float(row['exposure_start_s'])
        if transport and method=='A_fixed':result.append(None);continue
        min_frames=1 if transport and method=='M1' else 5
        span=0. if transport and method=='M1' else .25
        if transport:
            eligible=flag(row['C0']) and flag(row['G']) and (method=='M1' or flag(row['Q'])) and (method!='M3' or flag(row['S']) and flag(row['K']))
        else:
            eligible=flag(row['C0']) and flag(row['Q']) and float(row['rho_source'])>=.9 and float(row['source_distance_mm'])<=.576
        duplicate=last_time is not None and (t<=last_time or fid<=last_id)
        if duplicate:samples=[]
        else:
            if last_time is not None and (t-last_time>.18+1e-9 or fid!=last_id+1):samples=[]
            last_id,last_time=fid,t
            if not eligible:samples=[]
            else:
                samples.append((t,fid))
                while len(samples)>min_frames and t-samples[1][0]>=span-1e-9:samples.pop(0)
        confirmed=not duplicate and len(samples)>=min_frames and t-samples[0][0]>=span-1e-9
        new_event=bool(confirmed and not consumed)
        if confirmed:consumed=True
        result.append(dict(eligible=bool(eligible),window_count=len(samples),
            window_span_s=samples[-1][0]-samples[0][0] if samples else 0.,
            window_ids=';'.join(str(r[1]) for r in samples),new_event=new_event))
    return result


def derive_step_support(events,spans,route):
    values=[]
    for i,target in enumerate(route[1:]):
        relevant=[e for e in events if e.get('origin_step')==str(i) and e.get('action') in ('Update','Complete')]
        request=next((e for e in relevant if e['event'] in ('request','Complete')),None)
        applied=next((e for e in relevant if e['event']=='simulated_applied'),None)
        values.append(dict(reference_completed=any(s['target']==target for s in spans),
            request_supported=support_at(spans,target,float(request['time_s'])) if request else None,
            applied_supported=support_at(spans,target,float(applied['time_s']),left_limit=True) if applied else None))
    return values


def derive_core_metrics(events,world,derived_steps,captures,deliveries,route):
    terminal=next((e for e in events if e['event'] in ('Complete','Stop')),None)
    complete=terminal is not None and terminal['event']=='Complete'
    reference_path=all(s['reference_completed'] for s in derived_steps)
    request_path=all(s['request_supported'] is True for s in derived_steps)
    applied_path=all(s['applied_supported'] is True for s in derived_steps[:-1])
    strict=reference_path and request_path and applied_path
    category=('reference_supported_path_complete' if strict else 'workflow_complete_without_supported_path') if complete else terminal['reason'] if terminal else 'time_budget_exhausted'
    requests={e['request_id'] for e in events if e['event']=='request'}
    applications=[e for e in events if e['event']=='simulated_applied']
    remaining=requests-{e['request_id'] for e in applications}
    attempted={int(e['origin_step'])+(e['action']=='Update') for e in applications if e['action']!='Prepare'}
    tail=[r for r in world if terminal is not None and float(r['time_s'])>=float(terminal['time_s'])-1e-9]
    held=bool(tail and not remaining and len({r['active'] for r in tail})==1)
    delivered={int(r['frame_id']) for r in deliveries}
    queued=[int(c['frame_id']) for c in captures if int(c['frame_id']) not in delivered]
    return dict(terminal=category,transport_complete=complete,final_target_reference_completed=derived_steps[-1]['reference_completed'],
        sequential_reference_path=reference_path,request_supported_path=request_path,applied_supported_path=applied_path,
        reference_supported_path=strict,unsupported_requests=sum(s['request_supported'] is False for s in derived_steps),
        unsupported_applied=sum(s['applied_supported'] is False for s in derived_steps[:-1]),planned_steps=len(route)-1,
        attempted_steps=len(attempted),total_step_applied=sum(e['action']!='Prepare' for e in applications),
        terminal_holds_last_active=held,queued_at_horizon=len(queued),queued_frame_ids_at_horizon=queued,
        captures=len(captures),deliveries=len(deliveries),dropped_frames=0,random_draws=0)


def raster_polygon(poly,raster):
    out=np.zeros(raster['shape'],np.uint8);scale=raster['pixels_per_mm'];lower=np.array(raster['lower_mm'])
    lo=np.floor((np.array(poly.bounds[:2])-lower)*scale).astype(int)-1
    hi=np.ceil((np.array(poly.bounds[2:])-lower)*scale).astype(int)+1
    x0,y0=np.maximum(lo,0);x1,y1=np.minimum(hi,np.array(out.shape[::-1]))
    if x1>x0 and y1>y0:
        xs=lower[0]+(np.arange(x0,x1)+.5)/scale;ys=lower[1]+(np.arange(y0,y1)+.5)/scale
        out[y0:y1,x0:x1]=contains_xy(poly,xs[None,:],ys[:,None]).astype(np.uint8)*255
    return out


def audit(root):
    root=Path(root).resolve();failures=[];details=[];prefixes=[]
    def require(ok,message):
        if not ok:failures.append(message)
    for method in ('A_fixed','M1','M2','M3'):
        folder=root/method;m=load(folder/'manifest.json');cfg=load(folder/'config.json')['parameters']
        for rel,digest in m['artifacts'].items():require(sha(folder/rel)==digest,'hash:'+method+rel)
        for path,digest in m['source_code'].items():require(sha(path)==digest,'source:'+path)
        geometry=load(m['inputs']['map_path']);polys={e['control_id']:Polygon(e['polygon_map_mm']) for e in geometry['electrodes']}
        centers={k:p.centroid.coords[0] for k,p in polys.items()}
        world=read(folder/'world.csv');shapes=load(folder/'world_polygons.json');events=read(folder/'events.csv')
        captures=read(folder/'captures.csv');frames=read(folder/'frames.csv');steps=read(folder/'steps.csv');deliveries=read(folder/'deliveries.csv')
        metrics=load(folder/'metrics.json');raster=load(folder/'raster.json')
        require(len(steps)==3 and len(world)==round(cfg['horizon_s']/cfg['dt_s'])+1,'planned_denominator:'+method)
        require(len(captures)==math.ceil(cfg['horizon_s']*cfg['camera_fps']-1e-10),'complete_capture_denominator:'+method)
        actual_polys=[Polygon(s['polygon_mm']) for s in shapes]
        initial_area=actual_polys[0].area
        for i,(row,poly) in enumerate(zip(world,actual_polys)):
            t=float(row['time_s']);p=np.array([float(row['x_mm']),float(row['y_mm'])]);v=np.array([float(row['vx_mm_s']),float(row['vy_mm_s'])])
            require(poly.is_valid and abs(poly.area/initial_area-1)<1e-8 and math.dist(poly.centroid.coords[0],p)<1e-8,'area_centroid:'+method+str(i))
            require(np.linalg.norm(v)<=cfg['vmax_mm_s']+1e-8 and abs(float(row['speed_mm_s'])-np.linalg.norm(v))<1e-9,'speed:'+method+str(i))
            if i:
                prev=world[i-1];dt=t-float(prev['time_s']);oldp=np.array([float(prev['x_mm']),float(prev['y_mm'])]);oldv=np.array([float(prev['vx_mm_s']),float(prev['vy_mm_s'])])
                active=int(prev['active']);overlap=actual_polys[i-1].intersection(polys[active]).area
                if overlap<=0.:expectedv=np.zeros(2)
                else:
                    desired=cap((np.array(centers[active])-oldp)/cfg['settle_time_s'],cfg['vmax_mm_s']) if float(prev['time_s'])>=float(prev['response_at_s'])-1e-10 else np.zeros(2)
                    expectedv=oldv+cap((desired-oldv)/cfg['velocity_tau_s'],cfg['acceleration_mm_s2'])*dt
                require(np.linalg.norm(v-expectedv)<1e-8 and np.linalg.norm(p-(oldp+expectedv*dt))<1e-8,'independent_motion:'+method+str(i))
        source_ready=next((float(e['time_s']) for e in events if e['event']=='SourceReady'),None)
        prefix=[];mask_by_id={}
        for i,c in enumerate(captures):
            t=float(c['exposure_start_s']);tick=round(t/cfg['dt_s']);path=folder/c['mask_path']
            actual=cv2.imdecode(np.fromfile(path,np.uint8),0);expected=raster_polygon(actual_polys[tick],raster)
            require(int(c['frame_id'])==i and abs(t-i/cfg['camera_fps'])<1e-9,'capture_grid:'+method+str(i))
            require(sha(path)==c['mask_sha256'] and np.array_equal(actual,expected),'actual_mask:'+method+str(i))
            mask_by_id[i]=actual>0
            if source_ready is None or t<=source_ready+1e-9:prefix.append((i,t,hashlib.sha256(actual.tobytes()).hexdigest()))
        prefixes.append(prefix)
        masks={i:raster_polygon(polys[i],raster)>0 for i in cfg['route']}
        previous=None;high_id=high_t=None
        for f in frames:
            fid=int(f['frame_id']);t=float(f['exposure_start_s']);c=captures[fid];mask=mask_by_id[fid]
            ys,xs=np.nonzero(mask);point=np.array(raster['lower_mm'])+(np.array([xs.mean(),ys.mean()])+.5)/raster['pixels_per_mm']
            src=int(f['source']);dst=int(f['target']);n=len(xs)
            eta=np.count_nonzero(mask&masks[src])/n;rho=np.count_nonzero(mask&masks[dst])/masks[dst].sum()
            distance=math.dist(point,centers[dst]);quality=cv2.connectedComponents(mask.astype(np.uint8))[0]-1==1 and not(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any())
            rho_source=np.count_nonzero(mask&masks[src])/masks[src].sum()
            source_distance=math.dist(point,centers[src])
            require(all(abs(float(f[k])-v)<1e-8 for k,v in dict(x_mm=point[0],y_mm=point[1],eta_source=eta,rho_target=rho,
                rho_source=rho_source,distance_mm=distance,source_distance_mm=source_distance).items()),'independent_features:'+method+str(fid))
            require(flag(f['G'])==(rho>=.9 and eta<=.08) and flag(f['Q'])==bool(quality) and flag(f['S'])==(distance<=.576),'raw_spatial_gates:'+method+str(fid))
            require(float(f['processed_s'])>=float(c['available_s'])-1e-9,'available_before_processing:'+method+str(fid))
            duplicate=high_id is not None and (fid<=high_id or t<=high_t)
            if not duplicate:high_id,high_t=fid,t
            applied=next(float(e['time_s']) for e in reversed(events) if e['event']=='simulated_applied' and float(e['time_s'])<=float(f['processed_s'])+1e-9)
            context_equal=all(c['captured_'+key]==f[key] for key in ('epoch','step','attempt','source','target','phase'))
            if c['captured_applied_s']=='':context_equal=False
            else:
                context_equal=(context_equal and c['captured_clock_domain']=='simulation'
                    and c['captured_run_id']==load(folder/'config.json')['version']+':'+method
                    and abs(float(c['captured_applied_s'])-applied)<1e-9)
            accepted=not duplicate and context_equal and t>=applied-1e-10
            require(flag(f['C0'])==accepted,'independent_C0:'+method+str(fid))
            key=(f['epoch'],f['phase'])
            speed=None
            if accepted:
                if previous and previous[0]==key and 0<t-previous[1]<=.18:speed=math.dist(point,previous[2])/(t-previous[1])
                previous=(key,t,point)
            else:previous=None
            require(flag(f['K'])==(speed is None or speed<=19.2),'raw_history:'+method+str(fid))
        rebuilt=rebuild_windows(frames,method);expected_arrivals=[];expected_source=[]
        for f,w in zip(frames,rebuilt):
            if w is None:continue
            require(flag(f['eligible'])==w['eligible'] and int(f['window_count'])==w['window_count']
                and abs(float(f['window_span_s'])-w['window_span_s'])<1e-9,'independent_W:'+method+f['frame_id'])
            if f['phase']=='transport':
                require(f['window_ids']==w['window_ids'] and flag(f['new_event'])==w['new_event'],'independent_arrival_window:'+method+f['frame_id'])
                if w['new_event']:expected_arrivals.append((int(f['step']),int(f['epoch']),float(f['processed_s'])))
            elif w['new_event']:expected_source.append((int(f['step']),f['phase'],float(f['processed_s'])))
        actual_source=[(int(e['origin_step']),e['phase'],float(e['time_s'])) for e in events if e['event']=='SourceReady']
        require(actual_source==expected_source,'independent_P0:'+method)
        requests={e['request_id']:e for e in events if e['event']=='request'}
        applied=[e for e in events if e['event']=='simulated_applied']
        for e in applied:
            req=requests[e['request_id']]
            require(abs(float(e['time_s'])-float(req['time_s'])-cfg['applied_delay_s'])<1e-9 and e['target']==req['target'],'transaction:'+method)
            require(int(world[round(float(e['time_s'])/cfg['dt_s'])]['active'])==int(e['target']),'active_applied:'+method)
        require(not any(e.get('action')=='Complete' for e in applied),'no_fake_complete_applied:'+method)
        arrivals=read(folder/'arrivals.csv')
        require(len({e['step'] for e in arrivals})==len(arrivals) and (method!='A_fixed' or not arrivals),'once_only_arrivals:'+method)
        require([(int(e['step']),int(e['epoch']),float(e['decision_s'])) for e in arrivals]==expected_arrivals,'independent_arrival_times:'+method)
        if method=='A_fixed':
            for e in events:
                if e['event'] in ('request','Complete') and e.get('action') in ('Update','Complete'):
                    earlier=[a for a in applied if float(a['time_s'])<=float(e['time_s'])+1e-9]
                    require(abs(float(e['time_s'])-float(earlier[-1]['time_s'])-cfg['fixed_wait_s'])<1e-9,'independent_fixed_timer:'+method)
        spans=reference_intervals(world,centers,cfg);marks=read(folder/'reference_marks.csv')
        for mark in marks:
            supported=support_at(spans,int(mark['target']),float(mark['time_s']),left_limit=mark['kind']=='applied')
            require(flag(mark['supported'])==supported,'independent_request_applied_support:'+method+str(mark))
        derived=derive_step_support(events,spans,cfg['route'])
        for step,expected in zip(steps,derived):
            for key,value in expected.items():
                require((step[key]=='' if value is None else flag(step[key])==value),'independent_step_mark_join:'+method+step['step']+key)
        expected_path=all(s['reference_completed'] and s['request_supported'] is True for s in derived) and all(s['applied_supported'] is True for s in derived[:-1])
        require(metrics['reference_supported_path']==expected_path,'independent_path_support:'+method)
        core=derive_core_metrics(events,world,derived,captures,deliveries,cfg['route'])
        for key,value in core.items():require(metrics[key]==value,'independent_core_metrics:'+method+':'+key)
        for i,step in enumerate(steps):
            apps=[e for e in applied if e['action']!='Prepare' and int(e['origin_step'])+(e['action']=='Update')==i]
            require(int(step['applied_count'])==len(apps) and flag(step['attempted'])==bool(apps),'independent_attempts:'+method+str(i))
        blocked=[float(r['time_s']) for r in world if r['world_status']=='blocked_no_overlap']
        require(metrics['blocked_no_overlap_ticks']==len(blocked) and metrics['blocked_no_overlap_times_s']==blocked,'independent_blocked_metrics:'+method)
        require(metrics['random_draws']==0 and m['formal'] is False,'development_only:'+method)
        details.append(dict(method=method,checked_masks=len(captures),world_ticks=len(world),method_frames=len(frames),
                            events=len(events),arrival_events=len(arrivals),planned_steps=len(steps)))
    require(all(p==prefixes[0] for p in prefixes[1:]),'identical_P0_prefix')
    result=dict(passed=not failures,failures=sorted(set(failures)),trials=details,checked_masks=sum(r['checked_masks'] for r in details),
        independent_motion_and_reference=True,controller_or_scorer_called=False,audit_code_sha256=sha(__file__))
    (root/'independent_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if failures:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('data');args=parser.parse_args();audit(args.data)
