"""One empirical-shape observation replay of frozen normal kinematics."""
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil

import cv2
import numpy as np
from shapely.geometry import Polygon

from dmf.experiment.evidence import StepContext
from dmf.vision.pilot_annotation import PilotWorkspace
from .shape_sequence import normalize_mask,SDFShapeSequence,local_mask,shape_metrics,width_at_fraction
from .normal_speed import normal_config,audit_normal_trial
from .audit import audit_trial,read_rows
from .render import _decode_rows
from .model import DesignGeometry
from .observation import SyntheticCamera,extract_features
from .shadow import ShadowArrival
from .single_step import write_csv

TRIAL_ID='geometry_empirical_sdf_v3:normal:264900:190-191'
CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
BASE=CH/'仿真结果/2026-10-28_实验一_正常速度1p4mmps_v2/trial'
REVIEW=CH/'真实分割研究/2026-10-28_单次迁移8帧形态核查_v1/review'
OUT=CH/'仿真结果/2026-10-29_实验一_SDF经验形态同轨迹_v3'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def js(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def canonical_ids(row):
    result=dict(row)
    for key in ('active','target','source','activation_segment','frame_id'):
        if key in result and result[key] not in (None,''):
            value=float(result[key])
            if not math.isfinite(value) or int(value)!=value:raise ValueError('noninteger identifier '+key)
            result[key]=int(value)
    return result


def freeze_shape_inputs(review,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    (output/'images').mkdir();(output/'masks').mkdir()
    workspace=PilotWorkspace(review)
    if [int(r['source_frame_id']) for r in workspace.rows]!=[665,670,675,680,682,688,698,710]:
        raise ValueError('declared eight source frames required')
    inputs=[];centers=[];masks=[]
    for i,row in enumerate(workspace.rows):
        image,mask=workspace.images(i);ys,xs=np.nonzero(mask)
        if not len(xs):raise ValueError('empty source mask')
        centers.append(np.array([xs.mean(),ys.mean()]));masks.append(mask)
        current=row['working_mask_path'] or row['mask_path'] or row['draft_mask_path']
        frame=int(row['source_frame_id']);a=output/'images'/f'f{frame}.png';b=output/'masks'/f'f{frame}.png'
        shutil.copyfile(workspace.root/row['frame_path'],a);shutil.copyfile(workspace.root/current,b)
        inputs.append(dict(source_frame_id=frame,image_path=a.relative_to(output).as_posix(),
            mask_path=b.relative_to(output).as_posix(),image_sha256=sha(a),mask_sha256=sha(b),
            source_image=str(workspace.root/row['frame_path']),effective_source_mask=str(workspace.root/current),
            original_gui_mask_reviewed=bool(row['mask_reviewed']),state_gt='Unknown',
            usage='provisional_shape_model_input_not_independent_evaluation_GT',
            receive_timestamp_s=float(row['timestamp_s']),centroid_source_px=centers[-1].tolist()))
    direction=centers[-1]-centers[0];den=float(direction@direction)
    if den<=0:raise ValueError('unresolved movement direction')
    phases=[float((c-centers[0])@direction/den) for c in centers]
    phases[0]=0.;phases[-1]=1.
    polygons=[normalize_mask(m,direction,4.) for m in masks]
    sequence=SDFShapeSequence(phases,polygons)
    for record,q,p in zip(inputs,phases,polygons):
        record['phase']=q;record['normalized_polygon_mm']=np.asarray(p.exterior.coords).tolist()
    library=dict(schema='empirical_shape_sequence_v1',inputs=inputs,direction_source_px=direction.tolist(),
        target_equivalent_diameter_mm=4.,area_mm2=4*math.pi,
        local_raster=dict(pixels_per_mm=80.,half_extent_mm=5.),
        human_feedback=dict(date='2026-10-29',verbatim='mask基本没啥问题',
             interpretation='preliminary visual acceptance for modeling; not independent test GT'),
        original_reviewed_count=sum(r['original_gui_mask_reviewed'] for r in inputs),
        gui_review_flags_modified=False,independent_acquisition_groups=1,
        task_identity='inferred386→385 from recorded activation and visible leftward motion; not registered image GT',
        virtual_task='normalized orientation mapped to190→191 for model sensitivity only',
        valid_real_video_map_binding=False,heldout_evaluation_available=False,
        source_workspace_sha256=sha(workspace.root/'workspace.json'))
    js(output/'shape_library.json',library)
    return library,sequence


def run_empirical(output=OUT,review=REVIEW,base=BASE):
    output=Path(output);base=Path(base)
    if output.exists():raise FileExistsError(output)
    old_audit=audit_normal_trial(base)
    if not old_audit['passed']:raise ValueError(old_audit)
    output.mkdir(parents=True)
    library,sequence=freeze_shape_inputs(review,output/'shape_inputs')
    old=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    geometry=DesignGeometry(old['source_map_path']);config=normal_config()
    camera=SyntheticCamera(geometry,config)
    original_world=_decode_rows(read_rows(base/'world.csv'))
    original_obs=_decode_rows(read_rows(base/'observations.csv'))
    src=geometry.center(190);dst=geometry.center(191);axis=dst-src;den=float(axis@axis)
    world=[];shapes=[];by_time={};min_moving_overlap=float('inf')
    for i,row in enumerate(original_world):
        point=np.array([row['x_mm'],row['y_mm']]);q=float((point-src)@axis/den)
        if q< -1e-8 or q>1+1e-8:raise ValueError('base kinematic progress outside declared range')
        q=float(np.clip(q,0,1));p=sequence.polygon(q,point)
        if i and row['speed_mm_s']>1e-9:
            previous=Polygon(shapes[-1]['polygon_mm'])
            overlap=previous.intersection(geometry.polygons[int(row['active'])]).area
            min_moving_overlap=min(min_moving_overlap,overlap)
            if overlap<=1e-8:raise ValueError(f'no overlap on frozen moving trajectory at {row["time_s"]}; no trajectory repair')
        r=dict(row);r.pop('stretch',None)
        r.update(trial_id=TRIAL_ID,area_mm2=p.area,shape_phase=q,shape_model='empirical_sdf',
                 active_overlap_mm2=p.intersection(geometry.polygons[int(row['active'])]).area)
        world.append(canonical_ids(r));shapes.append(dict(time_s=row['time_s'],polygon_mm=np.asarray(p.exterior.coords).tolist()))
        by_time[round(row['time_s'],8)]=p
    trial=output/'trial';trial.mkdir();(trial/'masks').mkdir()
    context=StepContext(TRIAL_ID,1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54,applied_time_quality='simulation_exact')
    shadow=ShadowArrival(context);observations=[];previous=None
    events=[canonical_ids(dict(r,trial_id=TRIAL_ID)) for r in _decode_rows(read_rows(base/'events.csv'))
            if r['event'] in ('request','simulated_applied')]
    for original in original_obs:
        t=original['exposure_start_s'];fid=int(original['frame_id'])
        frame=camera.expose(fid,t,by_time[round(t,8)],context if t>=.54-1e-10 else None)
        frame.processed_at_s=original['processed_at_s']
        mask_path=trial/'masks'/f'{fid:04d}.png';mask_path.write_bytes(cv2.imencode('.png',frame.mask)[1].tobytes())
        features=extract_features(frame,camera.raster,190,191)
        row=dict(trial_id=TRIAL_ID,frame_id=fid,exposure_start_s=t,exposure_end_s=frame.exposure_end_s,
             available_s=frame.available_s,processed_at_s=frame.processed_at_s,source=190,target=191,
             clock_domain='simulation',captured_epoch=1 if frame.context else None,
             mask_path=mask_path.relative_to(trial).as_posix(),mask_sha256=sha(mask_path),**features)
        row['observed_speed_mm_s']=None
        if features['valid']:
            point=np.array([features['x_mm'],features['y_mm']])
            if previous is not None and 0<t-previous[0]<=.18:
                row['observed_speed_mm_s']=float(np.linalg.norm(point-previous[1])/(t-previous[0]))
            previous=(t,point)
        # Algorithm sees only camera Mask-derived features, frame/timing/context.
        gate=shadow.observe(frame,features);row.update(gate);observations.append(row)
        for key,name in [('single_event','single_confirmation'),('window_event','window_confirmation'),('spatiotemporal_event','spatiotemporal_confirmation')]:
            if gate[key]:events.append(dict(trial_id=TRIAL_ID,time_s=frame.processed_at_s,event=name,
                  target=191,action='ShadowOnly',frame_id=fid,exposure_start_s=t))
    reference=json.loads((base/'reference.json').read_text(encoding='utf-8'))
    if reference['confirmed_s'] is not None:events.append(dict(trial_id=TRIAL_ID,time_s=reference['confirmed_s'],
              event='independent_reference',target=191,action='ScoringOnly'))
    events.sort(key=lambda r:r['time_s'])
    write_csv(trial/'world.csv',world);write_csv(trial/'observations.csv',observations);write_csv(trial/'events.csv',events)
    js(trial/'world_polygons.json',shapes);js(trial/'raster.json',camera.raster.snapshot())
    js(trial/'reference.json',reference);js(trial/'template.json',library)
    js(trial/'camera_random_offsets.json',camera.position_errors.tolist())
    shutil.copyfile(base/'map_snapshot.json',trial/'map_snapshot.json')
    summary=dict(request_s=.5,applied_s=.54,response_start_s=.72,center_reached_s=old['summary']['center_reached_s'],
        reference_confirmation_s=reference['confirmed_s'],single_confirmation_s=shadow.single_s,
        window_confirmation_s=shadow.window_s,spatiotemporal_confirmation_s=shadow.full_s,
        world_ticks=len(world),processed_masks=len(observations),request_count=1,applied_count=1,
        min_moving_target_overlap_mm2=min_moving_overlap,
        max_geometric_area_relative_error=max(abs(r['area_mm2']/(4*math.pi)-1) for r in world),
        max_mask_area_relative_error=max(abs(r['area_mm2']/(4*math.pi)-1) for r in observations))
    manifest=dict(schema='geometry_empirical_sdf_v3',trial_id=TRIAL_ID,mode='simulation',scenario='normal',research_trials=1,
       clock_domain='simulation',source_preparation='controlled_initial_condition_not_P0',config=old['config'],summary=summary,
       source_map_path=old['source_map_path'],source_map_sha256=old['source_map_sha256'],
       source_template_sha256=sha(output/'shape_inputs/shape_library.json'),
       shape_library_manifest=str(output/'shape_inputs/shape_library.json'),
       source_kinematics=dict(root=str(base),manifest_sha256=sha(base/'manifest.json'),
              world_sha256=sha(base/'world.csv'),reference_sha256=sha(base/'reference.json'),
              equality_fields=['time_s','x_mm','y_mm','speed_mm_s','active','activation_segment','response_at_s','world_status']),
       methods=old['methods'],candidate_gates=old['candidate_gates'],five_state_classifier_used=False,
       algorithm_inputs=old['algorithm_inputs'],controller=old['controller'],
       source_code={str(Path(__file__).resolve()):sha(__file__),
                    str(Path(__file__).with_name('shape_sequence.py')):sha(Path(__file__).with_name('shape_sequence.py'))},
       model_limits=['Empirical video-informed normalized shape; not CFD or physical calibration.',
          'Eight modeling shapes have preliminary human visual acceptance; GUI has4/8 formal saved flags.',
          'No independent heldout migration or valid real video electrode binding; fitting metrics are not validation accuracy.',
          'Source and target IDs inferred from activation logs are not real-image task GT.'])
    manifest['artifacts']={p.relative_to(trial).as_posix():sha(p) for p in trial.rglob('*') if p.is_file()}
    js(trial/'manifest.json',manifest);write_csv(output/'sdf_interpolation_diagnostics.csv',list(sequence.diagnostics.values()))
    audit=audit_empirical(trial);js(output/'independent_audit.json',audit)
    if not audit['passed']:raise ValueError(audit)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    return manifest


def audit_empirical(root):
    root=Path(root);result=audit_trial(root)
    failures=[x for x in result['failures'] if x!='full_tick_and_frame_counts']
    m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if m['trial_id']!=TRIAL_ID:failures.append('empirical_trial_identity')
    w=read_rows(root/'world.csv');o=read_rows(root/'observations.csv')
    if (len(w),len(o))!=(601,120):failures.append('empirical_counts')
    base=Path(m['source_kinematics']['root']);old=read_rows(base/'world.csv')
    for a,b in zip(w,old):
        for key in m['source_kinematics']['equality_fields']:
            try:equal=abs(float(a[key])-float(b[key]))<1e-12
            except ValueError:equal=a[key]==b[key]
            if not equal:failures.append('frozen_kinematics:'+key)
    if sha(base/'manifest.json')!=m['source_kinematics']['manifest_sha256'] or sha(base/'world.csv')!=m['source_kinematics']['world_sha256']:
        failures.append('base_source_changed')
    if sha(root/'reference.json')!=m['source_kinematics']['reference_sha256']:failures.append('reference_changed')
    for source,digest in m['source_code'].items():
        if sha(source)!=digest:failures.append('empirical_source_changed')
    for r in w:
        if float(r['speed_mm_s'])>1.4+1e-8:failures.append('speed_exceeds_frozen_bound')
    result.update(passed=not failures,failures=sorted(set(failures)),
                  frozen_position_speed_activation_reference_equal=True,
                  evidence_scope='normal n=1 shape sensitivity, not independent shape or algorithm performance')
    return result


if __name__=='__main__':run_empirical()
