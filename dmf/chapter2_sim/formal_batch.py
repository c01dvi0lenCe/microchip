"""Versioned formal statistics, with independent seeds and streamed raw export.

Failed trials remain in the planned support. Conditional timing observations
are never imputed. This module does not change historical ``batch.METHODS``.
"""
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess

from .batch import (_bootstrap, _inputs, _json_safe, _manifest, _snapshot_geometry,
                    _wilson, _write_csv, _write_json)

METHODS = ('A', 'B', 'C', 'C_no_spatial', 'C_no_temporal', 'C_no_validity')
OFFLINE_METHODS = ('S1', 'S2', 'S3', 'S4', 'no_spatial', 'no_temporal', 'no_validity')
CONTINUOUS_METRICS = ('total_time_s', 'completion_time_s', 'confirmation_delay_s',
                      'retries', 'recoveries', 'recovery_resends', 'communication_retries',
                      'preparation_time_s', 'transport_execution_time_s')
COUNTERS = {'early_updates', 'issued_updates', 'retries', 'recoveries',
            'recovery_resends', 'communication_retries', 'pending_frames_at_termination'}


def _validate_metrics(row):
    """Reject invalid research inputs while preserving explicit missing values."""
    for field, value in row.items():
        if value is None:
            continue
        if field in COUNTERS or field.endswith(('_steps', '_frames', '_events', '_count')):
            if type(value) is not int or value < 0:
                raise ValueError(f'{field} must be an exact nonnegative integer or None')
        if field in CONTINUOUS_METRICS or field == 'execution_time_s':
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{field} must be finite and nonnegative or None')
    if row.get('path_complete') is not None and type(row['path_complete']) is not bool:
        raise ValueError('path_complete must be boolean or None')
    for smaller, larger in (
            ('early_updates', 'confirmed_steps'), ('confirmed_steps', 'transport_steps'),
            ('issued_updates', 'transport_steps'), ('reference_arrived_steps', 'transport_steps'),
            ('correct_confirmed_steps', 'confirmed_steps'),
            ('correct_confirmed_steps', 'reference_arrived_steps')):
        if row.get(smaller) is not None and row.get(larger) is not None and row[smaller] > row[larger]:
            raise ValueError(f'{smaller} cannot exceed {larger}')
    if all(row.get(k) is not None for k in ('correct_confirmed_steps', 'early_updates', 'confirmed_steps')):
        if row['correct_confirmed_steps'] + row['early_updates'] > row['confirmed_steps']:
            raise ValueError('Correct and early updates cannot exceed issued confirmations')


def _checked(rows, methods, simulation_only):
    rows = [dict(row) for row in rows]
    if not rows:
        raise ValueError('At least one trial is required')
    seen, versions, version_owners = set(), {}, {}
    for row in rows:
        _validate_metrics(row)
        identity = (row['scenario'], row['method'], row['seed'])
        if identity in seen:
            raise ValueError(f'Duplicate scenario/method/seed: {identity}')
        seen.add(identity)
        if row['method'] not in methods:
            raise ValueError('Unknown versioned method')
        if simulation_only and row.get('simulation') is not True:
            raise ValueError('Formal closed-loop trials require simulation=True')
        if type(row.get('simulation')) is not bool:
            raise ValueError('Trials must explicitly declare simulation scope')
        version = row.get('method_version')
        if not isinstance(version, str) or not version:
            raise ValueError('Explicit method_version is required')
        method = row['method']
        if method in versions and versions[method] != version:
            raise ValueError('Method version collision')
        if version in version_owners and version_owners[version] != method:
            raise ValueError('One version cannot label distinct methods')
        versions[method], version_owners[version] = version, method
    return sorted(rows, key=lambda r: (str(r['scenario']), r['method'], r['seed']))


def _sum_known(rows, field):
    """Partial support is unknown, not an assumed zero count."""
    values = [r.get(field) for r in rows]
    return sum(values) if all(v is not None for v in values) else None


def _ratio(rows, numerator, denominator):
    n, d = _sum_known(rows, numerator), _sum_known(rows, denominator)
    return n / d if n is not None and d else None


