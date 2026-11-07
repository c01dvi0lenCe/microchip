"""Run one declared noiseless arrival experiment, or render/audit saved data."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from dmf.chapter2_geometry_sim.audit import audit_trial
from dmf.chapter2_geometry_sim.footprint import AreaFootprint
from dmf.chapter2_geometry_sim.model import DesignGeometry
from dmf.chapter2_geometry_sim.preflight import static_geometry
from dmf.chapter2_geometry_sim.render import load_trial,make_figures,export_replay
from dmf.chapter2_geometry_sim.single_step import SingleStepConfig,run_single_step,write_csv

ROOT=Path(__file__).resolve().parent
DEFAULT_OUTPUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-28_实验一_真实几何4mm到达识别_v1')
DEFAULT_FFMPEG=Path('E:/Apps/Jianying/JianyingPro/11.6.0.14552/ffmpeg.exe')


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def render(trial,output,preflight,ffmpeg):
    data=load_trial(trial)
    if Path(output).exists():raise FileExistsError(output)
    Path(output).mkdir(parents=True)
    keys=make_figures(data,Path(output)/'figures',preflight)
    movie=export_replay(data,output,ffmpeg)
    report=dict(trial_id=data['manifest']['trial_id'],new_simulation_runs=0,keyframes=keys,movie=movie,
                source_manifest_sha256=hashlib.sha256((Path(trial)/'manifest.json').read_bytes()).hexdigest(),
                renderer_sha256=hashlib.sha256((ROOT/'dmf/chapter2_geometry_sim/render.py').read_bytes()).hexdigest(),
                figure_note='Only necessary geometry/axes/legend/time/SIMULATION; all explanation is in captions.',
                files={p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(output).rglob('*') if p.is_file()})
    write_json(Path(output)/'render_manifest.json',report)
    return report


def run(config_path,output,ffmpeg):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    raw=json.loads(Path(config_path).read_text(encoding='utf-8'))
    config=SingleStepConfig(**raw['parameters'])
    if config.position_noise_mm!=0 or config.duration_s!=3 or config.request_s!=.5:
        raise ValueError('only approved noiseless three-second trial permitted')
    geometry=DesignGeometry(raw['map_path'])
    template=Path(raw['template_path'])
    with (template.parents[1]/'samples.csv').open(encoding='utf-8-sig') as stream:
        records=list(csv.DictReader(stream))
    record=next(r for r in records if r['mask_path']=='masks/'+template.name)
    if record['mask_reviewed']!='True' or record['source_frame_id']!='153' or hashlib.sha256(template.read_bytes()).hexdigest()!=record['mask_path_sha256']:
        raise ValueError('reviewed frame153 template provenance mismatch')
    shape=AreaFootprint.from_mask(template,config.diameter_mm)
    preflight=static_geometry(geometry,shape)
    output.mkdir(parents=True)
    write_json(output/'geometry_preflight.json',preflight)
    write_csv(output/'geometry_preflight.csv',[{k:v for k,v in row.items() if k!='polygon_mm'} for row in preflight['rows']])
    (output/'experiment_config.json').write_bytes(Path(config_path).read_bytes())
    write_json(output/'template_provenance.json',record)
    if not preflight['logical_adjacency_verified'] or not preflight['endpoint_gate_feasible']:
        raise ValueError('static geometry/threshold feasibility failed; no trial was run')
    manifest=run_single_step(geometry,shape,config,output/'trial')
    audit=audit_trial(output/'trial');write_json(output/'independent_audit.json',audit)
    if not audit['passed']:raise ValueError(audit['failures'])
    rendering=render(output/'trial',output/'visualization',preflight,ffmpeg)
    print(json.dumps(dict(summary=manifest['summary'],audit=audit['passed'],movie=rendering['movie'],output=str(output)),ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('run','render','audit'))
    p.add_argument('--config',type=Path,default=ROOT/'configs/chapter2_geometry_single_step.json')
    p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    p.add_argument('--trial',type=Path)
    p.add_argument('--preflight',type=Path)
    p.add_argument('--ffmpeg',type=Path,default=DEFAULT_FFMPEG)
    a=p.parse_args()
    if a.action=='run':run(a.config,a.output,a.ffmpeg)
    elif a.action=='audit':
        report=audit_trial(a.trial);print(json.dumps(report,ensure_ascii=False,indent=2))
        raise SystemExit(0 if report['passed'] else 1)
    else:render(a.trial,a.output,json.loads(a.preflight.read_text(encoding='utf-8')),a.ffmpeg)
