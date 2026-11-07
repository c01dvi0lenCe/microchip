"""Create an immutable local provenance bundle only after every study stage."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8') as handle: return list(csv.DictReader(handle))


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()


def validate_figure_set(captions):
    expected = {'control_'+metric for metric in ('path_complete_rate','early_update_rate','arrival_confirmation_recall',
                'confirmation_delay_s_mean','completion_time_s_mean','total_time_s_mean','retries_mean','recoveries_mean')}
    expected.update('offline_'+metric for metric in ('path_complete_rate','early_update_rate','arrival_confirmation_recall'))
    expected.update(('paired_path_difference','prespecified_trajectory','prespecified_state_sequence',
                     'sensitivity_path_complete_rate','sensitivity_early_update_rate'))
    names = [item.get('figure') for item in captions]
    if len(names) != len(expected) or set(names) != expected or any(item.get('simulation') is not True for item in captions):
        raise ValueError('all 16 unique prespecified simulation figures are required')


def validate_stage_provenance(stages, root):
    root = Path(root).resolve(); smoke = stages['smoke']
    if smoke.get('smoke_gate_passed') is not True: raise ValueError('smoke gate did not pass')
    for key in ('semantic_source_sha256','configuration_sha256','resolved_simulation_config','map_input_sha256','frozen_study'):
        if any(key not in stage or stage[key] != smoke[key] for stage in stages.values()):
            raise ValueError('stage provenance does not describe one frozen study')
    hashes = smoke['semantic_source_sha256']
    if not isinstance(hashes, dict) or not hashes: raise ValueError('missing executed source hashes')
    for relative, expected in hashes.items():
        path = (root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path) != expected:
            raise ValueError(f'source changed since execution: {relative}')
    if sha256(root/'configs/chapter2_formal_simulation.yaml') != smoke['configuration_sha256']:
        raise ValueError('configuration changed since execution')
    map_path = smoke['resolved_simulation_config'].get('map_path')
    if map_path and sha256(Path(map_path)) != smoke['map_input_sha256']:
        raise ValueError('supplied map changed since execution')


def validate_qa_verdicts(alignment, collision):
    if alignment.get('verdict') not in {'PASS','NOT APPLICABLE'} or collision.get('verdict') != 'PASS':
        raise ValueError('figure QA has not passed; resolve or document findings before delivery')


def verify_batch_outputs(directory, expected_trials, *, expected_scenarios=None, expected_seeds=None,
                         expected_methods=None, expected_config=None, expected_source_hashes=None):
    directory = Path(directory).resolve(); manifest = read_json(directory/'manifest.json')
    required = {'config_snapshot.json','electrode_map_snapshot.json','trials.csv','frames.csv','truth.csv',
                'events.csv','summary.csv','summary.json','paired_differences.csv'}
    hashes = manifest.get('output_sha256', {})
    if manifest.get('simulation') is not True or not required <= hashes.keys():
        raise ValueError('missing required raw output digests')
    for name, expected in hashes.items():
        path = (directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or sha256(path) != expected:
            raise ValueError(f'raw output missing or changed: {name}')
    for key, expected in (('scenarios',expected_scenarios),('seeds',expected_seeds),('methods',expected_methods)):
        if expected is not None and manifest.get(key) != expected:
            raise ValueError(f'child batch {key} do not match frozen parent')
    if expected_config is not None and read_json(directory/'config_snapshot.json')['config'] != expected_config:
        raise ValueError('child batch configuration does not match frozen parent')
    if expected_source_hashes is not None and any(manifest.get('source_sha256',{}).get(k) != v for k,v in expected_source_hashes.items()):
        raise ValueError('child batch source provenance does not match frozen parent')
    rows = read_csv(directory/'trials.csv')
    keys = [(r['scenario'],int(r['seed']),r['method']) for r in rows]
    expected_keys = {(scenario,seed,method) for scenario in manifest['scenarios']
                     for seed in manifest['seeds'] for method in manifest['methods']}
    if (len(rows) != expected_trials or len(set(keys)) != len(keys) or set(keys) != expected_keys
        or any(r.get('simulation') != 'True' for r in rows)):
        raise ValueError('raw output trial identities/counts are incomplete')


def _verify_csv_matches_json(path, rows):
    expected = [{key: '' if value is None else str(value) for key,value in row.items()} for row in rows]
    actual = read_csv(path)
    if actual != expected: raise ValueError(f'CSV does not match persisted prediction JSON: {path.name}')


def expected_offline_row(scenario,seed,predicted,score):
    count=score['counts']; denominator=score['denominators']
    delays=[s['delay_upper_s'] for s in score['per_step'] if s['outcome']=='confirmed_after_arrival']
    return dict(simulation=True,scenario=scenario,seed=seed,method=predicted['variant'],
        method_version=predicted['method_version'],input_sha256=predicted['input_sha256'],
        transport_steps=denominator['eligible_steps'],path_complete=count['completed_paths']==1,
        early_updates=count['early_events']+count['false_events'],reference_arrived_steps=denominator['known_arrival_steps'],
        correct_confirmed_steps=count['confirmed_arrivals'],confirmed_steps=count['predicted_steps'],
        missing_prediction_steps=count['missing_prediction_steps'],
        unknown_frames=sum(f['state']=='Unknown' for f in predicted['frames']),
        missing_mask_frames=sum(not f['mask_available'] for f in predicted['frames']),
        invalid_frames=sum(f['observation_quality']=='invalid' for f in predicted['frames']),
        ambiguous_events=count['ambiguous_timing_events'],delay_censored_steps=count['missing_arrival_events'],
        confirmation_delay_s=sum(delays)/len(delays) if delays else None,delay_observed_steps=len(delays),
        delay_missing_steps=denominator['eligible_steps']-len(delays),
        **{k:count[k] for k in ('missing_arrival_events','missing_reference_steps','right_censored_reference_steps',
            'occluded_reference_steps','uncertain_reference_steps','unassessable_events','duplicate_events',
            'ambiguous_timing_events','early_events','false_events')})


def verify_offline_trial_row(row,scenario,seed,predicted,score):
    expected=expected_offline_row(scenario,seed,predicted,score)
    canonical={k:'' if v is None else str(v) for k,v in expected.items()}
    if row != canonical: raise ValueError('offline trial metrics contradict recomputed evaluation or prediction frames')


def verify_offline_outputs(directory, stage, root):
    """Audit cached bytes and recompute evaluation only; never rerun prediction."""
    import sys
    sys.path.insert(0, str(root))
    from dmf.experiment.mask_cache import load_cache
    from dmf.vision.event_evaluation import evaluate_simulation_events
    from dmf.chapter2_sim.formal_batch import summarize_offline
    directory = Path(directory); variants = stage['frozen_study']['offline_variants']
    expected_keys = {(scenario,seed,method) for scenario in stage['frozen_study']['scenarios']
                     for seed in stage['seeds'] for method in variants}
    trial_rows = read_csv(directory/'offline_trials.csv')
    indexed = {(r['scenario'],int(r['seed']),r['method']):r for r in trial_rows}
    if len(trial_rows) != stage['offline_runs'] or len(indexed) != len(trial_rows) or set(indexed) != expected_keys:
        raise ValueError('offline trial identities/counts are incomplete')
    for scenario in stage['frozen_study']['scenarios']:
        for seed in stage['seeds']:
            trial = directory/'cache_trials'/f'{scenario}_{seed}'
            cache = load_cache(trial/'inputs')
            refs = read_json(trial/'evaluation'/'references.json'); manifest = read_json(trial/'evaluation'/'trial_manifest.json')
            if len(manifest) != 1 or manifest[0].get('input_sha256') != cache['input_sha256']:
                raise ValueError('reference/cache binding changed')
            identity = {k:manifest[0][k] for k in ('trial_id','task_id','clock_domain')}
            for variant in variants:
                destination = directory/'predictions'/f'{scenario}_{seed}'/variant
                predicted = read_json(destination/'prediction.json')
                if (predicted.get('variant') != variant or predicted.get('input_sha256') != cache['input_sha256']
                    or predicted.get('simulation') is not True or predicted.get('clock_domain') != 'simulation'):
                    raise ValueError('prediction/cache binding changed')
                _verify_csv_matches_json(destination/'frames.csv', predicted['frames'])
                _verify_csv_matches_json(destination/'events.csv', predicted['events'])
                if any(e.get('clock_domain') != identity['clock_domain'] for e in predicted['events']):
                    raise ValueError('prediction event clock changed')
                score = evaluate_simulation_events([dict(e,**identity) for e in predicted['events']],refs,manifest)
                saved = read_json(destination/'evaluation.json')
                if any(score[k] != saved.get(k) for k in ('counts','denominators','rates','per_step','per_trial')):
                    raise ValueError('saved evaluation changed')
                verify_offline_trial_row(indexed[scenario,seed,variant],scenario,seed,predicted,score)
            del cache
    typed = []
    for row in trial_rows:
        typed.append({key: (value if key in {'scenario','method','method_version','input_sha256'}
                       else value=='True' if key in {'simulation','path_complete'}
                       else None if value=='' else float(value) if key.endswith('_s') else int(value))
                      for key,value in row.items()})
    summary = summarize_offline(typed, bootstrap_repeats=stage['frozen_study']['bootstrap_repeats'])
    _verify_csv_matches_json(directory/'offline_summary.csv', summary)


def package_results(directory):
    directory = Path(directory).resolve(); destination = directory/'result_manifest.json'
    archive = directory/'algorithm_source_snapshot.zip'
    if destination.exists() or archive.exists(): raise FileExistsError('immutable result package already exists')
    stages = {}
    expected = dict(smoke=(126,147), formal=(840,980), sensitivity=(180,0))
    for name, (trials, offline) in expected.items():
        manifest = json.loads((directory/name/'study_manifest.json').read_text(encoding='utf-8'))
        if (manifest.get('simulation') is not True or manifest.get('stage') != name
            or manifest.get('trials') != trials or manifest.get('offline_runs') != offline):
            raise ValueError(f'incomplete {name} stage')
        stages[name] = manifest
    root = Path(__file__).resolve().parents[1]
    validate_stage_provenance(stages, root)
    for name in ('smoke','formal'):
        stage=stages[name]
        verify_batch_outputs(directory/name/'closed_loop', stage['trials'],
            expected_scenarios=stage['frozen_study']['scenarios'],expected_seeds=stage['seeds'],
            expected_methods=stage['frozen_study']['methods'],expected_config=stage['resolved_simulation_config'],
            expected_source_hashes=stage['semantic_source_sha256'])
        verify_offline_outputs(directory/name, stages[name], root)
    sensitivity_batches = list((directory/'sensitivity').glob('eta_*_duration_*'))
    if len(sensitivity_batches) != 9: raise ValueError('incomplete sensitivity raw outputs')
    stage=stages['sensitivity']; conditions=set()
    for batch in sensitivity_batches:
        eta,duration=map(float,batch.name.removeprefix('eta_').split('_duration_'))
        if (eta,duration) in conditions: raise ValueError('duplicate sensitivity condition')
        conditions.add((eta,duration))
        cfg=dict(stage['resolved_simulation_config'],arrival_coverage=eta,stable_duration_s=duration)
        verify_batch_outputs(batch,20,expected_scenarios=[stage['frozen_study']['sensitivity_scenario']],
            expected_seeds=stage['seeds'],expected_methods=['C'],expected_config=cfg,
            expected_source_hashes=stage['semantic_source_sha256'])
    if conditions != {(eta,duration) for eta in stage['frozen_study']['arrival_coverages']
                       for duration in stage['frozen_study']['stable_durations_s']}:
        raise ValueError('sensitivity conditions differ from frozen parent')
    captions = json.loads((directory/'figures'/'captions.json').read_text(encoding='utf-8'))
    validate_figure_set(captions)
    for item in captions:
        for suffix in ('.svg','.pdf','.png','.alignment.json','.collision-audit.json'):
            if not (directory/'figures'/(item['figure']+suffix)).is_file(): raise ValueError('incomplete figure/QA bundle')
        read = lambda suffix: json.loads((directory/'figures'/(item['figure']+suffix)).read_text(encoding='utf-8'))
        validate_qa_verdicts(read('.alignment.json'), read('.collision-audit.json'))
    sources = [p for folder in ('dmf/chapter2_sim','dmf/experiment','dmf/vision') for p in (root/folder).glob('*.py')]
    sources += [root/'dmf/layout.py', root/'run_chapter2_formal_simulation.py',
                root/'configs/chapter2_formal_simulation.yaml', Path(__file__).resolve(),
                root/'scripts/evaluate_chapter2_baselines.py']
    source_hashes = {p.relative_to(root).as_posix(): sha256(p) for p in sorted(set(sources))}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(sources)): bundle.write(path, path.relative_to(root).as_posix())
    outputs = {p.relative_to(directory).as_posix(): sha256(p) for p in sorted(directory.rglob('*')) if p.is_file()}
    head = subprocess.run(['git','rev-parse','HEAD'], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    result = dict(simulation=True, evidence_scope='synthetic causal algorithm simulation; not real video or hardware evidence',
                  stages=stages, source_sha256=source_hashes, git_head=head,
                  source_archive=archive.name, output_sha256=outputs,
                  physical_timing_validated=False, real_unet_accuracy_evaluated=False)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return dict(manifest=str(destination), stages={k: dict(trials=v['trials'],offline_runs=v['offline_runs']) for k,v in stages.items()},
                hashed_files=len(outputs), archived_sources=len(source_hashes))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('directory')
    print(json.dumps(package_results(parser.parse_args().directory), indent=2))
