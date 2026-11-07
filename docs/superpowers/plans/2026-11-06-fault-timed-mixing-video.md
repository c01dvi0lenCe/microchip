# Fault reminders, timed mixing and video screening implementation plan

> For agentic workers: execute inline with checkpoints; no commit/push or hardware operation.

**Goal:** Add visual-only red reminders and independent APPLIED-timed 2×2 mixing, then prepare traceable new-video annotation candidates.

**Architecture:** Pure `controllers/timed_mixing.py` owns route validation and APPLIED-paced timing. A dedicated GUI mixin owns asynchronous transaction submission and Tk polling. Existing serial client/protocol remains unchanged. Fault reminders are independent from simulation faults and routing obstacles.

**Tech Stack:** Python, Tkinter, existing atomic transaction client, unittest; existing real-video screening workflow/OpenCV/Pillow for offline data only.

## Task 1: red-first pure mechanism tests
- [ ] Add tests for exact19 reminder IDs and unchanged 400/20 boundary.
- [ ] Add tests for `build_square_route(190,2)` => `[190,191,211,210,190,191,211,210,190]`, rejecting20/381/400.
- [ ] Add tests for waiting APPLIED, exact dwell, one pending target, stop/late acknowledgement, finite time and integer cycles.
- [ ] Run `python -m unittest tests.test_timed_mixing -v`; observe missing-feature failures before implementation.
- [ ] Implement pure route/sequencer and rerun.

## Task 2: UI integration tests then implementation
- [ ] Add Tk tests for red reminders under active state, manual clicks still work, manual control widgets, ownership/stop/close/reset/mode guards.
- [ ] Run failing tests before integration.
- [ ] Add dedicated mixin `controllers/timed_mixing_controller.py`, integrate in `app_controller.py`, `ui_controller.py`, `hardware_runtime.py`, lifecycle guards, and canvas color overlay.
- [ ] Worker uses existing transaction client; UI only polls results. Timer starts after successful APPLIED software receive/result, never before.
- [ ] Stop cancels future requests, reconciles any in-flight ACK, and keeps ownership until it settles. Pending-stop is not a physical cancel claim. ALL_OFF/reset waits until pending transaction settled to prevent late reactivation.
- [ ] Run new tests plus `tests.test_main_controller`, transaction tests and independent validation.

## Task 3: new video data
- [ ] Reuse source recording inventory SHA/timestamp checks into a new 1106 output directory.
- [ ] Generate traceable overview/operation candidates for final2 recordings; evaluate earlier4 sparsely without claiming full review.
- [ ] Keep candidate Mask unreviewed and split unassigned until chosen batch-level holdout plan; preserve old180 and model results.
- [ ] Deliver new-video quality verdict and proposed train/validation role; no new model training.

## Task 4: verification
- [ ] `python -m compileall -q main.py app_controller.py controllers dmf simulation validation`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python -m validation.closed_loop_chain.run_validation`
- [ ] Record changed files, tests, immutable research protection and remaining physical checks.

Design self-review: visual-only matches user's latest explicit choice; phase timing and pending-stop semantics remain distinct from physical droplet confirmation. No calibration or truth labels fabricated.
