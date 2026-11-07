"""Traceable Matplotlib figures of synthetic simulations, never camera results."""
import importlib.util
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
from matplotlib.path import Path as PlotPath
from matplotlib.transforms import Bbox
import numpy as np

from .geometry import SimulationMap

COLORS = {'A': '#7B8C96', 'B': '#B58C5B', 'C': '#477A9B'}
LABELS = {'A': 'A: Fixed time', 'B': 'B: Single frame', 'C': 'C: Event driven'}
MARKERS = {'A': 's', 'B': '^', 'C': 'o'}
SCENE_LABELS = {'normal': 'Normal', 'delayed': 'Delayed', 'partial_stall': 'Stall',
                'jitter': 'Jitter', 'dropout': 'Dropout', 'deviation': 'Deviation', 'failure': 'Failure'}


def _save(fig, name, output):
    fig.canvas.draw()
    qa = Path.home()/'.agents/skills/nature-figure/scripts/audit_panel_alignment.py'
    if qa.exists():
        spec = importlib.util.spec_from_file_location('chapter2_alignment_qa', qa)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.require_matplotlib_panel_alignment(fig, exclude_axes=[ax for ax in fig.axes if ax.get_label() == 'qa_colorbar'],
                                                   json_out=output/(name+'.alignment.json'),
                                                   strict=True)
    else:
        (output/(name+'.alignment.json')).write_text(json.dumps({
            'verdict': 'NOT AUDITABLE', 'reason': 'optional external alignment auditor unavailable'}), encoding='utf-8')
    paths = []
    for path in (output/f'{name}.png', output/f'{name}.pdf', output/f'{name}.svg'):
        fig.savefig(path, dpi=300, facecolor='white')
        paths.append(path)
    plt.close(fig)
    return paths


def _panel_labels(axes):
    for i, ax in enumerate(np.asarray(axes).reshape(-1)):
        ax.set_title(chr(97+i), loc='left', fontweight='bold', pad=10)


