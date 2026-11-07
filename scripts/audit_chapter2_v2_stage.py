"""Independent, read-only CSV reanalysis. Never imports a model or evaluator."""
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def value(s):
    if s=='':return None
    if s in ('True','False'):return s=='True'
    try:return json.loads(s)
    except (ValueError,TypeError):return s
def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return [{k:value(v) for k,v in r.items()} for r in csv.DictReader(f)]
def write_json(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def write_csv(path,rows):
    rows=list(rows);keys=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else v for k,v in r.items()} for r in rows)


def reference_from_ticks(rows,centers,spec,dt,planned_steps):
    """Reconstruct independent geometric/speed dwell from raw ticks, not labels."""
    found={};begins={};last=None;key=None
    for row in rows:
        current=(row['step'],row.get('epoch'),row['target'])
        t=row['time_s']
        if row['phase']!='transport' or row['step'] not in range(planned_steps):
            begins.clear();last=None;key=None;continue
        if current!=key or last is None or t<=last or t-last>dt+1e-9:begins.clear()
        key=current;last=t
        center=centers[int(row['target'])]
        inside=math.dist((row['x'],row['y']),center)<=spec['radius_pitch'] and row['true_speed']<=spec['max_speed_pitch_s']
        if not inside:begins.pop(current,None);continue
        begins.setdefault(current,t)
        if row['step'] not in found and t-begins[current]>=spec['dwell_s']-1e-9:
            found[row['step']]=dict(step=row['step'],target=row['target'],lower_s=max(0.,t-dt),upper_s=t,dwell_begin_s=begins[current])
    return [found[k] for k in sorted(found)]


def score_events(events,references,route):
    refs={r['step']:r for r in references};first={};seen=Counter();labels=[];wrong=duplicates=0
    for e in events:
        if e['event'] not in ('Update','Complete'):continue
        step=e['step'];t=e['time_s']
        if step not in range(len(route)-1) or e['target']!=route[step+1]:
            wrong+=1;labels.append(dict(step=step,time_s=t,label='wrong'));continue
        duplicates+=int(seen[step]>0);seen[step]+=1
        r=refs.get(step)
        label=('unsupported_no_reference' if r is None else 'premature' if t<r['lower_s']-1e-9 else 'uncertain' if t<r['upper_s']-1e-9 else 'supported')
        first.setdefault(step,label);labels.append(dict(step=step,time_s=t,label=label))
    counts=Counter(e['label'] for e in labels)
    supported=sum(label=='supported' for label in first.values())
    unsupported=counts['premature']+counts['unsupported_no_reference']
    complete=any(e['event']=='Complete' for e in events)
    return dict(planned_steps=len(route)-1,reference_arrivals=len(refs),supported=supported,
                unsupported=unsupported,unsupported_no_reference=counts['unsupported_no_reference'],premature=counts['premature'],
                uncertain=counts['uncertain'],wrong=wrong,duplicates=duplicates,
                missed=sum(first.get(step)!='supported' for step in refs),issued=sum(counts.values()),
                recall=supported/len(refs) if refs else None,
                path_complete=complete and supported==len(route)-1 and not(unsupported or counts['uncertain'] or wrong or duplicates),events=labels)


def execution_counts(events,frames,route,phase_mode):
    attempts=set();retries=recoveries=resends=0;requests={}
    for e in events:
        if e['event']!='Applied' and e.get('request_id') is not None:requests[e['request_id']]=e
        if e['event']!='Applied' or not e.get('accepted'):continue
        action=e.get('action')
        if action in ('Start','Update','Retry'):attempts.add(e['step'])
        recoveries+=int(action=='Recovery')
        if action=='Retry':
            recovery=requests.get(e.get('request_id'),{}).get('phase')=='recovering'
            retries+=int(not recovery);resends+=int(recovery)
    controlled=phase_mode=='transport_only'
    visual=not controlled and any(e['event'] in ('Start','SourcePrepared') for e in events)
    stops=Counter(e.get('reason') or 'unknown_stop_reason' for e in events if e['event']=='Stop')
    return dict(planned_trials=1,source_prepared=visual,controlled_initial=controlled,
                transport_complete=any(e['event']=='Complete' for e in events),
                attempted_steps=len(attempts),unattempted_steps=len(route)-1-len(attempts),
                retries=retries,recoveries=recoveries,recovery_resends=resends,stop_reasons=dict(stops),
                unknown_frames=sum(r['state']=='Unknown' for r in frames),total_frame_records=len(frames))


