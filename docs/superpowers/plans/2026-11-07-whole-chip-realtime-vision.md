# Whole-chip realtime vision implementation plan

> Execute approved design with test-first isolated new modules and independent spec then quality reviews. Work in the existing dirty checkout (continuation of user-owned work); create only the explicitly approved branch. Use a separate temporary clone only for deployment verification; do not copy or move frozen research assets.

**Goal:** Complete stageA full-frame U-Net sensing and portable delivery, no control output.
**Architecture:** Pure tile geometry + frozen-model predictor + bounded latest-frame worker/journal + thin operator camera UI. Existing camera source owns hardware; detector only receives FramePacket.
**Tech stack:** Tk, existing OpenCV/PyTorch/SMP G4 pipeline, unittest, Git.

- [x] Snapshot source status; audit explicit source/test/config/doc allowlist and commit current working operator baseline on codex/whole-chip-realtime-vision without generated assets. Preserve all other files.
- [x] Geometry tests RED/GREEN:512/384/64, full native coverage, optionalROI domain, crossing boundaries, all components incl1px, bad masks/ROI.
- [x] Export/load pure G4 state package with recorded hashes/versions; defaultdeviceauto, lazy optional Torch; single/batch parity fallback and provenance tests.
- [x] Worker tests RED/GREEN:single-slot replace, frame snapshot/result identity, no partial output, errors/stop/journal flush, raw timestamps and counters. No actuator imports or output fields.
- [x] UI tests RED/GREEN:start/stop/view/save/full-chip rectangle selection, poll-only Tk, match processed frame, preserve raw recording/manual/openloop, disabled visual control; local camera config and portable launch/preflight.
- [x] GPU export and120ROI parity;63wholeframe acceptance sources(30+30+3 lowlight), raw inputs/checkpoints unchanged, actual performance/errors only.
- [ ] Independent spec then quality review; local/compile/full/7chains; clean clone imports/start/help. Fix regressions with tests.
- [ ] Source-only staged diff/secret/size audit; feature commit then non-force push origin; report branch/commits/runtime evidence/model-transfer package and target-machine checklist.
