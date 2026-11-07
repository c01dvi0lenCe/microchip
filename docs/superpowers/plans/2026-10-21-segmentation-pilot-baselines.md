# Segmentation Pilot baseline implementation plan

> Execute inline against the current dirty workspace; no commit, push, worktree reset or sub-agent work. User approved the next Pilot operation after confirming all 18 Masks on 2026-10-21.

**Goal:** Run a reproducible, segmentation-only descriptive Pilot on the 18 human-reviewed images without touching control algorithms or pretending it is a held-out test.

**Architecture:** A new `dmf/segmentation_research/` package validates reviewed samples, freezes exact image/Mask copies and provenance, runs image-only baselines through the existing VisionResult contract, and reuses existing segmentation metric functions. A standalone CLI writes to a new chapter folder, refuses overwrites, and records unavailable U-Net rather than inventing outputs.

**Tech Stack:** Python unittest, OpenCV, NumPy, existing image I/O / metrics / contour postprocessing. No additional runtime dependencies.

**Completed:** All tasks below executed. 20 new tests pass, final full regression 566 tests (565 pass / 1 optional skip, 110.577s); compile/diff and seven independent chains pass. User clarified all 10 videos share one chip/loading/round, so an external hash-keyed group manifest is enforced and no independent-group inference is made. Final results use v2 group-confirmed output; v1 is retained history. No commit/push.

## Frozen Pilot choices (before inspecting algorithm scores)

- Fixed single-target native ROI; no resizing, no mm, no state classification.
- Both methods: grayscale, Gaussian blur 5x5; inverted threshold; morphology kernel 3, open 1 / close 2; reject border-connected components because the selected target must be fully visible; largest remaining external contour filled, min contour area 40 px. Border rejection and contour fill are explicit task priors, not GT-derived masks.
- Otsu uses per-image histogram threshold (not label-based tuning); Adaptive uses Gaussian block 51, C=5. No parameter scan or selection on these 18 images.
- CPU/OpenCV one thread; warmup 5, timed repeats 10 per image. Wall timing includes preprocessing, segmentation and postprocessing, excludes decoding / metrics / saving. Report input sizes and individual observations, mean/P50/P95; no real-camera throughput claim.
- All 18 approved images remain development/Pilot, split unassigned. Report per-image and equal-parent-video macro summaries; no confidence interval or hypothesis test with only 3 selected videos and unknown chip/session independence.
- Missing predictions, raised inference errors and empty masks remain in overlap denominators. Conditional centroid-error denominator and positive-GT miss count are explicit.
- No training or formal test result until grouped split, sufficient independent reviewed data and model workflow are ready.

## Tasks

### 1. Reviewed data validation and snapshot

Files: new `dmf/segmentation_research/data.py`, `__init__.py`, `tests/test_segmentation_research.py`.

- [x] Write tests for Unknown-state acceptance, unreviewed/duplicate/bad Mask rejection, parent/hash/group leakage, unassigned formal split rejection, and immutable snapshot.
- [x] Run `python -m unittest tests.test_segmentation_research -v`, confirm missing implementation is RED.
- [x] Implement `load_reviewed(path, formal=False)` and `freeze_samples(samples, output)`; validate image/Mask bytes, source IDs, SHA and ROI; do not invent chip/session.
- [x] Re-run tests to GREEN.

### 2. Image-only baselines and failure-preserving metrics

Files: new `baselines.py`, `evaluation.py`, same test file.

- [x] Add tests with hand-created binary geometry: dark object, border distractor, empty image, wrong dimensions, missing prediction, raised inference failure, pixel centroid error and unequal-video aggregation.
- [x] Run RED; implement `ThresholdBaseline`, `score_prediction`, `summarize_rows`, `run_pilot`; re-run GREEN.
- [x] Ensure methods receive only FramePacket, never GT; hash the frozen config and source/image/Mask records.

### 3. CLI and actual Pilot run

Files: new `run_segmentation_pilot.py`, `configs/chapter2_segmentation_pilot.json`, independent research documentation.

- [x] Add CLI test: no output overwrite; 2 methods / same frame count / prediction PNGs / CSV / configuration manifest / unavailable U-Net status.
- [x] Run RED then implement CLI. Validate timings with warmup and repeated successful/failed calls retained separately.
- [x] Audit original workspace inputs with existing PilotWorkspace, freeze approved samples, run the real 18-image Pilot using frozen defaults; repeat unchanged parameters in v2 to record user-confirmed grouping.
- [x] Inspect representative prediction masks including lowest-scoring failure without parameter tuning; record limitations and data-expansion entry, not formal Fig.A-D.

### 4. Verification and handoff

- [x] Local new tests plus existing annotation, metrics, inference and runner tests.
- [x] Compileall, full unittest discovery and seven independent control-chain checks. Record skips/warnings/failures literally.
- [x] Compare protected source hashes and source-image/Mask hashes, update planning and actual status, no commit/push.
- [x] Deliver real Pilot metrics with 18 frames / 3 parent videos / 1 acquisition group explicitly; U-Net and held-out evaluation not completed.
