"""Versioned normal-speed execution wrapper; legacy mechanisms remain frozen."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

from .single_step import SingleStepConfig
from .audit import audit_trial, read_rows
from .model import DesignGeometry
from .footprint import AreaFootprint

TRIAL_ID='geometry_single_step_normal1p4_v2:normal:264900:190-191'


def normal_config():
    return SingleStepConfig(speed_mm_s=1.4,duration_s=6.)


def validate_config(config):
    if asdict(config)!=asdict(normal_config()):
        raise ValueError('only declared normal1.4mm/s six-second configuration permitted')


def isolated_engine():
    # Execute the exact legacy source in a separate module namespace. Only the
    # run identity differs; the imported original module/global is not modified.
    name=__package__+'._normal_speed_execution'
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name('single_step.py'))
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    module.TRIAL=TRIAL_ID
    return module


def run_normal_trial(map_path,mask_path,output):
    config=normal_config();validate_config(config)
    engine=isolated_engine()
    result=engine.run_single_step(DesignGeometry(map_path),AreaFootprint.from_mask(mask_path,4.),config,output)
    result['execution_variant']=dict(version='normal1p4_v2',
        mechanism_source_unchanged=True,identity_binding='isolated module TRIAL constant only',
        parameter_changes_from_first_example=dict(speed_mm_s=[4.8,1.4],duration_s=[3.,6.]),
        wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        timing_quality='nominal_simulation_not_physical_calibration')
    Path(output,'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def audit_normal_trial(root):
    root=Path(root);result=audit_trial(root)
    # The frozen old auditor has a single fixed301/60 count assertion. All its
    # Mask features, gates, event and independent reference checks remain active.
    failures=[f for f in result['failures'] if f!='full_tick_and_frame_counts']
    m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if m['config']!=asdict(normal_config()):failures.append('normal_config_mismatch')
    world=read_rows(root/'world.csv');obs=read_rows(root/'observations.csv')
    shapes=json.loads((root/'world_polygons.json').read_text(encoding='utf-8'))
    if (len(world),len(shapes),len(obs))!=(601,601,120):failures.append('normal_record_counts')
    if m['trial_id']!=TRIAL_ID:failures.append('normal_trial_identity')
    for rows in (world,obs,read_rows(root/'events.csv')):
        if any(r['trial_id']!=TRIAL_ID for r in rows):failures.append('row_trial_identity')
    if abs(float(world[-1]['time_s'])-6)>1e-9:failures.append('complete_six_second_followup')
    max_speed=0.
    for i,row in enumerate(world):
        speed=float(row['speed_mm_s']);max_speed=max(max_speed,speed)
        if speed>1.4+1e-8:failures.append('normal_speed_limit')
        if i:
            old=world[i-1];dt=float(row['time_s'])-float(old['time_s'])
            distance=math.hypot(float(row['x_mm'])-float(old['x_mm']),float(row['y_mm'])-float(old['y_mm']))
            if abs(distance-speed*dt)>1e-8:failures.append('logged_velocity_displacement')
    for rel,digest in m['source_code']['files'].items():
        source=Path(__file__).resolve().parents[2]/rel
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:failures.append('frozen_mechanism_source:'+rel)
    if m['execution_variant']['wrapper_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        failures.append('normal_wrapper_source')
    result.update(passed=not failures,failures=sorted(set(failures)),max_speed_mm_s=max_speed,
                  configured_peak_mm_s=1.4,duration_s=6.,
                  legacy_count_check_replaced_by_strict_601_120=True)
    return result
