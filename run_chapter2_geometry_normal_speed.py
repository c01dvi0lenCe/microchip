"""One approved normal1.4mm/s run, or read-only audit/render of saved logs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from dmf.chapter2_geometry_sim.normal_speed import run_normal_trial,audit_normal_trial,normal_config
from dmf.chapter2_geometry_sim.normal_speed_visuals import render_normal
from dmf.chapter2_geometry_sim.model import DesignGeometry
from dmf.chapter2_geometry_sim.footprint import AreaFootprint
from dmf.chapter2_geometry_sim.preflight import static_geometry

ROOT=Path(__file__).resolve().parent
CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
OUT=CH/'仿真结果/2026-10-28_实验一_正常速度1p4mmps_v2'
OLD=CH/'仿真结果/2026-10-28_实验一_真实几何4mm到达识别_v1'
FFMPEG=Path('E:/Apps/Jianying/JianyingPro/11.6.0.14552/ffmpeg.exe')


def write(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def run(output):
    if output.exists():raise FileExistsError(output)
    previous=json.loads((OLD/'experiment_config.json').read_text(encoding='utf-8'))
    template=Path(previous['template_path'])
    with (template.parents[1]/'samples.csv').open(encoding='utf-8-sig') as f:
        record=next(r for r in csv.DictReader(f) if r['mask_path']=='masks/'+template.name)
    if record['mask_reviewed']!='True' or record['source_frame_id']!='153' or hashlib.sha256(template.read_bytes()).hexdigest()!=record['mask_path_sha256']:
        raise ValueError('reviewed template provenance mismatch')
    pre=static_geometry(DesignGeometry(previous['map_path']),AreaFootprint.from_mask(template,4.))
    if not pre['endpoint_gate_feasible'] or not pre['logical_adjacency_verified']:
        raise ValueError('geometry/threshold feasibility failed')
    output.mkdir(parents=True)
    write(output/'geometry_preflight.json',pre);write(output/'template_provenance.json',record)
    write(output/'execution_scope.json',dict(approved_config=str(ROOT/'configs/chapter2_geometry_normal1p4.json'),
          normal_only=True,research_trials=1,old_version_preserved=str(OLD),speed_is_nominal=True,
          parameter_changes=['speed_mm_s:4.8→1.4','duration_s:3→6'],all_arrival_gates_unchanged=True))
    manifest=run_normal_trial(previous['map_path'],template,output/'trial')
    audit=audit_normal_trial(output/'trial');write(output/'independent_audit.json',audit)
    if not audit['passed']:raise ValueError(audit['failures'])
    print(json.dumps(manifest['summary'],ensure_ascii=False,indent=2),flush=True)
    rendering=render_normal(output/'trial',output/'visualization',FFMPEG,OLD/'visualization_clean_v2/figures_final')
    write(output/'delivery_manifest.json',dict(summary=manifest['summary'],audit=audit,
           movie=rendering['movie'],trial_id=manifest['trial_id'],new_persisted_trials=1,
           evidence_scope='normal n=1 mechanism; not comparative performance or physical calibration'))
    print('completed',output,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('run','audit','render'))
    p.add_argument('--output',type=Path,default=OUT);p.add_argument('--visual-output',type=Path)
    args=p.parse_args()
    if args.action=='run':run(args.output)
    elif args.action=='audit':
        result=audit_normal_trial(args.output/'trial');print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
    else:render_normal(args.output/'trial',args.visual_output or args.output/'visualization',FFMPEG,OLD/'visualization_clean_v2/figures_final')
