"""Bounded E0–E3 development plan. There is deliberately no formal scan API."""
from collections import Counter,defaultdict
from dataclasses import asdict
import csv
import json
import math
from pathlib import Path
import traceback
import zipfile

from ..config import SCENARIOS
from ..formal_runner import run_formal_trial
from ..runner import TrialResult
from ..batch import _write_csv,_write_json
from ..fixed_inputs import generate_fixed_input
from dmf.experiment.benchmark import run_variant
from .spec import METHODS,DEVELOPMENT_SEEDS
from .runner import run_trial_v2,TrialV2
from .evaluation import summarize_phases,evaluate_trial
from .persistence import save_trial,sha256
from .benchmark import run_arrival_variant
from .probes import run_probe_matrix,write_probe_cache,CASES


def failed_trial(spec,scenario,seed,method,phase_mode,error):
    r=TrialV2(f'{scenario}:{seed}:{method}:{phase_mode}:failed',method,phase_mode,tuple(spec.environment.route))
    r.metrics=dict(simulation=True,scenario=scenario,seed=seed,method=method,phase_mode=phase_mode,terminal_outcome='infrastructure_error',
        prepared=False,source_visual_confirmed=False,preparation_status='unknown_infrastructure_error',execution_time_s=None,
        preparation_time_s=None,completion_time_s=None,captured_frames=0,retries=0,recoveries=0,recovery_resends=0,
        unknown_frames=0,missing_mask_frames=0,error=str(error))
    score=evaluate_trial(r);r.steps=score.pop('steps');r.event_evaluation=score.pop('event_evaluation');r.metrics.update(score)
    r.legacy=TrialResult(r.metrics,[],[],[]);r.geometry=dict(metadata=dict(simulation=True,coordinate_unit='pitch',status='unavailable'))
    return r


def _frozen_equal(rows,path,scenario):
    with path.open(encoding='utf-8-sig',newline='') as f:
        frozen=[r for r in csv.DictReader(f) if r['scenario']==scenario and r['seed']=='261000' and r['method']=='C' and r['ablation']=='full']
    if len(rows)!=len(frozen):return False
    for actual,expected in zip(rows,frozen):
        for key,value in actual.items():
            e=expected.get(key,'')
            if value is None:
                if e!='':return False
            elif isinstance(value,bool):
                if str(value)!=e:return False
            elif isinstance(value,(float,int)):
                if not e or not math.isclose(float(value),float(e),rel_tol=1e-10,abs_tol=1e-10):return False
            elif key=='method_version':
                if e.split('__')[0]!=value:return False
            elif isinstance(value,dict):
                if json.loads(e)!=value:return False
            elif e!=str(value):return False
    return True


def run_compatibility(spec,scenarios=('normal','jitter','partial_stall'),frozen_dir=None):
    records=[]
    for scene in scenarios:
        old=run_formal_trial(spec.environment,scene,261000)
        new=run_trial_v2(spec,scene,261000,'C_v1_compat')
        record=dict(scenario=scene,seed=261000,truth_equal=old.truth==new.legacy.truth,frames_equal=old.frames==new.legacy.frames,
            events_equal=old.events==new.legacy.events,metrics_equal=old.metrics==new.legacy.metrics)
        if frozen_dir:
            path=Path(frozen_dir)
            for name in ('truth','frames','events'):record['frozen_'+name+'_equal']=_frozen_equal(getattr(new.legacy,name),path/(name+'.csv'),scene)
            record['frozen_metrics_equal']=_frozen_equal([new.legacy.metrics],path/'trials.csv',scene)
        records.append(record)
    return dict(checked_trials=len(records),all_equal=all(all(v for k,v in r.items() if k.endswith('_equal')) for r in records),checks=records,
        evidence_scope='historical already observed seed, not new independent validation')


