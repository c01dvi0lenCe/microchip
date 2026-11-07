"""Only development plan; independent cohorts retain their own denominators."""
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
import json
import traceback
from ..batch import _write_csv,_write_json
from ..v2.runner import TrialV2
from ..runner import TrialResult
from .persistence import save_trial
from .spec import development_plan,S3Spec
from .runner import run_trial
from ..geometry import SimulationMap

def infrastructure_failure(spec,item,exc):
    """Keep a planned failure evaluable as missing evidence, not empty geometry."""
    p=item['protection'] or ('P_F' if item['method']=='F_full' else 'P_B')
    identity=f"{item['cohort']}:{item['scenario']}:{item['seed']}:{item['method']}:{p}:{item['phase_mode']}:invalid"
    r=TrialV2(identity,item['method'],item['phase_mode'],tuple(spec.common.environment.route))
    r.metrics=dict(item,simulation=True,protection=p,trial_id=identity,method_version=spec.version,planned_steps=3,unattempted_steps=3,
        source_prepared=False,transport_complete=False,path_complete=False,infrastructure_invalid=True,terminal_outcome='infrastructure_invalid',
        execution_time_s=None,stop_reason=f'{type(exc).__name__}: {exc}',reference_unknown_steps=3,max_step_applied=0,
        exogenous_hash=None,p0_prefix_hash=None,exogenous={},formal_seed_runs=0)
    r.steps=[dict(step=s,unattempted=True,outcome='unattempted',reference_unknown=True) for s in range(3)]
    g=SimulationMap(spec.common.environment)
    r.geometry=dict(g.snapshot(),lower=g.lower.tolist(),scale=g.scale,shape=[int(i) for i in g.shape])
    r.legacy=TrialResult(r.metrics,[],[],[])
    return r

def audit_development(metrics):
    expected=development_plan()
    key=lambda r:(r['cohort'],r['scenario'],r['seed'],r['method'],r.get('protection') or ('P_F' if r['method']=='F_full' else 'P_B'),r['phase_mode'])
    if sorted(map(key,metrics))!=sorted(map(key,expected)):raise ValueError('planned identities missing or duplicated')
    by=defaultdict(list)
    for r in metrics:
        if r['seed'] not in (264000,264001,264002):raise ValueError('non-development seed')
        if r['planned_steps']!=3 or r['max_step_applied']>7:raise ValueError('step/budget contract')
        by[r['scenario'],r['seed'],r['phase_mode']].append(r)
    for key,group in by.items():
        if len({r['exogenous_hash'] for r in group})!=1:raise ValueError('exogenous arrays differ')
        if key[2]=='end_to_end' and len({r['p0_prefix_hash'] for r in group})!=1:raise ValueError('P0 prefixes differ')
    return dict(passed=True,records=len(metrics),planned_steps=3*len(metrics),formal_seed_runs=0,
                cohorts={c:sum(r['cohort']==c for r in metrics) for c in ('main','bridge','diagnostic')},
                exogenous_groups=len(by),shared_p0_prefixes_verified=True)

def summarize(metrics):
    groups=defaultdict(list)
    for r in metrics:groups[r['cohort'],r['scenario'],r['method'],r['protection'],r['phase_mode']].append(r)
    rows=[]
    for key,items in groups.items():
        row=dict(zip(('cohort','scenario','method','protection','phase_mode'),key),planned_trials=len(items),planned_steps=3*len(items))
        for f in ('source_prepared','source_visual_confirmed','transport_started','transport_complete','path_complete','supported_confirmations',
                  'unsupported_requests','missed_confirmations','premature_requests','timing_uncertain_requests','unattempted_steps',
                  'retries','recoveries','recovery_resends','unknown_frames','missing_mask_frames','reference_unknown_steps','censored_steps'):
            row[f]=sum(r.get(f,0) for r in items)
        for terminal in ('infrastructure_invalid','source_preparation_failed','transport_aborted','workflow_complete_without_supported_path','reference_supported_path_complete'):
            row[terminal]=sum(r['terminal_outcome']==terminal for r in items)
        row['stop_reasons']={reason:sum(r['stop_reason']==reason for r in items) for reason in {r['stop_reason'] for r in items}}
        row['execution_times_s']=[r['execution_time_s'] for r in items]
        rows.append(row)
    return rows

def run_development(output):
    output=Path(output)
    if output.exists():raise FileExistsError('development results are append-only; output must be new')
    output.mkdir(parents=True);spec=S3Spec();plan=development_plan()
    _write_json(output/'planned_trials.json',plan);_write_json(output/'config_manifest.json',dict(schema=spec.version,spec=asdict(spec),formal_seed_runs=0,
        seed_policy='264000–264002 only',examples=[dict(scenario=s,seed=264000,cohort='main') for s in ('normal','deviation')]))
    metrics=[];step_rows=[];events=[]
    for i,item in enumerate(plan):
        try:r=run_trial(spec,**item)
        except Exception as exc:
            # Failed planned trials are retained, not retried or seed-replaced.
            r=infrastructure_failure(spec,item,exc)
            _write_json(output/f'error-{i:03d}.json',dict(item=item,error=str(exc),traceback=traceback.format_exc()))
        path=output/'trials'/f"{i:03d}_{item['scenario']}_{item['seed']}_{item['method']}_{r.metrics['protection']}"
        save_trial(r,path,spec);r.metrics['relative_trial_path']=str(path.relative_to(output)).replace('\\','/')
        metrics.append(dict(r.metrics))
        step_rows.extend(dict(row,trial_id=r.trial_id,cohort=item['cohort']) for row in r.steps)
        events.extend(dict(row,trial_id=r.trial_id,cohort=item['cohort']) for row in r.event_evaluation)
        print(f"{i+1}/120 {item['cohort']} {item['scenario']} {item['seed']} {item['method']} {r.metrics['terminal_outcome']}",flush=True)
        del r
    _write_csv(output/'development_trials.csv',metrics);_write_csv(output/'development_steps.csv',step_rows)
    _write_csv(output/'request_applied_evaluation.csv',events);_write_csv(output/'development_summary.csv',summarize(metrics))
    invalid=sum(r['terminal_outcome']=='infrastructure_invalid' for r in metrics)
    audit=audit_development(metrics) if not invalid else dict(passed=False,infrastructure_invalid=invalid,records=len(metrics),formal_seed_runs=0)
    _write_json(output/'development_audit.json',audit);return audit
