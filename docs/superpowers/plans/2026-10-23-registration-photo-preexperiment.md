# Photo Registration Pre-experiment Implementation Plan

> Inline execution of the approved independent-registration design; no commit/push or worktree replacement of the existing dirty checkout.

**Goal:** Prepare two true industrial-camera photos for manual registration pre-experiment, never final calibration.

**Architecture:** Add `registration_photos.prepare_photo_workspace` for native PNG/hash/input provenance. Reuse all point review, fitting, report and launch machinery. Existing video inputs remain backward compatible.

**Tech Stack:** Existing Python/OpenCV/NumPy/Tk/Matplotlib stack.

## Tasks and verification

Execution complete for the pending-human-review package: all tasks below executed; 12 new tests RED→GREEN, 48 registration regressions pass, full 622 (621 pass/1 optional skip), seven validators pass. Four final PDF plates pass glyph/collision audits. No new manual pixels or accuracy claims. Human review is the next checkpoint, not an unimplemented software task.

- [ ] Create `tests/test_registration_photos.py` with: source kind has no invented video/frame; 8fit/16check all pending; preserved PNG; unconfirmed source/bad hash/invalid or out-of-frame navigation quad/duplicate identity/final-purpose input rejected; output not overwritten; CLI route; source and pre-experiment figure labels; GUI title.
- [ ] Run `python -m unittest discover -s tests -p test_registration_photos.py -v` and verify expected missing-feature RED failures.
- [ ] Add `dmf/vision/registration_photos.py` exposing `prepare_photo_workspace(design_directory, inputs_path, output)`. Preflight complete input before creating output; use `point_catalog(design, inverse_h)` and `seal_catalog(workspace)`; all observed pixels remain null.
- [ ] Extend `run_design_registration.py` with `prepare-photos --design-dir --inputs --output [--no-figures]`; preserve existing prepare/review/build.
- [ ] Extend only source/scope labels in `registration_plotting.py`, a pre-experiment banner/title in `registration_gui.py`, and propagation of scope flags in `registration_workspace.build_report`; do not alter fitting/thresholds or existing review state machines.
- [ ] Add frozen `configs/chapter2_registration_photo_preexperiment.json` with both SHA256s and unconfirmed navigation quadrilaterals. Generate a new chapter directory. Manual review remains required.
- [ ] Run `python -m unittest discover -s tests -p '*registration*.py' -v`, compile, full test discovery and software validator. Compare protected pre-existing source/workspace/photo hashes.
- [ ] Run source/PDF glyph/collision QA on four new review figures, inspect all outputs and write bounded delivery notes with actual test outcomes. No experimental precision claim until real point review completes.