def _summary(trials, methods, simulation_only, bootstrap_repeats):
    if type(bootstrap_repeats) is not int or bootstrap_repeats < 1:
        raise ValueError('bootstrap_repeats must be a positive integer')
    groups = defaultdict(list)
    for row in _checked(trials, methods, simulation_only):
        groups[(row['scenario'], row['method'], row['simulation'])].append(row)
    summaries = []
    for (scenario, method, simulation), rows in sorted(groups.items()):
        key = f'formal:{scenario}:{method}:{simulation}'
        count = len(rows)
        # A missing completion outcome remains an unsuccessful planned trial.
        completed = sum(r.get('path_complete') is True for r in rows)
        summary = dict(simulation=simulation, scenario=scenario, method=method,
                       method_version=rows[0]['method_version'], n_trials=count, n_seeds=count,
                       path_complete_count=completed, path_complete_rate=completed/count,
                       path_complete_missing_trials=sum(r.get('path_complete') is None for r in rows),
                       path_complete_rate_ci_method='wilson_95', bootstrap_repeats=bootstrap_repeats,
                       independent_unit='seed', physical_timing_validated=False)
        summary['path_complete_rate_ci_low'], summary['path_complete_rate_ci_high'] = _wilson(completed, count)
        counts = {'transport_steps', 'early_updates', 'confirmed_steps', 'reference_arrived_steps',
                  'correct_confirmed_steps', 'delay_observed_steps', 'delay_missing_steps',
                  'delay_censored_steps', 'delay_no_arrival_steps', 'delay_unattempted_steps',
                  'unknown_frames', 'missing_mask_frames', 'total_frames',
                  'captured_frames', 'pending_frames_at_termination'}
        # Preserve externally evaluated uncertainty categories without inventing
        # absent categories in older schemas.
        counts.update(k for r in rows for k in r
                      if k.endswith(('_steps', '_frames', '_events')))
        for field in sorted(counts):
            summary[field] = _sum_known(rows, field)
            summary[field+'_missing_trials'] = sum(r.get(field) is None for r in rows)
        summary['issued_updates'] = summary['confirmed_steps']
        for metric, numerator, denominator in (
                ('early_update_rate', 'early_updates', 'transport_steps'),
                ('early_update_rate_per_issued_update', 'early_updates', 'confirmed_steps'),
                ('arrival_confirmation_recall', 'correct_confirmed_steps', 'reference_arrived_steps')):
            statistic = lambda sample, n=numerator, d=denominator: _ratio(sample, n, d)
            summary[metric] = statistic(rows)
            summary[metric+'_ci_low'], summary[metric+'_ci_high'] = (
                _bootstrap(rows, statistic, bootstrap_repeats, key+':'+metric)
                if summary[metric] is not None else (None, None))
            summary[metric+'_ci_method'] = 'seed_cluster_bootstrap_ratio'
        summary['arrival_confirmation_recall_planned_denominator'] = summary['transport_steps']
        for metric in CONTINUOUS_METRICS:
            values = [float(r[metric]) for r in rows if r.get(metric) is not None
                      and (metric != 'completion_time_s' or r.get('path_complete') is True)]
            summary[metric+'_mean'] = statistics.fmean(values) if values else None
            summary[metric+'_n'] = len(values)
            summary[metric+'_missing_trials'] = count-len(values)
            summary[metric+'_ci_low'], summary[metric+'_ci_high'] = _bootstrap(
                values, statistics.fmean, bootstrap_repeats, key+':'+metric)
            summary[metric+'_ci_method'] = 'seed_bootstrap_mean'
        summary['total_time_s_estimand'] = 'all_planned_trials_execution_time'
        summary['completion_time_s_estimand'] = 'conditional_on_path_complete'
        summary['confirmation_delay_s_estimand'] = 'mean_of_observed_seed_means_conditional_on_confirmation'
        summary['confirmation_delay_s_missing_steps'] = summary['delay_missing_steps']
        summary['confirmation_delay_s_censored_steps'] = summary['delay_censored_steps']
        summary['confirmation_delay_s_no_arrival_steps'] = summary['delay_no_arrival_steps']
        summary['confirmation_delay_s_unattempted_steps'] = summary['delay_unattempted_steps']
        summary['rate_note'] = ('route recognition completion, not physical control success' if not simulation_only
                                else 'synthetic causal simulation, not physical validation')
        summaries.append(summary)
    return summaries


