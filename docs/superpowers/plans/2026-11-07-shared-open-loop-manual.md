# Shared Open-loop / Manual Transactions Implementation Plan

> For agentic workers: use subagent-driven-development for the pure overlay seam and independent spec then quality reviews. Main integrates existing worker lifecycle. Preserve current dirty branch and all user changes; no worktree copying, commit/push or hardware.

**Goal:** Operator manual switches coexist with timed paths without racing or overwriting each other. Latest user decision supersedes pause-confirm: original task-route electrodes cannot be switched manually; unsafe external changes are refused. Colors follow APPLIED only.

**Architecture:** New pure OpenLoopManualOverlay(plan) derives task targets plus dynamic holds, validates remaining route conflicts using existing compiler, and reconciles acknowledged state. A dedicated manual-session mixin owns bounded intents and dispatch revalidation; existing timed runner remains the only serial worker. Manual marker results never call sequence.applied.

**Tech stack:** Python/Tkinter/unittest, existing delta transaction and AsyncCsvLog.

## 1. Pure overlay, TDD
- [x] New controllers/open_loop_manual.py and tests/test_open_loop_manual.py.
- [x] API targets_at(phase), current_task_ids(phase), conflict_reasons(changes,phase), reconcile(active_ids,phase), validate_resume(active_ids,phase). IDs1..420; immutable original plan, mutable acknowledged holds.
- [x] Remaining paths are sliced at current phase with completed groups held; reuse compile_routes. Original task list remains protected in full; external holds can be edited, no implicit neighbor closure.
- [x] Task electrodes and conflicting external changes are rejected, with no confirm override; extra holds can be switched OFF.

## 2. Runtime, test-first
- [x] New controllers/open_loop_manual_controller.py and tests/test_open_loop_manual_controller.py. Hook only real operator open_loop ownership, retain other ownership guards.
- [x] Initialize overlay/deque/inflight intent at start. Request UI toggles explicit acknowledged current state; per-electrode pending duplicates rejected, queue capacity64.
- [x] Manual conflict: refuse entire intent, leave task timing unchanged; no modal override (latest user decision).
- [x] Factor _timed_mix_start_transaction(token,changes) from existing submit. Preserve existing five-field result queue; use immutable ManualTransaction marker. Manual receive updates UI/overlay/log only; route receive calls sequence.applied with original token but logs actual composed active set.
- [x] Process FIFO manual intents before new path frames, never while another worker is pending. Manual no-op recorded without fake ACK. Stop/failure/close cancel unissued intents and drain only actual in-flight transaction.
- [x] Task protection applies through direct toggle, canvas, batch, paused, resumed and single-step paths; no manual intervention override exists.

## 3. View / trace
- [x] Pending manual/task changes outlined while fill remains last APPLIED; shared update_ui_only refreshes both canvases. Keep red fault border/green ON indicator.
- [x] Extend journal with manual_commands.csv and new source hashes. Record queued/submitted/APPLIED/rejected/cancelled/failed status and actual sequence; retain old results unchanged.
- [x] Operator manual_toggle bypasses adjacent-off behavior during shared session, and _apply_manual... routes through queue before old lock. Other modes unchanged.

## 4. Review / verification
- [x] Reproduce RED then GREEN: safe manual hold survives next frame; manualACK does not increment step; stop pending and ALL_OFF ordering; task/conflict refusal; ACK-only colors and external-SYNC race protection.
- [x] Independent spec review then quality/safety review; close SYNC issue with two regression cases.
- [x] Compile, focused40, final full1329 (1328passed/1optional skip), seven independent software chains and memory peer. No user main.py operation, real COM/camera/highvoltage or frozen experiment writes.
- [x] Update guide/status and actual test results, leave work uncommitted. Evidence: .planning/2026-11-07-shared-manual/.
