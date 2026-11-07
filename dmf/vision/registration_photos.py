"""Native industrial-camera photo input, explicitly limited to pre-experiment use."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys

import cv2
import numpy as np

from .calibration import ArrayGridCalibration
from .design_registration import file_hash, load_design_map, seal_catalog
from .image_io import read_image
from .pilot_annotation import _json
from .registration_workspace import point_catalog, write_review_launcher


def prepare_photo_workspace(design_directory, inputs_path, output):
    design_directory,inputs_path,output=(Path(p).resolve() for p in
                                       (design_directory,inputs_path,output))
    if output.exists():
        raise FileExistsError('photo output exists; select a new version')
    inputs=json.loads(inputs_path.read_text(encoding='utf-8'))
    if (inputs.get('schema')!='dmf_photo_registration_inputs_v1' or
            inputs.get('user_confirmed_industrial_camera_photos') is not True):
        raise ValueError('user-confirmed industrial-camera photos required')
    if inputs.get('use_scope')!='pre_experiment_only':
        raise ValueError('this photo adapter supports pre-experiment use only')
    manifest=json.loads((design_directory/'manifest.json').read_text(encoding='utf-8'))
    map_path=design_directory/'electrode_design_map.json'
    design=load_design_map(map_path,manifest['outputs_sha256'][map_path.name])
    for name,expected in manifest['outputs_sha256'].items():
        if Path(name).name!=name or file_hash(design_directory/name)!=expected:
            raise ValueError('design export hash mismatch')
    verified=[];identities=set()
    for entry in inputs['references']:
        identity=entry['resource_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',identity):
            raise ValueError('unsafe resource identifier')
        if identity in identities:
            raise ValueError('duplicate photo resource identifier')
        identities.add(identity)
        image_path=Path(entry['image'])
        if not image_path.is_absolute():image_path=inputs_path.parent/image_path
        image_path=image_path.resolve()
        if image_path.suffix.lower()!='.png':
            raise ValueError('native PNG photograph required; no disguised re-encoding')
        if file_hash(image_path)!=entry['sha256']:
            raise ValueError('photo hash mismatch')
        image=read_image(image_path,cv2.IMREAD_COLOR)
        if image is None or list(image.shape[1::-1])!=entry['image_size']:
            raise ValueError('native photo size mismatch')
        quad=np.asarray(entry['initial_core_corners_px'],dtype=float)
        width,height=entry['image_size']
        if (quad.shape!=(4,2) or not np.isfinite(quad).all() or
                np.any(quad<0) or np.any(quad[:,0]>=width) or np.any(quad[:,1]>=height)):
            raise ValueError('navigation quadrilateral must be inside native image')
        calibration=ArrayGridCalibration(tuple(tuple(p) for p in quad),
                                        pitch_mm=float(design.get('pitch_mm',3.2)))
        initial_h=np.diag([calibration.pitch_mm,calibration.pitch_mm,1.])@calibration._pixel_to_grid
        verified.append((identity,entry,image_path,initial_h))
    if not verified:
        raise ValueError('no source photos')
    output.mkdir(parents=True)
    shutil.copy2(map_path,output/'electrode_design_map.json')
    workspaces=[]
    for identity,entry,image_path,initial_h in verified:
        folder=output/identity;folder.mkdir()
        shutil.copy2(image_path,folder/'original.png')
        if file_hash(folder/'original.png')!=entry['sha256']:
            raise OSError('photo copy hash mismatch')
        workspace=dict(schema='dmf_design_registration_review_v1',simulation=False,
            resource_id=identity,use_scope='pre_experiment_only',
            final_experiment_calibration_approved=False,transfer_to_old_videos_verified=False,
            final_relative_height_fixed=False,
            source=dict(kind='real_industrial_camera_photo',source_image=str(image_path),
                source_image_sha256=entry['sha256'],user_confirmed_source=True,
                exposure_timestamp_verified=False,crop=None,resized=False,
                brightness_contrast_gamma_adjusted=False,
                independent_acquisition_group='photo_session_not_independent_chip_replicates',
                capture_time_source='filename_only_not_verified_exposure'),
            image_path='original.png',image_sha256=entry['sha256'],image_size=entry['image_size'],
            design_map_path='../electrode_design_map.json',design_map_sha256=file_hash(map_path),
            design_map_version=design['version'],initial_image_to_design_mm=initial_h.tolist(),
            initial_core_corners_px=entry['initial_core_corners_px'],
            initial_transform_status='assistant_photo_quad_navigation_only_unconfirmed',
            fit_freeze=None,points=point_catalog(design,np.linalg.inv(initial_h)),
            notes='Pre-experiment only. Navigation is not observation. Final apparatus height/optical state requires a separate calibration.')
        seal_catalog(workspace)
        path=folder/'workspace.json';_json(path,workspace);workspaces.append(path)
    repo=Path(__file__).resolve().parents[2]
    for index,path in enumerate(workspaces):
        name='启动配准核对.cmd' if index==0 else f'核对照片{index+1}.cmd'
        write_review_launcher(output/name,repo,Path(sys.executable),path)
    _json(output/'manifest.json',dict(schema='dmf_photo_registration_resources_v1',
        simulation=False,use_scope='pre_experiment_only',
        final_experiment_calibration_approved=False,transfer_to_old_videos_verified=False,
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_inputs=str(inputs_path),source_inputs_sha256=file_hash(inputs_path),
        design_map_sha256=file_hash(map_path),source_design_map=str(map_path),
        source_photos=[dict(resource_id=identity,path=str(image_path),sha256=entry['sha256'])
                       for identity,entry,image_path,_ in verified],
        workspaces=[str(p.relative_to(output)) for p in workspaces],
        old_video_annotations_imported=False,originals_modified=False,
        navigation_observations_confirmed=False))
    return workspaces
