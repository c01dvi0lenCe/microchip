"""Export final Chapter 3 figures from saved CSV only; never run simulations."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
from matplotlib import rc_context

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.chapter3_plot_style import (
    CAP_SIZE, ERROR_WIDTH, FAULT_COLORS, FIGURE_WIDTH, INK, LABEL_SIZE, LEGEND_SIZE,
    LINE_WIDTH, LINES, MARKERS, MARKER_SIZE, METHOD_COLORS, METHOD_LABELS, METHOD_ZORDERS,
    TICK_SIZE, TITLE_SIZE, VERSION_COLORS, VERSION_LABELS, decorate, error_line, export,
    font_settings, panels, shared_legend,
)

METHODS = ("static_astar", "safe_serial", "coordinated")
TEXT_FIELDS = {"group", "method", "placement", "status", "reason"}
SD_CAPTION = "Error bars denote sample standard deviations; lower bounds are clipped at zero for non-negative metrics."


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_numeric_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = []
    for row in rows:
        parsed = {}
        for key, value in row.items():
            if value == "":
                parsed[key] = None
            elif key == "status_counts":
                parsed[key] = json.loads(value)
            elif key in TEXT_FIELDS:
                parsed[key] = value
            else:
                parsed[key] = float(value)
                if not math.isfinite(parsed[key]):
                    raise ValueError(f"Non-finite CSV value: {path}/{key}")
        result.append(parsed)
    return result


def read_summary(csv_path, json_path):
    rows = read_numeric_csv(csv_path)
    reference = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if rows != reference:
        raise ValueError(f"CSV/JSON statistics do not match exactly: {csv_path}")
    return rows


def one(rows, **selectors):
    selected = [r for r in rows if all(r.get(k) == v for k, v in selectors.items())]
    if len(selected) != 1:
        raise ValueError(f"Expected one CSV row, got {len(selected)}: {selectors}")
    return selected[0]


class PlotAudit:
    def __init__(self):
        self.rows = []

    def metric(self, figure, panel, row, metric, x, series, source):
        record = {"figure": figure, "panel": panel, "series": series, "source_csv": str(source),
                  "metric": metric, "x": x, "mean": row.get(metric + "_mean"),
                  "sample_sd": row.get(metric + "_std"), "metric_n": row.get(metric + "_n"),
                  "total_n": row["n"], "ci_low": None, "ci_high": None}
        if metric == "success_rate":
            record.update(mean=row[metric], sample_sd=None, metric_n=row["n"],
                          ci_low=row["success_ci_low"], ci_high=row["success_ci_high"])
        self.rows.append(record)
        return record


def metric_line(ax, rows, x_key, metric, figure, panel, series, source, audit,
                color, label, marker="o", linestyle="-", zorder=2, hollow=False):
    records = [audit.metric(figure, panel, row, metric, row[x_key], series, source) for row in rows]
    x = [r["x"] for r in records]
    y = [r["mean"] if r["mean"] is not None else np.nan for r in records]
    if metric == "success_rate":
        errors = [[r["mean"] - r["ci_low"] for r in records],
                  [r["ci_high"] - r["mean"] for r in records]]
    else:
        # Missing means remain NaN to break paths. Never bridge failed scales.
        errors = [r["sample_sd"] if r["sample_sd"] is not None else np.nan for r in records]
    error_line(ax, x, y, errors, color, label, marker, linestyle, zorder, hollow)


def plot_a(rows, config, source, audit):
    fig, axes, _ = panels(2, 2, 5.8)
    definitions = (
        ("conflict_pair_steps", "(a) Conflict pair-steps", "$C$"),
        ("makespan_steps", "(b) Valid makespan", "$T_{\\mathrm{makespan}}$ (steps)"),
        ("planning_time_ms", "(c) Planning time", "$T_{\\mathrm{plan}}$ (ms)"),
        ("wait_steps", "(d) Wait steps", "$N_{\\mathrm{wait}}$ (steps)"),
    )
    for index, (metric, title, ylabel) in enumerate(definitions):
        ax = axes[index // 2][index % 2]
        labels = []
        for position, method in enumerate(METHODS):
            row = one(rows, group="scale", droplet_count=config["baseline_plot_droplets"], method=method)
            value = audit.metric("A", index, row, metric, position, method, source)
            if value["mean"] is not None:
                kwargs = {} if value["sample_sd"] is None else {"yerr": value["sample_sd"]}
                ax.bar(position, value["mean"], color=METHOD_COLORS[method], width=0.6,
                       edgecolor=INK, linewidth=0.35, **kwargs,
                       error_kw={"ecolor": "#59646C", "elinewidth": ERROR_WIDTH,
                                 "capsize": CAP_SIZE, "capthick": ERROR_WIDTH})
            else:
                ax.text(position, 0.04, "N/A", ha="center", transform=ax.get_xaxis_transform(), fontsize=TICK_SIZE)
            name = METHOD_LABELS[method]
            labels.append(name + f"\n$n={int(value['metric_n'])}/{int(value['total_n'])}$")
        ax.set_xticks(range(3), labels)
        ax.set_xlim(-0.6, 2.6)
        decorate(ax, title, ylabel)
        ax.set_ylim(bottom=0)
    return fig


def plot_b(rows, config, source, audit):
    fig, axes, legend = panels(3, 2, 8.8, legend=True)
    definitions = (
        ("success_rate", "(a) Safe completion rate", "$P_{\\mathrm{success}}$"),
        ("makespan_steps", "(b) Makespan", "$T_{\\mathrm{makespan}}$ (steps)"),
        ("wait_steps", "(c) Wait steps", "$N_{\\mathrm{wait}}$ (steps)"),
        ("planning_time_ms", "(d) Planning time", "$T_{\\mathrm{plan}}$ (ms)"),
        ("spatial_length", "(e) Spatial length", "$L_{\\mathrm{total}}$ (edges)"),
        ("conflict_pair_steps", "(f) Conflict pair-steps", "$C$"),
    )
    for index, (metric, title, ylabel) in enumerate(definitions):
        ax = axes[index // 2][index % 2]
        for method in METHODS:
            selected = [one(rows, group="scale", droplet_count=n, method=method) for n in config["droplet_counts"]]
            metric_line(ax, selected, "droplet_count", metric, "B", index, method, source, audit,
                        METHOD_COLORS[method], METHOD_LABELS[method], MARKERS[method], LINES[method],
                        METHOD_ZORDERS[method], hollow=True)
        decorate(ax, title, ylabel, "$N_d$")
        ax.set_xticks(config["droplet_counts"])
        if metric == "success_rate":
            ax.set_ylim(0, 1.035)
        else:
            ax.set_ylim(bottom=0)
    shared_legend(legend, axes[0][0], 3)
    return fig


def plot_c(rows, config, source, audit):
    fig, axes, _ = panels(3, 2, 8.8)
    definitions = (
        ("wait_steps", "(a) Wait steps", "$N_{\\mathrm{wait}}$ (steps)"),
        ("max_release_delay_steps", "(b) Maximum release delay", "$t_{\\mathrm{release,max}}$ (steps)"),
        ("makespan_steps", "(c) Makespan", "$T_{\\mathrm{makespan}}$ (steps)"),
        ("wait_fraction", "(d) Wait fraction", "$\\rho_{\\mathrm{wait}}$"),
        ("spatial_length", "(e) Spatial length", "$L_{\\mathrm{total}}$ (edges)"),
        ("static_core_overlap_pair_cells", "(f) Spatial path overlap", "$O_{\\mathrm{path}}$ (pair-cells)"),
    )
    selected = [one(rows, group="congestion", gate_width=w, method="coordinated") for w in config["congestion_gate_widths"]]
    for index, (metric, title, ylabel) in enumerate(definitions):
        ax = axes[index // 2][index % 2]
        metric_line(ax, selected, "gate_width", metric, "C", index, "coordinated", source, audit,
                    METHOD_COLORS["coordinated"], "Coordinated")
        decorate(ax, title, ylabel)
        ax.set_xticks([20, 7, 3], ["Wide\n(20)", "Medium\n(7)", "Narrow\n(3)"])
        ax.invert_xaxis()
        ax.set_ylim(bottom=0)
    return fig


def plot_d(rows, config, source, audit):
    if any(row["eligible_n"] != row["n"] for row in rows):
        raise ValueError("Recovery title requires the stored nominal tasks to be eligible; do not change denominators")
    fig, axes, legend = panels(2, 2, 5.8, legend=True)
    definitions = (
        ("success_rate", "(a) Safe recovery rate", "$P_{\\mathrm{recovery}}$"),
        ("detour_vs_zero_fault", "(b) Normalized path length", "$R_L$"),
        ("replanning_time_ms", "(c) Replanning time", "$T_{\\mathrm{replan}}$ (ms)"),
        ("delta_makespan_vs_zero_fault", "(d) Makespan change", "$\\Delta T_{\\mathrm{makespan}}$ (steps)"),
    )
    for index, (metric, title, ylabel) in enumerate(definitions):
        ax = axes[index // 2][index % 2]
        for placement in config["fault_placements"]:
            selected = [one(rows, placement=placement, fault_count=n) for n in config["fault_counts"]]
            metric_line(ax, selected, "fault_count", metric, "D_v2", index, placement, source, audit,
                FAULT_COLORS[placement], "Random faults" if placement == "random" else "Path-critical faults",
                "o" if placement == "random" else "s", "-" if placement == "random" else "--")
        decorate(ax, title, ylabel, "$N_f$")
        ax.set_xticks(config["fault_counts"])
        if metric == "success_rate":
            ax.set_ylim(0, 1.035)
        elif metric != "delta_makespan_vs_zero_fault":
            ax.set_ylim(bottom=0)
    shared_legend(legend, axes[0][0], 2)
    return fig


def status_counts(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        counts = Counter(r["status"] for r in csv.DictReader(stream))
    if set(counts) - {"success", "invalid_replay", "protective_pause", "unreachable"}:
        raise ValueError("Unknown outcome category; do not silently omit failures")
    return counts


def plot_identity(v1_path, v2_path, comparison, audit):
    counts = {"v1": status_counts(v1_path), "v2": status_counts(v2_path)}
    for version in counts:
        if dict(counts[version]) != comparison[version + "_status_counts"]:
            raise ValueError("Identity count CSV disagrees with comparison.json")
    fig, axes, legend = panels(1, 2, 3.4, legend=True, width_ratios=[1, 2])
    for index, (keys, title) in enumerate(((['success'], "(a) Safe success"),
                   (['invalid_replay', 'protective_pause', 'unreachable'], "(b) Other outcomes"))):
        ax = axes[0][index]
        x = np.arange(len(keys))
        for version, offset in (("v1", -0.17), ("v2", 0.17)):
            values = [counts[version][key] for key in keys]
            bars = ax.bar(x + offset, values, width=0.30, color=VERSION_COLORS[version],
                          edgecolor=INK, linewidth=0.35, label=VERSION_LABELS[version])
            ax.bar_label(bars, padding=3, color=INK, fontsize=TICK_SIZE)
            for key, value in zip(keys, values):
                audit.rows.append(dict(figure="Identity", panel=index, series=version,
                    source_csv=str(v1_path if version == "v1" else v2_path), metric="status_count",
                    x=key, mean=value, sample_sd=None, metric_n=None, total_n=sum(counts[version].values()),
                    ci_low=None, ci_high=None))
        labels = {'success': 'Safe success', 'invalid_replay': 'Invalid\nreplay',
                  'protective_pause': 'Protective\npause', 'unreachable': 'Unreachable'}
        ax.set_xticks(x, [labels[k] for k in keys])
        decorate(ax, title, "Trials")
        ax.set_ylim(0, max(counts[v][k] for v in counts for k in keys) * 1.24)
    shared_legend(legend, axes[0][0], 2)
    return fig


def plot_tails(rows, source, audit):
    fig, axes, legend = panels(1, 1, 3.8, legend=True)
    ax = axes[0][0]
    selected = [one(rows, droplet_count=n) for n in (20, 24, 30)]
    for metric, label, color, marker, line in (
        ("median_ms", "Median", METHOD_COLORS["coordinated"], "o", "-"),
        ("p95_ms", "P95", METHOD_COLORS["safe_serial"], "D", "--"),
        ("max_ms", "Max", "#667079", "^", ":"),
    ):
        ax.plot([r["droplet_count"] for r in selected], [r[metric] for r in selected],
                color=color, marker=marker, linestyle=line, linewidth=LINE_WIDTH, markersize=MARKER_SIZE, label=label)
        for row in selected:
            audit.rows.append(dict(figure="B_tails", panel=0, series=label, source_csv=str(source),
                metric=metric, x=row["droplet_count"], mean=row[metric], sample_sd=None,
                metric_n=row["n"], total_n=row["n"], ci_low=None, ci_high=None))
    decorate(ax, "High-load planning-time statistics", "$T_{\\mathrm{plan}}$ (ms)", "$N_d$")
    ax.set_xticks([20, 24, 30])
    ax.set_ylim(bottom=0)
    shared_legend(legend, ax, 3)
    return fig


def generate(baseline, replay, output, dpi=300):
    baseline, replay, output = Path(baseline), Path(replay), Path(output)
    sources = [baseline / name for name in ("summary.csv", "summary.json", "config.json")]
    sources += [replay / name for name in ("summary_v2.csv", "summary_v2.json", "v1_replay_records.csv",
                "v2_records.csv", "comparison.json", "planning_time_tails_v1.csv")]
    before = {str(p.resolve()): sha(p) for p in sources}
    # Fingerprint all experiment data, not just the files consumed by plotting.
    protected = [p for folder in (baseline, replay) for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in (".csv", ".json", ".jsonl")]
    protected_before = {str(p.resolve()): sha(p) for p in protected}
    rows = read_summary(baseline / "summary.csv", baseline / "summary.json")
    fault_rows = read_summary(replay / "summary_v2.csv", replay / "summary_v2.json")
    config = json.loads((baseline / "config.json").read_text(encoding="utf-8"))
    comparison = json.loads((replay / "comparison.json").read_text(encoding="utf-8"))
    tails = read_numeric_csv(replay / "planning_time_tails_v1.csv")
    settings, font = font_settings()
    output.mkdir(parents=True, exist_ok=False)
    audit = PlotAudit()
    files = []
    with rc_context(settings):
        builders = (
            ("A_baseline_final", lambda: plot_a(rows, config, baseline / "summary.csv", audit)),
            ("B_scalability_final", lambda: plot_b(rows, config, baseline / "summary.csv", audit)),
            ("C_congestion_final", lambda: plot_c(rows, config, baseline / "summary.csv", audit)),
            ("D_v2_robustness_final", lambda: plot_d(fault_rows, config, replay / "summary_v2.csv", audit)),
            ("D_identity_validation", lambda: plot_identity(replay / "v1_replay_records.csv", replay / "v2_records.csv", comparison, audit)),
            ("B_planning_tails", lambda: plot_tails(tails, replay / "planning_time_tails_v1.csv", audit)),
        )
        for name, build in builders:
            files.extend(export(build(), output, name, dpi))
            print(f"Exported PNG/PDF: {name}", flush=True)
    after = {str(p.resolve()): sha(p) for p in protected}
    if after != protected_before:
        raise AssertionError("An original experiment file changed")
    with (output / "plot_values.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit.rows[0]))
        writer.writeheader()
        writer.writerows(audit.rows)
    metadata = dict(created_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), simulation_rerun=False,
        original_data_unchanged=True, input_sha256=before, protected_data_sha256=protected_before,
        csv_json_statistics_exact_match=True, font=font, png_dpi=dpi, figure_width_inches=FIGURE_WIDTH,
        point_sizes={"title": TITLE_SIZE, "axis": LABEL_SIZE, "legend": LEGEND_SIZE, "tick": TICK_SIZE},
        colors={"methods": METHOD_COLORS, "faults": FAULT_COLORS, "versions": VERSION_COLORS},
        drawing={"line_width_pt": LINE_WIDTH, "marker_size_pt": MARKER_SIZE,
                 "error_width_pt": ERROR_WIDTH, "cap_size_pt": CAP_SIZE},
        statistics="Existing mean/sample SD, Wilson 95% bounds and metric_n copied exactly from CSV; no recomputation or seed filtering.",
        display_policy="Non-negative axes start at zero; raw error lengths are unchanged and clipped by axes only. Signed makespan change is not clipped.",
        method_zorders=METHOD_ZORDERS, errorbar_caption=SD_CAPTION,
        files=files, paired_success_count=comparison["common_success_trials"],
        paired_makespan_changed=comparison["common_makespan_changed"])
    (output / "plot_manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    captions = ["# Figure Captions", ""]
    for name in ("A_baseline_final", "B_scalability_final", "C_congestion_final", "D_v2_robustness_final"):
        captions.extend(["## " + name, SD_CAPTION])
        if name in ("B_scalability_final", "D_v2_robustness_final"):
            captions.append("Success-rate error bars denote Wilson 95% confidence intervals.")
        if name == "D_v2_robustness_final":
            captions.append("Makespan change is signed; its display range is not clipped at zero.")
        captions.append("")
    captions.extend(["## B_planning_tails", "Auxiliary high-load planning-time statistics for the scalability experiment. Median, P95 and Max come from the existing records; no theoretical distribution is asserted.",
                     "", "## D_identity_validation", "Before identity check denotes the archived implementation; Identity-preserving denotes the fixed implementation. Aggregate outcomes come from the same 280 fault trials; protective pause is not counted as safe success.",
                     "", "# Definitions for Captions or Methods", "",
                     "Uncoordinated A* denotes independent spatial A* routing without cross-source temporal coordination; the original fixed dispensing interval remains unchanged.",
                     "Continuous metrics are reported as mean +/- sample SD; success/recovery rates are shown with Wilson 95% confidence intervals.",
                     "Wide (20), Medium (7), Narrow (3): the numbers denote the bottleneck channel width in electrode cells.",
                     r"Conflict pair-steps: $C=\sum_t\sum_{i<j}\mathbf{1}[(i,j)\text{ violate a conflict constraint at }t]$. One violation is counted per pair and time step, including vertex, edge-swap, spacing and transition-spacing constraints; completed droplets remain occupied.",
                     r"Wait fraction: $\rho_{\mathrm{wait}}=N_{\mathrm{wait}}/(L_{\mathrm{total}}+N_{\mathrm{wait}})$. Wait counts consecutive equal non-empty scheduled positions; None release prefixes and rendering-only terminal holds are excluded.",
                     r"Spatial path overlap: $O_{\mathrm{path}}=\sum_{e\in E_{\mathrm{core}}}\binom{n_e}{2}$, where $n_e$ is the number of distinct spatial paths containing core cell $e$. The unit is pair-cells, not simultaneous conflicts.",
                     r"Normalized path length: $R_L=L_{\mathrm{fault}}/L_0$, where both lengths are the total remaining edge counts of unfinished droplets from the identical fault-time state; $L_0$ comes from zero-fault replanning, not the initial full journey.", ""])
    (output / "figure_captions.md").write_text("\n".join(captions), encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "results/chapter3_statistics_20261006_audited")
    parser.add_argument("--replay", type=Path, default=ROOT / "results/chapter3_identity_fix_20261006/replay")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dpi", type=int, choices=(300, 600), default=300)
    args = parser.parse_args()
    output = args.output or ROOT / "results" / ("chapter3_final_style_" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S"))
    generate(args.baseline, args.replay, output, args.dpi)
    print(f"Final figures: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