def run_smoke(spec,output,*,frozen_dir=None):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    compatibility=run_compatibility(spec,frozen_dir=frozen_dir)
    _write_json(output/'compatibility.json',compatibility)
    if not compatibility['all_equal']:raise RuntimeError('E0 compatibility failed; smoke stopped')
    matrix=run_probe_matrix(spec);_write_json(output/'module_mechanism_matrix.json',matrix)
    _write_csv(output/'module_mechanism_matrix.csv',matrix)
    contracts={m:spec.algorithm_contract(m) for m in METHODS}
    if contracts['BTQ']['target']!=contracts['F']['target']:raise RuntimeError('unfair baseline window')
    _write_json(output/'method_contracts.json',contracts)
    runs=[];errors=[]
    plan=[(s,seed,m,'end_to_end') for s in SCENARIOS for seed in DEVELOPMENT_SEEDS for m in METHODS]
    plan += [(s,seed,m,view) for s in ('normal','jitter') for seed in DEVELOPMENT_SEEDS for m in ('BTQ','F') for view in ('source_only','transport_only')]
    _write_json(output/'planned_trials.json',[dict(scenario=s,seed=seed,method=m,phase_mode=v,planned_steps=len(spec.environment.route)-1) for s,seed,m,v in plan])
    for index,(scene,seed,method,view) in enumerate(plan,1):
        try:r=run_trial_v2(spec,scene,seed,method,phase_mode=view)
        except Exception as exc:
            errors.append(dict(scenario=scene,seed=seed,method=method,phase_mode=view,traceback=traceback.format_exc()))
            r=failed_trial(spec,scene,seed,method,view,exc)
        save_trial(r,output/'trials'/f'{view}__{scene}__{seed}__{method}',spec);runs.append(r)
        print(f'Development trial {index}/{len(plan)}: {view} {scene} {seed} {method} => {r.metrics["terminal_outcome"]}',flush=True)
    _write_csv(output/'trials.csv',[r.metrics for r in runs])
    _write_csv(output/'step_ledger.csv',[dict(trial_id=r.trial_id,method=r.method,phase_mode=r.phase_mode,**s) for r in runs for s in r.steps])
    groups=defaultdict(list)
    for r in runs:groups[(r.phase_mode,r.metrics['scenario'],r.method)].append(r)
    summaries=[]
    for (view,scene,method),items in groups.items():summaries.append(dict(scenario=scene,method=method,**summarize_phases(items)))
    _write_json(output/'phase_summaries.json',summaries);_write_csv(output/'phase_summaries.csv',summaries)
    reasons=Counter((r.metrics['scenario'],r.method,g['stage'],reason) for r in runs for g in r.gates for reason in g.get('rebuild_reasons',[]))
    _write_csv(output/'window_rebuild_counts.csv',[dict(scenario=s,method=m,stage=stage,reason=reason,count=count,unit='window_rebuild_occurrences_not_failed_trials') for (s,m,stage,reason),count in reasons.items()])
    predictions=[]
    for case in CASES:
        path=output/'mechanism_inputs'/case;write_probe_cache(path,case,spec)
        for m in ('BT','BTQ','F'):
            rep=run_arrival_variant(path,m,output/'mechanism_predictions'/case/m,spec)
            predictions.append(dict(kind='synthetic_mechanism',condition=case,method=m,input_sha256=rep['input_sha256'],arrival_events=len(rep['events'])))
    for scene in SCENARIOS:
        for seed in DEVELOPMENT_SEEDS:
            block=output/'shared_inputs'/f'{scene}_{seed}'
            generate_fixed_input(spec.environment,scene,seed,block)
            for method in ('S1','S2','S3','S4'):
                run_variant(block/'inputs',method,output/'historical_baseline_predictions'/f'{scene}_{seed}'/method)
            for method in ('BT','BTQ','F'):
                rep=run_arrival_variant(block/'inputs',method,output/'research_predictions'/f'{scene}_{seed}'/method,spec)
                predictions.append(dict(kind='development_shared_cache',condition=f'{scene}_{seed}',method=method,input_sha256=rep['input_sha256'],arrival_events=len(rep['events'])))
    _write_csv(output/'shared_input_prediction_support.csv',predictions)
    _write_json(output/'infrastructure_errors.json',errors)
    root=Path(__file__).resolve().parents[3]
    sources=list(Path(__file__).parent.glob('*.py'))+[root/'configs/chapter2_simulation_v2.yaml',root/'run_chapter2_simulation_v2.py']
    sources += [Path(__file__).parents[1]/n for n in ('world.py','vision.py','formal_adapter.py','formal_runner.py','geometry.py')]
    with zipfile.ZipFile(output/'source_snapshot.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in sources:
            if p.exists():z.write(p,str(p.relative_to(root)))
    report=dict(simulation=True,purpose='E0-E3_development_only',formal_scan_started=False,
        planned_trials=len(plan),end_to_end_trials=84,phase_diagnostic_trials=24,completed_records=len(runs),infrastructure_errors=len(errors),
        mechanism_runs=len(matrix),shared_cache_count=21,research_offline_runs=63,historical_offline_runs=84,mechanism_prediction_runs=24,
        development_seeds=list(DEVELOPMENT_SEEDS),compatibility=compatibility,config=asdict(spec),
        source_sha256={str(p.relative_to(root)):sha256(p) for p in sources if p.exists()},
        demo_trial='end_to_end__normal__262000__F',all_planned_records_preserved=len(runs)==len(plan))
    _write_json(output/'study_manifest.json',report)
    if errors:raise RuntimeError('Infrastructure failures retained in ledger; formal progression blocked')
    return report
