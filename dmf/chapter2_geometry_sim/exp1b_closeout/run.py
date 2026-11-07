"""Complete only B1 via saved-outline replay; copy all other cases unchanged."""
import json
import math
from pathlib import Path
import shutil
import cv2
import numpy as np
from shapely.geometry import Polygon
from dmf.experiment.evidence import StepContext
from ..sdf_trial import OUT as SHAPE_BASE,js,sha
from ..model import DesignGeometry
from ..observation import Raster,CameraFrame,extract_features
from ..reference import evaluate_reference
from ..single_step import write_csv
from ..render import _decode_rows
from ..exp1b.generate import make_kinematics,verify_baseline
from ..exp1b.spec import METHODS
from ..exp1b.gates import RawAssessor,GateRunner
from ..exp1b.evaluate import score_event
from ..exp1b.audit import read,load,audit_development
from .replay import SavedOutlineReplay
from .semantics import exclusive_outcome

VERSION='geometry_exp1b_closeout_saved_replay_v1'


def saved_pool():
    rows=_decode_rows(read(SHAPE_BASE/'trial/world.csv'))
    shapes=load(SHAPE_BASE/'trial/world_polygons.json')
    phases=[];polygons=[];source_ticks=[]
    for i,(row,shape) in enumerate(zip(rows,shapes)):
        q=float(row['shape_phase'])
        if phases and q==phases[-1]:continue
        phases.append(q);polygons.append(Polygon(shape['polygon_mm']));source_ticks.append(i)
    return rows,SavedOutlineReplay(phases,polygons),source_ticks