def summarize_trials(rows, bootstrap_repeats=2000):
    return _summary(rows, METHODS, True, bootstrap_repeats)


def summarize_offline(rows, bootstrap_repeats=2000):
    rows = list(rows)
    for row in rows:
        if row.get('method_version') != f"{row.get('method')}_mask_cache_v1":
            raise ValueError('Offline rows require explicit mask-cache method versions')
    return _summary(rows, OFFLINE_METHODS, False, bootstrap_repeats)


def paired_differences(rows, bootstrap_repeats=2000):
    """Matched-seed differences; conditional missing pairs are counted."""
    checked = _checked(rows, METHODS, True)
    grouped = defaultdict(dict)
    for row in checked:
        grouped[row['scenario']][row['seed'], row['method']] = row
    output = []
    for scenario, indexed in sorted(grouped.items()):
        seeds = sorted({seed for seed, _ in indexed})
        for later, earlier in (('C','A'), ('C','B'), ('B','A'),
                               ('C_no_spatial','C'), ('C_no_temporal','C'), ('C_no_validity','C')):
            for metric in CONTINUOUS_METRICS + ('path_complete', 'early_update_rate',
                                               'early_update_rate_per_issued_update', 'arrival_confirmation_recall'):
                differences = []
                matched = 0
                for seed in seeds:
                    a, b = indexed.get((seed, later)), indexed.get((seed, earlier))
                    if a is None or b is None:
                        continue
                    matched += 1
                    def value(row):
                        ratios = {'early_update_rate': ('early_updates','transport_steps'),
                                  'early_update_rate_per_issued_update': ('early_updates','confirmed_steps'),
                                  'arrival_confirmation_recall': ('correct_confirmed_steps','reference_arrived_steps')}
                        if metric in ratios:
                            return _ratio([row], *ratios[metric])
                        if metric == 'completion_time_s' and row.get('path_complete') is not True:
                            return None
                        return row.get(metric)
                    left, right = value(a), value(b)
                    if left is not None and right is not None:
                        differences.append(float(left)-float(right))
                comparison = later+'-'+earlier
                low, high = _bootstrap(differences, statistics.fmean, bootstrap_repeats,
                                       f'formal_paired:{scenario}:{comparison}:{metric}')
                output.append(dict(simulation=True, scenario=scenario, comparison=comparison, metric=metric,
                    n_pairs=len(differences), matched_seed_pairs=matched, missing_pairs=len(seeds)-len(differences),
                    unmatched_seed_pairs=len(seeds)-matched, conditional_missing_pairs=matched-len(differences),
                    mean_difference=statistics.fmean(differences) if differences else None,
                    ci_low=low, ci_high=high, ci_method='paired_seed_bootstrap_mean',
                    bootstrap_repeats=bootstrap_repeats, estimand='mean_within_seed_difference'))
    return output