def group_counts(records,keys):
    groups=defaultdict(list)
    for row in records:groups[tuple(row[k] for k in keys)].append(row)
    out=[]
    fields=('planned_trials','source_prepared','controlled_initial','transport_complete','path_complete','planned_steps',
            'reference_arrivals','supported','unsupported','unsupported_no_reference','premature','uncertain','wrong','duplicates',
            'missed','issued','attempted_steps','unattempted_steps','retries','recoveries','recovery_resends','unknown_frames','missing_mask_frames','total_frame_records')
    for key,rs in groups.items():
        item=dict(zip(keys,key));item.update({k:sum(r[k] for r in rs) for k in fields})
        stops=Counter()
        for r in rs:stops.update(r['stop_reasons'])
        item.update(stop_reasons=dict(stops),seeds=[r['seed'] for r in rs],recall=item['supported']/item['reference_arrivals'] if item['reference_arrivals'] else None)
        out.append(item)
    return out


def run_audit(v2_root,v1_root,output):
    v2_root,v1_root,output=map(Path,(v2_root,v1_root,output));repo=Path(__file__).resolve().parents[1]
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);inputs={};mismatches=[]
    def csv_input(path):inputs[str(path)]=sha(path);return read_csv(path)
    def json_input(path):inputs[str(path)]=sha(path);return read_json(path)
    plan=json_input(v2_root/'planned_trials.json');aggregate=csv_input(v2_root/'trials.csv')
    aggregate_lookup={(r['phase_mode'],r['scenario'],r['seed'],r['method']):r for r in aggregate}
    records=[];gate_summaries=[];checked_hashes=0
    for declared in plan:
        name=f"{declared['phase_mode']}__{declared['scenario']}__{declared['seed']}__{declared['method']}";path=v2_root/'trials'/name
        manifest=json_input(path/'trial_manifest.json')
        for rel,h in manifest['files'].items():
            checked_hashes+=1
            if sha(path/rel)!=h:raise ValueError('Trial data hash mismatch: '+str(path/rel))
        cfg=json_input(path/'config_snapshot.json');map_snapshot=json_input(path/'electrode_map_snapshot.json');route=cfg['environment']['route']
        events=csv_input(path/'observations/events.csv');frames=csv_input(path/'observations/frames.csv')
        captures=csv_input(path/'observations/captures.csv');truth=csv_input(path/'evaluation/truth_ticks.csv')
        stored_refs=csv_input(path/'evaluation/reference_intervals.csv');gates=csv_input(path/'observations/gate_trace.csv')
        # These maps contain rectangles; use the polygon area centroid, not
        # an image-coordinate template or an assumed physical millimetre scale.
        centers={int(k):polygon_center(p) for k,p in map_snapshot['polygons'].items()}
        refs=reference_from_ticks(truth,centers,cfg['reference'],cfg['environment']['dt_s'],len(route)-1)
        if len(refs)!=len(stored_refs) or any(any(abs(r[k]-s[k])>1e-9 for k in ('lower_s','upper_s','dwell_begin_s')) or r['step']!=s['step'] for r,s in zip(refs,stored_refs)):
            mismatches.append(dict(trial=name,field='reference_intervals',independent=refs,stored=stored_refs))
        scored=score_events(events,refs,route);scored_events=scored.pop('events')
        execution=execution_counts(events,frames,route,declared['phase_mode'])
        item=dict(trial=name,**{k:declared[k] for k in ('phase_mode','scenario','seed','method')},**execution,**scored,
                  missing_mask_frames=sum(not r.get('mask_path') for r in captures))
        records.append(item)
        stored=aggregate_lookup[(declared['phase_mode'],declared['scenario'],declared['seed'],declared['method'])]
        translation={'source_prepared':'source_visual_confirmed','path_complete':'path_complete','reference_arrivals':'reference_arrived_steps',
                     'supported':'correct_confirmed_steps','unsupported':'unsupported_events','missed':'missed_reference_events','wrong':'wrong_events',
                     'duplicates':'duplicate_events','uncertain':'uncertain_events','unattempted_steps':'unattempted_steps',
                     'retries':'retries','recoveries':'recoveries','recovery_resends':'recovery_resends','unknown_frames':'unknown_frames',
                     'missing_mask_frames':'missing_mask_frames'}
        for independent,original in translation.items():
            if item[independent]!=stored[original]:mismatches.append(dict(trial=name,field=original,independent=item[independent],stored=stored[original]))
        if item['transport_complete']!=(stored['terminal_outcome']=='transport_complete'):
            mismatches.append(dict(trial=name,field='transport_complete'))
        counts=Counter()
        for g in gates:
            if g['stage']!='target' or not isinstance(g.get('raw'),dict):continue
            raw=g['raw'];counts['target_gate_rows']+=1
            if g.get('coverage_passed') is None or not {'S','K','Q'}<=set(raw):continue
            counts['C0_passed']+=bool(g.get('C0_passed'))
            counts['Q_fail']+=not raw['Q'];counts['S_fail']+=not raw['S'];counts['K_fail']+=not raw['K']
            coverage=g['coverage_passed'];counts['coverage_candidates']+=bool(coverage)
            counts['coverage_Q_pass_S_fail']+=bool(coverage and raw['Q'] and not raw['S'])
            counts['coverage_Q_pass_K_fail']+=bool(coverage and raw['Q'] and not raw['K'])
        gate_summaries.append(dict(trial=name,phase_mode=item['phase_mode'],scenario=item['scenario'],seed=item['seed'],method=item['method'],**counts))
    grouped=group_counts([r for r in records if r['phase_mode']=='end_to_end'],('scenario','method'))
    diagnostic=group_counts([r for r in records if r['phase_mode']!='end_to_end'],('phase_mode','scenario','method'))
    write_csv(output/'v2_independent_trials.csv',records);write_csv(output/'v2_scene_method_counts.csv',grouped)
    write_csv(output/'v2_phase_diagnostic_counts.csv',diagnostic);write_csv(output/'v2_gate_diagnostic_counts.csv',gate_summaries)
    historic=csv_input(v1_root/'trials.csv');groups=defaultdict(list)
    for r in historic:
        if r['ablation']=='full':groups[(r['scenario'],r['method'])].append(r)
    history=[]
    for (scene,method),rs in groups.items():
        status=Counter(r['status'] for r in rs)
        history.append(dict(scenario=scene,method=method,planned_trials=len(rs),source_prepared=sum(r['preparation_time_s'] is not None for r in rs),
                            transport_complete=sum(r['status'] in ('completed','completed_with_early_updates') for r in rs),
                            path_complete=sum(r['path_complete'] for r in rs),early_updates=sum(r['early_updates'] for r in rs),
                            reference_arrivals=sum(r['reference_arrived_steps'] for r in rs),supported=sum(r['correct_confirmed_steps'] for r in rs),statuses=dict(status)))
    write_csv(output/'v1_historical_counts.csv',history)
    old_cfg=json_input(v1_root/'config_snapshot.json')['config'];new_cfg=json_input(v2_root/'study_manifest.json')['config']['environment']
    environment_differences={k:dict(v1=old_cfg.get(k),v2=new_cfg.get(k)) for k in set(old_cfg)|set(new_cfg) if old_cfg.get(k)!=new_cfg.get(k)}
    shared=[];gate_shared=[]
    for condition in sorted((v2_root/'research_predictions').iterdir()):
        b=json_input(condition/'BTQ/prediction_manifest.json');f=json_input(condition/'F/prediction_manifest.json')
        signature=lambda d:[(e['step_id'],e['timestamp_s']) for e in d['events']]
        shared.append(dict(condition=condition.name,input_same=b['input_sha256']==f['input_sha256'],BTQ_events=signature(b),F_events=signature(f),identical=signature(b)==signature(f)))
        gs=csv_input(condition/'F/gate_trace.csv');ct=Counter()
        for g in gs:
            if not isinstance(g.get('raw'),dict) or not {'S','K','Q'}<=set(g['raw']):continue
            raw=g['raw'];ct['parsed']+=1;ct['Q_fail']+=not raw['Q'];ct['K_fail']+=not raw['K'];ct['S_fail']+=not raw['S']
            ct['coverage_candidates']+=bool(g['coverage_passed'])
            ct['candidate_S_only_reject']+=bool(g['coverage_passed'] and raw['Q'] and raw['K'] and not raw['S'])
            ct['candidate_K_only_reject']+=bool(g['coverage_passed'] and raw['Q'] and raw['S'] and not raw['K'])
        gate_shared.append(dict(condition=condition.name,**ct))
    write_csv(output/'shared_cache_BTQ_F_events.csv',shared);write_csv(output/'shared_cache_gate_support.csv',gate_shared)
    selected=v2_root/'trials/end_to_end__normal__262000__F';vis=v2_root.parent/'visualization_r2'
    vm=json_input(vis/'visualization_manifest.json');tm=json_input(selected/'trial_manifest.json')
    if vm['trial_id']!=tm['trial_id'] or sha(selected/'trial_manifest.json')!=vm['trial_manifest_sha256']:raise ValueError('Figure trial provenance mismatch')
    for rel,h in vm['files'].items():
        if sha(vis/rel)!=h:raise ValueError('Visualization hash mismatch')
    frame_index=csv_input(vis/'frame_index.csv');key_sources=csv_input(vis/'figures/keyframe_sources.csv')
    if {r['trial_id'] for r in frame_index+key_sources}!={tm['trial_id']}:raise ValueError('Mixed trial visualization')
    assets=output/'review_assets';assets.mkdir();(assets/'figures').mkdir()
    copies={}
    for source in (vis/'figures').iterdir():
        if source.suffix in ('.pdf','.svg','.png') and 'alignment' not in source.name:
            target=assets/'figures'/source.name;shutil.copy2(source,target);copies[str(target.relative_to(output))]=dict(source=str(source),sha256=sha(source))
    for source in [vis/'normal_262000_F_v2_development.mp4',vis/'visualization_manifest.json',vis/'frame_index.csv',vis/'figures/keyframe_sources.csv']:
        target=assets/source.name;shutil.copy2(source,target);copies[str(target.relative_to(output))]=dict(source=str(source),sha256=sha(source))
    shutil.copytree(vis/'keyframes',assets/'six_keyframes')
    shutil.copytree(selected,assets/'trial')
    fs=read_csv(selected/'observations/frames.csv');ev=read_csv(selected/'observations/events.csv')
    availability=dict(trial_id=tm['trial_id'],states=dict(Counter(r['state'] for r in fs)),frame_actions=dict(Counter(r['action'] for r in fs)),
                      event_counts=dict(Counter(r['event'] for r in ev)),keyframes=key_sources,
                      absent_states=[s for s in ('Stationary','Moving','Partial','Arrived','Deviation','Unknown') if not any(r['state']==s for r in fs)],
                      absent_actions=[a for a in ('Hold','Update','Retry','Recovery') if not any(r['action']==a for r in fs)],
                      warning='Predicted labels, not independent five-state ground truth; missing states/actions are not fabricated')
    write_json(output/'selected_trial_availability.json',availability)
    write_json(output/'asset_sources.json',copies)
    changed=[str(p) for p,h in inputs.items() if sha(p)!=h]
    report=dict(simulation=True,purpose='independent_stage_acceptance_no_new_simulation',planned_records=len(plan),actual_records=len(records),
                end_to_end_records=len([r for r in records if r['phase_mode']=='end_to_end']),planned_steps=sum(r['planned_steps'] for r in plan),
                step_denominator=sum(r['planned_steps'] for r in records),raw_trial_files_hash_checked=checked_hashes,
                metric_mismatches=mismatches,environment_differences=environment_differences,
                shared_cache_comparisons=len(shared),shared_cache_identical=sum(r['identical'] for r in shared),
                missing_planned_rows=len(plan)-len(records),input_changes=changed,selected_trial=availability,
                algorithm_sources_imported=False,new_model_runs=0,formal_scan_started=False,
                git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip())
    write_json(output/'audit_results.json',report);write_json(output/'input_sha256.json',inputs)
    write_json(output/'auditor_source.json',dict(path=str(Path(__file__).resolve()),sha256=sha(__file__)))
    print(json.dumps({k:v for k,v in report.items() if k!='selected_trial'},ensure_ascii=False,indent=2))
    if mismatches or changed:raise SystemExit(1)
    return report


def polygon_center(points):
    area=cx=cy=0.
    for (x,y),(u,v) in zip(points,points[1:]+points[:1]):
        a=x*v-u*y;area+=a;cx+=(x+u)*a;cy+=(y+v)*a
    if abs(area)<1e-12:raise ValueError('Degenerate map polygon')
    return cx/(3*area),cy/(3*area)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v2',type=Path,required=True);parser.add_argument('--v1',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run_audit(args.v2,args.v1,args.output)