def run_closeout(parent,output):
    parent,output=Path(parent),Path(output)
    if output.exists():raise FileExistsError(output)
    parent_audit=audit_development(parent)
    if not parent_audit['passed']:raise ValueError('parent consistency audit failed')
    verify_baseline()
    output.mkdir(parents=True);(output/'provenance').mkdir()
    copied=[]
    def copy(source,dest):
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        copied.append(dict(source=str(source.resolve()),relative=dest.relative_to(output).as_posix(),sha256=sha(dest)))
    for rel in ('config.json','baseline_entries.json','map_snapshot.json','raster.json','shape_library.json'):
        copy(parent/rel,output/rel)
    for category,excluded in [('worlds','slow'),('caches','B1')]:
        for folder in (parent/category).iterdir():
            if folder.name==excluded:continue
            for p in folder.rglob('*'):
                if p.is_file():copy(p,output/p.relative_to(parent))
    for rel in ('manifest.json','failures.json','independent_audit.json','worlds/slow/failure.json','caches/B1/failure.json'):
        copy(parent/rel,output/'provenance'/rel)
    js(output/'copy_inventory.json',copied)
    js(output/'closeout_protocol.json',dict(version=VERSION,parent=str(parent.resolve()),
        parent_manifest_sha256=sha(parent/'manifest.json'),new_cache_runs=1,reused_caches=15,
        fallback='nearest saved valid outline by world progress; tie chooses lower; translation only',
        new_SDF_interpolation=False,thresholds_changed=False,control_safety_evaluated=False,
        no_random_batch=True,seed=264900,random_draws=0))
    geometry=DesignGeometry(output/'map_snapshot.json');raster=Raster(geometry,190,191,40.,4.)
    old_world,pool,source_ticks=saved_pool()
    rows=make_kinematics(old_world,'slow');polygons=[];diagnostics=[]
    source=geometry.center(190);target=geometry.center(191);axis=target-source;den=float(axis@axis)
    min_overlap=math.inf;area_error=0.
    for i,row in enumerate(rows):
        point=np.array([row['x_mm'],row['y_mm']]);q=float((point-source)@axis/den)
        p,info=pool.at(q,point)
        if not p.is_valid or len(p.interiors):raise ValueError('invalid translated saved contour; no repair')
        area_error=max(area_error,abs(p.area/pool.area-1))
        if math.hypot(p.centroid.x-point[0],p.centroid.y-point[1])>1e-8:raise ValueError('centroid mismatch')
        if i and row['speed_mm_s']>1e-8:
            overlap=polygons[-1].intersection(geometry.polygons[int(row['active'])]).area
            min_overlap=min(min_overlap,overlap)
            if overlap<=1e-8:raise ValueError('motion without active overlap')
        diagnostics.append(dict(time_s=row['time_s'],source_tick=source_ticks[info['selected_index']],**info))
        row.update(trial_id=VERSION+':B1',world_id='slow',shape_phase=q,selected_shape_phase=info['selected_phase'],
            area_mm2=p.area,active_overlap_mm2=p.intersection(geometry.polygons[int(row['active'])]).area)
        polygons.append(p)
    folder=output/'worlds/slow';folder.mkdir(parents=True)
    reference=evaluate_reference(rows,target,191,.54)
    write_csv(folder/'internal_world.csv',rows)
    write_csv(folder/'outline_replay_diagnostics.csv',diagnostics)
    js(folder/'internal_polygons.json',[dict(time_s=r['time_s'],polygon_mm=list(p.exterior.coords)) for r,p in zip(rows,polygons)])
    js(folder/'reference.json',reference)
    js(folder/'control_events.json',[dict(time_s=.5,event='request',target=191),dict(time_s=.54,event='simulated_applied',target=191)])
    actual_error=max(abs(r['phase_error']) for r in diagnostics)
    js(folder/'world_manifest.json',dict(world_id='slow',ticks=len(rows),reference=reference['confirmed_s'],
        shape_provider='nearest_saved_valid_outline',saved_pool_count=len(pool.phases),
        max_phase_error=actual_error,phase_error_bound=pool.max_phase_error_bound,
        max_phase_distance_mm=actual_error*math.sqrt(den),max_geometric_area_relative_error=area_error,
        minimum_moving_overlap_mm2=min_overlap,source_pool_world_sha256=sha(SHAPE_BASE/'trial/world.csv'),
        source_pool_polygons_sha256=sha(SHAPE_BASE/'trial/world_polygons.json'),
        source='model_generated_not_empirically_calibrated'))
    cache=output/'caches/B1';cache.mkdir(parents=True);(cache/'masks').mkdir()
    context=StepContext(VERSION+':B1',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54,
        applied_time_quality='simulation_exact')
    raw_assessor=RawAssessor(context);runners=[GateRunner(m,context) for m in METHODS]
    captures=[];deliveries=[];raw_rows=[];predictions={m.name:[] for m in METHODS}
    max_mask_area_error=0.
    for i in range(200):
        t=round(i*.05,10);mask=raster.mask(polygons[i*5]);path=cache/'masks'/f'{i:04d}.png'
        path.write_bytes(cv2.imencode('.png',mask)[1].tobytes())
        frame=CameraFrame(i,t,t+.008,t+.048,mask,context if t>=.54-1e-10 else None,round(t+.05,10))
        features=extract_features(frame,raster,190,191)
        if not features['valid']:raise ValueError('empty slow observation')
        max_mask_area_error=max(max_mask_area_error,abs(features['area_mm2']/pool.area-1))
        captures.append(dict(frame_id=i,exposure_start_s=t,exposure_end_s=frame.exposure_end_s,available_s=frame.available_s,
            captured_epoch=frame.context.epoch if frame.context else None,mask_path=path.relative_to(cache).as_posix(),
            mask_sha256=sha(path),changed_pixels=0,delivered=True,**features))
        deliveries.append(dict(frame_id=i,processed_s=frame.processed_at_s,old_context=False,duplicate_delivery=False))
        raw=raw_assessor.observe(frame,features)
        common=dict(delivery_id=i,frame_id=i,exposure_start_s=t,available_s=frame.available_s,
            processed_at_s=frame.processed_at_s,**features,**raw)
        raw_rows.append(common)
        for runner in runners:predictions[runner.spec.name].append(dict(common,**runner.observe(frame,raw)))
    write_csv(cache/'captures.csv',captures);write_csv(cache/'deliveries.csv',deliveries);write_csv(cache/'raw_observations.csv',raw_rows)
    summaries=[r for r in read(parent/'planned_method_results.csv') if r['case_id']!='B1']
    for runner in runners:
        write_csv(cache/(runner.spec.name+'_frames.csv'),predictions[runner.spec.name]);js(cache/(runner.spec.name+'_event.json'),runner.event)
        summaries.append(dict(case_id='B1',case_label='慢速',method=runner.spec.name,world_id='slow',source_type='model_generated',
            status='executed',processed_frames=200,invalid_observations=sum(not r['C0'] for r in raw_rows),
            generated_masks=200,dropped_frames=0,**score_event(runner.event,reference,10.)))
    order={r['name']:i for i,r in enumerate(load(output/'config.json')['cases'])}
    method_order={m.name:i for i,m in enumerate(METHODS)}
    summaries.sort(key=lambda r:(order[r['case_id']],method_order[r['method']]))
    write_csv(output/'planned_method_results.csv',summaries)
    write_csv(output/'exclusive_step_outcomes.csv',[dict(case_id=r['case_id'],method=r['method'],**exclusive_outcome(r)) for r in summaries])
    js(cache/'manifest.json',dict(case_id='B1',world_id='slow',source_type='model_generated',generated_masks=200,
        processed_deliveries=200,mutated_frames=0,dropped_frames=0,duplicate_deliveries=0,
        cache_sha256=sha(cache/'captures.csv'),raw_history_sha256=sha(cache/'raw_observations.csv'),
        shape_provider='nearest_saved_valid_outline',max_mask_area_relative_error=max_mask_area_error,
        model_boundary='SIMULATION; normalized4mm silhouette; not CFD or actual U-Net'))
    if area_error>.005 or max_mask_area_error>.02 or actual_error>pool.max_phase_error_bound+1e-12:
        raise ValueError('replay numeric tolerance failed')
    js(output/'failures.json',[])
    parent_manifest=load(parent/'manifest.json');sources=dict(parent_manifest['source_code'])
    for p in Path(__file__).parent.glob('*.py'):sources[str(p.resolve())]=sha(p)
    js(output/'manifest.json',dict(version=VERSION,planned_caches=16,planned_method_records=96,base_worlds=4,random_draws=0,
        seed=264900,source_baseline=str(SHAPE_BASE),parent=str(parent.resolve()),new_cache_runs=1,reused_caches=15,
        source_code=sources,failures=[],historical_failure_preserved=True,
        artifacts={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps(dict(B1_reference_s=reference['confirmed_s'],max_phase_error=actual_error,
        max_phase_distance_mm=actual_error*math.sqrt(den),area_error=area_error,mask_area_error=max_mask_area_error,
        confirmations={r.spec.name:r.event['decision_s'] if r.event else None for r in runners}),ensure_ascii=False,indent=2),flush=True)
    return summaries
