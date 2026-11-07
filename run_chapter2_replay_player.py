"""Build a self-contained offline player. Never executes a simulation."""
import argparse
import csv
import json
from pathlib import Path
import shutil

from dmf.chapter2_replay.data import build_bundle,audit_bundle,sha

DEFAULT_TRIAL=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1/development_smoke_r2/trials/end_to_end__normal__262000__F')


def build(trial,output):
    output=Path(output)
    if output.exists():raise FileExistsError('Use a new output directory; no existing artifacts are overwritten')
    b=build_bundle(trial);a=audit_bundle(b,trial)
    if not a['passed']:raise ValueError(a)
    output.mkdir(parents=True)
    text=json.dumps(b,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    (output/'replay_bundle.json').write_text(text,encoding='utf-8')
    template=Path(__file__).parent/'dmf/chapter2_replay/player.html'
    (output/'DMF单液滴仿真播放器.html').write_text(template.read_text(encoding='utf-8').replace('__BUNDLE_JSON__',text.replace('<','\\u003c')),encoding='utf-8')
    (output/'source_check.json').write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'event_check.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['csv_line','time_s','event','matched']);w.writeheader();w.writerows(a['event_rows'])
    sources=output/'原始日志副本';sources.mkdir()
    for name in ['observations/frames.csv','observations/gate_trace.csv','observations/events.csv','observations/captures.csv','evaluation/truth_ticks.csv','evaluation/reference_intervals.csv','trial_manifest.json','config_snapshot.json','electrode_map_snapshot.json']:
        shutil.copy2(Path(trial)/name,sources/Path(name).name)
    manifest=dict(simulation=True,trial_id=b['trial_id'],source_trial=str(Path(trial).resolve()),source_files=b['source_sha256'],bundle_sha256=sha(output/'replay_bundle.json'),html_sha256=sha(output/'DMF单液滴仿真播放器.html'),code_sha256={str(p):sha(p) for p in [Path(__file__),template,Path(__file__).parent/'dmf/chapter2_replay/data.py']},no_interpolation=True,new_simulation_runs=0,units='pitch',clock='simulation')
    (output/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(output/'DMF单液滴仿真播放器.html'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,default=DEFAULT_TRIAL);p.add_argument('--output',type=Path,required=True);args=p.parse_args();build(args.trial,args.output)
