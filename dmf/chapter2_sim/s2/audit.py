"""Read-only prior timing and per-condition development feasibility reports."""
import csv
import argparse
import hashlib
import json
from pathlib import Path

from .spec import CONDITIONS, METHODS
from .study import gate_counts, _rows


def compare_signatures(a,b):
    signature=lambda es:sorted((e['step_id'],e['target'],e['timestamp_s']) for e in es)
    return signature(a)==signature(b)


def audit_legacy_timing(v2_root):
    root=Path(v2_root);records=[];hashes={}
    def read(path):
        hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text(encoding='utf-8'))
    for folder in sorted((root/'shared_inputs').iterdir()):
        if not folder.is_dir():continue
        cache=read(folder/'inputs'/'manifest.json');task=cache['tasks'][0]
        generation=read(folder/'evaluation'/'generation.json')
        truth=read(folder/'evaluation'/'truth.json');refs=read(folder/'evaluation'/'references.json')
        b=read(root/'research_predictions'/folder.name/'BTQ'/'prediction_manifest.json')
        f=read(root/'research_predictions'/folder.name/'F'/'prediction_manifest.json')
        first_truth=[r for r in truth if task['start_s']<=r['time_s']<task['end_s']]
        consistent=bool(first_truth) and all(r['step_id']==task['step_id'] for r in first_truth)
        first_ref=next(r for r in refs if r['step_id']==0)
        upper=first_ref.get('arrival_upper_s')
        records.append(dict(cache_id=folder.name,first_start_s=task['start_s'],first_applied_s=task['applied_s'],
            first_end_s=task['end_s'],next_task_start_s=cache['tasks'][1]['start_s'],
            single_first_task_identity=consistent,
            applied_matches_teacher_schedule=abs(task['applied_s']-task['start_s']-generation['config']['ack_delay_s'])<=1e-9,
            available_followup_after_reference_s=None if upper is None else task['end_s']-upper,
            active_response_fields_present=all('world_active' in r and 'response_at_s' in r for r in first_truth),
            crossing_boundary_captures=sum(r['exposure_start_s']<task['end_s']<=r['available_s'] for r in cache['frames']),
            BTQ_events=len(b['events']),F_events=len(f['events']),
            events_identical=compare_signatures(b['events'],f['events']),
            same_input_hash=b['input_sha256']==f['input_sha256']))
    s1=root/'trials'/'end_to_end__normal__262000__F'
    events=_rows(s1/'observations'/'events.csv')
    initial=next(r for r in events if r['event']=='Prepare')
    start=next(r for r in events if r['event']=='Start')
    update=next(r for r in events if r['event']=='Update')
    s1_timing=dict(trial_id='normal:262000:F:end_to_end',initial_prepare_request_s=float(initial['time_s']),
        initial_prepare_scheduled_applied_s=float(initial['applied_s']),
        transport_start_s=float(start['time_s']),transport_applied_s=float(start['applied_s']),
        first_update_s=float(update['time_s']),next_applied_s=float(update['applied_s']))
    path=s1/'observations'/'events.csv';hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(shared_caches=len(records),identical_event_caches=sum(r['events_identical'] for r in records),
        legacy_records=records,S1_closed_loop_timing=s1_timing,source_sha256=hashes,
        conclusion='Distinct protocols: S1 .04 is initialization, .54 transport; fixed teacher .04 transport, next task at4. No S1 trajectory relabeling.',
        limitations='Old fixed truth lacks active/response fields; task schedule alone is not complete execution telemetry.')


def feasibility_table(study_root):
    root=Path(study_root);scores=_rows(root/'step_scores.csv');records=[]
    for condition in CONDITIONS:
        group=[r for r in scores if r['condition']==condition]
        seeds=sorted({int(r['seed']) for r in group})
        totals={m:{k:sum(int(r[k]) for r in group if r['method']==m)
                   for k in ('reference_arrivals','supported_confirmations','premature_confirmations',
                             'unsupported_confirmations','missed_supported_confirmation','confirmation_right_censored')}
                for m in METHODS}
        counts=[];changes={k:0 for k in ('S','K','W','Q','F_vs_BTQ')}
        pairs={'S':('BTQ','BTQ+S'),'K':('BTQ','BTQ+K'),
               'W':('BQ_single_frame','BTQ'),'Q':('B_single_frame','BQ_single_frame'),
               'F_vs_BTQ':('BTQ','F_arrival')}
        for seed in seeds:
            cache_id=f'{condition}_{seed}'
            counts.append(gate_counts(_rows(root/'predictions'/cache_id/'BTQ'/'gate_trace.csv')))
            events={}
            for m in METHODS+('BQ_single_frame',):
                p=root/('diagnostics' if m=='BQ_single_frame' else 'predictions')/cache_id/m/'prediction_manifest.json'
                events[m]=json.loads(p.read_text(encoding='utf-8'))['events']
            for key,(a,b) in pairs.items():changes[key]+=int(not compare_signatures(events[a],events[b]))
        records.append(dict(condition=condition,development_seed_count=len(seeds),
            G_candidates=sum(c['G_candidates'] for c in counts),
            S_only_candidates=sum(c['S_only'] for c in counts),K_only_candidates=sum(c['K_only'] for c in counts),
            Q_only_candidates=sum(c['Q_only'] for c in counts),
            event_difference_counts=changes,method_counts=totals,simulation=True,formal_conclusion=False))
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Read-only S2 timing and mechanism audit')
    parser.add_argument('--legacy',required=True);parser.add_argument('--study',required=True)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    out=Path(args.output)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True)
    from ..batch import _write_csv,_write_json
    from .study import audit_development
    legacy=audit_legacy_timing(args.legacy);table=feasibility_table(args.study)
    _write_json(out/'legacy_timing_audit.json',legacy)
    _write_csv(out/'legacy_21_cache_timing.csv',legacy['legacy_records'])
    _write_json(out/'13_condition_feasibility.json',table)
    _write_csv(out/'13_condition_feasibility.csv',table)
    integrity=audit_development(args.study);_write_json(out/'development_integrity.json',integrity)
    print(json.dumps(dict(old_caches=legacy['shared_caches'],old_identical=legacy['identical_event_caches'],
        conditions=len(table),**integrity),ensure_ascii=False))
