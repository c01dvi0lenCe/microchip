"""Deterministic observation perturbations; no truth is supplied to algorithms."""
import cv2
import numpy as np
import json
from pathlib import Path
from dataclasses import replace
import math
import shutil
from shapely.geometry import Polygon
from dmf.experiment.evidence import StepContext
from ..sdf_trial import OUT as BASE,sha,js
from ..model import DesignGeometry
from ..shape_sequence import SDFShapeSequence
from ..observation import Raster,CameraFrame,extract_features
from ..reference import evaluate_reference
from ..single_step import write_csv
from ..audit import read_rows
from ..render import _decode_rows
from .spec import CASES,METHODS,HORIZON,VERSION,snapshot
from .gates import RawAssessor,GateRunner
from .evaluate import score_event


def alter_mask(case,mask,t,lower,target_template):
    result=mask.copy()
    near=4.2-1e-9<=t<=4.5+1e-9
    if case in ('C5','C6') and (abs(t-2)<1e-9 if case=='C5' else 2-1e-9<=t<=2.3+1e-9):
        return target_template.copy()
    dy=0
    if case=='C1' and near:dy=1 if round(t*20)%2==0 else -1
    if case=='C2' and near:dy=8
    if case=='D6' and abs(t-4.4)<1e-9:dy=48
    if dy:
        result=cv2.warpAffine(result,np.array([[1,0,0],[0,1,dy]],dtype=np.float64),
            result.shape[::-1],flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    if case in ('C3','C4') and near:
        ys,xs=np.nonzero(result)
        if len(xs):
            if case=='C3':result[:, :int(xs.min()+.2*(xs.max()-xs.min()+1))]=0
            else:
                y=round(float(ys.mean()));result[y:y+2,:]=0
    return result


def delivery_plan(case,frame_id,t,processed_s):
    if case=='D1' and abs(t-4.4)<1e-9:return []
    if case=='D2' and 4.3-1e-9<=t<=4.5+1e-9:return []
    row=dict(frame_id=frame_id,processed_s=processed_s,old_context=case=='D5' and abs(t-4.4)<1e-9,
             duplicate_delivery=False)
    if case=='D4' and abs(t-4.4)<1e-9:row['processed_s']+=.3
    if case=='D3' and abs(t-4.4)<1e-9:
        return [row,dict(row,processed_s=processed_s+.001,duplicate_delivery=True)]
    return [row]


def make_kinematics(base,kind):
    if kind not in ('normal','slow','pause','stall'):raise ValueError('undeclared world')
    src=np.array([base[0]['x_mm'],base[0]['y_mm']]);dst=np.array([base[-1]['x_mm'],base[-1]['y_mm']])
    length=float(np.linalg.norm(dst-src));axis=dst-src
    pause_index=next(i for i,r in enumerate(base) if (np.array([r['x_mm'],r['y_mm']])-src)@axis/(length**2)>=.55)
    result=[]
    for i in range(1001):
        t=round(i*.01,10)
        index=min(i,len(base)-1)
        if kind=='pause':index=min(i if i<pause_index else max(pause_index,i-100),len(base)-1)
        if kind=='stall':index=min(i,pause_index)
        row=dict(base[index],time_s=t,base_tick_index=index)
        if kind=='slow':
            duration=1.875*length/.7;u=min(1.,max(0.,(t-.72)/duration))
            q=10*u**3-15*u**4+6*u**5;point=src+q*axis
            row.update(x_mm=float(point[0]),y_mm=float(point[1]),base_tick_index=-1,
                active=191 if t>=.54-1e-10 else 190,activation_segment=int(t>=.54-1e-10),response_at_s=.72)
        if i:
            previous=result[-1]
            row['speed_mm_s']=math.hypot(row['x_mm']-previous['x_mm'],row['y_mm']-previous['y_mm'])/.01
        else:row['speed_mm_s']=0.
        if t<=.72+1e-9 and row['speed_mm_s']>1e-8:raise ValueError('motion before response')
        result.append(row)
    return result


def verify_baseline():
    expected={'trial/manifest.json':'0e8972d02a555dff1253fc1465f90563514e0142cd17292277e731c6255eba3f',
        'shape_inputs/shape_library.json':'b16c6db24e3dc5f22b2b686a76009fda8c15f33d1044f1f8ad7a7b887300afc8',
        'visualization/render_manifest.json':'bd47962234816119389a0a7efd9832a0c000c21aafd6154d5f53c48c687afb64'}
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    for rel,digest in expected.items():
        if sha(BASE/rel)!=digest:raise ValueError('frozen entry changed '+rel)
    m=load(BASE/'trial/manifest.json')
    for rel,digest in m['artifacts'].items():
        if sha(BASE/'trial'/rel)!=digest:raise ValueError('frozen artifact changed '+rel)
    for p,digest in m['source_code'].items():
        if sha(p)!=digest:raise ValueError('frozen source changed '+p)
    library=load(BASE/'shape_inputs/shape_library.json')
    for r in library['inputs']:
        for k,h in [('image_path','image_sha256'),('mask_path','mask_sha256')]:
            if sha(BASE/'shape_inputs'/r[k])!=r[h]:raise ValueError('shape input changed')
    return m,library,expected


def unattempted_results(case,error):
    return [dict(case_id=case.name,case_label=case.label,method=m.name,world_id=case.world,
        source_type=case.source_type,status='world_generation_failed',planned_steps=1,
        reference_arrivals=None,unattempted=True,error=error) for m in METHODS]


def run_development(output,reuse_normal_from=None):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    baseline,library,frozen=verify_baseline()
    output.mkdir(parents=True)
    js(output/'config.json',snapshot());js(output/'baseline_entries.json',frozen)
    (output/'shape_library.json').write_bytes((BASE/'shape_inputs/shape_library.json').read_bytes())
    (output/'map_snapshot.json').write_bytes((BASE/'trial/map_snapshot.json').read_bytes())
    geometry=DesignGeometry(output/'map_snapshot.json')
    raster=Raster(geometry,190,191,40.,4.)
    js(output/'raster.json',raster.snapshot())
    source=geometry.center(190);target=geometry.center(191);axis=target-source;den=float(axis@axis)
    base_rows=_decode_rows(read_rows(BASE/'trial/world.csv'))
    base_polygons=json.loads((BASE/'trial/world_polygons.json').read_text(encoding='utf-8'))
    sequence=SDFShapeSequence([r['phase'] for r in library['inputs']],
        [Polygon(r['normalized_polygon_mm']) for r in library['inputs']])
    worlds={};references={};summaries=[];failures=[]
    for kind in ('normal','slow','pause','stall'):
        folder=output/'worlds'/kind;folder.mkdir(parents=True)
        if kind=='normal' and reuse_normal_from is not None:
            origin=Path(reuse_normal_from)
            for p in origin.iterdir():
                if p.is_file():shutil.copyfile(p,folder/p.name)
            rows=_decode_rows(read_rows(folder/'internal_world.csv'))
            polygons=[Polygon(r['polygon_mm']) for r in json.loads((folder/'internal_polygons.json').read_text(encoding='utf-8'))]
            worlds[kind]=(rows,polygons);references[kind]=json.loads((folder/'reference.json').read_text(encoding='utf-8'))
            js(output/'reused_normal_source.json',dict(source=str(origin.resolve()),
                files={p.name:sha(p) for p in origin.iterdir() if p.is_file()},reason='reuse_completed_normal_from_aborted_preacceptance_attempt'))
            print('world normal reused, reference',references[kind]['confirmed_s'],flush=True)
            continue
        rows=make_kinematics(base_rows,kind);polygons=[];min_overlap=math.inf
        world_error=None
        for i,row in enumerate(rows):
            point=np.array([row['x_mm'],row['y_mm']]);q=float(np.clip((point-source)@axis/den,0,1))
            try:
                p=(sequence.polygon(q,point) if kind=='slow' else Polygon(base_polygons[row['base_tick_index']]['polygon_mm']))
            except ValueError as error:
                world_error=dict(stage='world_generation',world_id=kind,case_id='B1',tick=i,time_s=row['time_s'],
                    shape_phase=q,error=str(error),topology_repaired=False)
                break
            if abs(p.area/(4*math.pi)-1)>0.005:raise ValueError('world area')
            if math.hypot(p.centroid.x-point[0],p.centroid.y-point[1])>1e-7:raise ValueError('shape centroid drift')
            if i and row['speed_mm_s']>1e-8:
                overlap=polygons[-1].intersection(geometry.polygons[row['active']]).area
                min_overlap=min(min_overlap,overlap)
                if overlap<=1e-8:raise ValueError('frozen trajectory blocked by non-overlap')
            row.update(world_id=kind,shape_phase=q,area_mm2=p.area,active_overlap_mm2=p.intersection(geometry.polygons[row['active']]).area)
            polygons.append(p)
        if world_error:
            failures.append(world_error);js(folder/'failure.json',world_error)
            write_csv(folder/'partial_world_before_failure.csv',rows[:i])
            print('world failed',world_error,flush=True)
            continue
        reference=evaluate_reference(rows,target,191,.54)
        write_csv(folder/'internal_world.csv',rows)
        js(folder/'internal_polygons.json',[dict(time_s=r['time_s'],polygon_mm=list(p.exterior.coords)) for r,p in zip(rows,polygons)])
        js(folder/'reference.json',reference)
        js(folder/'control_events.json',[dict(time_s=.5,event='request',target=191),dict(time_s=.54,event='simulated_applied',target=191)])
        js(folder/'world_manifest.json',dict(world_id=kind,reference=reference['confirmed_s'],ticks=len(rows),
            minimum_moving_overlap_mm2=min_overlap,source='model_generated_not_empirically_calibrated'))
        worlds[kind]=(rows,polygons);references[kind]=reference
        print('world',kind,'reference',reference['confirmed_s'],flush=True)
    target_template=raster.mask(worlds['normal'][1][-1])
    for case in CASES:
        folder=output/'caches'/case.name;folder.mkdir(parents=True);(folder/'masks').mkdir()
        if case.world not in worlds:
            error=next(f for f in failures if f.get('world_id')==case.world)
            js(folder/'failure.json',error);summaries.extend(unattempted_results(case,error['error']))
            continue
        try:
            rows,polygons=worlds[case.world]
            context=StepContext(VERSION+':'+case.name,1,0,1,190,191,clock_domain='simulation',
                applied_timestamp_s=.54,applied_time_quality='simulation_exact')
            captures=[];deliveries=[];frames={};features_by_id={};mutation_count=0
            for frame_id in range(200):
                t=round(frame_id*.05,10);p=polygons[frame_id*5];original=raster.mask(p)
                mask=alter_mask(case.name,original,t,raster.lower,target_template)
                changed=not np.array_equal(mask,original);mutation_count+=int(changed)
                path=folder/'masks'/f'{frame_id:04d}.png'
                path.write_bytes(cv2.imencode('.png',mask)[1].tobytes())
                capture_context=context if t>=.54-1e-10 else None
                if case.name=='D5' and abs(t-4.4)<1e-9:capture_context=replace(context,epoch=0)
                frame=CameraFrame(frame_id,t,t+.008,t+.048,mask,capture_context,round(t+.05,10))
                features=extract_features(frame,raster,190,191)
                frames[frame_id]=frame;features_by_id[frame_id]=features
                plans=delivery_plan(case.name,frame_id,t,frame.processed_at_s)
                deliveries.extend(plans)
                captures.append(dict(frame_id=frame_id,exposure_start_s=t,exposure_end_s=frame.exposure_end_s,
                    available_s=frame.available_s,captured_epoch=capture_context.epoch if capture_context else None,
                    mask_path=path.relative_to(folder).as_posix(),mask_sha256=sha(path),
                    changed_pixels=int(np.count_nonzero(mask!=original)),delivered=bool(plans),**features))
            deliveries.sort(key=lambda r:(r['processed_s'],r['duplicate_delivery']))
            raw_assessor=RawAssessor(context);runners=[GateRunner(s,context) for s in METHODS]
            prediction_rows={m.name:[] for m in METHODS};raw_rows=[]
            for delivery_id,d in enumerate(deliveries):
                frame=replace(frames[d['frame_id']],processed_at_s=d['processed_s'])
                if frame.processed_at_s>HORIZON+1e-9:continue
                feature=features_by_id[frame.frame_id];raw=raw_assessor.observe(frame,feature)
                common=dict(delivery_id=delivery_id,frame_id=frame.frame_id,exposure_start_s=frame.exposure_start_s,
                    available_s=frame.available_s,processed_at_s=frame.processed_at_s,**feature,**raw)
                raw_rows.append(common)
                for runner in runners:
                    prediction_rows[runner.spec.name].append(dict(common,**runner.observe(frame,raw)))
            write_csv(folder/'captures.csv',captures);write_csv(folder/'deliveries.csv',deliveries)
            write_csv(folder/'raw_observations.csv',raw_rows)
            for runner in runners:
                write_csv(folder/(runner.spec.name+'_frames.csv'),prediction_rows[runner.spec.name])
                js(folder/(runner.spec.name+'_event.json'),runner.event)
                score=score_event(runner.event,references[case.world],HORIZON)
                summaries.append(dict(case_id=case.name,case_label=case.label,method=runner.spec.name,
                    world_id=case.world,source_type=case.source_type,status='executed',processed_frames=len(raw_rows),
                    invalid_observations=sum(not r['C0'] for r in raw_rows),
                    generated_masks=200,dropped_frames=sum(not r['delivered'] for r in captures),**score))
            manifest=dict(case_id=case.name,world_id=case.world,source_type=case.source_type,
                generated_masks=200,processed_deliveries=len(raw_rows),mutated_frames=mutation_count,
                dropped_frames=sum(not r['delivered'] for r in captures),
                duplicate_deliveries=sum(r['duplicate_delivery'] for r in deliveries),
                cache_sha256=sha(folder/'captures.csv'),raw_history_sha256=sha(folder/'raw_observations.csv'),
                model_boundary='SIMULATION; no U-Net, no CFD; nominal mm after 4mm area normalization')
            js(folder/'manifest.json',manifest)
            print('case',case.name,[(r.spec.name,None if r.event is None else r.event['decision_s']) for r in runners],flush=True)
        except Exception as error:
            failures.append(dict(case_id=case.name,error=repr(error)));js(folder/'failure.json',failures[-1])
            for method in METHODS:
                summaries.append(dict(case_id=case.name,case_label=case.label,method=method.name,
                    world_id=case.world,source_type=case.source_type,status='execution_error',planned_steps=1,
                    unattempted=True,error=repr(error)))
    write_csv(output/'planned_method_results.csv',summaries);js(output/'failures.json',failures)
    source_files=list(Path(__file__).parent.glob('*.py'))+[Path(__file__).resolve().parents[1]/name for name in
        ('shape_sequence.py','sdf_trial.py','model.py','observation.py','reference.py','single_step.py')]
    source_files.append(Path(__file__).resolve().parents[2]/'experiment/evidence.py')
    js(output/'manifest.json',dict(version=VERSION,planned_caches=16,planned_method_records=96,
        base_worlds=4,random_draws=0,seed=264900,source_baseline=str(BASE),
        source_code={str(p.resolve()):sha(p) for p in source_files},failures=failures,
        artifacts={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}))
    return summaries
