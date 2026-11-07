# Real Vision Offline Preview Implementation Plan

> Execute the already authorized minimal offline preparation inline. No commit/push, camera/COM/AM output, retraining, frozen-data edits or new algorithm design. Stop before inventing unreviewed calibration/arrival GT.

**Goal:** Reuse frozen G4 inference for the existing120 November6 candidate ROIs, preserve provenance and produce inspectable predictions; remove approved explanatory parentheses from operator headings.

**Architecture:** A separate offline orchestration script imports the existing G4 build_model/predict unchanged. It reads native ROI PNGs and source manifests, checks hashes, writes predictions/overlays/component diagnostics into a new output directory only. It never imports controller/actuator classes. Maps remain explicitly unbound, no arrival/accuracy scores.

**Tech Stack:** Existing G4 Python/PyTorch CUDA environment, OpenCV/Pillow, unittest.

## Tasks

- [x] Operator title regression RED then GREEN; two text strings only, warnings/disabled state retained.
- [x] Five independent data/provenance tests RED then GREEN; output index completeness regression RED then GREEN.
- [x] Reuse existing G4 predict unchanged; native masks/overlays/components/manifests implemented in separate offline script.
- [x] Actual120×2=240 predictions,0runtime errors,382protected inputs unchanged,610outputs checked.
- [x] All6 contact sheets inspected;20review candidates and3near-full-foreground low-light failures preserved. Two native video references independently redecoded and source hashes rechecked; no H claimed.
- [x] 68related tests passed,31.773s. Final compile recorded separately. No new full-regression claim.
- [x] Review package and repo index delivered. Accepted mapping, identity and deployment parity remain gates before online no-output dry_run.
