"""Seeded, software-only Chapter 3 comparisons around the production planner."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import yaml
from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dmf import build_multi_droplet_assignments, MultiDropletAssignment, replan_multi_assignments_after_fault
from dmf.layout import SIDE_RESERVOIR_LARGE, electrode_id
from dmf.planning.assignment import assign_sources_to_targets, order_assignments_by_transport_dependencies
from dmf.planning.geometry import pull_risk_neighbors, target_merge_region_map
from scripts.generate_chapter3_advantage_case import (
    assignment_data, audit_schedule, cell_at, metrics, serial_reference, uncoordinated_reference,
)
from scripts.generate_chapter3_results import _base_planner, _release_delay

METHODS = ("static_astar", "safe_serial", "coordinated")
COLORS = {"static_astar": "#687782", "safe_serial": "#B87412", "coordinated": "#1852C2"}
LABELS = {"static_astar": "Static A*", "safe_serial": "Safe serial", "coordinated": "Coordinated"}
METRICS = (
    "spatial_length", "makespan_steps", "nominal_timeline_steps", "wait_steps",
    "max_release_delay_steps", "wait_fraction", "planning_time_ms", "conflict_pair_steps",
    "static_core_overlap_pair_cells", "detour_ratio", "detour_vs_zero_fault",
    "replanning_time_ms", "delta_makespan_vs_original", "delta_makespan_vs_zero_fault",
    "paired_reduction_vs_serial_percent",
)
GROUP_KEYS = ("group", "droplet_count", "gate_width", "fault_count", "placement", "method")


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    required = {
        "seed_start", "repeats", "droplet_counts", "scale_obstacle_count", "baseline_plot_droplets",
        "congestion_gate_widths", "congestion_droplets", "fault_counts", "fault_droplets",
        "fault_placements", "emission_spacing_steps",
    }
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("Unexpected or missing experiment configuration fields")
    for key in required - {"fault_placements"}:
        values = config[key] if isinstance(config[key], list) else [config[key]]
        if not values or any(type(v) is not int for v in values):
            raise ValueError(f"{key} must contain integers")
    if config["repeats"] < 1 or config["emission_spacing_steps"] < 1:
        raise ValueError("Repetitions and dispensing interval must be positive")
    if not 0 <= config["scale_obstacle_count"] <= 100:
        raise ValueError("Unsupported obstacle count")
    if any(not 1 <= n <= 40 for n in config["droplet_counts"]):
        raise ValueError("Scale exceeds the eight reservoirs' five-drop capacities")
    if len(set(config["droplet_counts"])) != len(config["droplet_counts"]):
        raise ValueError("Duplicate scale levels")
    if config["baseline_plot_droplets"] not in config["droplet_counts"]:
        raise ValueError("Baseline plot scale must be included")
    if not 1 <= config["congestion_droplets"] <= 16 or not 2 <= config["fault_droplets"] <= 16:
        raise ValueError("Unsupported congestion/fault task size")
    if any(w not in (20, 7, 3) for w in config["congestion_gate_widths"]):
        raise ValueError("Supported gate widths: 20, 7, 3")
    if len(set(config["congestion_gate_widths"])) != len(config["congestion_gate_widths"]):
        raise ValueError("Duplicate gate widths")
    if not config["fault_counts"] or config["fault_counts"][0] != 0:
        raise ValueError("Fault experiment requires a zero-fault control first")
    if config["fault_counts"] != sorted(set(config["fault_counts"])) or config["fault_counts"][-1] > 100:
        raise ValueError("Fault counts must be unique, ascending and at most 100")
    if not config["fault_placements"] or any(p not in ("random", "path_critical") for p in config["fault_placements"]):
        raise ValueError("Unsupported fault placement")
    if len(set(config["fault_placements"])) != len(config["fault_placements"]):
        raise ValueError("Duplicate fault placements")
    return config


def scale_task(seed, count, obstacle_count=20):
    rng = random.Random(seed)
    # A common spaced target pool and obstacle set are retained across sizes.
    parity = (rng.randrange(2), rng.randrange(2))
    pool = [(r, c) for r in range(parity[0], 20, 2) for c in range(parity[1], 20, 2)]
    rng.shuffle(pool)
    reserved = set(pool[:40])
    entries = {(0, 6), (0, 13), (6, 0), (13, 0), (6, 19), (13, 19), (19, 6), (19, 13)}
    candidates = sorted({(r, c) for r in range(20) for c in range(20)} - reserved - entries)
    obstacles = set(rng.sample(candidates, obstacle_count))
    sources = sorted(SIDE_RESERVOIR_LARGE, key=lambda cell: electrode_id(*cell))
    return dict(seed=seed, sources=sources, targets=pool[:count], obstacles=sorted(obstacles))


def congestion_task(seed, count, gate_width):
    original = json.loads((ROOT / "presets" / "复杂瓶颈并行运输.json").read_text(encoding="utf-8"))["settings"]
    obstacles = {tuple(c) for c in original["obstacle_cells"] if c[0] != 10}
    # Only the common-channel width changes within each seed's matched tasks.
    opening = set(range(20)) if gate_width == 20 else set(range(7, 14)) if gate_width == 7 else {9, 10, 11}
    obstacles.update((10, c) for c in range(20) if c not in opening)
    rng = random.Random(seed)
    pool = [(r, c) for r in range(12, 20, 2) for c in range(2, 18, 2) if (r, c) not in obstacles]
    rng.shuffle(pool)
    if count > len(pool):
        raise ValueError("Insufficient distinct congestion targets")
    return dict(seed=seed, sources=[tuple(c) for c in original["loaded_reservoirs"]],
                targets=pool[:count], obstacles=sorted(obstacles))


def check_geometry(assignments, task, expected_starts=None, completed=()):
    planner = _base_planner()
    blocked = {tuple(c) for c in task["obstacles"]}
    expected_targets = {tuple(c) for c in task["targets"]}
    if len(assignments) != len(expected_targets) or {a.target for a in assignments} != expected_targets:
        return False
    if len({a.droplet_id for a in assignments}) != len(assignments):
        return False
    for a in assignments:
        schedule = a.scheduled_path
        active = [c for c in schedule if c is not None]
        start = expected_starts[a.droplet_id] if expected_starts is not None else a.source
        if not active or active[0] != start or active[-1] != a.target:
            return False
        if any(c is None for c in schedule[schedule.index(active[0]):]):
            return False
        path = [a.target] if a.droplet_id in completed else a.path
        if path[0] != start or path[-1] != a.target:
            return False
        if any(c in blocked or not planner._in_bounds(c) for c in active + path):
            return False
        if any(b != a and b not in planner._neighbors(a) for a, b in zip(active, active[1:])):
            return False
        if any(b not in planner._neighbors(a) for a, b in zip(path, path[1:])):
            return False
        compressed = [c for i, c in enumerate(active) if i == 0 or c != active[i - 1]]
        if compressed != path:
            return False
    return True


def result_row(task, method, assignments, elapsed_ms, status=None, **extra):
    row = {"seed": task["seed"], "droplet_count": len(task["targets"]), "method": method,
           "gate_width": None, "fault_count": None, "placement": None,
           "planning_time_ms": elapsed_ms, "success": False}
    row.update(extra)
    if not assignments:
        row["status"] = status or "unreachable_or_unschedulable"
        return row
    data = metrics(method, assignments)
    row.update(data)
    row["nominal_timeline_steps"] = data["makespan_steps"]
    row["max_release_delay_steps"] = max(_release_delay(a.scheduled_path) for a in assignments)
    row["wait_fraction"] = data["wait_steps"] / (data["spatial_length"] + data["wait_steps"])
    occupancy = Counter(c for a in assignments for c in set(a.path) if 0 <= c[0] < 20 and 0 <= c[1] < 20)
    row["static_core_overlap_pair_cells"] = sum(n * (n - 1) // 2 for n in occupancy.values())
    geometric = check_geometry(assignments, task)
    row["success"] = geometric and data["safety_valid"]
    row["status"] = "safe_completed" if row["success"] else "unsafe" if geometric else "invalid_geometry"
    # Unsafe static replay is not a valid completed execution time.
    if not row["success"]:
        row["makespan_steps"] = None
    return row


def run_triplet(task, emission_spacing=3):
    planner = _base_planner()
    sources, targets, obstacles = task["sources"], task["targets"], task["obstacles"]
    start = time.perf_counter_ns()
    raw = assign_sources_to_targets(sources, targets, planner, obstacles)
    raw = order_assignments_by_transport_dependencies(raw, target_merge_region_map(targets))
    pair_ms = (time.perf_counter_ns() - start) / 1e6
    start = time.perf_counter_ns()
    proposed = build_multi_droplet_assignments(sources, targets, planner, obstacles)
    proposed_ms = (time.perf_counter_ns() - start) / 1e6
    # Production fallback may reassign sources. References use those same final
    # pairs, without importing its temporal schedule or its rerouted paths.
    final_pairs = proposed if len(proposed) == len(targets) else [
        MultiDropletAssignment(i, source, target, path, path)
        for i, (source, target, path) in enumerate(raw, 1)
    ]
    origin = "production_final" if final_pairs is proposed else "initial_greedy"
    changed = sorted((s, t) for s, t, _ in raw) != sorted((a.source, a.target) for a in final_pairs)
    pairs = [(a.source, a.target) for a in final_pairs]
    rows = []
    traces = {}
    for method in METHODS:
        assignments, error = [], None
        start = time.perf_counter_ns()
        try:
            if len(final_pairs) != len(targets):
                error = "assignment_unreachable"
            elif method == "static_astar":
                assignments = uncoordinated_reference(final_pairs, planner, obstacles, emission_spacing)
            elif method == "safe_serial":
                assignments = serial_reference(final_pairs, planner, obstacles)
            else:
                assignments = proposed
        except ValueError as exc:
            error = "reference_unreachable"
            traces[method + "_reason"] = str(exc)
        elapsed = proposed_ms if method == "coordinated" else pair_ms + (time.perf_counter_ns() - start) / 1e6
        row = result_row(task, method, assignments, elapsed, error,
                         reference_pair_origin=origin, assignment_changed_by_fallback=changed,
                         shared_initial_assignment_ms=pair_ms)
        rows.append(row)
        traces[method] = [assignment_data(a) for a in assignments]
        if assignments and sorted((a.source, a.target) for a in assignments) != sorted(pairs):
            raise AssertionError("Source-target pairs differ between comparators")
    if rows[1]["success"] and rows[2]["success"]:
        rows[2]["paired_reduction_vs_serial_percent"] = 100 * (1 - rows[2]["makespan_steps"] / rows[1]["makespan_steps"])
    traces["task"] = task
    traces["reference_pairs"] = pairs
    return rows, traces, proposed


def fault_snapshot(assignments):
    if not assignments:
        raise ValueError("No nominal schedule")
    horizon = max(len(a.scheduled_path) for a in assignments) - 1
    step = min(horizon - 1, max(max(_release_delay(a.scheduled_path) for a in assignments), horizon // 3))
    positions = {a.droplet_id: cell_at(a.scheduled_path, step) for a in assignments}
    if any(c is None for c in positions.values()):
        raise ValueError("Runtime fault snapshot cannot hide unproduced droplets")
    completed = {a.droplet_id for a in assignments if positions[a.droplet_id] == a.target}
    return step, positions, completed


def fault_order(task, assignments, step, positions, placement):
    forbidden = set(task["obstacles"]) | set(task["targets"]) | set(positions.values())
    candidates = sorted({(r, c) for r in range(20) for c in range(20)} - forbidden)
    remaining = {c for a in assignments for c in a.scheduled_path[step:] if c in candidates}
    rng = random.Random(task["seed"] + (7919 if placement == "path_critical" else 0))
    if placement == "random":
        rng.shuffle(candidates)
        return candidates, remaining
    critical = sorted(remaining)
    other = sorted(set(candidates) - remaining)
    rng.shuffle(critical)
    rng.shuffle(other)
    return critical + other, remaining


def run_fault_trial(task, original, step, positions, completed, faults, replan_fn=None):
    planner = _base_planner()
    start = time.perf_counter_ns()
    function = replan_fn or replan_multi_assignments_after_fault
    result = function(copy.deepcopy(original), positions, completed, task["obstacles"], faults, planner)
    elapsed = (time.perf_counter_ns() - start) / 1e6
    row = {"seed": task["seed"], "droplet_count": len(original), "method": "coordinated",
           "group": "fault", "gate_width": None, "fault_count": len(faults),
           "eligible": True, "success": False, "status": result.status,
           "fault_step": step, "replanning_time_ms": elapsed, "reason": result.reason}
    success_status = result.status in ("success", "completed")
    holds = all(set(a.scheduled_path) == {a.target} for a in result.assignments if a.droplet_id in completed)
    checked_task = dict(task, obstacles=sorted(set(task["obstacles"]) | set(faults)))
    geometric = success_status and check_geometry(result.assignments, checked_task, positions, completed)
    conflicts = audit_schedule(result.assignments) if geometric else None
    identity_changes = [{"droplet_id": a.droplet_id, "expected_current": positions[a.droplet_id],
                         "returned_start": next((c for c in a.scheduled_path if c is not None), None)}
                        for a in result.assignments if a.droplet_id in positions
                        and next((c for c in a.scheduled_path if c is not None), None) != positions[a.droplet_id]]
    row["completed_droplets_held"] = holds if success_status else None
    row["success"] = bool(geometric and holds and not conflicts)
    if success_status and not row["success"]:
        row["status"] = "invalid_replay"
        row["reason"] = "identity_start_changed" if identity_changes else "geometry_or_safety_audit_failed"
    if row["success"]:
        length = sum(len(a.path) - 1 for a in result.assignments if a.droplet_id not in completed)
        makespan = max(len(a.scheduled_path) for a in result.assignments) - 1
        row.update(spatial_length=length, makespan_steps=makespan,
                   conflict_pair_steps=0, delta_makespan_vs_original=makespan - (
                       max(len(a.scheduled_path) for a in original) - 1 - step),
                   detour_ratio=length / result.nominal_remaining_length if result.nominal_remaining_length else None)
    return row, {"faults": faults, "assignments": [assignment_data(a) for a in result.assignments],
                 "returned_status": result.status, "geometry_valid": geometric,
                 "safety_conflicts": conflicts, "identity_changes": identity_changes,
                 "current_positions": positions, "completed_ids": sorted(completed)}


def wilson_interval(successes, total):
    if not total:
        return None, None
    z = 1.959963984540054
    p = successes / total
    divisor = 1 + z * z / total
    center = (p + z * z / (2 * total)) / divisor
    radius = z / divisor * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, center - radius), min(1.0, center + radius)


def summarize(records):
    groups = {}
    for row in records:
        key = tuple(row.get(name) for name in GROUP_KEYS)
        groups.setdefault(key, []).append(row)
    output = []
    for key, rows in groups.items():
        entry = dict(zip(GROUP_KEYS, key))
        count = sum(bool(r["success"]) for r in rows)
        eligible = sum(r.get("eligible", True) for r in rows)
        entry.update(n=len(rows), successes=count, success_rate=count / len(rows),
                     eligible_n=eligible, success_rate_given_eligible=count / eligible if eligible else None,
                     status_counts=dict(Counter(r["status"] for r in rows)))
        entry["success_ci_low"], entry["success_ci_high"] = wilson_interval(count, len(rows))
        for metric in METRICS:
            values = [float(r[metric]) for r in rows if r.get(metric) is not None]
            if any(not math.isfinite(v) for v in values):
                raise ValueError(f"Non-finite metric: {metric}")
            entry[metric + "_n"] = len(values)
            entry[metric + "_mean"] = float(np.mean(values)) if values else None
            entry[metric + "_std"] = float(np.std(values, ddof=1)) if len(values) > 1 else None
        output.append(entry)
    return output


def write_csv(path, rows, fields=None):
    fields = fields or sorted({key for row in rows for key in row})
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def plot_line(ax, entries, x_key, metric, method, label=None, color=None):
    rows = sorted([r for r in entries if r["method"] == method], key=lambda r: r[x_key])
    rows = [r for r in rows if r.get(metric + "_mean") is not None]
    if rows:
        ax.errorbar([r[x_key] for r in rows], [r[metric + "_mean"] for r in rows],
                    yerr=[r.get(metric + "_std") or 0 for r in rows], marker="o", markersize=4,
                    capsize=3, linewidth=1.5, label=label or LABELS[method], color=color or COLORS[method])


def style_axes(axes):
    for ax in np.asarray(axes).flat:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.18)
        ax.tick_params(labelsize=10)


def save_figure(fig, path):
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=200, facecolor="white")


def plot_results(summary, config, folder):
    folder.mkdir(parents=True, exist_ok=True)
    with rc_context({"font.family": "Arial", "font.size": 11, "axes.titlesize": 12}):
        baseline = [r for r in summary if r["group"] == "scale" and r["droplet_count"] == config["baseline_plot_droplets"]]
        fig = Figure(figsize=(10.5, 7), layout="constrained")
        axes = fig.subplots(2, 2)
        for ax, metric, title in zip(axes.flat, ("conflict_pair_steps", "makespan_steps", "planning_time_ms", "wait_steps"),
                                     ("(a) Conflict pair-steps", "(b) Valid makespan (steps)", "(c) Planning time (ms)", "(d) Wait steps")):
            tick_labels = []
            for i, method in enumerate(METHODS):
                row = next(r for r in baseline if r["method"] == method)
                value = row.get(metric + "_mean")
                if value is not None:
                    ax.bar(i, value, yerr=row.get(metric + "_std") or 0, capsize=4, color=COLORS[method], width=0.6)
                else:
                    ax.text(i, 0.02, "N/A", ha="center", transform=ax.get_xaxis_transform())
                tick_labels.append(f"{LABELS[method]}\nn={row[metric + '_n']}/{row['n']}")
            ax.set_xticks(range(3), tick_labels)
            ax.set_title(title, loc="left")
            ax.set_ylim(bottom=0)
        style_axes(axes)
        save_figure(fig, folder / "A_baseline_comparison.png")

        scale = [r for r in summary if r["group"] == "scale"]
        fig = Figure(figsize=(11, 10), layout="constrained")
        axes = fig.subplots(3, 2)
        titles = ("(a) Safe completion rate", "(b) Makespan (steps)", "(c) Wait steps",
                  "(d) Planning time (ms)", "(e) Spatial length (edges)", "(f) Conflict pair-steps")
        for ax, title in zip(axes.flat, titles):
            ax.set_title(title, loc="left")
            ax.set_xlabel("Droplets")
            ax.set_xticks(config["droplet_counts"])
        for method in METHODS:
            rows = sorted([r for r in scale if r["method"] == method], key=lambda r: r["droplet_count"])
            axes[0, 0].errorbar([r["droplet_count"] for r in rows], [r["success_rate"] for r in rows],
                yerr=[[r["success_rate"] - r["success_ci_low"] for r in rows], [r["success_ci_high"] - r["success_rate"] for r in rows]],
                color=COLORS[method], label=LABELS[method], marker="o", capsize=3, markersize=4)
            for ax, metric in zip(list(axes.flat)[1:], ("makespan_steps", "wait_steps", "planning_time_ms", "spatial_length", "conflict_pair_steps")):
                plot_line(ax, scale, "droplet_count", metric, method)
        axes[0, 0].set_ylim(-0.03, 1.03)
        axes[0, 0].legend(fontsize=9)
        for ax in list(axes.flat)[1:]:
            ax.set_ylim(bottom=0)
        style_axes(axes)
        save_figure(fig, folder / "B_droplet_scalability.png")

        congestion = [r for r in summary if r["group"] == "congestion" and r["method"] == "coordinated"]
        fig = Figure(figsize=(10.5, 10), layout="constrained")
        axes = fig.subplots(3, 2)
        for ax, metric, title in zip(axes.flat,
                    ("wait_steps", "max_release_delay_steps", "makespan_steps", "wait_fraction", "spatial_length", "static_core_overlap_pair_cells"),
                    ("(a) Wait steps", "(b) Maximum release delay (steps)", "(c) Makespan (steps)", "(d) Wait fraction",
                     "(e) Spatial length (edges)", "(f) Spatial path overlap (pair-cells)")):
            plot_line(ax, congestion, "gate_width", metric, "coordinated")
            ax.set_title(title, loc="left")
            ax.set_xticks([20, 7, 3], ["Wide (20)", "Medium (7)", "Narrow (3)"])
            ax.invert_xaxis()
            ax.set_ylim(bottom=0)
        style_axes(axes)
        save_figure(fig, folder / "C_channel_congestion.png")

        faults = [r for r in summary if r["group"] == "fault"]
        fig = Figure(figsize=(10.5, 7), layout="constrained")
        axes = fig.subplots(2, 2)
        for placement, color in (("random", "#1852C2"), ("path_critical", "#B23A48")):
            rows = sorted([r for r in faults if r["placement"] == placement], key=lambda r: r["fault_count"])
            label = "Random" if placement == "random" else "Path-critical"
            axes[0, 0].errorbar([r["fault_count"] for r in rows], [r["success_rate"] for r in rows],
                yerr=[[r["success_rate"] - r["success_ci_low"] for r in rows], [r["success_ci_high"] - r["success_rate"] for r in rows]],
                color=color, marker="o", capsize=3, markersize=4, label=label)
            for ax, metric in zip(list(axes.flat)[1:], ("detour_vs_zero_fault", "replanning_time_ms", "delta_makespan_vs_zero_fault")):
                plot_line(ax, rows, "fault_count", metric, "coordinated", label, color)
        for ax, title in zip(axes.flat, ("(a) Task and recovery success rate", "(b) Remaining length / zero-fault length",
                                        "(c) Replanning time (ms)", "(d) Makespan change vs zero faults")):
            ax.set_title(title, loc="left")
            ax.set_xlabel("Faulty electrodes")
            ax.set_xticks(config["fault_counts"])
        axes[0, 0].set_ylim(-0.03, 1.03)
        axes[0, 0].legend(fontsize=9)
        axes[1, 0].set_ylim(bottom=0)
        style_axes(axes)
        save_figure(fig, folder / "D_fault_robustness.png")


def run(config, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    seeds = list(range(config["seed_start"], config["seed_start"] + config["repeats"]))
    records = []
    started = time.perf_counter()
    save_json(output / "config.json", config)
    with (output / "traces.jsonl").open("w", encoding="utf-8") as traces, (output / "records.jsonl").open("w", encoding="utf-8") as log:
        def store(rows, trace):
            records.extend(rows)
            for row in rows:
                log.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            traces.write(json.dumps(trace, ensure_ascii=False, allow_nan=False) + "\n")
            log.flush()
            traces.flush()

        for size in config["droplet_counts"]:
            for seed in seeds:
                task = scale_task(seed, size, config["scale_obstacle_count"])
                rows, trace, _ = run_triplet(task, config["emission_spacing_steps"])
                for row in rows:
                    row["group"] = "scale"
                trace.update(group="scale", droplet_count=size)
                store(rows, trace)
            print(f"B/A droplets={size}: {len(seeds)} matched tasks", flush=True)

        for width in config["congestion_gate_widths"]:
            for seed in seeds:
                task = congestion_task(seed, config["congestion_droplets"], width)
                rows, trace, _ = run_triplet(task, config["emission_spacing_steps"])
                for row in rows:
                    row.update(group="congestion", gate_width=width)
                trace.update(group="congestion", gate_width=width)
                store(rows, trace)
            print(f"C gate_width={width}: {len(seeds)} matched tasks", flush=True)

        for seed in seeds:
            task = congestion_task(seed, config["fault_droplets"], 3)
            assignments = build_multi_droplet_assignments(task["sources"], task["targets"], _base_planner(), task["obstacles"])
            nominal_valid = check_geometry(assignments, task) and not audit_schedule(assignments)
            if not nominal_valid:
                rows = [dict(group="fault", seed=seed, droplet_count=config["fault_droplets"], method="coordinated",
                             gate_width=None, fault_count=count, placement=placement, eligible=False,
                             success=False, status="nominal_unavailable")
                        for placement in config["fault_placements"] for count in config["fault_counts"]]
                store(rows, dict(group="fault", task=task, status="nominal_unavailable"))
                continue
            step, positions, completed = fault_snapshot(assignments)
            zero, zero_trace = run_fault_trial(task, assignments, step, positions, completed, [])
            for placement in config["fault_placements"]:
                ordered, remaining = fault_order(task, assignments, step, positions, placement)
                for count in config["fault_counts"]:
                    faults = ordered[:count]
                    if len(faults) != count:
                        raise ValueError("Insufficient fault candidates")
                    row, trace = (copy.deepcopy(zero), copy.deepcopy(zero_trace)) if count == 0 else run_fault_trial(
                        task, assignments, step, positions, completed, faults)
                    row.update(placement=placement, faults_on_remaining_path=sum(c in remaining for c in faults))
                    if row["success"] and zero["success"]:
                        row["detour_vs_zero_fault"] = row["spatial_length"] / zero["spatial_length"] if zero["spatial_length"] else None
                        row["delta_makespan_vs_zero_fault"] = row["makespan_steps"] - zero["makespan_steps"]
                    trace.update(group="fault", placement=placement, fault_count=count, task=task,
                                 fault_step=step, original=[assignment_data(a) for a in assignments])
                    store([row], trace)
            print(f"D seed={seed}: random/path-critical faults complete", flush=True)

    summary = summarize(records)
    write_csv(output / "records.csv", records)
    write_csv(output / "failed_replays.csv", [r for r in records if r["status"] == "invalid_replay"],
              fields=sorted({key for row in records for key in row}))
    write_csv(output / "summary.csv", summary)
    save_json(output / "summary.json", summary)
    figure_dir = output / "图片"
    plot_results(summary, config, figure_dir)
    source_files = [Path(__file__), ROOT / "scripts/generate_chapter3_advantage_case.py",
                    ROOT / "scripts/generate_chapter3_results.py",
                    ROOT / "presets/复杂瓶颈并行运输.json", *sorted((ROOT / "dmf/planning").glob("*.py")),
                    ROOT / "dmf/layout.py", ROOT / "dmf/models.py"]
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    save_json(output / "manifest.json", {
        "simulation_only": True, "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "config": config, "seeds": seeds, "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": {name: version(name) for name in ("numpy", "matplotlib", "PyYAML")},
        "git_head": git.stdout.strip() if git.returncode == 0 else None,
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "records": len(records), "elapsed_s": time.perf_counter() - started,
        "mean_errors": "Sample SD; success rates use Wilson 95% intervals. Missing values remain null.",
        "baseline_pairing": "References share final production source-target pairs when available; fallback changes are logged.",
        "completion": "Geometric graph replay plus independent safety audit; not physical arrival.",
        "timing": "Production end-to-end call vs reference route generation plus measured initial greedy assignment; audit/export excluded.",
        "fault_endpoint_policy": "Faults exclude current/target cells and known obstacles. Random placement is uniform over remaining core cells.",
        "fault_baseline": "Same snapshot zero-fault replanning; completed targets stay occupied; all emitted droplets remain present.",
    })
    print(f"Saved {len(records)} records and four figures: {output.resolve()}", flush=True)
    return records, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/chapter3_statistics.yaml")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, help="Override repetitions; recorded in the manifest")
    parser.add_argument("--plot-from", type=Path, help="Redraw an existing summary without rerunning or changing its data")
    args = parser.parse_args()
    if args.plot_from is not None:
        if args.output is not None or args.repeats is not None:
            parser.error("--plot-from cannot be combined with --output or --repeats")
        folder = args.plot_from
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        plot_results(summary, config, folder / "图片")
        save_json(folder / "plot_manifest.json", {
            "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "summary_sha256": hashlib.sha256((folder / "summary.json").read_bytes()).hexdigest(),
            "data_changed": False,
        })
        print(f"Redrawn four figures from unchanged records: {folder.resolve()}")
        return 0
    config = load_config(args.config)
    if args.repeats is not None:
        if args.repeats < 1:
            parser.error("--repeats must be positive")
        config["repeats"] = args.repeats
    output = args.output or ROOT / "results" / ("chapter3_statistics_" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S"))
    run(config, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
