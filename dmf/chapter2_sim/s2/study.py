"""Small, ledgered development only. Confirmation seeds have no entry here."""
from collections import Counter
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess

from ..batch import _write_csv, _write_json
from ..v2.probes import CASES, write_probe_cache
from .spec import METHODS, DIAGNOSTICS, SEEDS, CONDITIONS, NORMAL_BASE, MODEL_GENERATED
from .inputs import generate_base, validate_teacher, observation_variant, freeze_input
from .benchmark import predict_arrivals
from .evaluation import build_reference, score_step


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def _rows(path):
    with Path(path).open(encoding='utf-8',newline='') as handle:
        return list(csv.DictReader(handle))


def _bool(value):
    if value in ('True','true',True):return True
    if value in ('False','false',False,None,''):return False
    raise ValueError('invalid persisted boolean')


def gate_counts(rows):
    counts=Counter();longest=0.;raw_sequence=[]
    for row in rows:
        passed=_bool(row.get('C0_passed'))
        counts['frames']+=1;counts['C0_valid']+=int(passed)
        if not passed:counts['C0_'+row.get('C0_reason','unknown')]+=1
        raw=json.loads(row['raw']) if row.get('raw') else None
        raw_sequence.append((row['frame_id'],raw))
        if raw is not None:
            g=_bool(row.get('coverage_passed'));s,k,q=(bool(raw[x]) for x in 'SKQ')
            counts['G_candidates']+=int(g)
            counts['Q_reject']+=int(not q);counts['S_reject']+=int(not s);counts['K_reject']+=int(not k)
            counts['S_only']+=int(g and q and k and not s)
            counts['K_only']+=int(g and q and s and not k)
            counts['Q_only']+=int(g and s and k and not q)
        if row.get('window_duration_s'):longest=max(longest,float(row['window_duration_s']))
    for key in ('frames','C0_valid','G_candidates','Q_reject','S_reject','K_reject','S_only','K_only','Q_only'):
        counts.setdefault(key,0)
    return dict(counts,longest_window_s=longest,raw_sequence_sha256=_digest(raw_sequence))


