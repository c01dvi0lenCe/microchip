# Image–Design Registration Implementation Plan

> Execution: inline in the existing dirty checkout to preserve the user's uncommitted dependency chain. No worktree copying, commit or push. Checkpoints are tests and the final human point review.

**Goal:** Prepare a provenance-checked, offline registration work package without inventing observed reference points or accuracy.

**Architecture:** Pure registration math and review validation in one new vision module; a separate workspace/CLI and a small GUI reuse existing image I/O and ImageCanvas. Runtime calibration and controllers remain untouched.

**Tech Stack:** Python, NumPy, OpenCV, Pillow, Tk, Matplotlib.

## Task 1 — Red regression tests

- [ ] Create `tests/test_design_registration.py` with known projective correspondences, held-out checks with hand-computable 3-4-5 errors, pending observations, duplicate features, degenerate geometry, frozen fit tampering, point outside image and wrong map hash.
- [ ] Run `python -m unittest discover -s tests -p test_design_registration.py -v`; verify expected missing-feature failures.

Completed: initial 18 expected RED failures, final 22 geometry tests GREEN. Four later tests added for independently hand-computable percentiles and post-result observation sealing.

## Task 2 — Pure offline registration

- [ ] Add `dmf/vision/design_registration.py`: `load_design_map(path, expected_sha256)`, `fit_transform(points)`, `freeze_fit(workspace)`, `evaluate_registration(workspace)`, `record_observation(workspace, point_id, pixel, reviewer)`. Projection reuses existing calibrated transform helper.
- [ ] Reject nonfinite/duplicate/out-of-frame observations, altered point catalog and altered frozen fit; no check coordinate enters fitting.
- [ ] Rerun Task 1 until all pass; add a failing test before each uncovered behavior is implemented.

Completed; all 22 pass. Complete check results are also sealed before first exposure.

## Task 3 — Reproducible workspace and review UI

- [ ] Add `dmf/vision/registration_workspace.py`, `dmf/vision/registration_gui.py`, `run_design_registration.py` and command tests.
- [ ] `prepare` validates confirmed design manifest and copies only three known native real-video reference frames; validates original videos against their resource manifest and copied PNG hashes.
- [ ] Predeclare 8 fit/16 check actual polygon vertices. Projected suggestions remain distinct from null observed pixels. Freeze fit before allowing check clicks; hide residuals during point review.
- [ ] Reuse `ImageCanvas` for full-resolution zoom/pan. Saving generates a new report folder, never replaces earlier reports.

Completed; 12 additional file/CLI/GUI/figure tests pass. New workspace contains three native real-video frames with original source/video/map hashes verified; additional fresh decoder comparison was pixel-exact for all three.

## Task 4 — Review figures and delivery

- [ ] Add `dmf/vision/registration_plotting.py`, covered by an output smoke test. Export single-image overlays and point navigation with explicit pending labels, all 420 real polygons and selected readable IDs; no physical scale bar.
- [ ] Figure contract: one review image per file, white margin, 183mm wide, editable >=7pt text, SVG/PDF/600dpi PNG. Single-panel alignment not applicable; execute PDF glyph and collision QA and inspect output.
- [ ] Generate new chapter directory, manifests, CSV, summary with null metrics until human confirmation. Document excluded non-industrial photo and bare contact-board video.
- [ ] Run local, full regression, compile, independent software-chain validator, protected file hash comparison. Record exact outcomes and remaining human review.

Completed for the pending-review deliverable: final 34 local tests pass, full 608 tests (607 pass, 1 optional skip), compile/diff and all seven software chains pass; 102 protected pre-existing code/config files unchanged. Six final single-image PDF figures pass glyph/collision QA. Human fit/check confirmation and actual accuracy remain explicitly pending; no fabricated numerical result.
