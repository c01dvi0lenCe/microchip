# Chapter 2 Formal Simulation Implementation Plan

> **For agentic workers:** Use subagent-driven-development and TDD; retain this dirty checkout at the user's request. No commit/push. User approved the versioned adapter + shared-cache design on 2026-10-21.

**Goal:** Reuse the B1–B4 algorithm in a versioned simulation controller, implement GT-isolated S1–S4/ablation benchmarks, and run reproducible paired simulation only after smoke gates.

**Architecture:** Keep legacy simulation source/CLI unchanged. Add a normalized-unit adapter around formal perception/evidence/policy, a separate paired runner, immutable mask-cache benchmark and version-aware evaluation/export. Human and simulation references remain separate.

**Tech Stack:** Existing Python, NumPy/OpenCV, dataclasses, unittest, YAML, CSV/JSON, matplotlib.

## Task 1 — normalized formal adapter and causal runner

Files: add `dmf/chapter2_sim/formal_adapter.py`, `formal_runner.py`, `tests/test_chapter2_formal_adapter.py`; minimal compatible changes allowed only in `dmf/experiment/evidence.py` and `perception.py` for explicit simulation/ablation seams.

- [x] Write and run failing tests: simulation domain never fills real ACK/host timestamps; duplicate/gap/invalid/old-context clear confirmation; same formal inputs give same states/actions; delayed accept controls counters; local recovery/partial stall bounded; position gate and ledger once.
- [x] Implement `NormalizedMap(geometry)` / `from_snapshot(snapshot)` with coordinate_unit=pitch and documented legacy numeric aliases, not a fabricated mm calibration; `make_frame_packet(frame, ...)`; `state_config(cfg)`, `control_config(cfg)`; `FormalAdapter` using actual PriorFeatures/StateRecognizer/EventController and evidence.
- [x] Public adapter contract: `observe(frame, now_s)` returns a result with packet, observation, state, decision and arrival_event; `tick(now_s)` advances safety clocks without inventing observations; `accept(decision, applied_s, accepted=True)` mutates only on accepted simulated application; expose controller/context/source/target/phase.
- [x] Implement `run_formal_trial(cfg, scenario, seed, method='C', ablation='full') -> TrialResult` with request/APPLIED separation, paired world/camera streams, shared source confirmation, hidden truth evaluator only and explicit method_version. Keep old run_trial unchanged.
- [x] Run new tests plus old causal/evidence/policy/runner/simulation tests, then spec review and quality review.

Example test obligation:
```python
assert adapter.context.clock_domain == 'simulation'
assert adapter.context.applied_receive_ns is None
before = adapter.controller.retry_total
decision = adapter.tick(expired_s)
assert adapter.controller.retry_total == before
adapter.accept(decision, applied_s)
assert adapter.controller.retry_total == before + 1
```

## Task 2 — immutable common mask cache and S1–S4

Files: add `dmf/experiment/mask_cache.py`, `benchmark.py`, tests `test_chapter2_benchmark.py`.

- [x] Test RED: missing/corrupt mask hash, duplicate frame keys, mixed units/clocks, incomplete tasks, GT fields in inputs, duplicate output directory.
- [x] Implement cache with frozen masks/map/parameters, frame capture+available times, task steps and hashes; no world truth or reference path in prediction inputs. Explicit missing-mask rows retained.
- [x] Test RED: S1 single centroid, S2 single eta, S3 spatial target gate, S4 formal causal stability; single-frame groups have no fabricated five-state output; all receive identical input hash; change references without changing predictions.
- [x] Implement `run_variant(cache_dir, variant, output_dir)` with variants S1/S2/S3/S4 and no_spatial/no_temporal/no_validity; task windows teacher-forced; one event/step, missing/Unknown retained.
- [x] Add true-data material validation; no fake weights, human reference, or physical length/time claim.

API invariants:
```python
prediction = run_variant(cache, 'S4', output)
assert prediction['input_sha256'] == run_variant(cache, 'S1', other_output)['input_sha256']
# run_variant has no references argument and never opens an evaluation resource.
```

## Task 3 — independent simulation references and statistics

Files: extend strict event evaluator via separate `evaluate_simulation_events`, add `dmf/chapter2_sim/formal_batch.py` and tests `test_chapter2_formal_statistics.py`.

- [x] RED: human evaluator refuses simulation source; simulation evaluator refuses fake human source; missing/failed/unknown/censored rows retain planned denominators.
- [x] Reuse B4 counting core behind explicit origin validation; never relabel synthetic references human. Output seed-level recall/support, early rates, conditional delay/completion, all-trial execution time, retry/recovery counters and paired CI.
- [x] RED: same seed/config deterministic; versioned methods cannot collide; Wilson/seed-cluster bootstrap use seeds, not frames; failed completion time stays missing.
- [x] Export raw truth/frame/event/trial rows, config/map snapshots and manifest with dirty source hashes/dependencies/seeds/method versions/output hashes. Preserve old batch functions.

## Task 4 — CLI, fixed-input generation, plots, small-to-formal gate

Files: new `run_chapter2_formal_simulation.py`, `scripts/evaluate_chapter2_baselines.py`, `configs/chapter2_formal_simulation.yaml`, fixed-input and plotting modules/tests.

- [x] CLI tests RED then GREEN for smoke/formal/sensitivity/cache/run/evaluate/materials-check, no hardware construction, overwrite refusal.
- [x] Generate teacher-forced simulation inputs with a fixed command schedule; truth only in sibling evaluation files, repeat electrode visits scoped per step.
- [x] Freeze seven scenes; smoke seeds260600–260602; formal261000–261019; six closed-loop methods (ABC + three C ablations); seven offline variants; jitter sensitivity [.75,.85,.95]×[.25,.4,.6].
- [x] Run smoke first:126 closed-loop trials +21 caches/147 offline runs. Inspect counts/causality/failure bounds/CI definitions. Fix bugs under new recorded code hash before final inputs are frozen.
- [x] Only after smoke gate run formal840 comparison/ablation trials +180 sensitivity trials,140 caches/980 offline runs; actual counts, not predictions, enter the report.
- [x] Build new simulation-marked PNG/PDF figures from persisted CSV only; keep all seven scenes and missing/censored values. Perform rendered QA before claiming figure completion.

## Task 5 — review, verification, delivery

- [x] Spec and quality review, reproduce and repair every important finding with regression tests.
- [x] Run baseline/new local regressions, compileall, complete unittest discovery and seven independent control chains; preserve Tk warning/skip history honestly.
- [x] Compare protected baseline hashes (except explicitly allowed shared seams), validate all new manifests and experiment counts.
- [x] Report files/commands/actual quantitative results/method versions/missing real materials/limits; update status and approved design progress. Do not commit/push or run hardware.

Verification commands:
```powershell
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -q
python -m validation.closed_loop_chain.run_validation
git diff --check
```
