"""Separate raw-CSV versus plotted-payload check; no plotting/algorithm imports."""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math

OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-27_仿真论文图_学术整理候选_v2')
def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run():
    index=json.loads((OUT/'每图正式来源与hash索引.json').read_text(encoding='utf-8'))
    manifest=json.loads((OUT/'source_manifest.json').read_text(encoding='utf-8'))
    payload=json.loads((OUT/'source_data/S3-A_实际绘制序列.json').read_text(encoding='utf-8'))
    trials={r['trial_id']:r for r in index['S3-A1']['trials']};errors=[];point_count=state_count=event_count=0
    for tid,item in trials.items():
        paths={Path(r['path']).name:r['path'] for r in item['files']}
        frames=read(paths['frames.csv']);truth=read(paths['truth_ticks.csv']);events=read(paths['events.csv'])
        for series in [r for r in payload['series'] if r['trial_id']==tid]:
            f=series['field'];raw=truth if series['kind']=='truth' else frames
            tk='time_s' if series['kind']=='truth' else 'processing_s'
            expected=[[float(r[tk]),float(r[f])] for r in raw if r.get(tk) and r.get(f)]
            actual=[pair for pair in series['points'] if None not in pair]
            if actual!=expected:errors.append('series:'+tid+':'+f)
            point_count+=len(actual)
        expected=Counter((r['state'],float(r['processing_s'])) for r in frames if r.get('processing_s'))
        actual=Counter((r['state'],r['time_s']) for r in payload['states'] if r['trial_id']==tid)
        if actual!=expected:errors.append('states:'+tid)
        state_count+=sum(actual.values())
        def kind(r):
            action=r['action'] if r['event']=='Applied' else r['event']
            origin=r.get('origin_phase') if r['event']=='Applied' else r.get('phase')
            return 'resend' if action=='Retry' and origin=='recovering' else action
        allowed={'Prepare','Start','Update','Retry','Recovery','Complete','Stop','Applied'}
        expected=Counter((r['event'],kind(r),float(r['time_s'])) for r in events if r['event'] in allowed)
        actual=Counter((r['event'],r['kind'],r['time_s']) for r in payload['events'] if r['trial_id']==tid)
        if actual!=expected:errors.append('events:'+tid)
        event_count+=sum(actual.values())
    bsrc=list(index['S3-B']['source_files'])
    summary=read(next(q for q in bsrc if Path(q).name=='formal_summary.csv'))
    intervals=read(next(q for q in bsrc if Path(q).name=='time_and_action_intervals.csv'))
    plotted=read(OUT/'source_data/S3-B_实际绘制数值.csv');ci_count=0
    for row in plotted:
        if row['panel'] in ('a','b'):
            src=next(r for r in summary if r['cohort']=='main' and r['scenario']==row['category'] and r['method']==row['method'])
            expect=[float(src[row['metric']+k])*100 for k in ('_rate','_ci_low','_ci_high')]
            if src['planned_trials']!='20':errors.append('n')
        else:
            src=next(r for r in intervals if r['scenario']==row['category'] and r['method']==row['method'] and r['protection']==row['protection'] and r['metric']==row['metric'])
            expect=[float(src[k]) for k in ('mean','ci_low','ci_high')]
            if src['n']!='20':errors.append('n')
        if any(not math.isclose(float(row[k]),v,abs_tol=1e-12) for k,v in zip(('estimate','lower','upper'),expect)):errors.append('statistic')
        ci_count+=1
    checked={**manifest['protected_files'],**manifest['source_files']}
    s1_manifest=next(q for q in index['S1-A']['frozen_input_index'] if Path(q).name=='figure_manifest.json')
    checked.update(json.loads(Path(s1_manifest).read_text(encoding='utf-8'))['source_hashes'])
    for path,h in checked.items():
        if sha(path)!=h:errors.append('hash:'+path)
    for row in manifest['copied_unchanged']:
        if sha(row['source'])!=sha(row['output']):errors.append('unchanged_copy')
    for item in trials.values():
        for row in item['files']:
            if sha(row['path'])!=row['sha256'] or sha(row['local_copy'])!=row['sha256']:errors.append('source_copy_hash')
    result=dict(passed=not errors,errors=errors,series_values_checked=point_count,
        state_predictions_checked=state_count,logged_control_events_checked=event_count,
        estimates_and_intervals_checked=ci_count,input_hashes_checked=len(checked),
        independent_of_plot_module=True,model_or_scoring_imports=False,new_simulation_runs=0,bootstrap_rerun=False)
    (OUT/'QA/独立逐项一致性检查.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));assert result['passed']

if __name__=='__main__':run()
