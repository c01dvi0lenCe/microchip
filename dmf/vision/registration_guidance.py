"""Coarse region assistance, explicitly NOT blinded point measurement."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import numpy as np

from .design_registration import digest,file_hash,load_design_map
from .registration_audit import homogeneous
from .registration_workspace import load_workspace


def build_regions(workspace,design):
    """Use design neighborhoods + frozen H only, never old check observations."""
    by_id={e['control_id']:e for e in design['electrodes']}
    inverse=np.linalg.inv(np.asarray(workspace['fit_freeze']['image_to_design_mm'],float))
    width,height=workspace['image_size'];quantum=32
    pitch=float(np.linalg.norm(np.asarray(by_id[2]['center_map_mm'])-by_id[1]['center_map_mm']))
    if not np.isfinite(pitch) or pitch<=0:raise ValueError('invalid design pitch for guidance')
    result={}
    for p in workspace['points']:
        if p['role']!='check':continue
        electrode_id=p['control_id']
        if electrode_id<=400:
            row,column=divmod(electrode_id-1,20)
            row0=max(0,min(17,row-1));col0=max(0,min(17,column-1))
            neighbors=[r*20+c+1 for r in range(row0,row0+3) for c in range(col0,col0+3)]
            xy=np.concatenate([by_id[i]['polygon_map_mm'] for i in neighbors])
            lo,hi=xy.min(axis=0),xy.max(axis=0)
        else:
            neighbors=[electrode_id];xy=np.asarray(by_id[electrode_id]['polygon_map_mm'])
            lo,hi=xy.min(axis=0)-pitch,xy.max(axis=0)+pitch
        corners=[[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]]
        pixels=homogeneous(corners,inverse)
        lower=np.floor((pixels.min(axis=0)-8)/quantum)*quantum
        upper=np.ceil((pixels.max(axis=0)+8)/quantum)*quantum
        lower=np.maximum(lower,[0,0]);upper=np.minimum(upper,[width-1,height-1])
        if np.any(upper<=lower):raise ValueError('coarse region outside source image')
        result[p['point_id']]=dict(bounds_px=[*map(float,lower),*map(float,upper)],
            neighbor_electrodes=neighbors,control_id=electrode_id,
            meaning='search region only; neither electrode boundary nor precise point')
    return result


def validate_guidance(data):
    guidance=data.get('guidance',{})
    if digest(guidance)!=data.get('guidance_sha256'):raise ValueError('coarse guidance changed')
    regions=guidance.get('regions',{});width,height=data['image_size']
    if set(regions)!={p['point_id'] for p in data['catalog']}:raise ValueError('incomplete coarse regions')
    for p in data['catalog']:
        region=regions[p['point_id']];bounds=np.asarray(region.get('bounds_px'),float)
        if (bounds.shape!=(4,) or not np.isfinite(bounds).all() or
            not (0<=bounds[0]<bounds[2]<width and 0<=bounds[1]<bounds[3]<height) or
            region.get('control_id')!=p['control_id']):
            raise ValueError('invalid coarse search region')


def prepare_assisted(workspace_path,output):
    from .registration_repeatability import new_review,save_new
    source=Path(workspace_path).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError('choose a new assisted review version')
    w=load_workspace(source)
    if not w.get('evaluation_freeze'):raise ValueError('sealed source evaluation required')
    design=load_design_map(source.parent/w['design_map_path'],w['design_map_sha256'])
    regions=build_regions(w,design)
    data=new_review([p for p in w['points'] if p['role']=='check'],w['image_size'])
    data.update(schema='dmf_assisted_registration_repeatability_v1',review_mode='coarse_region_assisted',
        blinding='not_blind: coarse search regions derived from prior frozen H; no precise prediction shown',
        image_path='original.png',image_sha256=w['image_sha256'],
        design_map_path='electrode_design_map.json',design_map_sha256=w['design_map_sha256'],
        original_workspace_sha256=file_hash(source),guidance=dict(regions=regions,
        source_workspace_sha256=file_hash(source),quantization_px=32,
        source='frozen pre-experiment H, for coarse navigation only',
        ground_truth=False))
    data['guidance_sha256']=digest(data['guidance'])
    output.mkdir(parents=True,exist_ok=False)
    for source_file,name,expected in ((source.parent/w['image_path'],'original.png',w['image_sha256']),
        (source.parent/w['design_map_path'],'electrode_design_map.json',w['design_map_sha256'])):
        shutil.copyfile(source_file,output/name)
        if file_hash(output/name)!=expected:raise ValueError('copied resource hash mismatch')
    path=output/'repeatability.json';save_new(path,data)
    repo=Path(__file__).resolve().parents[2]
    for name,command in [('启动粗范围辅助点选.cmd','review'),('导出辅助点选重复性报告.cmd','repeat-report')]:
        lines=['@echo off','chcp 65001 >nul',f'cd /d "{repo}"',
            f'"{sys.executable}" "{repo / "run_registration_audit.py"}" {command} "{path}"',
            'if errorlevel 1 pause' if command=='review' else 'pause']
        (output/name).write_bytes(('\r\n'.join(lines)+'\r\n').encode('utf-8'))
    return path
