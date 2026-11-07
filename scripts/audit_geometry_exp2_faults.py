"""Independent audit of persisted fault mechanisms; never executes a study."""
import argparse
import json
import math
from pathlib import Path
import sys
from collections import Counter

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.affinity import translate

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_geometry_exp2_mechanisms import load, read, sha, flag, cap, raster_polygon, rebuild_windows, support_at
from scripts.analyze_geometry_exp2_outcomes import analyze_trial, write_json, write_csv


def audit_case(folder):
    folder=Path(folder).resolve(); failures=[]
    def require(ok,message):
        if not ok:failures.append(message)
    manifest=load(folder/'manifest.json');cfg=load(folder/'config.json')['parameters'];case=load(folder/'case.json')
    for name,digest in manifest['artifacts'].items():require(sha(folder/name)==digest,'artifact_hash:'+name)
    for name,digest in manifest['source_code'].items():require(sha(name)==digest,'source_hash:'+name)
    design=load(manifest['inputs']['map_path'])
    require(sha(manifest['inputs']['map_path'])==manifest['inputs']['map_sha256'],'map_hash')
    polys={e['control_id']:Polygon(e['polygon_map_mm']) for e in design['electrodes']}
    centers={k:p.centroid.coords[0] for k,p in polys.items()}
    world=read(folder/'world.csv');shapes=load(folder/'world_polygons.json');captures=read(folder/'captures.csv')
    frames=read(folder/'frames.csv');deliveries=read(folder/'deliveries.csv');events=read(folder/'events.csv')
    steps=read(folder/'steps.csv');metrics=load(folder/'metrics.json');raster=load(folder/'raster.json')
    interventions=read(folder/'interventions.csv');actual_polys=[Polygon(s['polygon_mm']) for s in shapes]
    version='geometry_exp2_fault_mechanisms_development_v1'
    expected_run_id=version+':'+case['case_id']
    require(len(steps)==3 and len(world)==round(cfg['horizon_s']/cfg['dt_s'])+1,'planned_denominator')
    require(len(captures)==math.ceil(cfg['horizon_s']*cfg['camera_fps']-1e-10),'capture_denominator')
    area=actual_polys[0].area;stall=case['stall_at_s'];pin=None
    for i,(row,poly) in enumerate(zip(world,actual_polys)):
        t=float(row['time_s']);p=np.array([float(row['x_mm']),float(row['y_mm'])]);v=np.array([float(row['vx_mm_s']),float(row['vy_mm_s'])])
        require(poly.is_valid and abs(poly.area/area-1)<1e-8 and math.dist(poly.centroid.coords[0],p)<1e-8,'shape_area_centroid:'+str(i))
        require(np.linalg.norm(v)<=cfg['vmax_mm_s']+1e-8,'speed_cap:'+str(i))
        require(abs(float(row['speed_mm_s'])-np.linalg.norm(v))<1e-9,'speed_consistency:'+str(i))
        if stall is not None and t>=stall-1e-9:
            if pin is None:pin=p.copy()
            require(np.linalg.norm(v)<1e-10 and np.linalg.norm(p-pin)<1e-10,'permanent_stall:'+str(i))
        if i:
            prev=world[i-1];dt=t-float(prev['time_s']);oldp=np.array([float(prev['x_mm']),float(prev['y_mm'])]);oldv=np.array([float(prev['vx_mm_s']),float(prev['vy_mm_s'])])
            if stall is not None and t>stall+1e-9:continue
            active=int(prev['active']);overlap=actual_polys[i-1].intersection(polys[active]).area
            desired=cap((np.array(centers[active])-oldp)/cfg['settle_time_s'],cfg['vmax_mm_s']) if float(prev['time_s'])>=float(prev['response_at_s'])-1e-10 else np.zeros(2)
            expected=oldv+cap((desired-oldv)/cfg['velocity_tau_s'],cfg['acceleration_mm_s2'])*dt if overlap>0 else np.zeros(2)
            require(np.linalg.norm(p-oldp-expected*dt)<1e-8,'motion_position:'+str(i))
            if stall is None or t<stall-1e-9:require(np.linalg.norm(v-expected)<1e-8,'motion_velocity:'+str(i))
    mask_by_id={}
    expected_fake_mask=None
    if case['fake_electrode'] is not None and 'pool_polygons_path' in manifest['inputs']:
        pool=load(manifest['inputs']['pool_polygons_path']);last_tick=manifest['inputs']['pool_source_ticks'][-1]
        endpoint=Polygon(pool[last_tick]['polygon_mm']);cx,cy=endpoint.centroid.coords[0];tx,ty=centers[case['fake_electrode']]
        expected_fake_mask=raster_polygon(translate(endpoint,tx-cx,ty-cy),raster)
    expected_operations=[]
    for i,c in enumerate(captures):
        fid=int(c['frame_id']);t=float(c['exposure_start_s']);tick=round(t/cfg['dt_s'])
        visible=cv2.imdecode(np.fromfile(folder/c['mask_path'],np.uint8),0)
        source=cv2.imdecode(np.fromfile(folder/c['source_mask_path'],np.uint8),0)
        expected=raster_polygon(actual_polys[tick],raster)
        require(np.array_equal(source,expected),'mask_source_geometry:'+str(fid))
        require(sha(folder/c['mask_path'])==c['mask_sha256']==c['visible_mask_sha256'],'visible_hash:'+str(fid))
        require(sha(folder/c['source_mask_path'])==c['source_mask_sha256'],'original_mask_hash:'+str(fid))
        require(fid==i and abs(t-fid/cfg['camera_fps'])<1e-9,'camera_grid:'+str(fid))
        first_applied=min(float(e['time_s']) for e in events if e['event']=='simulated_applied')
        identity_ok=(c['captured_run_id']==expected_run_id and c['captured_clock_domain']=='simulation')
        if c['captured_epoch']=='':identity_ok=(t<first_applied-1e-9 and c['captured_run_id']=='' and c['captured_clock_domain']=='')
        require(identity_ok,'capture_run_identity:'+str(fid))
        injected=t in case['fake_exposures_s'];require(flag(c['mask_injected'])==injected,'declared_fake:'+str(fid))
        require(flag(c['dropped'])==(fid in case['drop_frame_ids']),'declared_drop:'+str(fid))
        delay=case['extra_delay_s'] if fid==case['delayed_frame_id'] else 0.
        require(abs(float(c['available_s'])-t-cfg['exposure_s']-cfg['processing_delay_s']-delay)<1e-9,'declared_delay:'+str(fid))
        if not injected:require(np.array_equal(visible,source),'noninjected_mask_changed:'+str(fid))
        else:
            expected_operations.append(('mask_replace',fid,t))
            if expected_fake_mask is not None:require(np.array_equal(visible,expected_fake_mask),'declared_fake_shape:'+str(fid))
            yy,xx=np.nonzero(visible);point=np.array(raster['lower_mm'])+(np.array([xx.mean(),yy.mean()])+.5)/raster['pixels_per_mm']
            require(math.dist(point,centers[case['fake_electrode']])<.02,'fake_at_declared_target:'+str(fid))
        mask_by_id[fid]=visible>0
        if flag(c['dropped']):expected_operations.append(('delivery_drop',fid,t))
        if fid==case['delayed_frame_id']:expected_operations.append(('delivery_delay',fid,t))
        if fid==case['duplicate_frame_id']:expected_operations.append(('delivery_duplicate',fid,t))
    if stall is not None and stall<=cfg['horizon_s']+1e-9:expected_operations.append(('world_stall',None,stall))
    if case['applied_delay_s'] is not None:expected_operations.append(('applied_delay_stress',None,0.))
    actual_operations=[(r['operation'],int(r['frame_id']) if r.get('frame_id','')!='' else None,float(r['time_s'])) for r in interventions]
    require(Counter(actual_operations)==Counter(expected_operations),'intervention_log_matches_declarations')
    for r in interventions:
        if r['operation']=='mask_replace':
            c=captures[int(r['frame_id'])]
            require(int(r['electrode_id'])==case['fake_electrode'] and float(r['fixed_pool_phase'])==1. and
                r['source_mask_sha256']==c['source_mask_sha256'] and r['visible_mask_sha256']==c['visible_mask_sha256'],'intervention_mask_join')
    uidmap={d['delivery_uid']:d for d in deliveries};require(len(uidmap)==len(deliveries),'unique_delivery_uid')
    consumed_uids=[d['delivery_uid'] for d in deliveries if flag(d['consumed'])]
    require(Counter(f['delivery_uid'] for f in frames)==Counter(consumed_uids),'consumed_delivery_frame_bijection')
    for d in deliveries:
        fid=int(d['frame_id']);c=captures[fid]
        require(not flag(c['dropped']),'dropped_frame_delivered:'+str(fid))
        require(float(d['processed_s'])>=float(d['available_s'])-1e-9,'availability:'+str(fid))
        for key in c:
            if key.startswith('captured_'):require(c[key]==d[key],'context_rebound:'+str(fid)+key)
    observed_counts={i:sum(int(d['frame_id'])==i for d in deliveries) for i in range(len(captures))}
    for i,c in enumerate(captures):require(int(c['delivery_count'])==observed_counts[i],'delivery_count:'+str(i))
    raw_prev=None;high_id=high_t=None;regions={i:raster_polygon(polys[i],raster)>0 for i in cfg['route']}
    for f in frames:
        fid=int(f['frame_id']);d=uidmap[f['delivery_uid']];c=captures[fid];mask=mask_by_id[fid]
        joined=(int(d['frame_id'])==fid and flag(d['consumed']) and d['current_epoch']==f['epoch']
                and flag(d['duplicate_delivery'])==flag(f['duplicate_delivery'])
                and d['visible_mask_sha256']==c['visible_mask_sha256'])
        for key in ('exposure_start_s','available_s','processed_s'):
            joined=joined and abs(float(d[key])-float(f[key]))<1e-9
        joined=joined and abs(float(d['processed_s'])-float(f['processed_at_s']))<1e-9
        require(joined,'frame_delivery_join:'+str(fid))
        t=float(f['exposure_start_s']);yy,xx=np.nonzero(mask);point=np.array(raster['lower_mm'])+(np.array([xx.mean(),yy.mean()])+.5)/raster['pixels_per_mm']
        require(abs(float(f['x_mm'])-point[0])<1e-9 and abs(float(f['y_mm'])-point[1])<1e-9,'feature_centroid:'+str(fid))
        src=int(f['source']);dst=int(f['target']);eta=np.count_nonzero(mask&regions[src])/len(xx)
        rho=np.count_nonzero(mask&regions[dst])/regions[dst].sum();rho_src=np.count_nonzero(mask&regions[src])/regions[src].sum()
        distance=math.dist(point,centers[dst]);quality=cv2.connectedComponents(mask.astype(np.uint8))[0]-1==1 and not(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any())
        for key,value in dict(eta_source=eta,rho_target=rho,rho_source=rho_src,distance_mm=distance,source_distance_mm=math.dist(point,centers[src])).items():require(abs(float(f[key])-value)<1e-8,'feature:'+str(fid)+key)
        require(flag(f['G'])==(rho>=.9 and eta<=.08) and flag(f['Q'])==bool(quality) and flag(f['S'])==(distance<=.576),'GQS:'+str(fid))
        duplicate=high_id is not None and (fid<=high_id or t<=high_t)
        if not duplicate:high_id,high_t=fid,t
        applied=next(float(e['time_s']) for e in reversed(events) if e['event']=='simulated_applied' and float(e['time_s'])<=float(f['processed_s'])+1e-9)
        equal=(all(c['captured_'+k]==f[k] for k in ('epoch','step','attempt','source','target','phase'))
               and c['captured_run_id']==expected_run_id and c['captured_clock_domain']=='simulation'
               and c['captured_applied_s']!='' and abs(float(c['captured_applied_s'])-applied)<1e-9)
        accepted=not duplicate and equal and t>=applied-1e-10
        require(flag(f['C0'])==accepted,'C0:'+str(fid))
        key=(f['epoch'],f['phase']);speed=None
        if accepted:
            if raw_prev and raw_prev[0]==key and 0<t-raw_prev[1]<=.18:speed=math.dist(point,raw_prev[2])/(t-raw_prev[1])
            raw_prev=(key,t,point)
        else:raw_prev=None
        require(flag(f['K'])==(speed is None or speed<=19.2),'K:'+str(fid))
    expected_arrivals=[]
    for f,w in zip(frames,rebuild_windows(frames,case['method'])):
        if w is None:continue
        require(flag(f['eligible'])==w['eligible'] and int(f['window_count'])==w['window_count'] and abs(float(f['window_span_s'])-w['window_span_s'])<1e-9,'W:'+f['frame_id'])
        if f['phase']=='transport':
            require(flag(f['new_event'])==w['new_event'] and f['window_ids']==w['window_ids'],'event_evidence:'+f['frame_id'])
            if w['new_event']:expected_arrivals.append((int(f['step']),float(f['processed_s'])))
    arrivals=read(folder/'arrivals.csv');require([(int(e['step']),float(e['decision_s'])) for e in arrivals]==expected_arrivals,'arrival_event_times')
    require(len({e['step'] for e in arrivals})==len(arrivals),'once_per_step')
    pending=None;stop=None
    for e in events:
        if e['event']=='request':require(pending is None and stop is None,'illegal_new_transaction');pending=e
        elif e['event']=='simulated_applied':
            require(pending is not None and pending['request_id']==e['request_id'] and e['target']==pending['target'],'applied_matching')
            if pending:require(abs(float(e['time_s'])-float(pending['time_s'])-cfg['applied_delay_s'])<1e-9,'applied_delay')
            require(stop is None and float(e['time_s'])<=cfg['control_budget_s']+1e-9,'applied_after_terminal_budget');pending=None
        elif e['event'] in ('Complete','Stop'):require(stop is None,'exclusive_terminal');stop=e
    require(not any(e['action']=='Complete' for e in events if e['event']=='simulated_applied'),'no_complete_applied')
    require(all(int(s['applied_count'])<=cfg['max_step_applied'] and int(s['retries'])<=cfg['max_retries'] and int(s['recoveries'])<=cfg['max_recoveries'] for s in steps),'protection_budgets')
    outcome,align,spans,origin=analyze_trial(folder)
    for mark in read(folder/'reference_marks.csv'):
        require(flag(mark['supported'])==support_at(spans,int(mark['target']),float(mark['time_s']),left_limit=mark['kind']=='applied'),'reference_mark_support')
    require(outcome['attempted_steps']==metrics['attempted_steps'],'independent_attempted_denominator')
    return dict(passed=not failures,failures=failures,case=case['case_id'],checked_masks=len(captures),
        checked_frames=len(frames),intervention_count=len(interventions),outcome=outcome,origin=origin,
        controller_world_or_original_scorer_called=False)


def audit_suite(root,output):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    from dmf.chapter2_geometry_sim.exp2_faults.spec import CASES
    declarations=load(root/'mechanisms_summary.json')['declarations'];details=[]
    expected=json.loads(json.dumps([c.snapshot() for c in CASES]))
    if declarations!=expected:raise ValueError('suite must contain exact ten unique approved declarations in declared order')
    for case in declarations:
        result=audit_case(root/case['case_id']);details.append(result)
        if not result['passed']:print(result['case'],result['failures'][:20])
    result=dict(passed=len(details)==10 and all(r['passed'] for r in details),trials=details,
        checked_masks=sum(r['checked_masks'] for r in details),source_sha256=sha(__file__))
    write_json(output/'independent_audit.json',result)
    print(json.dumps(dict(passed=result['passed'],cases=len(details),checked_masks=result['checked_masks']),ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('data');p.add_argument('output');a=p.parse_args();audit_suite(a.data,a.output)
