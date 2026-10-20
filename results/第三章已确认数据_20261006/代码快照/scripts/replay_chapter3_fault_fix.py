"""Replay stored fault states against hash-verified v1 and live v2 planners."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo

import numpy as np
from matplotlib import rc_context
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dmf import MultiDropletAssignment
from dmf.planning import geometry
from scripts.generate_chapter3_advantage_case import cell_at
from scripts.run_chapter3_statistics import (
    plot_line, run_fault_trial, save_figure, save_json, style_axes, summarize, write_csv,
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_hash(manifest, relative):
    hashes = {k.replace("\\", "/"): v for k, v in manifest["source_sha256"].items()}
    return hashes[relative]


def load_v1_replanner(source_dir, manifest):
    source_dir = Path(source_dir)
    for filename in ("scheduler.py", "assignment.py"):
        if digest(source_dir / filename) != manifest_hash(manifest, "dmf/planning/" + filename):
            raise ValueError(f"v1 archive hash mismatch: {filename}")
    for relative in ("dmf/planning/geometry.py", "dmf/planning/astar.py", "dmf/layout.py", "dmf/models.py"):
        if digest(ROOT / relative) != manifest_hash(manifest, relative):
            raise ValueError(f"Shared v1 dependency changed: {relative}")
    # A separate package namespace preserves relative imports without replacing
    # the live application's scheduler or assignment modules.
    package = "dmf._chapter3_v1_replay"
    module = types.ModuleType(package)
    module.__path__ = [str(source_dir)]
    sys.modules[package] = module
    sys.modules[package + ".geometry"] = geometry
    for name in ("scheduler", "assignment"):
        spec = importlib.util.spec_from_file_location(package + "." + name, source_dir / (name + ".py"))
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = loaded
        spec.loader.exec_module(loaded)
    return sys.modules[package + ".assignment"].replan_multi_assignments_after_fault


def trial_key(row):
    return row["seed"], row["placement"], row["fault_count"]


def restore_trial(trace):
    task = copy.deepcopy(trace["task"])
    for field in ("sources", "targets", "obstacles"):
        task[field] = [tuple(c) for c in task[field]]
    originals = [MultiDropletAssignment(
        item["droplet_id"], tuple(item["source"]), tuple(item["target"]),
        [tuple(c) for c in item["path"]],
        [tuple(c) if c is not None else None for c in item["scheduled_path"]],
    ) for item in trace["original"]]
    positions = {int(i): tuple(c) for i, c in trace["current_positions"].items()}
    step = trace["fault_step"]
    if any(cell_at(a.scheduled_path, step) != positions[a.droplet_id] for a in originals):
        raise ValueError("Stored current positions do not match the original schedule")
    completed = set(trace["completed_ids"])
    if completed != {a.droplet_id for a in originals if positions[a.droplet_id] == a.target}:
        raise ValueError("Stored completed IDs do not match target occupancy")
    faults = [tuple(c) for c in trace["faults"]]
    if len(faults) != trace["fault_count"] or len(set(faults)) != len(faults):
        raise ValueError("Fault count or uniqueness mismatch")
    if set(faults) & (set(positions.values()) | set(task["targets"]) | set(task["obstacles"])):
        raise ValueError("Fault endpoints differ from the original experiment contract")
    return task, originals, step, positions, completed, faults


def time_tail_rows(records):
    output, slow = [], []
    sizes = sorted({r["droplet_count"] for r in records if r["group"] == "scale"})
    for size in sizes:
        rows = [r for r in records if r["group"] == "scale" and r["method"] == "coordinated" and r["droplet_count"] == size]
        values = [r["planning_time_ms"] for r in rows]
        output.append(dict(droplet_count=size, n=len(rows), success_n=sum(r["success"] for r in rows),
            mean_ms=float(np.mean(values)), sample_sd_ms=float(np.std(values, ddof=1)) if len(rows) > 1 else None,
            median_ms=float(np.median(values)), p90_ms=float(np.quantile(values, 0.90)),
            p95_ms=float(np.quantile(values, 0.95)), max_ms=max(values)))
        for rank, row in enumerate(sorted(rows, key=lambda r: r["planning_time_ms"], reverse=True)[:5], 1):
            slow.append(dict(droplet_count=size, rank=rank, seed=row["seed"],
                             planning_time_ms=row["planning_time_ms"], status=row["status"]))
    return output, slow


def plot_comparison(old, new, comparisons, config, folder):
    folder.mkdir(parents=True, exist_ok=True)
    colors = {("v1", "random"): "#687782", ("v2", "random"): "#1852C2",
              ("v1", "path_critical"): "#B23A48", ("v2", "path_critical"): "#4E7A2E"}
    with rc_context({"font.family": "Arial", "font.size": 11, "axes.titlesize": 12}):
        fig = Figure(figsize=(11, 7.5), layout="constrained")
        axes = fig.subplots(2, 2)
        for version, summary in (("v1", old), ("v2", new)):
            for placement in config["fault_placements"]:
                rows = sorted([r for r in summary if r["placement"] == placement], key=lambda r: r["fault_count"])
                x = [r["fault_count"] for r in rows]
                label = version + (" random" if placement == "random" else " critical")
                style = "--" if version == "v1" else "-"
                color = colors[version, placement]
                axes[0, 0].errorbar(x, [r["success_rate"] for r in rows],
                    yerr=[[r["success_rate"] - r["success_ci_low"] for r in rows],
                          [r["success_ci_high"] - r["success_rate"] for r in rows]],
                    color=color, linestyle=style, marker="o", capsize=2, markersize=4, label=label)
                axes[1, 0].errorbar(x, [r["replanning_time_ms_mean"] for r in rows],
                    yerr=[r["replanning_time_ms_std"] or 0 for r in rows], color=color,
                    linestyle=style, marker="o", capsize=2, markersize=4)
        for version, summary, color in (("v1", old, "#B23A48"), ("v2", new, "#1852C2")):
            counts = [sum(r["status_counts"].get("invalid_replay", 0) for r in summary if r["fault_count"] == n)
                      for n in config["fault_counts"]]
            axes[0, 1].plot(config["fault_counts"], counts, marker="o", color=color, label=version)
        for placement, color in (("random", "#1852C2"), ("path_critical", "#4E7A2E")):
            means, sds = [], []
            for count in config["fault_counts"]:
                values = [r["paired_makespan_delta"] for r in comparisons if r["placement"] == placement
                          and r["fault_count"] == count and r["paired_makespan_delta"] is not None]
                means.append(float(np.mean(values)) if values else np.nan)
                sds.append(float(np.std(values, ddof=1)) if len(values) > 1 else 0)
            axes[1, 1].errorbar(config["fault_counts"], means, yerr=sds, color=color, marker="o",
                capsize=2, markersize=4, label="Random" if placement == "random" else "Path-critical")
        axes[0, 0].set_ylim(-0.03, 1.03)
        axes[0, 0].legend(fontsize=9, ncols=2)
        axes[0, 1].legend(fontsize=9)
        axes[1, 0].set_ylim(bottom=0)
        axes[1, 1].axhline(0, color="#687782", linewidth=0.8)
        axes[1, 1].legend(fontsize=9)
        for ax, title in zip(axes.flat, ("(a) Safe recovery rate", "(b) Invalid replays (trials)",
                                       "(c) Replanning time (ms)", "(d) Paired makespan change: v2 - v1")):
            ax.set_title(title, loc="left")
            ax.set_xlabel("Faulty electrodes")
            ax.set_xticks(config["fault_counts"])
        style_axes(axes)
        save_figure(fig, folder / "D_identity_fix_before_after.png")

        fig = Figure(figsize=(10.5, 7), layout="constrained")
        axes = fig.subplots(2, 2)
        for placement, color in (("random", "#1852C2"), ("path_critical", "#B23A48")):
            rows = sorted([r for r in new if r["placement"] == placement], key=lambda r: r["fault_count"])
            label = "Random" if placement == "random" else "Path-critical"
            axes[0, 0].errorbar([r["fault_count"] for r in rows], [r["success_rate"] for r in rows],
                yerr=[[r["success_rate"] - r["success_ci_low"] for r in rows],
                      [r["success_ci_high"] - r["success_rate"] for r in rows]],
                color=color, marker="o", capsize=3, markersize=4, label=label)
            for ax, metric in zip(list(axes.flat)[1:], ("detour_vs_zero_fault", "replanning_time_ms", "delta_makespan_vs_zero_fault")):
                plot_line(ax, rows, "fault_count", metric, "coordinated", label, color)
        for ax, title in zip(axes.flat, ("(a) Safe recovery rate", "(b) Remaining length / zero-fault length",
                                       "(c) Replanning time (ms)", "(d) Makespan change vs zero faults")):
            ax.set_title(title, loc="left")
            ax.set_xlabel("Faulty electrodes")
            ax.set_xticks(config["fault_counts"])
        axes[0, 0].set_ylim(-0.03, 1.03)
        axes[0, 0].legend(fontsize=9)
        axes[1, 0].set_ylim(bottom=0)
        style_axes(axes)
        save_figure(fig, folder / "D_v2_fault_robustness.png")


def replay(baseline, v1_source, output):
    baseline, output = Path(baseline), Path(output)
    manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    old_function = load_v1_replanner(v1_source, manifest)
    config = json.loads((baseline / "config.json").read_text(encoding="utf-8"))
    original_records = [json.loads(line) for line in (baseline / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    old_records = {trial_key(r): r for r in original_records if r["group"] == "fault"}
    traces = [json.loads(line) for line in (baseline / "traces.jsonl").read_text(encoding="utf-8").splitlines()]
    fault_traces = [t for t in traces if t["group"] == "fault" and "original" in t]
    if len(fault_traces) != len(old_records) or len(old_records) != config["repeats"] * len(config["fault_counts"]) * len(config["fault_placements"]):
        raise ValueError("Baseline must include every eligible stored fault state")
    output.mkdir(parents=True, exist_ok=False)
    fresh_old, fresh_new, comparisons = [], [], []
    zero_cache = {}
    with (output / "replay_traces.jsonl").open("w", encoding="utf-8") as stream:
        for index, trace in enumerate(fault_traces):
            task, originals, step, positions, completed, faults = restore_trial(trace)
            key = (task["seed"], trace["placement"], trace["fault_count"])
            baseline_row = old_records[key]
            if not faults and task["seed"] in zero_cache:
                old_row, old_trace, new_row, new_trace = copy.deepcopy(zero_cache[task["seed"]])
            else:
                results = {}
                order = ("v1", "v2") if index % 2 == 0 else ("v2", "v1")
                for version in order:
                    results[version] = run_fault_trial(task, originals, step, positions, completed, faults,
                                                       old_function if version == "v1" else None)
                old_row, old_trace = results["v1"]
                new_row, new_trace = results["v2"]
                if not faults:
                    zero_cache[task["seed"]] = copy.deepcopy((old_row, old_trace, new_row, new_trace))
            for metric in ("status", "success", "makespan_steps", "spatial_length", "detour_ratio"):
                if old_row.get(metric) != baseline_row.get(metric):
                    raise AssertionError(f"v1 outcome no longer reproduces stored record: {key} / {metric}")
            for version, row in (("v1", old_row), ("v2", new_row)):
                row.update(placement=trace["placement"], faults_on_remaining_path=baseline_row["faults_on_remaining_path"])
                zero = zero_cache[task["seed"]][0 if version == "v1" else 2]
                if row["success"] and zero["success"]:
                    row["detour_vs_zero_fault"] = row["spatial_length"] / zero["spatial_length"] if zero["spatial_length"] else None
                    row["delta_makespan_vs_zero_fault"] = row["makespan_steps"] - zero["makespan_steps"]
            fresh_old.append(old_row)
            fresh_new.append(new_row)
            common = old_row["success"] and new_row["success"]
            comparisons.append(dict(seed=task["seed"], placement=trace["placement"], fault_count=len(faults),
                v1_status=old_row["status"], v2_status=new_row["status"], v1_success=old_row["success"], v2_success=new_row["success"],
                v1_time_ms=old_row["replanning_time_ms"], v2_time_ms=new_row["replanning_time_ms"],
                paired_time_delta_ms=new_row["replanning_time_ms"] - old_row["replanning_time_ms"],
                common_success=common,
                paired_makespan_delta=new_row["makespan_steps"] - old_row["makespan_steps"] if common else None,
                paired_length_delta=new_row["spatial_length"] - old_row["spatial_length"] if common else None,
                paired_detour_delta=new_row["detour_ratio"] - old_row["detour_ratio"] if common else None))
            stream.write(json.dumps(dict(seed=task["seed"], placement=trace["placement"], fault_count=len(faults),
                stored_state=trace, v1=old_trace, v2=new_trace), ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            if (index + 1) % (len(config["fault_counts"]) * len(config["fault_placements"])) == 0:
                print(f"Matched replay seed={task['seed']}: complete", flush=True)

    old_summary, new_summary = summarize(fresh_old), summarize(fresh_new)
    write_csv(output / "v1_original_records.csv", list(old_records.values()))
    write_csv(output / "v1_replay_records.csv", fresh_old)
    write_csv(output / "v2_records.csv", fresh_new)
    write_csv(output / "matched_comparison.csv", comparisons)
    for name, summary in (("v1_replay", old_summary), ("v2", new_summary)):
        write_csv(output / ("summary_" + name + ".csv"), summary)
        save_json(output / ("summary_" + name + ".json"), summary)
    tails, slow = time_tail_rows(original_records)
    write_csv(output / "planning_time_tails_v1.csv", tails)
    write_csv(output / "slow_seeds_v1.csv", slow)
    plot_comparison(old_summary, new_summary, comparisons, config, output / "图片")
    common_rows = [r for r in comparisons if r["common_success"]]
    formerly_invalid = [r for r in comparisons if r["v1_status"] == "invalid_replay"]
    report = dict(trials=len(fresh_new), v1_status_counts=dict(Counter(r["status"] for r in fresh_old)),
        v2_status_counts=dict(Counter(r["status"] for r in fresh_new)),
        formerly_invalid_after=dict(Counter(r["v2_status"] for r in formerly_invalid)),
        common_success_trials=len(common_rows),
        common_makespan_changed=sum(r["paired_makespan_delta"] != 0 for r in common_rows),
        common_length_changed=sum(r["paired_length_delta"] != 0 for r in common_rows),
        v1_outcomes_match_original=True)
    save_json(output / "comparison.json", report)
    save_json(output / "manifest.json", dict(
        simulation_only=True, created_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), config=config,
        baseline=str(baseline.resolve()), baseline_records_sha256=digest(baseline / "records.jsonl"),
        baseline_traces_sha256=digest(baseline / "traces.jsonl"),
        v1_source={name: digest(Path(v1_source) / name) for name in ("scheduler.py", "assignment.py")},
        v2_source={name: digest(ROOT / name) for name in ("dmf/planning/scheduler.py", "dmf/planning/assignment.py",
            "scripts/run_chapter3_statistics.py", "scripts/replay_chapter3_fault_fix.py")},
        pairing="Identical stored original schedules, current positions, completed IDs and faults; never regenerate tasks.",
        timing="Fresh hash-verified v1 and v2 calls alternate order; each seed's zero-fault control is reused, not independently duplicated.",
    ))
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"Saved matched fault replays: {output.resolve()}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "results/chapter3_statistics_20261006_audited")
    parser.add_argument("--v1-source", type=Path, default=ROOT / "results/chapter3_identity_fix_20261006/source_v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plot-from", type=Path, help="Redraw stored v1/v2 summaries without rerunning planners")
    args = parser.parse_args()
    if args.plot_from is not None:
        if args.output is not None:
            parser.error("--plot-from cannot be combined with --output")
        folder = args.plot_from
        config = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["config"]
        old = json.loads((folder / "summary_v1_replay.json").read_text(encoding="utf-8"))
        new = json.loads((folder / "summary_v2.json").read_text(encoding="utf-8"))
        with (folder / "matched_comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
            comparisons = list(csv.DictReader(stream))
        for row in comparisons:
            row["fault_count"] = int(row["fault_count"])
            row["paired_makespan_delta"] = float(row["paired_makespan_delta"]) if row["paired_makespan_delta"] else None
        plot_comparison(old, new, comparisons, config, folder / "图片")
        save_json(folder / "plot_manifest.json", dict(data_changed=False, source_sha256=digest(__file__),
            inputs={name: digest(folder / name) for name in ("summary_v1_replay.json", "summary_v2.json", "matched_comparison.csv")}))
        print(f"Redrawn two figures from unchanged replays: {folder.resolve()}")
        return 0
    output = args.output or ROOT / "results" / ("chapter3_identity_replay_" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S"))
    replay(args.baseline, args.v1_source, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
