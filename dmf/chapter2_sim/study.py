"""Frozen study orchestration. All references are read only after prediction."""
from dataclasses import asdict, replace
import csv
import hashlib
import json
import re
from pathlib import Path

import yaml

from .config import SCENARIOS
from .batch import _write_csv, _write_json
from .fixed_inputs import generate_fixed_input
from dmf.experiment.benchmark import run_variant, VARIANTS


def validate_study_spec(spec):
    from .formal_batch import METHODS
    expected = dict(scenarios=list(SCENARIOS), smoke_seeds=[260600,260601,260602],
                    formal_seed_start=261000, formal_seed_count=20, methods=list(METHODS),
                    offline_variants=list(VARIANTS), arrival_coverages=[.75,.85,.95],
                    stable_durations_s=[.25,.4,.6], sensitivity_scenario='jitter', bootstrap_repeats=2000)
    for key, value in expected.items():
        if spec.get(key) != value: raise ValueError(f'{key} differs from the approved frozen study')
    duration = spec.get('teacher_step_duration_s')
    if not isinstance(duration, (int,float)) or isinstance(duration, bool) or duration <= 0:
        raise ValueError('positive teacher-forced task duration required')


def validate_closed_loop_bundle(directory, cfg):
    """Smoke gate over persisted evidence, including all failed trials."""
    directory = Path(directory); counts = dict(frames=0, confirmations=0, trials=0)
    with (directory/'frames.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            counts['frames'] += 1
            if row['method'].startswith('C') and row.get('action') in {'Update', 'Complete'}:
                if (row.get('valid') != 'True' or row.get('clock_domain') != 'simulation' or
                    row.get('causality') != 'simulation_exposure_verified' or
                    float(row['exposure_start_s']) < float(row['applied_s'])-1e-9):
                    raise ValueError('formal confirmation used invalid or pre-application evidence')
    seen = set()
    with (directory/'events.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row.get('event') in {'Update', 'Complete'}:
                key = (row['scenario'], row['seed'], row['method'], row['step'])
                if key in seen: raise ValueError('duplicate confirmation for one transport step')
                seen.add(key); counts['confirmations'] += 1
    with (directory/'trials.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            counts['trials'] += 1
            steps = int(row['transport_steps'])
            if (int(row['confirmed_steps']) > steps or float(row['total_time_s']) > cfg.max_time_s+1e-9 or
                int(row['retries']) > steps*cfg.max_retries*(cfg.max_recoveries+1) or
                int(row['recoveries']) > steps*cfg.max_recoveries):
                raise ValueError('trial exceeds prescribed control bounds')
    return counts


def semantic_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = [p for p in (root/'dmf'/'chapter2_sim').glob('*.py') if p.name not in {'plotting.py', 'formal_plotting.py'}]
    paths += [root/'dmf'/'experiment'/name for name in ('evidence.py', 'perception.py', 'policy.py', 'config.py', 'benchmark.py', 'mask_cache.py')]
    paths += list((root/'dmf'/'vision').glob('*.py'))
    paths.append(root/'dmf'/'layout.py')
    return {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def evaluate_prediction_file(prediction, references, trial_manifest, output, *, simulation=False):
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    load = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
    predicted = load(prediction); refs = load(references); manifest = load(trial_manifest)
    if len(manifest) != 1: raise ValueError('one prediction cache must map to exactly one trial')
    digest = predicted.get('input_sha256')
    if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise ValueError('explicit SHA-256 input binding required')
    if manifest[0].get('input_sha256') != predicted.get('input_sha256'):
        raise ValueError('reference manifest belongs to a different input cache')
    if any(row.get('input_sha256') != predicted.get('input_sha256') for row in refs):
        raise ValueError('reference rows belong to a different input cache')
    identity = {key: manifest[0][key] for key in ('trial_id', 'task_id', 'clock_domain')}
    if predicted['clock_domain'] != identity['clock_domain']: raise ValueError('clock mismatch')
    events = []
    for event in predicted['events']:
        if event.get('clock_domain') != identity['clock_domain']:
            raise ValueError('event clock does not match prediction/reference clock')
        if any(key in event and event[key] != identity[key] for key in ('trial_id', 'task_id')):
            raise ValueError('event identity does not match reference manifest')
        events.append(dict(event, **identity))
    if simulation:
        from dmf.vision.event_evaluation import evaluate_simulation_events
        result = evaluate_simulation_events(events, refs, manifest)
    else:
        from dmf.vision.event_evaluation import evaluate_events
        result = evaluate_events(events, refs, manifest)
    result.update(variant=predicted['variant'], input_sha256=predicted['input_sha256'], simulation=simulation)
    output.parent.mkdir(parents=True, exist_ok=True); _write_json(output, result)
    return result


def _offline(cfg, scenarios, seeds, output, bootstrap_repeats, step_duration):
    from .formal_batch import summarize_offline
    rows = []
    for scenario in scenarios:
        for seed in seeds:
            trial = output/'cache_trials'/f'{scenario}_{seed}'
            generated = generate_fixed_input(cfg, scenario, seed, trial, step_duration_s=step_duration)
            for variant in VARIANTS:
                dest = output/'predictions'/f'{scenario}_{seed}'/variant
                predicted = run_variant(trial/'inputs', variant, dest)
                scored = evaluate_prediction_file(dest/'prediction.json', trial/'evaluation'/'references.json',
                                                 trial/'evaluation'/'trial_manifest.json', dest/'evaluation.json', simulation=True)
                counts = scored['counts']; denominator = scored['denominators']
                delay = [step['delay_upper_s'] for step in scored['per_step'] if step['outcome']=='confirmed_after_arrival']
                rows.append(dict(simulation=True, scenario=scenario, seed=seed, method=variant,
                    method_version=predicted['method_version'], input_sha256=generated['input_sha256'],
                    transport_steps=denominator['eligible_steps'], path_complete=counts['completed_paths']==1,
                    early_updates=counts['early_events']+counts['false_events'],
                    reference_arrived_steps=denominator['known_arrival_steps'], correct_confirmed_steps=counts['confirmed_arrivals'],
                    confirmed_steps=counts['predicted_steps'], missing_prediction_steps=counts['missing_prediction_steps'],
                    unknown_frames=sum(f['state']=='Unknown' for f in predicted['frames']),
                    missing_mask_frames=sum(not f['mask_available'] for f in predicted['frames']),
                    invalid_frames=sum(f['observation_quality']=='invalid' for f in predicted['frames']),
                    ambiguous_events=counts['ambiguous_timing_events'],
                    delay_censored_steps=counts['missing_arrival_events'],
                    confirmation_delay_s=sum(delay)/len(delay) if delay else None,
                    delay_observed_steps=len(delay), delay_missing_steps=denominator['eligible_steps']-len(delay),
                    **{key: counts[key] for key in ('missing_arrival_events', 'missing_reference_steps',
                        'right_censored_reference_steps', 'occluded_reference_steps', 'uncertain_reference_steps',
                        'unassessable_events', 'duplicate_events', 'ambiguous_timing_events', 'early_events', 'false_events')}))
    _write_csv(output/'offline_trials.csv', rows)
    summaries = summarize_offline(rows, bootstrap_repeats=bootstrap_repeats)
    _write_csv(output/'offline_summary.csv', summaries)
    return rows


def run_study(cfg, config_path, stage, output, *, smoke_manifest=None):
    from .formal_batch import run_formal_batch, METHODS
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    spec = yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))['study']
    if stage not in {'smoke', 'formal', 'sensitivity'}: raise ValueError('unknown study stage')
    validate_study_spec(spec)
    hashes = semantic_hashes()
    resolved_config = json.loads(json.dumps(asdict(cfg)))
    map_hash = hashlib.sha256(Path(cfg.map_path).read_bytes()).hexdigest() if cfg.map_path else None
    if stage != 'smoke':
        if not smoke_manifest: raise ValueError('smoke gate required')
        gate = json.loads(Path(smoke_manifest).read_text(encoding='utf-8'))
        if gate.get('stage')!='smoke' or gate.get('smoke_gate_passed') is not True: raise ValueError('smoke gate not passed')
        if gate['semantic_source_sha256'] != hashes: raise ValueError('algorithm changed since smoke; rerun smoke in a new directory')
        if gate['frozen_study'] != spec: raise ValueError('study changed since smoke')
        if gate.get('resolved_simulation_config') != resolved_config or gate.get('map_input_sha256') != map_hash:
            raise ValueError('simulation environment or map changed since smoke')
    seeds = list(spec['smoke_seeds']) if stage=='smoke' else list(range(spec['formal_seed_start'], spec['formal_seed_start']+spec['formal_seed_count']))
    output.mkdir(parents=True)
    if stage=='sensitivity':
        trial_count = 0
        for eta in spec['arrival_coverages']:
            for duration in spec['stable_durations_s']:
                rows = run_formal_batch(replace(cfg, arrival_coverage=eta, stable_duration_s=duration),
                    [spec['sensitivity_scenario']], seeds, output/f'eta_{eta}_duration_{duration}',
                    methods=('C',), bootstrap_repeats=spec['bootstrap_repeats'])
                trial_count += len(rows)
        manifest = dict(simulation=True, stage=stage, trials=trial_count, offline_runs=0, seeds=seeds,
                        frozen_study=spec, semantic_source_sha256=hashes, smoke_gate_passed=False)
    else:
        rows = run_formal_batch(cfg, SCENARIOS, seeds, output/'closed_loop', methods=METHODS,
                                bootstrap_repeats=spec['bootstrap_repeats'])
        evidence_checks = validate_closed_loop_bundle(output/'closed_loop', cfg)
        offline = _offline(cfg, SCENARIOS, seeds, output, spec['bootstrap_repeats'], spec['teacher_step_duration_s'])
        expected = len(SCENARIOS)*len(seeds)*len(METHODS)
        passed = (len(rows)==expected and len(offline)==len(SCENARIOS)*len(seeds)*len(VARIANTS)
                  and all(r['simulation'] is True and r['total_time_s'] <= cfg.max_time_s+1e-9 for r in rows)
                  and all(r['confirmed_steps']<=r['transport_steps'] for r in rows))
        if not passed: raise RuntimeError('study count/bounds gate failed')
        manifest = dict(simulation=True, stage=stage, trials=len(rows), offline_runs=len(offline),
                        caches=len(SCENARIOS)*len(seeds), seeds=seeds, frozen_study=spec,
                        semantic_source_sha256=hashes, evidence_checks=evidence_checks,
                        smoke_gate_passed=stage=='smoke' and passed)
    manifest.update(resolved_simulation_config=resolved_config, map_input_sha256=map_hash,
                    configuration_sha256=hashlib.sha256(Path(config_path).read_bytes()).hexdigest())
    _write_json(output/'study_manifest.json', manifest)
    return manifest
