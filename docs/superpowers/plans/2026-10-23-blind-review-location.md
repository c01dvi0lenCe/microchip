# Blind Review Location Assistance Implementation Plan

**Goal:** Add approved design-only global electrode location and row/column labels without exposing H/prior pixels.

**Architecture:** One pure location formatter and one design-only Tk renderer inside the existing isolated GUI. No new consumer or data migration.

**Tech Stack:** Python/Tk, existing confirmed420 design loader, unittest.

- [x] Inspect current GUI/data; user approved global+local map and textual position. Snapshot original files.
- [x] Add2 tests and strengthen isolated GUI assertions; verify RED (missing functions/location widget) then GREEN.
- [x] Implement design-only formatter/renderer and two side-by-side maps; photo overlay/click/save/seal methods unchanged.
- [x] Run24 scoped/72 registration tests, compile/diff, real-photo hidden Tk smoke. Only intended GUI changed in198-file baseline;197 protected files unchanged, including old records.
- [x] Save `docs/chapter2-blind-review-location-2026-10-23.md`; same launcher, reopen rather than recreate data. No commit/push.
