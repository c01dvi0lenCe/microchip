"""Independent, read-only separation of decision, Applied and final transport.

Input: persisted World/time/electrode state and actual events. No World,
controller, gate, or original score function is executed.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_geometry_exp2_mechanisms import reference_intervals, support_at


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer=csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def separate_outcomes(events, spans, route, horizon):
    """Three planned rows; lifecycle Complete never becomes a transaction."""
    updates = [e for e in events if e['event']=='request' and e.get('action')=='Update']
    requests = {str(e['request_id']):e for e in updates}
    if len(requests)!=len(updates):
        raise ValueError('duplicate Update request identity')
    applications = [e for e in events if e['event']=='simulated_applied' and e.get('action')=='Update']
    applied_by_id = {}
    for e in applications:
        key=str(e['request_id']); request=requests.get(key)
        if (request is None or key in applied_by_id or int(e['target'])!=int(request['target']) or
            str(e['origin_step'])!=str(request['origin_step']) or float(e['time_s'])<float(request['time_s'])):
            raise ValueError('unmatched/duplicate/reversed Update Applied')
        applied_by_id[key]=e
    completes = [e for e in events if e['event']=='Complete']
    if len(completes)>1:
        raise ValueError('more than one lifecycle Complete')
    if completes and (int(completes[0]['target'])!=route[-1] or int(completes[0]['origin_step'])!=len(route)-2):
        raise ValueError('Complete does not match final planned task')
    align=[]
    for i, (source, target) in enumerate(zip(route, route[1:])):
        candidates = [e for e in updates if int(e['origin_step'])==i]
        if i==len(route)-2:
            if candidates:
                raise ValueError('final task cannot command an unplanned Update')
            candidates=completes
        if len(candidates)>1:
            raise ValueError('more than one advancement decision per planned step')
        decision=candidates[0] if candidates else None
        applied=applied_by_id.get(str(decision['request_id'])) if decision and decision['event']=='request' else None
        command=int(decision['target']) if decision and decision['event']=='request' else None
        if command is not None and command!=route[i+2]:
            raise ValueError('commanded target differs from next planned electrode')
        align.append(dict(step=i, source_electrode=source, completed_task_target=target,
            decision_kind=decision['action'] if decision else None,
            decision_s=float(decision['time_s']) if decision else None,
            decision_reference_supported=support_at(spans,target,float(decision['time_s'])) if decision else None,
            commanded_active_electrode=command,
            request_id=str(decision['request_id']) if command is not None else None,
            applied_s=float(applied['time_s']) if applied else None,
            applied_active_electrode=int(applied['target']) if applied else None,
            applied_reference_supported=support_at(spans,target,float(applied['time_s']),left_limit=True) if applied else None))
    first=min((s['start_s'] for s in spans if s['target']==route[-1]), default=None)
    done=float(completes[0]['time_s']) if completes else None
    attempted={int(e['origin_step'])+(e.get('action')=='Update') for e in events
               if e['event']=='simulated_applied' and e.get('action')!='Prepare'}
    if any(i<0 or i>=len(route)-1 for i in attempted):
        raise ValueError('Applied outside planned steps')
    outcome=dict(planned_steps=len(route)-1, attempted_steps=len(attempted), decision_count=sum(r['decision_s'] is not None for r in align),
        supported_decisions=sum(r['decision_reference_supported'] is True for r in align),
        unsupported_decisions=sum(r['decision_reference_supported'] is False for r in align),
        update_request_count=len(updates), update_applied_count=len(applications),
        unsupported_update_requests=sum(r['commanded_active_electrode'] is not None and r['decision_reference_supported'] is False for r in align),
        unsupported_update_applied=sum(r['applied_reference_supported'] is False for r in align),
        workflow_complete_s=done, final_target_reference_first_s=first,
        final_reference_ever_completed=first is not None,
        final_reference_supported_at_complete=support_at(spans,route[-1],done) if done is not None else None,
        final_reference_supported_at_horizon=support_at(spans,route[-1],horizon),
        final_reference_minus_complete_s=round(first-done,12) if first is not None and done is not None else None,
        observation_horizon_s=horizon, physical_safety_evaluated=False)
    return outcome, align


def analyze_trial(folder):
    from shapely.geometry import Polygon
    folder=Path(folder).resolve(); manifest=load(folder/'manifest.json')
    parameters=load(folder/'config.json')['parameters']
    design=load(manifest['inputs']['map_path'])
    centers={e['control_id']:Polygon(e['polygon_map_mm']).centroid.coords[0] for e in design['electrodes']}
    world=read(folder/'world.csv');events=read(folder/'events.csv')
    spans=reference_intervals(world,centers,parameters)
    outcome, align=separate_outcomes(events,spans,tuple(parameters['route']),float(world[-1]['time_s']))
    legacy=load(folder/'metrics.json')
    outcome.update(method=legacy['method'], legacy_terminal=legacy['terminal'],
        recorded_attempted_steps=legacy['attempted_steps'], legacy_transport_complete=legacy['transport_complete'],
        reference_time_unit='simulation seconds', analysis_reads_internal_truth=True,
        controller_receives_internal_truth=False, legacy_files_modified=False)
    source={name:sha(folder/name) for name in ('world.csv','events.csv','config.json','manifest.json','metrics.json')}
    source['map']=sha(manifest['inputs']['map_path'])
    return outcome,align,spans,dict(trial=str(folder),inputs_sha256=source)


def analyze(folders, output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    summaries=[]; origins=[]
    for folder in map(Path,folders):
        result,alignment,spans,origin=analyze_trial(folder)
        destination=output/folder.name;destination.mkdir()
        write_json(destination/'outcome_separation.json',result)
        write_csv(destination/'decision_alignment.csv',alignment)
        write_json(destination/'independent_reference_intervals.json',spans)
        summaries.append(dict(trial=folder.name,**result));origins.append(origin)
    write_csv(output/'outcome_summary.csv',summaries)
    write_json(output/'manifest.json',dict(source=str(Path(__file__).resolve()),source_sha256=sha(__file__),
        independent_reference_source=str(ROOT/'scripts/audit_geometry_exp2_mechanisms.py'),
        independent_reference_sha256=sha(ROOT/'scripts/audit_geometry_exp2_mechanisms.py'),
        simulation=True,development_only=True,new_simulation_runs=0,origins=origins,
        artifacts={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',action='append',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();analyze(args.trial,args.output)