def _source_manifest(spec):
    repo=Path(__file__).resolve().parents[3]
    folders=[repo/'dmf/chapter2_sim',repo/'dmf/experiment',repo/'dmf/vision']
    paths=[p for folder in folders for p in folder.rglob('*.py') if '__pycache__' not in p.parts]
    formal=spec.study_phase=='confirmatory'
    return dict(simulation=True,study_phase=spec.study_phase,development_only=not formal,
        formal_seed_runs=0,planned_formal_unique_seeds=20 if formal else 0,
        version=spec.version,config=asdict(spec),methods=list(METHODS),diagnostics=list(DIAGNOSTICS),
        model_boundary='2D point motion + synthetic masks; pitch; not CFD, electrowetting physics or U-Net',
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        git_dirty_status=subprocess.check_output(['git','status','--short'],cwd=repo,text=True,encoding='utf-8'),
        source_sha256={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def run_mechanism(output, spec):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    records=[]
    for case in CASES:
        cache=output/'inputs'/case
        write_probe_cache(cache,case,spec.common)
        raw=[]
        for method in METHODS+DIAGNOSTICS:
            diagnostic=method in DIAGNOSTICS
            p=output/('diagnostics' if diagnostic else 'predictions')/case/method
            report=predict_arrivals(cache,method,p,spec,diagnostic=diagnostic)
            counts=gate_counts(_rows(p/'gate_trace.csv'));raw.append(counts['raw_sequence_sha256'])
            records.append(dict(case=case,method=method,role=report['role'],
                event_count=len(report['events']),event_times=[e['timestamp_s'] for e in report['events']],
                **counts,simulation=True,synthetic_stress=True,has_independent_reference=False))
        if len(set(raw))!=1:raise AssertionError('switches changed raw observation history')
    _write_csv(output/'mechanism.csv',records)
    result=dict(cases=len(CASES),primary_runs=len(CASES)*len(METHODS),
        diagnostic_runs=len(CASES)*len(DIAGNOSTICS),raw_features_invariant=True,
        no_performance_scoring=True,simulation=True)
    _write_json(output/'manifest.json',dict(_source_manifest(spec),**result))
    return result


def run_development(output, spec, *, conditions=CONDITIONS, seeds=SEEDS):
    if spec.study_phase!='development':raise ValueError('development entry rejects confirmatory specification')
    return _run_paired(output,spec,conditions=conditions,seeds=seeds)


def _run_paired(output, spec, *, conditions, seeds):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    conditions=tuple(conditions);seeds=tuple(seeds)
    if len(set(conditions))!=len(conditions) or not conditions or any(c not in CONDITIONS for c in conditions):
        raise ValueError('undeclared or duplicate condition')
    if len(set(seeds))!=len(seeds) or not seeds:raise ValueError('invalid development seeds')
    for seed in seeds:spec.validate_seed(seed)
    output.mkdir(parents=True)
    _write_json(output/'configuration_manifest.json',_source_manifest(spec))
    plan=[dict(cache_id=f'{c}_{s}',condition=c,seed=s,method=m,planned_steps=1)
          for c in conditions for s in seeds for m in METHODS]
    _write_csv(output/'plan.csv',plan)
    bases={};scores=[];diagnostic_scores=[];gates=[];errors=[];identities=[]
    for seed in seeds:
        for scenario in ('normal','failure'):
            try:
                base=generate_base(spec,seed,scenario);bases[seed,scenario]=base
                target=output/'scoring_side'/'base_worlds'/f'{scenario}_{seed}'
                target.mkdir(parents=True)
                for name,content in [('truth',base['truth']),('commands',base['commands']),
                                     ('applied_events',base['applied_events']),('capture_samples',base['capture_samples'])]:
                    _write_json(target/(name+'.json'),content)
                _write_json(target/'teacher_audit.json',validate_teacher(base))
            except Exception as exc:
                bases[seed,scenario]=None
                errors.append(dict(base_world=f'{scenario}_{seed}',error_type=type(exc).__name__,error=str(exc)))
    for condition in conditions:
        for seed in seeds:
            cache_id=f'{condition}_{seed}'
            base=bases[seed,'normal' if condition in NORMAL_BASE else 'failure']
            camera='jitter' if condition=='F_jitter' else 'dropout' if condition=='F_dropout' else 'normal'
            task=dict(step_id=0,source=190,target=191,start_s=0.,end_s=spec.duration_s,applied_s=spec.environment.ack_delay_s)
            references=[dict(step_id=0,target=191,status='reference_right_censored',truth_complete=False)]
            cache=None
            try:
                if base is None:raise RuntimeError('base world unavailable; independent reference unknown')
                # Truth is method-independent, including when input/prediction writing fails.
                references=build_reference(base['truth'],base['tasks'],base['geometry'],spec.reference,spec.environment.dt_s)
                frames=observation_variant(base['observations'][camera],base['snapshot'],condition,spec)
                cache_path=output/'inputs'/cache_id
                cache=freeze_input(base,frames,cache_path,spec)
                score_path=output/'scoring_side'/cache_id;score_path.mkdir(parents=True)
                truth_hash=_digest(base['truth'])
                _write_json(score_path/'references.json',references)
                _write_json(score_path/'generation.json',dict(condition=condition,seed=seed,
                    base_world=base['scenario'],teacher_audit=validate_teacher(base),
                    truth_sha256=truth_hash,input_sha256=cache['input_sha256'],
                    condition_category='model_generated' if condition in MODEL_GENERATED else 'synthetic_stress',
                    missing_masks_preserved=True,stress_observations_not_real_unet=True,
                    frame_count=len(frames),simulation=True))
                raw=[]
                for method in METHODS+DIAGNOSTICS:
                    diagnostic=method in DIAGNOSTICS
                    destination=output/('diagnostics' if diagnostic else 'predictions')/cache_id/method
                    prediction=predict_arrivals(cache_path,method,destination,spec,diagnostic=diagnostic)
                    counts=gate_counts(_rows(destination/'gate_trace.csv'));raw.append(counts['raw_sequence_sha256'])
                    row=score_step(base['tasks'][0],references[0],prediction['events'],
                        dict(task_entered=True,input_generated=True,records_end_s=spec.duration_s,truth_end_s=spec.duration_s),
                        horizon_s=spec.followup_s)
                    row.update(cache_id=cache_id,condition=condition,seed=seed,method=method,
                        role=prediction['role'],input_sha256=cache['input_sha256'],truth_sha256=truth_hash,
                        category='model_generated' if condition in MODEL_GENERATED else 'synthetic_stress')
                    (diagnostic_scores if diagnostic else scores).append(row)
                    gates.append(dict(cache_id=cache_id,condition=condition,seed=seed,method=method,
                        role=prediction['role'],events=len(prediction['events']),**counts))
                if len(set(raw))!=1:raise AssertionError('raw features differ by method')
                identities.append(dict(cache_id=cache_id,input_sha256=cache['input_sha256'],
                    truth_sha256=truth_hash,all_methods_same_raw=True))
            except Exception as exc:
                errors.append(dict(cache_id=cache_id,error_type=type(exc).__name__,error=str(exc)))
                existing={r['method'] for r in scores if r['cache_id']==cache_id}
                for method in METHODS:
                    if method not in existing:
                        fallback=score_step(task,references[0],[],dict(task_entered=False,input_generated=cache is not None,
                            records_end_s=spec.duration_s if cache is not None else None,
                            truth_end_s=spec.duration_s if base is not None else None),horizon_s=spec.followup_s)
                        fallback.update(cache_id=cache_id,condition=condition,seed=seed,method=method,
                            role='primary',confirmation_label='infrastructure_unknown',error=str(exc))
                        scores.append(fallback)
                if not any(r['cache_id']==cache_id for r in diagnostic_scores):
                    fallback=score_step(task,references[0],[],dict(task_entered=False,input_generated=cache is not None,
                        records_end_s=None,truth_end_s=spec.duration_s if base is not None else None),horizon_s=spec.followup_s)
                    diagnostic_scores.append(dict(fallback,cache_id=cache_id,condition=condition,seed=seed,
                        method='BQ_single_frame',role='auxiliary_diagnostic',error=str(exc)))
    _write_csv(output/'step_scores.csv',scores)
    _write_csv(output/'diagnostic_scores.csv',diagnostic_scores)
    _write_csv(output/'gate_diagnostics.csv',gates)
    _write_json(output/'input_identity_audit.json',identities)
    _write_json(output/'infrastructure_errors.json',errors)
    keys=('planned_steps','reference_arrivals','supported_confirmations','premature_confirmations',
          'unsupported_confirmations','timing_uncertain_confirmations','missed_supported_confirmation',
          'confirmation_right_censored','reference_right_censored','unattempted_steps','infrastructure_unknown')
    summary=[]
    for condition in conditions:
        for method in METHODS:
            group=[r for r in scores if r['condition']==condition and r['method']==method]
            summary.append(dict(condition=condition,method=method,seeds_per_condition=len(seeds),
                **({'development_seeds':len(seeds)} if spec.study_phase=='development' else {}),
                **{k:sum(int(r.get(k,0)) for r in group) for k in keys},simulation=True))
    formal=spec.study_phase=='confirmatory'
    _write_csv(output/('condition_summary.csv' if formal else 'development_summary.csv'),summary)
    result=dict(simulation=True,study_phase=spec.study_phase,development_only=not formal,
        formal_seed_runs=len(seeds) if formal else 0,
        formal_unique_seeds=len(seeds) if formal else 0,
        seeds=list(seeds),conditions=list(conditions),base_worlds=sum(b is not None for b in bases.values()),
        planned_method_steps=len(plan),input_caches=len(identities),
        primary_prediction_runs=len([r for r in scores if not r.get('infrastructure_unknown')]),
        diagnostic_prediction_runs=sum(not r.get('infrastructure_unknown') for r in diagnostic_scores),
        planned_diagnostic_steps=len(conditions)*len(seeds),raw_features_invariant=len(identities)==len(conditions)*len(seeds),
        infrastructure_errors=len(errors),no_formal_performance_claim=not formal)
    _write_json(output/'run_report.json',result)
    return result


def audit_development(output):
    return _audit_study(output,'development',SEEDS)


def _audit_study(output,expected_phase,allowed_seeds):
    output=Path(output)
    report=json.loads((output/'run_report.json').read_text(encoding='utf-8'))
    if report.get('study_phase','development')!=expected_phase:raise ValueError('study phase mismatch')
    scores=_rows(output/'step_scores.csv');plan=_rows(output/'plan.csv')
    identity=lambda r:(r['cache_id'],int(r['seed']),r['condition'],r['method'])
    if Counter(map(identity,scores))!=Counter(map(identity,plan)):raise ValueError('planned identities lost/duplicated')
    if {int(r['seed']) for r in scores}-set(allowed_seeds):raise ValueError('unauthorized seed')
    if {r['method'] for r in scores}!=set(METHODS):raise ValueError('primary registry changed')
    if any(r['role']!='primary' for r in scores):raise ValueError('diagnostics mixed into primary study')
    if report['infrastructure_errors']:raise ValueError('infrastructure failures retained; not accepted')
    from dmf.experiment.mask_cache import load_cache
    from types import SimpleNamespace
    from ..v2.spec import ReferenceSpec
    from ..formal_adapter import NormalizedMap
    items=json.loads((output/'input_identity_audit.json').read_text(encoding='utf-8'))
    expected_cache={r['cache_id'] for r in plan}
    if Counter(r['cache_id'] for r in items)!=Counter({c:1 for c in expected_cache}):
        raise ValueError('cache identity ledger incomplete or duplicated')
    config=json.loads((output/'configuration_manifest.json').read_text(encoding='utf-8'))['config']
    reference_spec=ReferenceSpec(**config['common']['reference'])
    checked_scores=0
    for item in items:
        cache=load_cache(output/'inputs'/item['cache_id'])
        if cache['input_sha256']!=item['input_sha256']:raise ValueError('input changed')
        gen=json.loads((output/'scoring_side'/item['cache_id']/'generation.json').read_text(encoding='utf-8'))
        truth=json.loads((output/'scoring_side'/'base_worlds'/f"{gen['base_world']}_{gen['seed']}"/'truth.json').read_text(encoding='utf-8'))
        if _digest(truth)!=gen['truth_sha256'] or gen['truth_sha256']!=item['truth_sha256']:
            raise ValueError('scoring truth changed')
        mapping=NormalizedMap.from_snapshot(cache['map'])
        geometry=SimpleNamespace(centers={r.electrode_id:r.center_mm for r in mapping})
        rebuilt=build_reference(truth,cache['tasks'],geometry,reference_spec,config['common']['environment']['dt_s'])
        saved=json.loads((output/'scoring_side'/item['cache_id']/'references.json').read_text(encoding='utf-8'))
        if rebuilt!=saved:raise ValueError('independent reference inconsistent with stored truth')
        raw_hashes=[]
        for method in METHODS+DIAGNOSTICS:
            folder=output/('diagnostics' if method in DIAGNOSTICS else 'predictions')/item['cache_id']/method
            p=json.loads((folder/'prediction_manifest.json').read_text(encoding='utf-8'))
            raw_hashes.append(gate_counts(_rows(folder/'gate_trace.csv'))['raw_sequence_sha256'])
            if p['input_sha256']!=cache['input_sha256']:raise ValueError('methods saw different inputs')
            if method in DIAGNOSTICS:continue
            row=next(r for r in scores if r['cache_id']==item['cache_id'] and r['method']==method)
            recomputed=score_step(cache['tasks'][0],saved[0],p['events'],
                dict(task_entered=True,input_generated=True,records_end_s=config['duration_s'],truth_end_s=config['duration_s']),
                horizon_s=config['followup_s'])
            for key,value in recomputed.items():
                actual=row.get(key,'')
                if value is None:equal=actual==''
                elif isinstance(value,bool):equal=_bool(actual)==value
                elif isinstance(value,(int,float)):equal=actual!='' and abs(float(actual)-value)<=1e-9
                else:equal=actual==str(value)
                if not equal:raise ValueError('score inconsistent: '+item['cache_id']+'/'+method+'/'+key)
            checked_scores+=1
        if len(set(raw_hashes))!=1:raise ValueError('persisted raw features differ by method')
    summaries=_rows(output/('condition_summary.csv' if expected_phase=='confirmatory' else 'development_summary.csv'))
    expected_groups=Counter({(r['condition'],r['method']):1 for r in plan})
    if Counter((r['condition'],r['method']) for r in summaries)!=expected_groups:
        raise ValueError('summary groups missing or duplicated')
    required_counts=('planned_steps','reference_arrivals','supported_confirmations','premature_confirmations',
        'unsupported_confirmations','timing_uncertain_confirmations','missed_supported_confirmation',
        'confirmation_right_censored','reference_right_censored','unattempted_steps','infrastructure_unknown')
    for row in summaries:
        if not set(required_counts)<=row.keys():raise ValueError('summary count columns missing')
        group=[r for r in scores if r['condition']==row['condition'] and r['method']==row['method']]
        for key in row:
            if key in group[0] and key not in ('condition','method','simulation'):
                if int(row[key])!=sum(int(r.get(key,0)) for r in group):raise ValueError('summary count mismatch: '+key)
    return dict(accepted_integrity=True,study_phase=expected_phase,
                accepted_development_integrity=expected_phase=='development',planned_rows=len(plan),
                independent_references_recomputed=len(items),scores_recomputed=checked_scores,
                new_formal_results=expected_phase=='confirmatory')
