"""Provenance-checked, additive offline workspaces for real-video registration."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

import cv2
import numpy as np

from .calibration import ArrayGridCalibration
from .config import load_yaml
from .dataset import write_csv_rows
from .design_registration import (file_hash, load_design_map, project, seal_catalog,
                                  evaluate_registration, seal_evaluation)
from .image_io import read_image
from .pilot_annotation import _json


def write_review_launcher(path, repository, python_executable, workspace):
    """Windows cmd needs explicit CRLF, especially across a UTF-8 codepage switch."""
    path=Path(path)
    repository,python_executable,workspace=(Path(p).resolve() for p in
        (repository,python_executable,workspace))
    for item in (repository,python_executable,workspace):
        if any(char in str(item) for char in ('"','\r','\n','%')):
            raise ValueError('unsafe batch launcher path')
    lines=['@echo off','chcp 65001 >nul',f'cd /d "{repository}"',
           f'"{python_executable}" "{repository / "run_design_registration.py"}" review "{workspace}"',
           'if errorlevel 1 pause']
    path.write_bytes(('\r\n'.join(lines)+'\r\n').encode('utf-8'))


def point_catalog(design, initial_design_to_image):
    by_id = {e['control_id']: e for e in design['electrodes']}
    # These feature/role assignments are made before observing any new pixels.
    fit = [(402,'tl'),(404,'tr'),(406,'tr'),(408,'br'),
           (410,'br'),(412,'bl'),(414,'bl'),(416,'tl')]
    checks = [(i,'tl') for i in (1,20,181,200,381,400,85,96,305,316,190,211)]
    checks += [(417,'tl'),(418,'tr'),(419,'br'),(420,'bl')]
    points = []
    for role, features in [('fit', fit), ('check', checks)]:
        for number, (electrode_id, corner) in enumerate(features, 1):
            electrode = by_id[electrode_id]
            polygon = np.asarray(electrode['polygon_map_mm'], dtype=float)
            lo, hi = polygon.min(axis=0), polygon.max(axis=0)
            target = {'tl':lo, 'tr':[hi[0],lo[1]], 'br':hi, 'bl':[lo[0],hi[1]]}[corner]
            index = int(np.argmin(np.linalg.norm(polygon-target, axis=1)))
            xy = polygon[index].tolist()
            points.append(dict(point_id=('F' if role=='fit' else 'C')+str(number),
                role=role, control_id=electrode_id, vertex_index=index, map_mm=xy,
                feature_definition='Exact polygon vertex shown by the design reference cross; not the bounding box or droplet edge',
                suggested_px=list(project([xy], initial_design_to_image)[0]),
                observed_px=None, status='pending', observation_method=None,
                reviewer='', reviewed_utc=None, exclusion_reason=''))
    return points


def prepare_workspace(design_directory, pilot_workspace, resource_manifest, output, *, legacy_maps=None):
    design_directory, pilot_workspace = Path(design_directory).resolve(), Path(pilot_workspace).resolve()
    resource_manifest, output = Path(resource_manifest).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('output exists; choose a new version directory')
    manifest = json.loads((design_directory/'manifest.json').read_text(encoding='utf-8'))
    map_path = design_directory/'electrode_design_map.json'
    design = load_design_map(map_path, manifest['outputs_sha256'][map_path.name])
    for name, expected in manifest['outputs_sha256'].items():
        if Path(name).name != name or file_hash(design_directory/name) != expected:
            raise ValueError('design export manifest mismatch')
    pilot = json.loads(pilot_workspace.read_text(encoding='utf-8'))
    resources = json.loads(resource_manifest.read_text(encoding='utf-8'))
    resources = {entry['video_id']:entry for entry in resources['videos']}
    verified = []
    for video_id, reference in pilot['references'].items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', video_id):
            raise ValueError('unsafe video identifier')
        source = Path(reference['source_video']).resolve()
        resource = resources[video_id]
        if (resource.get('source_kind') != 'real_camera_recording_user_confirmed' or
                Path(resource['source']).resolve() != source):
            raise ValueError('confirmed industrial-camera source provenance required')
        if file_hash(source) != resource['sha256']:
            raise ValueError('video hash mismatch')
        image_path = (pilot_workspace.parent/reference['image']).resolve()
        if file_hash(image_path) != reference['image_sha256']:
            raise ValueError('image hash mismatch')
        image = read_image(image_path, cv2.IMREAD_COLOR)
        if image is None or list(image.shape[1::-1]) != [reference['width'], reference['height']]:
            raise ValueError('native image size mismatch')
        legacy = (Path(legacy_maps[video_id]) if legacy_maps else
                  pilot_workspace.parent/pilot['calibrations'][video_id]['path'])
        config = load_yaml(legacy)
        calibration = ArrayGridCalibration(tuple(tuple(p) for p in config['core_corners_px']),
                                           pitch_mm=float(config['pitch_mm']))
        initial_h = np.diag([calibration.pitch_mm, calibration.pitch_mm, 1.]) @ calibration._pixel_to_grid
        verified.append((video_id, reference, image_path, source, resource, legacy, initial_h))
    if not verified:
        raise ValueError('no verified real video reference frames')
    output.mkdir(parents=True)
    shutil.copy2(map_path, output/'electrode_design_map.json')
    workspaces = []
    for video_id, reference, image_path, source, resource, legacy, initial_h in verified:
        folder = output/video_id;folder.mkdir()
        shutil.copy2(image_path, folder/'original.png')
        source_record = dict(reference, source_video=str(source),
            source_video_sha256=resource['sha256'], video_hash_verified=True,
            frame_origin='prior native OpenCV video extraction, reference PNG hash verified',
            raw_sensor_exposure_verified=False, crop=None, resized=False,
            brightness_contrast_gamma_adjusted=False, independent_acquisition_group='same_chip_fill_round_user_confirmed')
        workspace = dict(schema='dmf_design_registration_review_v1', simulation=False,
            video_id=video_id, source=source_record, image_path='original.png',
            image_sha256=reference['image_sha256'], image_size=[reference['width'], reference['height']],
            design_map_path='../electrode_design_map.json', design_map_sha256=file_hash(map_path),
            design_map_version=design['version'], initial_image_to_design_mm=initial_h.tolist(),
            initial_transform_status='legacy_nominal_grid_four_corners_navigation_only',
            initial_map_source=str(legacy.resolve()), initial_map_sha256=file_hash(legacy),
            fit_freeze=None, points=point_catalog(design, np.linalg.inv(initial_h)),
            notes='No observed pixels or independent accuracy until explicit manual point review.')
        seal_catalog(workspace)
        path=folder/'workspace.json';_json(path,workspace);workspaces.append(path)
    repo = Path(__file__).resolve().parents[2]
    launcher_names=['启动配准核对.cmd','核对第二张.cmd','核对第三张.cmd']
    for index,path in enumerate(workspaces):
        name=launcher_names[index] if index<len(launcher_names) else f'review_{index+1}.cmd'
        write_review_launcher(output/name,repo,Path(sys.executable),path)
    try:
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        status=subprocess.check_output(['git','status','--porcelain=v1'],cwd=repo,text=True)
    except (OSError,subprocess.CalledProcessError):
        head,status='unavailable','unavailable'
    _json(output/'manifest.json',dict(schema='dmf_registration_resources_v1',simulation=False,
        created_utc=datetime.now(timezone.utc).isoformat(), code_head=head,code_status=status,
        source_design_map=str(map_path), design_map_sha256=file_hash(map_path),
        source_pilot_workspace=str(pilot_workspace), source_pilot_sha256=file_hash(pilot_workspace),
        resource_manifest=str(resource_manifest), resource_manifest_sha256=file_hash(resource_manifest),
        workspaces=[str(p.relative_to(output)) for p in workspaces],
        excluded_materials=['non-industrial-camera empty-chip photograph (user confirmed)',
                            'bare contact-board video; not the working FPC electrode surface'],
        original_materials_modified=False, runtime_configuration_replaced=False))
    return workspaces


def load_workspace(path):
    path=Path(path)
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 'dmf_design_registration_review_v1' or data.get('simulation') is not False:
        raise ValueError('real-image registration workspace required')
    image=path.parent/data['image_path']
    if file_hash(image) != data['image_sha256']:
        raise ValueError('image hash mismatch')
    frame=read_image(image,cv2.IMREAD_COLOR)
    if frame is None or list(frame.shape[1::-1]) != data['image_size']:
        raise ValueError('native image size mismatch')
    design=load_design_map(path.parent/data['design_map_path'],data['design_map_sha256'])
    by_id={e['control_id']:e for e in design['electrodes']}
    for point in data['points']:
        vertex=by_id[point['control_id']]['polygon_map_mm'][point['vertex_index']]
        if vertex != point['map_mm']:
            raise ValueError('catalog point is not the declared actual design vertex')
    evaluate_registration(data)
    data['_loaded_sha256']=file_hash(path)
    return data


def save_workspace(path, data):
    path=Path(path)
    if file_hash(path) != data.get('_loaded_sha256'):
        raise ValueError('workspace changed externally; reopen before saving')
    evaluate_registration(data)
    clean={k:v for k,v in data.items() if not k.startswith('_')}
    _json(path,clean)
    data['_loaded_sha256']=file_hash(path)


def build_report(path, *, figures=True):
    path=Path(path).resolve();data=load_workspace(path)
    result=evaluate_registration(data)
    if data.get('use_scope')=='pre_experiment_only':
        result.update(use_scope='pre_experiment_only',final_experiment_calibration_approved=False,
                      transfer_to_old_videos_verified=False,final_relative_height_fixed=False)
    if result['rmse_px'] is not None and not data.get('evaluation_freeze'):
        seal_evaluation(data)
        save_workspace(path,data)
    revision=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f')+'_'+uuid.uuid4().hex[:6]
    output=path.parent/'reports'/revision;output.mkdir(parents=True,exist_ok=False)
    _json(output/'workspace_snapshot.json',{k:v for k,v in data.items() if not k.startswith('_')})
    _json(output/'registration_result.json',result)
    rows=[]
    residuals={r['point_id']:r for r in result['residuals']}
    for point in data['points']:
        actual=point['observed_px'] or [None,None]
        error=residuals.get(point['point_id'],{})
        rows.append(dict(point_id=point['point_id'],role=point['role'],control_id=point['control_id'],
            vertex_index=point['vertex_index'],x_design_mm=point['map_mm'][0],y_design_mm=point['map_mm'][1],
            navigation_u=point['suggested_px'][0],navigation_v=point['suggested_px'][1],
            observed_u=actual[0],observed_v=actual[1],status=point['status'],
            reviewer=point['reviewer'],reviewed_utc=point['reviewed_utc'],
            exclusion_reason=point['exclusion_reason'],error_px=error.get('error_px'),
            error_design_mm=error.get('error_design_mm')))
    write_csv_rows(output/'points.csv',rows)
    write_csv_rows(output/'summary.csv',[{k:v for k,v in result.items() if k not in
        ('residuals','image_to_design_mm','design_mm_to_image')}])
    if figures:
        from .registration_plotting import render_registration
        design=load_design_map(path.parent/data['design_map_path'],data['design_map_sha256'])
        image=read_image(path.parent/data['image_path'],cv2.IMREAD_COLOR)
        render_registration(data,design,image,result,output)
    _json(output/'manifest.json',dict(schema='dmf_registration_report_v1',simulation=False,
        workspace_sha256=file_hash(path),image_sha256=data['image_sha256'],
        design_map_sha256=data['design_map_sha256'],source=data['source'],
        status=result['status'],source_code_sha256={p.name:file_hash(p) for p in
            [Path(__file__),Path(__file__).with_name('design_registration.py'),
             Path(__file__).with_name('registration_plotting.py')] if p.exists()},
        outputs_sha256={p.name:file_hash(p) for p in output.iterdir() if p.is_file()}))
    return output
