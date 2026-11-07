# Multi-group open-loop implementation plan

> For agentic workers: subagent-driven-development for isolated mechanism work and independent review; main agent integrates GUI. Do not commit/push or operate hardware. Existing dirty files belong to the user.

**Goal:** Execute approved user-drawn multi-group four-cell single-droplet routes synchronously without vision, retaining camera preview/recording and removing research configuration from the default GUI.

**Architecture:** New pure immutable plan/sequence module; reuse the existing APPLIED-paced transaction runner with target sets rather than one electrode. New dedicated editor/controller mixin uses the path canvas. No production perception, firmware, third-chapter planning, frozen simulation or training results change.

**Tech Stack:** Python/Tkinter/unittest; existing layout pull-risk geometry, atomic client, recording observer.

## 1. Pure mechanism, test-first
- [ ] New `controllers/open_loop_sequence.py`, `tests/test_open_loop_sequence.py`.
- [ ] Frozen `FourCellTask(group_id,start,ring,target)`, `OpenLoopPlan.routes` mapping with `length`, `active_at(i)`, `positions_at(i)`; four-cell and generic route compilation.
- [ ] Preserve requested order; full cycles then forward terminal prefix; four-cell start/end inside actual 2x2; reject bad/core IDs, same/adjacent/cross/hold conflicts; forbidden16 red IDs default.
- [ ] `TimedPlanSequence` compatible with existing runner `.route`, `.index`, `.pending`, `.running/.complete`, `.next_request(now,manual_step=False)`, `.applied(target,at)`, `.stop()`, plus pause/resume.
- [ ] Watch missing-feature tests fail then implement; no planner modification. Keep validation practical for9999cycles using repeated transition deduplication.

## 2. Default GUI research-page removal, test-first
- [ ] Default notebook only manual/path pages, no research configuration or run controls. Preserve research algorithms/CLI and an explicit opt-in constructor for legacy GUI adapter regression only.
- [ ] `start_experiment` on default GUI refuses and points to CLI; update obsolete default-tab tests while retaining opt-in experiment adapter regressions.

## 3. Editor and runtime integration, test-first
- [ ] New `controllers/open_loop_controller.py`, `tests/test_open_loop_controller.py`.
- [ ] Task list add/select/delete/clear, source/ring/target picking roles, shared dwell/cycles, precheck, start, pause/resume, manual step, stop. Editor groups do not merge droplets.
- [ ] Freeze route/group/extra holds at start; preview and list per-global-step command positions, not true droplet states. New overlay does not draw synthetic detections.
- [ ] Generalize existing `_timed_mix_submit/_accept` to int or frozen active set, sharing one transaction worker and ownership flag. All starts freshly acknowledged; no duplicate pending. Completed groups and extra holds remain active.
- [ ] Legacy timed single group remains compatible; no old auto_loop or synthetic input invoked for new execution.
- [ ] Runtime session journal saves plan/manifest, requests, APPLIED/serial observer events, steps and terminal reason. Reject preflight forbidden/hold/pull conflicts atomically. Camera preview and recorder remain independent.
- [ ] Pause/manual-step cannot bypass pending ACK; resume restarts current hold conservatively. Stop/reset/close/disconnect follow existing in-flight reconciliation and ALL_OFF ordering.

## 4. Review and verification
- [ ] Independent spec review, then independent safety/quality review; reproduce and fix findings test-first.
- [ ] Compileall, targeted tests, complete unittest discovery, seven independent software chain scenarios.
- [ ] In-memory serial integration, GUI layout inspection, source/data preservation. No COM/camera device opened and no real AM output.
- [ ] Update current status and delivery guide, distinguish sequence completion from physical transport; explain real-vision readiness gates and retain frozen research results.

## Latest scope decision

User approved simultaneous groups, source/target within each2x2, and automatic rejection of16 red zones while manual testing remains available. User also requested the Chapter2 experiment configuration no longer appear in normal upper-computer GUI; interpret this as removing the research configuration/run tab by default, preserving all CLI/backend capabilities.

## Execution closeout — 2026-11-07

All four implementation/review stages above have been executed; original unchecked bullets are retained as the initial plan text, not an outstanding-work list. Pure core and integration spec reviews followed by safety review completed; findings were reproduced test-first and closed. Targeted80 passed; final full1260 ran with1259 passed/1 skipped (575.562s); compileall and seven software chains passed. Memory serial two-group7-batch audit passed; default editor canvas354px; no COM/camera/highvoltage operation. Prior full-run OpenCV error and the successful no-code-change repeat are both retained; intermittent cause is not claimed fixed. Tk cleanup warnings remain recorded.

Current operator guide: `docs/multi-four-cell-open-loop-2026-11-06.md`. Follow-on real-video readiness audit: `docs/chapter2-real-vision-offline-readiness-2026-11-07.md`; four native inference smoke checks are not new GT metrics or physical closed-loop authorization. No commit/push performed.