class _RawSpool:
    """JSONL first pass discovers union headers; CSV second pass is bounded."""
    def __init__(self, output, name):
        self.path = output / ('.'+name+'.jsonl')
        self.destination = output / (name+'.csv')
        self.keys = {}
        self.handle = self.path.open('x', encoding='utf-8')

    def append(self, rows, labels):
        for raw in rows:
            row = _json_safe(dict(raw, **labels))
            self.keys.update(dict.fromkeys(row))
            self.handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
        self.handle.flush()

    def finish(self):
        self.handle.close()
        with self.destination.open('x', encoding='utf-8', newline='') as target, self.path.open(encoding='utf-8') as source:
            writer = csv.DictWriter(target, fieldnames=list(self.keys) or ['simulation','scenario','seed','method'])
            writer.writeheader()
            for line in source:
                row = json.loads(line)
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else v
                                 for k,v in row.items()})
        self.path.unlink()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run_formal_batch(cfg, scenarios, seeds, output, methods=METHODS, bootstrap_repeats=2000):
    """Return metric rows, retaining raw rows only for the current trial."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite formal output: {output}')
    scenarios, seeds = _inputs(scenarios, seeds)
    methods = list(methods)
    from .config import SCENARIOS
    if any(scene not in SCENARIOS for scene in scenarios):
        raise ValueError('Unknown formal scenario')
    if not methods or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods):
        raise ValueError('Methods must be unique nonempty formal labels')
    if any(type(seed) is not int for seed in seeds):
        raise ValueError('Seeds must be integers')
    if type(bootstrap_repeats) is not int or bootstrap_repeats < 1:
        raise ValueError('bootstrap_repeats must be a positive integer')
    from .formal_runner import run_formal_trial
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output/'config_snapshot.json', dict(simulation=True, config=_json_safe(cfg)))
    _snapshot_geometry(cfg, output)
    spools = {name: _RawSpool(output,name) for name in ('frames','truth','events')}
    trials = []
    try:
        for scenario in scenarios:
            for seed in seeds:
                for method in methods:
                    base = method.split('_',1)[0]
                    ablation = method[2:] if method.startswith('C_') else 'full'
                    result = run_formal_trial(cfg, scenario, seed, method=base, ablation=ablation)
                    source_version = result.metrics['method_version']
                    version = source_version + ('__formal_full' if base in ('A','B') else '__'+ablation)
                    labels = dict(simulation=True, scenario=scenario, seed=seed, method=method,
                                  base_method=base, method_version=version, ablation=ablation,
                                  coordinate_unit='pitch', clock_domain='simulation')
                    missing_reasons = {'CAMERA_DROPPED', 'NO_MASK'}
                    raw_counts = dict(total_frames=len(result.frames),
                        unknown_frames=(sum(frame['state'] == 'Unknown' for frame in result.frames)
                                        if all('state' in frame for frame in result.frames) else None),
                        missing_mask_frames=(sum(frame['reason'] in missing_reasons for frame in result.frames)
                                             if all('reason' in frame for frame in result.frames) else None))
                    trials.append(dict(result.metrics, **labels, **raw_counts))
                    for name, spool in spools.items():
                        spool.append(getattr(result,name), labels)
                    del result
        summary = summarize_trials(trials, bootstrap_repeats)
        for spool in spools.values():
            spool.finish()
    finally:
        for spool in spools.values():
            spool.handle.close()
    _write_csv(output/'trials.csv',trials)
    _write_csv(output/'summary.csv',summary)
    _write_csv(output/'paired_differences.csv',paired_differences(trials,bootstrap_repeats))
    _write_json(output/'summary.json',dict(simulation=True, groups=summary))
    manifest = _manifest(cfg,scenarios,seeds,output,bootstrap_repeats,'formal_comparison')
    root = Path(__file__).resolve().parents[2]
    sources = [p for directory in ('dmf/chapter2_sim','dmf/experiment','dmf/vision')
               for p in (root/directory).glob('*.py')]
    sources.append(root/'dmf/layout.py')
    manifest['source_sha256'].update({p.relative_to(root).as_posix():_sha256(p) for p in sources})
    try:
        dirty = subprocess.run(['git','status','--porcelain'],cwd=root,capture_output=True,
                               text=True,timeout=5,check=False)
        manifest['git_dirty'] = bool(dirty.stdout) if dirty.returncode == 0 else None
        manifest['git_status_porcelain'] = dirty.stdout.splitlines() if dirty.returncode == 0 else None
    except (OSError,subprocess.TimeoutExpired):
        manifest['git_dirty'], manifest['git_status_porcelain'] = None, None
    manifest.update(methods=methods, method_versions={r['method']:r['method_version'] for r in trials},
                    units=dict(length='pitch',time='s',velocity='pitch/s',clock_domain='simulation'),
                    independent_truth=dict(source='simulation_physics',independent_of_control_thresholds=True,
                        radius_pitch=cfg.truth_radius,max_speed_pitch_s=cfg.truth_max_speed,dwell_s=cfg.truth_dwell_s),
                    raw_export='per-trial JSONL spool, union-header CSV second pass',
                    config_sha256=_sha256(output/'config_snapshot.json'))
    manifest['output_sha256'] = {p.name:_sha256(p) for p in sorted(output.iterdir()) if p.is_file()}
    _write_json(output/'manifest.json',manifest)
    return trials
