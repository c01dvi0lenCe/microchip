# Chapter 3: Known-Fault Multi-Droplet Replanning

## Scope

This addition preserves the existing greedy source-to-target assignment, static A*,
and reservation scheduler. It adds known faulty-electrode masking and global
rerouting/rescheduling for a running multi-droplet simulation. Fault locations are
provided by the operator; no automatic diagnosis is performed.

## Reproducible simulation

For a preplanned fault, select simulation mode and the multi-droplet operation,
choose **设置已知故障电极**, and click a core-array cell before planning. It is
shown separately from a user static obstacle, saved in task presets/undo snapshots,
and combined with static obstacles for routing. Faults on selected sources or
targets are rejected.

For a runtime fault, start a multi-droplet simulation, reveal the simulation tests,
enter a core electrode ID from 1 to 400, then select **注入并全局重排**. The ID uses
the existing row-major 20 x 20 core mapping. All unfinished droplets are replanned
from their current simulated cells to their original targets. Completed droplets
remain on their goals; those goals and their pull-risk neighborhoods constrain the
new routes. A successful schedule starts at a fresh local step zero. If a fault is
occupied, makes a route unreachable, or prevents safe scheduling, the run enters
protective hold and reports the reason.

Execution-deviation recovery remains a separate single-droplet path correction.
It is not called local repair and is not used for faulty-electrode events.

## Metrics

The operation-metrics CSV adds:

- `path_lengths`, `total_spatial_path_length`: initial A* lengths in electrode steps.
- `scheduled_makespan_steps`: maximum initial discrete schedule length minus one;
  it is not elapsed physical time.
- `wait_steps_by_droplet`, `wait_steps_total`: repeated non-empty adjacent scheduled
  cells; `None` release prefix is excluded.
- `release_delay_steps_by_droplet`: first non-empty schedule index.
- `deviation_replan_count`, `fault_global_replan_count`, and aggregate `replan_count`.
- `fault_replan_compute_times_ms`, `fault_detour_ratios`, and `faulty_electrodes`.
- `assignment_time_ms`, `routing_time_ms`, `scheduling_time_ms`, and
  `total_planning_time_ms` for the initial plan.
- `planning_status`: `success`, `unreachable`, `protective_pause`, or `completed`.

The computation time for a fault event is measured separately and includes the
fault-triggered route/schedule work plus its runtime overhead. Per-stage initial
planning times use `perf_counter_ns`; routing time sums measured Static A* calls,
while assignment and scheduling times exclude those calls.

## Algorithm boundary

The implemented fault chain is:

```text
known fault -> static obstacle union -> Static A* for every unfinished droplet
-> existing reservation scheduler with completed-goal holds -> new local timeline
-> continue simulation or protective pause
```

Task DAG, time-expanded A*, CBS, reinforcement learning, and automatic fault
diagnosis are not implemented. Multi-droplet execution on real AM hardware is not
implemented or validated; this feature is for reproducible simulation studies.

## Simulation display and result figures

Each source reservoir has one fixed liquid color. Released droplets and route
arrows share that source color; individual droplets retain their own IDs. The GUI
captures this association when planning, so a runtime replan from a new current
cell does not change the liquid color.

During multi-droplet execution, the canvas shows each droplet's next scheduled
move or a `W` for waiting. Targets retain their green outlines. Reservoir pads use
straight borders and fit within the board; routes have no background bands or
artificial core-entry markers. Manual electrode IDs and hit geometry are retained.

Run `python scripts/generate_chapter3_results.py` to export images and data to
`results/chapter3_simulation_results/`. When present, the user's
`presets/复杂瓶颈并行运输.json` supplies the recommended Figure 01 (the original
`presets/多液滴正常路径调度.json` is retained as a fallback), and
`presets/多液滴正常路径调度2.json` supplies the supplementary initial-droplet case.
The configuration snapshots, paths, schedules, and conflict checks are saved
alongside the figures. The second preset's existing faults do not intersect its
nominal paths, so that case is not used as fault-detour evidence.

## Shared-channel comparison

Import `presets/复杂瓶颈并行运输.json` to replay the recommended complex case:
four reservoirs, eight transported droplets, 39 obstacle electrodes, and a
three-column passage at ROW 11 / COL 10-12. All target positions are separated
by at least one intervening core electrode.

`python scripts/generate_chapter3_advantage_case.py` exports planned trajectories,
same-clock coordination comparison, four execution snapshots, complete schedules,
and comparator metrics to `results/chapter3_complex_benchmark/`.
The independent audit checks same-cell occupancy, swaps, present spacing and
cross-step pull risk, including settled-goal holds. Comparators share the exact
source-target pairs: independent Static A* with fixed per-source dispensing,
safe one-at-a-time transport, and the unmodified production coordinator.
Only the two safe comparators support completion-time comparison. This purposely
constructed example demonstrates mechanisms, not global optimality or statistical
superiority over other planning algorithms.

## Identity-preserving runtime continuation (2026-10-06)

The fill-batch fallback now locks each existing droplet to its original target
and current start when `hold_start_during_delay=True`. Even a droplet currently
on a reservoir pad is an existing entity, not a new five-drop dispensing pool.
The complete result is validated before any live assignment is changed. A wrong
source, target, or disappearing schedule causes protective pause without partial
mutation. Normal initial dispensing retains its previous assignment behavior.

`scripts/replay_chapter3_fault_fix.py` replays stored v1 states against the
hash-verified archived v1 modules and current v2 modules in separate namespaces.
Among 280 matched fault trials, nine false-success identity violations become
proper protective pauses. The 245 valid successes retain their lengths and
makespans. This is a correctness fix, not an improvement in recovery success rate.
See `docs/chapter3-statistics.md` for the comparison and timing definitions.
