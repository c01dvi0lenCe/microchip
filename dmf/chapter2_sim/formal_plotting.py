"""SIMULATION figures drawn only from persisted study CSV, never new samples."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams.update({'svg.fonttype': 'none', 'pdf.fonttype': 42, 'font.size': 7, 'axes.spines.top': False,
                     'axes.spines.right': False, 'legend.frameon': False})

from .config import SCENARIOS

COLORS = ('#767676', '#42949E', '#0F4D92', '#9A4D8E', '#B64342', '#AD8A45', '#4D4D4D')
width_mm = 183


def _read(path):
    with Path(path).open(encoding='utf-8', newline='') as handle: return list(csv.DictReader(handle))


def _number(value):
    return float(value) if value not in (None, '', 'None') else np.nan


def load_sensitivity_rows(directory, seeds):
    directory = Path(directory)
    paths = sorted(directory.glob('eta_*_duration_*/summary.csv'))
    if len(paths) != 9: raise ValueError('all nine prespecified sensitivity conditions are required')
    if len(seeds) != 20 or len(set(seeds)) != 20: raise ValueError('20 paired sensitivity seeds required')
    parent = json.loads((directory/'study_manifest.json').read_text(encoding='utf-8'))
    if parent.get('stage') != 'sensitivity' or parent.get('trials') != 180 or parent.get('seeds') != seeds:
        raise ValueError('incomplete sensitivity study manifest')
    all_rows = []; conditions = set()
    for path in paths:
        eta, duration = map(float, path.parent.name.removeprefix('eta_').split('_duration_'))
        if (eta, duration) in conditions: raise ValueError('duplicate sensitivity condition')
        conditions.add((eta, duration))
        rows = _read(path)
        manifest = json.loads((path.parent/'manifest.json').read_text(encoding='utf-8'))
        cfg = json.loads((path.parent/'config_snapshot.json').read_text(encoding='utf-8'))['config']
        if (len(rows) != 1 or rows[0]['method'] != 'C' or rows[0]['scenario'] != 'jitter'
            or rows[0]['n_trials'] != '20' or manifest['seeds'] != seeds
            or cfg['arrival_coverage'] != eta or cfg['stable_duration_s'] != duration):
            raise ValueError('sensitivity metadata/data mismatch')
        all_rows.append(dict(rows[0], eta=eta, duration=duration))
    if conditions != {(eta, duration) for eta in (.75,.85,.95) for duration in (.25,.4,.6)}:
        raise ValueError('sensitivity grid differs from frozen plan')
    return all_rows


def render_figures(study, output, *, sensitivity=None, qa_scripts=None):
    study = Path(study); output = Path(output)
    if output.exists(): raise FileExistsError(output)
    summaries = _read(study/'closed_loop'/'summary.csv')
    offline = _read(study/'offline_summary.csv')
    manifest = json.loads((study/'study_manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('stage') != 'formal' or manifest.get('trials') != 840 or manifest.get('offline_runs') != 980
        or manifest.get('seeds') != list(range(261000,261020))):
        raise ValueError('plots require the completed prespecified formal study')
    sensitivity_rows = load_sensitivity_rows(sensitivity, manifest['seeds']) if sensitivity else None
    if qa_scripts is None: raise ValueError('provide the installed scientific-figure QA scripts directory')
    spec = importlib.util.spec_from_file_location('chapter2_alignment_audit', Path(qa_scripts)/'audit_panel_alignment.py')
    audit = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = audit; spec.loader.exec_module(audit)
    output.mkdir(parents=True)
    captions = []

    def save(fig, name, caption):
        fig.canvas.draw()
        audit.require_matplotlib_panel_alignment(fig, json_out=str(output/f'{name}.alignment.json'),
                                                 tolerance_pt=1.5, strict=True)
        fig.savefig(output/f'{name}.svg')
        fig.savefig(output/f'{name}.pdf')
        fig.savefig(output/f'{name}.png', dpi=600)
        plt.close(fig); captions.append(dict(figure=name, caption=caption, simulation=True,
            study_n_seeds_per_scene=20, displayed_seed_count=1 if name.startswith('prespecified_') else 20,
            method_versions={r['method']:r['method_version'] for r in summaries+offline}))

    def comparison(data, metric, name, label, *, subset=None):
        methods = list(dict.fromkeys(r['method'] for r in data))
        if subset: methods = [m for m in subset if m in methods]
        fig, ax = plt.subplots(figsize=(width_mm/25.4, 125/25.4))
        fig.subplots_adjust(left=.18, right=.97, bottom=.16, top=.81)
        for j, method in enumerate(methods):
            selected = {r['scenario']: r for r in data if r['method']==method}
            y = np.arange(len(SCENARIOS))+(j-(len(methods)-1)/2)*.1
            center = np.array([_number(selected[s].get(metric)) for s in SCENARIOS])
            lo = np.array([_number(selected[s].get(metric+'_ci_low')) for s in SCENARIOS])
            hi = np.array([_number(selected[s].get(metric+'_ci_high')) for s in SCENARIOS])
            # Means use *_mean but their interval keys conventionally omit mean.
            if metric.endswith('_mean'):
                lo = np.array([_number(selected[s].get(metric[:-5]+'_ci_low')) for s in SCENARIOS])
                hi = np.array([_number(selected[s].get(metric[:-5]+'_ci_high')) for s in SCENARIOS])
            finite = np.isfinite(center)
            ax.errorbar(center[finite], y[finite], xerr=[np.maximum(0., center[finite]-lo[finite]),
                         np.maximum(0., hi[finite]-center[finite])], fmt='o', ms=3, lw=.8,
                         color=COLORS[j % len(COLORS)], label={'A':'A_fixed','B':'B_single','C':'C_formal'}.get(method,method))
        ax.set_yticks(range(len(SCENARIOS)), SCENARIOS); ax.invert_yaxis(); ax.set_xlabel(label)
        ax.set_title('SIMULATION — '+name.replace('_', ' '), pad=38)
        ax.legend(loc='lower center', bbox_to_anchor=(.5, 1.01), ncol=3, fontsize=6)
        save(fig, name, 'All seven prespecified scenes; points and 95% CI. Independent unit: seed. '
             'Path rates: Wilson; other estimates: 2000 seed-cluster bootstrap. Missing values omitted as marks, not imputed; '
             'all denominators and missing counts remain in CSV. Completion time and confirmation delay are conditional.')

    for metric, label in (
        ('path_complete_rate', 'Path completion rate / all trials'),
        ('early_update_rate', 'Early updates / all planned steps'),
        ('arrival_confirmation_recall', 'Correct confirmations / known physical arrivals'),
        ('confirmation_delay_s_mean', 'Observed confirmation delay (s; conditional)'),
        ('completion_time_s_mean', 'Successful completion time (s; conditional)'),
        ('total_time_s_mean', 'Execution time (s; all trials)'),
        ('retries_mean', 'Transport Retry count / trial'),
        ('recoveries_mean', 'Recovery count / trial')):
        comparison(summaries, metric, 'control_'+metric, label)
    for metric, label in (('path_complete_rate', 'Route recognition completion / all trials'),
                           ('early_update_rate', 'Early/false events / all planned steps'),
                           ('arrival_confirmation_recall', 'Confirmed arrivals / known arrival events')):
        comparison(offline, metric, 'offline_'+metric, label)

    paired = _read(study/'closed_loop'/'paired_differences.csv')
    selected = [r for r in paired if r['metric']=='path_complete' and r['comparison'] in ('C-A', 'C-B')]
    fig, ax = plt.subplots(figsize=(183/25.4, 110/25.4)); fig.subplots_adjust(left=.18, right=.97, bottom=.16, top=.78)
    for j, contrast in enumerate(('C-A', 'C-B')):
        group = {r['scenario']: r for r in selected if r['comparison']==contrast}
        mean = np.array([_number(group[s]['mean_difference']) for s in SCENARIOS])
        lo = np.array([_number(group[s]['ci_low']) for s in SCENARIOS]); hi = np.array([_number(group[s]['ci_high']) for s in SCENARIOS])
        ax.errorbar(mean, np.arange(7)+j*.15, xerr=[np.maximum(0.,mean-lo), np.maximum(0.,hi-mean)],
                    fmt='o', ms=3, color=COLORS[j+1], label=contrast.replace('C','C_formal'))
    ax.axvline(0, ls=':', lw=.7, color='#767676'); ax.set_yticks(range(7), SCENARIOS); ax.invert_yaxis()
    ax.set_xlabel('Within-seed path completion difference'); ax.set_title('SIMULATION — paired control differences', pad=27)
    ax.legend(loc='lower center', bbox_to_anchor=(.5, 1.01), ncol=2)
    save(fig, 'paired_path_difference', 'Mean within-seed difference and paired seed-bootstrap95% CI; all scenes retained. No significance inference.')

    # Preselected illustrative trial, never selected by best measured performance.
    with (study/'closed_loop'/'truth.csv').open(encoding='utf-8', newline='') as handle:
        truth = [r for r in csv.DictReader(handle) if r['scenario']=='normal' and r['seed']=='261000' and r['method']=='C']
    with (study/'closed_loop'/'frames.csv').open(encoding='utf-8', newline='') as handle:
        frames = [r for r in csv.DictReader(handle) if r['scenario']=='normal' and r['seed']=='261000' and r['method']=='C']
    if truth and frames:
        fig, ax = plt.subplots(figsize=(120/25.4, 100/25.4)); fig.subplots_adjust(left=.18, right=.96, bottom=.18, top=.85)
        snapshot = json.loads((study/'closed_loop'/'electrode_map_snapshot.json').read_text(encoding='utf-8'))
        config = json.loads((study/'closed_loop'/'config_snapshot.json').read_text(encoding='utf-8'))['config']
        for electrode in config['route']:
            polygon = np.asarray(snapshot['polygons'][str(electrode)])
            ring = np.vstack((polygon, polygon[0]))
            ax.plot(ring[:,0], ring[:,1], color='#CFCECE', lw=.6)
        ax.plot([_number(r['x']) for r in truth], [_number(r['y']) for r in truth], color=COLORS[2], lw=1.)
        ax.set(xlabel='x (pitch)', ylabel='y (pitch)', title='SIMULATION — normal / seed261000 / C_formal')
        ax.set_aspect('equal', adjustable='datalim')
        save(fig, 'prespecified_trajectory', 'Independent physical position trajectory of prespecified normal/261000/C_formal; normalized pitch, not mm. Map display cropped to the manually prescribed route, not a full-array image.')
        states = ['Unknown', 'Stationary', 'Moving', 'Partial', 'Arrived', 'Deviation']
        fig, ax = plt.subplots(figsize=(183/25.4, 80/25.4)); fig.subplots_adjust(left=.14, right=.97, bottom=.23, top=.82)
        ax.scatter([_number(r['exposure_s']) for r in frames], [states.index(r['state']) for r in frames], s=4, color=COLORS[2])
        ax.set_yticks(range(6), states); ax.set_xlabel('Exposure end (simulation s)')
        ax.set_title('SIMULATION — formal five-state sequence, including Unknown')
        save(fig, 'prespecified_state_sequence', 'Same prespecified trial. Unknown and dropped observations retained; no fabricated labels for S1–S3.')

    if sensitivity:
        all_rows = sensitivity_rows
        for metric, label in (('path_complete_rate', 'Path completion rate'), ('early_update_rate', 'Early updates / all planned steps')):
            fig, ax = plt.subplots(figsize=(140/25.4, 95/25.4)); fig.subplots_adjust(left=.17, right=.96, bottom=.19, top=.76)
            for j, duration in enumerate(sorted({r['duration'] for r in all_rows})):
                group = sorted([r for r in all_rows if r['duration']==duration], key=lambda r:r['eta'])
                x = [r['eta'] for r in group]; mean = np.array([_number(r[metric]) for r in group])
                lo = np.array([_number(r[metric+'_ci_low']) for r in group]); hi = np.array([_number(r[metric+'_ci_high']) for r in group])
                ax.errorbar(x, mean, yerr=[np.maximum(0.,mean-lo),np.maximum(0.,hi-mean)], fmt='o-', ms=3,
                            lw=.8, color=COLORS[j], label=f'{duration:g} s')
            ax.set(xlabel='Coverage threshold (shared gates)', ylabel=label)
            ax.set_title('SIMULATION — jitter sensitivity', pad=27)
            ax.legend(loc='lower center', bbox_to_anchor=(.5,1.01), ncol=3, fontsize=6)
            save(fig, 'sensitivity_'+metric, 'All prespecified nine conditions and20 paired seeds.95% CI; independent physical reference unchanged. Source preparation and Recovery gates also vary: this is not an isolated target-only threshold scan.')
    (output/'captions.json').write_text(json.dumps(captions, indent=2), encoding='utf-8')
    return captions


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('study'); p.add_argument('output')
    p.add_argument('--sensitivity'); p.add_argument('--qa-scripts', required=True)
    args = p.parse_args(); render_figures(args.study, args.output, sensitivity=args.sensitivity, qa_scripts=args.qa_scripts)


if __name__ == '__main__': main()