def plot_results(config, results, summary, sensitivity, output):
    """Plot supplied results without rerunning or selecting favourable seeds."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Arial', 'DejaVu Sans'],
                         'font.size': 9, 'axes.labelsize': 9, 'xtick.labelsize': 8,
                         'ytick.labelsize': 8, 'legend.fontsize': 8,
                         'pdf.fonttype': 42, 'svg.fonttype': 'none',
                         'axes.spines.right': False, 'axes.spines.top': False})
    paths = []
    geometry = SimulationMap(config)
    scenario = results[0].metrics['scenario']
    seed = results[0].metrics['seed']
    selected = [r for r in results if r.metrics['scenario'] == scenario and r.metrics['seed'] == seed]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    fig.subplots_adjust(left=.12, right=.96, bottom=.2, top=.88)
    bounds = Bbox.from_extents(*geometry.lower, *geometry.upper)
    for electrode, polygon in geometry.polygons.items():
        if (polygon.max(axis=0) >= geometry.lower).all() and (polygon.min(axis=0) <= geometry.upper).all():
            # Materialize clipping so PDF paths, not just their clip masks, stay
            # inside the map viewport (also makes geometry QA unambiguous).
            clipped = PlotPath(np.vstack([polygon, polygon[0]]), closed=True).clip_to_bbox(bounds)
            ax.add_patch(Polygon(clipped.vertices, facecolor='#EEF1F3', edgecolor='#BFC7CC', linewidth=.5))
    for r in selected:
        method = r.metrics['method']
        ax.plot([v['x'] for v in r.truth], [v['y'] for v in r.truth], color=COLORS[method],
                linestyle={'A': ':', 'B': '--', 'C': '-'}[method], linewidth=1.5, label=LABELS[method])
    centers = np.asarray([geometry.center(i) for i in config.route])
    ax.scatter(centers[:, 0], centers[:, 1], marker='x', color='#333333', s=35, zorder=10)
    ax.set(xlim=(geometry.lower[0], geometry.upper[0]), ylim=(geometry.lower[1], geometry.upper[1]),
           xlabel='x (electrode pitch)', ylabel='y (electrode pitch)',
           title=f'SIMULATION | {scenario} | seed {seed}')
    ax.invert_yaxis()
    ax.set_aspect('equal')
    fig.legend(loc='lower center', ncol=3, bbox_to_anchor=(.5, .015))
    paths += _save(fig, '01_trajectory_simulation', output)

    r = next((r for r in selected if r.metrics['method'] == 'C'), selected[-1])
    data = sorted((f for f in r.frames if f.get('processing_s') is not None), key=lambda f: f['processing_s'])
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7.4), sharex=True)
    fig.subplots_adjust(left=.17, right=.96, bottom=.1, top=.88, hspace=.48)
    states = ['Unknown', 'Stationary', 'Moving', 'Partial', 'Arrived', 'Deviation']
    t = [f['processing_s'] for f in data]
    axes[0].step(t, [states.index(f['state']) for f in data], where='post', color=COLORS['C'], linewidth=1)
    axes[0].set_yticks(range(6), states)
    axes[0].set_ylim(-.5, 5.5)
    for key, label, style in (('eta_target', 'Target / droplet area', '-'),
                              ('eta_source', 'Source / droplet area', '--'),
                              ('progress', 'Directed progress', ':')):
        axes[1].plot(t, [f.get(key, np.nan) for f in data], style, linewidth=1, label=label)
    axes[1].set_ylabel('Coverage / progress')
    axes[1].legend(loc='upper center', bbox_to_anchor=(.5, 1.25), ncol=3)
    actions = {'Start': 0, 'Resume': 0, 'Update': 1, 'Complete': 1, 'Retry': 2, 'Recovery': 3, 'Stop': 4}
    for event in r.events:
        if event['event'] in actions:
            axes[2].scatter(event['time_s'], actions[event['event']], s=24, color=COLORS['C'])
    axes[2].set_yticks(range(5), ['Activate', 'Update', 'Retry', 'Recovery', 'Stop'])
    axes[2].set_ylim(-.5, 4.5)
    axes[2].set_xlabel('Simulation decision time (s)')
    for ax in axes:
        ax.grid(alpha=.12)
    _panel_labels(axes)
    fig.suptitle(f'SIMULATION | C state and action timeline | {scenario} | seed {seed}', fontsize=10)
    paths += _save(fig, '02_state_timeline_simulation', output)

    scenarios = list(dict.fromkeys(row['scenario'] for row in summary))
    fields = [('path_complete_rate', 'Path completion rate'), ('early_update_rate', 'Early updates / planned steps'),
              ('confirmation_delay_s_mean', 'Confirmation delay (s)'), ('total_time_s_mean', 'Time to termination (s)'),
              ('retries_mean', 'Retry count'), ('recoveries_mean', 'Recovery count')]
    fig, axes = plt.subplots(3, 2, figsize=(7.2, 9.4))
    fig.subplots_adjust(left=.11, right=.97, bottom=.13, top=.9, hspace=.85, wspace=.42)
    for ax, (key, label) in zip(axes.flat, fields):
        for j, method in enumerate('ABC'):
            indexed = {s['scenario']: s for s in summary if s['method'] == method}
            values, lower, upper = [], [], []
            base = key[:-5] if key.endswith('_mean') else key
            for scene in scenarios:
                row = indexed.get(scene, {})
                value = row.get(key)
                values.append(np.nan if value is None else value)
                low, high = row.get(base+'_ci_low'), row.get(base+'_ci_high')
                lower.append(0 if value is None or low is None else max(0, value-low))
                upper.append(0 if value is None or high is None else max(0, high-value))
            x = np.arange(len(scenarios))+(j-1)*.22
            ax.errorbar(x, values, yerr=[lower, upper], fmt=MARKERS[method], markersize=3, capsize=2,
                        color=COLORS[method], linewidth=.8, label=LABELS[method])
        ax.set_xticks(range(len(scenarios)), [SCENE_LABELS.get(s, s) for s in scenarios], rotation=90, ha='right', va='center', rotation_mode='anchor')
        ax.set_ylabel(label)
        ax.set_ylim(bottom=0)
        ax.grid(axis='y', alpha=.15)
    _panel_labels(axes)
    sample_sizes = sorted({row['n_seeds'] for row in summary})
    fig.suptitle(f'SIMULATION | A/B/C | 95% confidence intervals | n={sample_sizes} seeds/group', fontsize=10)
    fig.legend(handles=[Line2D([], [], color=COLORS[m], marker=MARKERS[m], linestyle='', label=LABELS[m]) for m in 'ABC'],
               loc='lower center', ncol=3, bbox_to_anchor=(.5, .025))
    paths += _save(fig, '03_control_comparison_simulation', output)

    if sensitivity:
        coverages = sorted({row['arrival_coverage'] for row in sensitivity})
        durations = sorted({row['stable_duration_s'] for row in sensitivity})
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.8))
        fig.subplots_adjust(left=.1, right=.92, bottom=.19, top=.78, wspace=.48)
        for ax, key, label in zip(axes, ('path_complete_rate', 'early_update_rate'),
                                  ('Path completion', 'Early / planned steps')):
            matrix = np.full((len(durations), len(coverages)), np.nan)
            for row in sensitivity:
                matrix[durations.index(row['stable_duration_s']), coverages.index(row['arrival_coverage'])] = row[key]
            image = ax.imshow(matrix, vmin=0, vmax=1, cmap='Blues', origin='lower', aspect='auto')
            for row_index, col_index in np.ndindex(matrix.shape):
                value = matrix[row_index, col_index]
                if np.isfinite(value):
                    ax.text(col_index, row_index, f'{value:.0%}', ha='center', va='center',
                            color='white' if value > .6 else '#333333', fontsize=9)
            ax.set_xticks(range(len(coverages)), [str(c) for c in coverages])
            ax.set_yticks(range(len(durations)), [str(d) for d in durations])
            ax.set(xlabel='Target coverage threshold', ylabel='Stable duration (s)')
            ax.set_title(label, fontsize=9, pad=23)
        # Dedicated colorbar does not alter either comparable axes rectangle.
        bar_ax = fig.add_axes((.95, .19, .016, .59))
        bar_ax.set_label('qa_colorbar')
        fig.colorbar(image, cax=bar_ax)
        fig.suptitle('SIMULATION | C threshold sensitivity (fixed physical truth)', fontsize=10)
        # Colorbar is not a comparable evidence panel.
        bar_ax.set_in_layout(False)
        paths += _save(fig, '04_threshold_sensitivity_simulation', output)
    notes = '''# Simulation figure notes

All panels show synthetic algorithm simulation, not real video, trained U-Net,
electrode calibration accuracy or physical closed-loop results. Coordinates are
normalized electrode pitches. Example420 geometry is not measured geometry.

Trajectory/state panels use the first supplied scenario and seed, selected before
viewing results, not a best-performing run. State timestamps are processing/decision
times. Source/target fractions use droplet area; directed progress is not coverage.
Missing/drop frames are Unknown or absent evidence, not true Deviation.

Control panels retain all prescribed trials including failures. Completion uses
trial Wilson95% intervals. Other intervals use seed-level bootstrap95%; early-rate
resamples seed clusters with all planned steps in its denominator. Time is time to
termination including failed runs, not successful transport speed. Delay conditions
on true arrivals confirmed by the controller; absent values are blank, not zero.
See summary.csv for observed/censored/no-arrival/unattempted denominators, and
paired_differences.csv for within-seed comparisons. Repeats are simulation seeds,
not biological replicates. Sensitivity does not change hidden physical truth.
Flat sensitivity cells are displayed as explicit percentages, not missing data.
Zero-event bootstrap intervals can be degenerate; they do not prove zero risk.
Coverage can be redundant with the stricter center-distance/source-release gates.
PNG is a 300-dpi preview; use editable vector PDF/SVG for thesis line art.
'''
    (output/'figure_notes.md').write_text(notes, encoding='utf-8')
    payload = dict(config=asdict(config), summary=summary, sensitivity=sensitivity,
                   illustrations=[asdict(result) for result in selected])
    manifest = dict(simulation=True, generated_utc=datetime.now(timezone.utc).isoformat(),
                    plotting_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    input_payload_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    illustrative_scenario=scenario, illustrative_seed=seed,
                    n_seeds_per_summary_group=sample_sizes,
                    provenance_note='Figure rendering provenance; does not replace the original batch manifest.',
                    output_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    (output/'figure_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return paths
