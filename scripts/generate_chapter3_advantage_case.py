"""Replay a shared-channel task using the existing planning and scheduling code."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dmf import MultiDropletAssignment, build_multi_droplet_assignments, electrode_id
from dmf.layout import is_reservoir_cell
from dmf.planning.geometry import pull_risk_neighbors
from scripts.generate_chapter3_results import (
    PALETTE, INK, _Canvas, _base_planner, _map_panel, _new_canvas,
    _save_assignments_csv, _save_image, _save_json, _snapshot_action,
    _draw_text, _wait_count, _release_delay,
)

DEFAULT_PRESET = ROOT / "presets" / "复杂瓶颈并行运输.json"


def cell_at(schedule, step):
    return schedule[min(step, len(schedule) - 1)] if step >= 0 and schedule else None


def audit_schedule(assignments):
    """Count one violation type per pair and step, including transition pull risk."""
    horizon = max((len(a.scheduled_path) for a in assignments), default=0)
    events = []
    for step in range(horizon):
        for i, a in enumerate(assignments):
            current = cell_at(a.scheduled_path, step)
            previous = cell_at(a.scheduled_path, step - 1)
            if current is None:
                continue
            for b in assignments[i + 1:]:
                other = cell_at(b.scheduled_path, step)
                other_previous = cell_at(b.scheduled_path, step - 1)
                if other is None:
                    continue
                kind = None
                if current == other:
                    kind = "vertex"
                elif previous == other and other_previous == current:
                    kind = "edge_swap"
                elif other in pull_risk_neighbors(current):
                    kind = "spacing"
                elif (
                    previous is not None and current != previous
                    and other_previous in pull_risk_neighbors(current)
                ) or (
                    other_previous is not None and other != other_previous
                    and previous in pull_risk_neighbors(other)
                ):
                    kind = "transition_spacing"
                if kind:
                    events.append({
                        "step": step, "droplet_a": a.droplet_id, "droplet_b": b.droplet_id,
                        "type": kind, "cross_source": a.source != b.source,
                        "cell_a": current, "cell_b": other,
                        "previous_a": previous, "previous_b": other_previous,
                    })
    return events


def uncoordinated_reference(assignments, planner, obstacles, emission_spacing=3):
    """Use shortest A* routes with fixed per-reservoir dispensing intervals."""
    released = defaultdict(int)
    result = []
    for a in assignments:
        path = planner.plan(a.source, a.target, obstacles)
        if not path:
            raise ValueError(f"No independent A* path for D{a.droplet_id}")
        delay = emission_spacing * released[a.source]
        released[a.source] += 1
        result.append(MultiDropletAssignment(a.droplet_id, a.source, a.target, path, [None] * delay + path))
    return result


def serial_reference(assignments, planner, obstacles):
    """Dispense one task at a time and keep completed targets protected."""
    if any(not is_reservoir_cell(a.source) for a in assignments):
        raise ValueError("This serial reference requires unproduced reservoir droplets")
    result = []
    cursor = 0
    parked = set()
    for a in assignments:
        path = planner.plan(a.source, a.target, set(obstacles) | parked)
        if not path:
            raise ValueError(f"Serial task D{a.droplet_id} is unreachable")
        result.append(MultiDropletAssignment(a.droplet_id, a.source, a.target, path, [None] * cursor + path))
        # The next source may be enabled on the previous droplet's arrival step.
        cursor += len(path) - 1
        parked.update(pull_risk_neighbors(a.target))
    return result


def metrics(name, assignments):
    events = audit_schedule(assignments)
    horizon = max(len(a.scheduled_path) for a in assignments)
    moving = [sum(
        cell_at(a.scheduled_path, t - 1) is not None
        and cell_at(a.scheduled_path, t) != cell_at(a.scheduled_path, t - 1)
        for a in assignments
    ) for t in range(horizon)]
    types = Counter(e["type"] for e in events)
    return {
        "method": name, "droplets": len(assignments),
        "spatial_length": sum(len(a.path) - 1 for a in assignments),
        "makespan_steps": horizon - 1,
        "wait_steps": sum(_wait_count(a.scheduled_path) for a in assignments),
        "total_release_delay_steps": sum(_release_delay(a.scheduled_path) for a in assignments),
        "peak_simultaneous_moves": max(moving),
        "conflict_pair_steps": len(events),
        "cross_source_conflict_pair_steps": sum(e["cross_source"] for e in events),
        "vertex": types["vertex"], "edge_swap": types["edge_swap"],
        "spacing": types["spacing"], "transition_spacing": types["transition_spacing"],
        "safety_valid": not events,
    }


def evaluate_case(preset_path=DEFAULT_PRESET):
    preset = json.loads(Path(preset_path).read_text(encoding="utf-8"))
    settings = preset["settings"]
    sources = sorted({tuple(c) for c in settings["loaded_reservoirs"]}, key=lambda c: electrode_id(*c))
    targets = [tuple(c) for c in settings["target_shape_cells"]]
    obstacles = {tuple(c) for c in settings["obstacle_cells"]}
    if settings.get("initial_droplet_cells") or settings.get("faulty_electrodes"):
        raise ValueError("This benchmark uses reservoir dispensing and static obstacles")
    if any(target in obstacles for target in targets):
        raise ValueError("A target overlaps an obstacle")
    if any(b in pull_risk_neighbors(a) for i, a in enumerate(targets) for b in targets[i + 1:]):
        raise ValueError("Targets must retain distinct droplets outside each other's pull-risk zone")
    planner = _base_planner()
    timing = {}
    proposed = build_multi_droplet_assignments(sources, targets, planner, obstacles, planning_metrics=timing)
    if len(proposed) != len(targets):
        raise ValueError("The production planner did not assign every target")
    baseline = uncoordinated_reference(proposed, planner, obstacles)
    serial = serial_reference(proposed, planner, obstacles)
    rows = [metrics("static_astar_fixed_dispensing", baseline), metrics("safe_serial", serial), metrics("coordinated", proposed)]
    if not rows[1]["safety_valid"] or not rows[2]["safety_valid"]:
        raise ValueError("A purported safe reference failed the independent audit")
    if not rows[0]["cross_source_conflict_pair_steps"] or rows[2]["peak_simultaneous_moves"] < 2:
        raise ValueError("The scene does not exercise multi-source temporal coordination")
    return preset, sources, targets, obstacles, proposed, baseline, serial, rows, timing


def assignment_data(a):
    return {"droplet_id": a.droplet_id, "source": a.source, "target": a.target,
            "path": a.path, "scheduled_path": a.scheduled_path}


def generate(output_dir, preset_path=DEFAULT_PRESET):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    preset, sources, targets, obstacles, proposed, baseline, serial, rows, timing = evaluate_case(preset_path)
    source_colors = {source: PALETTE[i % len(PALETTE)] for i, source in enumerate(sources)}
    colors = {a.droplet_id: source_colors[a.source] for a in proposed}
    common = dict(sources=sources, targets=targets, obstacles=obstacles, source_colors=source_colors, route_colors=colors)
    droplet_count = len(proposed)
    makespan = rows[2]["makespan_steps"]
    image = _new_canvas(1880, 990)
    _map_panel(image, (45, 40, 890, 820), proposed, paths="static", title="(a) Planned routes", **common)
    _map_panel(image, (930, 40, 1775, 820), proposed, frame=makespan, title="(b) Final occupancy", **common)
    _draw_text(_Canvas(image), (65, 910), f"$N_d={droplet_count},\\quad L_{{\\mathrm{{total}}}}={rows[2]['spatial_length']},\\quad T_{{\\mathrm{{makespan}}}}={makespan},\\quad N_{{\\mathrm{{wait}}}}={rows[2]['wait_steps']}$", 21)
    _save_image(image, output_dir / "01_complex_routes.png")

    events = audit_schedule(baseline)
    candidates = {e["step"] for e in events if e["cross_source"]}
    # Prefer a conflict step where all positions remain individually visible.
    unique_steps = [t for t in candidates if not any(e["type"] == "vertex" and e["step"] == t for e in events)]
    candidates = unique_steps or sorted(candidates)
    critical_step = max(sorted(candidates), key=lambda t: sum(e["step"] == t and e["cross_source"] for e in events))
    critical_events = [e for e in events if e["step"] == critical_step]
    conflict_cells = {e[key] for e in critical_events for key in ("cell_a", "cell_b", "previous_a", "previous_b") if e[key] is not None}
    image = _new_canvas(1880, 990)
    _map_panel(image, (45, 40, 890, 820), baseline, frame=critical_step, show_routes=False, conflict_cells=conflict_cells, title=f"(a) Static A*: t={critical_step}", **common)
    _map_panel(image, (930, 40, 1775, 820), proposed, frame=critical_step, show_routes=False, title=f"(b) Coordinated: t={critical_step}", **common)
    _draw_text(_Canvas(image), (65, 910), f"$C_{{\\mathrm{{static}}}}={rows[0]['conflict_pair_steps']},\\quad C_{{\\mathrm{{coord}}}}=0,\\quad T_{{\\mathrm{{serial}}}}={rows[1]['makespan_steps']},\\quad T_{{\\mathrm{{coord}}}}={makespan}$", 21)
    _save_image(image, output_dir / "02_coordination_comparison.png")

    snapshot_steps = [0, round(makespan / 3), round(2 * makespan / 3), makespan]
    image = _new_canvas(1880, 1490)
    snapshots = []
    for label, step, (x, y) in zip("abcd", snapshot_steps, [(35, 45), (965, 45), (35, 715), (965, 715)]):
        _map_panel(image, (x, y, x + 880, y + 640), proposed, frame=step, show_routes=False, title=f"({label}) t={step}", **common)
        snapshots.append({"step": step, "droplets": [
            {"droplet_id": a.droplet_id, "action": _snapshot_action(a.scheduled_path, step, a.target)[0],
             "current": cell_at(a.scheduled_path, step), "next": cell_at(a.scheduled_path, step + 1)}
            for a in proposed if cell_at(a.scheduled_path, step) is not None
        ]})
    _draw_text(_Canvas(image), (65, 1420), f"$N_d={droplet_count},\\quad T_{{\\mathrm{{makespan}}}}={makespan},\\quad N_{{\\mathrm{{wait}}}}={rows[2]['wait_steps']}$", 21)
    _save_image(image, output_dir / "03_parallel_execution.png")

    for name, assignments in (("coordinated", proposed), ("uncoordinated", baseline), ("serial", serial)):
        _save_assignments_csv(output_dir / f"{name}_assignments.csv", assignments, method=name)
    with (output_dir / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _save_json(output_dir / "preset.json", preset)
    summary = {
        "simulation_only": True, "input_preset": str(Path(preset_path).resolve()),
        "input_sha256": hashlib.sha256(Path(preset_path).read_bytes()).hexdigest(),
        "sources": sources, "targets": targets, "obstacles": sorted(obstacles),
        "source_colors": [{"source": src, "color": color} for src, color in source_colors.items()],
        "comparators_share_source_target_pairs": True,
        "uncoordinated_emission_spacing_steps": 3,
        "metrics": rows, "planning_time_ms": timing,
        "makespan_reduction_vs_safe_serial_percent": 100 * (1 - makespan / rows[1]["makespan_steps"]),
        "critical_step": critical_step, "uncoordinated_conflicts": events,
        "snapshot_steps": snapshot_steps, "snapshots": snapshots,
        "coordinated": [assignment_data(a) for a in proposed],
        "uncoordinated": [assignment_data(a) for a in baseline],
        "serial": [assignment_data(a) for a in serial],
        "final_targets_reached_in_safe_replay": all(a.scheduled_path[-1] == a.target for a in proposed + serial),
    }
    _save_json(output_dir / "summary.json", summary)
    (output_dir / "README.md").write_text(
        "# Shared-channel coordination case\n\n"
        "Import presets/复杂瓶颈并行运输.json in the existing GUI. It uses four source reservoirs, eight targets, and 39 static obstacles.\n\n"
        "The barrier has a three-column passage at ROW 11 / COL 10-12 (one-based); staggered obstacle clusters force multi-turn approaches.\n\n"
        "All comparators use the same source-target assignment. Static A* uses independent shortest obstacle-avoiding routes and a fixed three-step interval between emissions from the same reservoir, without inter-source coordination. Its geometric replay fails the safety audit and is not a successful transport run.\n\n"
        "The safe serial reference releases one task at a time and reroutes around completed targets and their pull-risk zones. The next source may be enabled on the previous arrival step. The proposed result is exported unchanged from build_multi_droplet_assignments. No algorithm settings are tuned in the exporter.\n\n"
        "Conflicts are counted once per droplet pair and discrete time step, classified as vertex, edge swap, spacing, or transition spacing. The audit includes completed-goal holds through the entire horizon. The coordinate snapshots all use one shared schedule clock. W indicates waiting; red shading in the comparison marks implicated cells. Colors identify source reservoirs, and IDs identify individual drops.\n\n"
        "Makespan is a discrete schedule-step count, not elapsed hardware time. This is a deliberately constructed bottleneck example supporting coordination and parallelism claims against these explicit references, not a proof of global optimality or general superiority across datasets.\n",
        encoding="utf-8",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", type=Path, default=DEFAULT_PRESET)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "chapter3_complex_benchmark")
    args = parser.parse_args()
    result = generate(args.output, args.preset)
    print(f"Generated: {args.output.resolve()}")
    for row in result["metrics"]:
        print(f"{row['method']}: L={row['spatial_length']} T={row['makespan_steps']} W={row['wait_steps']} conflicts={row['conflict_pair_steps']} parallel_moves={row['peak_simultaneous_moves']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
