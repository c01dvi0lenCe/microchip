# Operator-only UI Implementation Plan

> For agentic workers: use subagent-driven-development for isolated missing-field validation and independent spec/quality reviews. Main integrates the tightly coupled GUI profile. Preserve this current dirty codex branch in place; do not commit/push, copy or discard user research changes.

**Goal:** main.py is real-experiment-only, open-loop controls live on manual tab, visual tab truthfully unavailable pending acceptance, and incomplete tasks identify exact fields.

**Architecture:** OperatorProfileMixin owns real-only page construction/click intent/visual readiness. Legacy constructor remains research-test compatible; main passes operator_only=True. Shared dmf.layout and existing canvas geometry, planner and APPLIED runner remain single sources.

**Tech Stack:** Tkinter/Python/unittest, existing transaction client and memory serial tests.

## 1. Missing-field diagnostics
- [ ] Add tests for missing start/target/ring and multiple groups, observe current None/unnamed refusal.
- [ ] Export pure four_cell_missing_fields(tasks) from controllers/open_loop_sequence.py and call before core-ID compilation. Return group→tuple of human field labels. Do not infer points.
- [ ] GUI precheck focuses first incomplete group and logs all missing fields. Test no serial submission.

## 2. Hardware-only profile, test first
- [ ] New tests/test_operator_profile.py checks main entry, no simulation constructors/callbacks, fixed hardware semantics, two pages, open-loop/manual parent, disabled visual start, no fake detections and disconnected start.
- [ ] Add controllers/operator_profile.py and composition flag. Use mode_var=实物, sim_camera/detector/sim_droplet=None, sim_droplets=[] for operator; do not schedule/render simulation startup.
- [ ] Branch UiController._build_ui to operator page builder while retaining common header, camera/log panels and shared matrix builder. Real page selection is not an AM trigger.
- [ ] Manual tools choose direct switch vs task picking. Planned-path picking writes start_cell/goal_cell and clears only cached path; group picking delegates to existing handler. Precheck uses unchanged compile/planner/runner. No actuation during picking/precheck.
- [ ] Visual page shows real model/map/arrival/dry-run prerequisite status and disabled Start; guards reject old auto loop and direct simulated methods in operator profile.
- [ ] Shared canvas operator renderer shows electrodes/IDs/command state/task paths only; both pages use identical geometry; no synthetic positions/detections.

## 3. Independent simulation and lifecycle checks
- [ ] Add run_planning_simulator.py using existing compatibility profile, never real hardware mode from that launcher. Keep current frozen research entrypoints.
- [ ] Guard on_mode_changed/operator is_simulation_mode and preset import against entering simulation. Do not enable real output because a preset says simulation.
- [ ] Preserve open-loop ACK/pending/release/camera behavior and manual fault reminders; no firmware/protocol/planner edits.
- [ ] Verify layout IDs and perimeter center/connector geometries match between independent simulation and operator canvases at equal viewport dimensions.

## 4. Review and verify
- [ ] Independent spec review then safety/quality review. Reproduce important findings as tests before fixes.
- [ ] Run compileall, operator/missing-field/open-loop/camera/transaction regression, full unittest and seven software chains. Use temporary data/memory serial only.
- [ ] Record actual counts, failures/warnings, update operator guide and status. No physical completion claims; maintain branch/files uncommitted as requested.

## Completion record — 2026-11-07

All four stages implemented and verified. Original bullets retain the planned steps; this record is their completion state. New29tests (19profile/UI,10missingfields) observedfeature/bug failures beforefixes; existing1260 retained. Independent spec review closed2importantbypasses; qualityreview and late role-picker review approved. Final full discover1289,1288passed/1optional skip,362.139s,exit0,OpenCVtestthreads1. Compileall and7softwarechains passed. Mappeddefaultmanualcanvas322px; memoryPeer2groups7frames withrealclient/hold350/completedhold/release passed. No COM/camera/highvoltage/userapp operation, frozen research moves/overwrites, commit or push. Main is operator_only; simulator explicitindependent. See docs/operator-only-ui-2026-11-07.md and .planning/2026-11-07-operator-only.
