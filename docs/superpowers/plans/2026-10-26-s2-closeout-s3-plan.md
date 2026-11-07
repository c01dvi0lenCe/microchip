# S2 Closeout and S3 Design Implementation Plan

> For agentic workers: use executing-plans inline. User prohibits Commit/Push; no worktree or research-code changes needed.

**Goal:** Deliver read-only S2 publication figures, complete tables, bounded analysis and a fair S3 protocol.

**Architecture:** New drawing/export scripts read frozen sources; current S2 modules remain untouched. A full file inventory outside the frozen directory verifies source invariance. S3 is documentation only.

**Tech Stack:** Python/matplotlib, unittest, SHA256, ReportLab/PyMuPDF/PyPDF.

### Task 1: Immutable inputs and tests

- [x] Add tests for fixed six-condition display, complete65 rows, NA reference, miss/late separation and no model/scorer imports.
- [x] Observe missing-interface failures, then implement read-only loader in scripts/chapter2_s2_closeout.py.
- [x] Save old S2/source content hashes in the new output before rendering and compare after.

### Task 2: Figures

- [x] New S2-A renderer reuses persisted data loader and four axes; keep exact event, frame, exposure-window and reference data. Improve width/legend/reference annotation only.
- [x] S2-B main six conditions: A_normal, C_jump_short, D_tail_false, C_jump_persistent, F_jitter, F_dropout. No effect-based seed selection.
- [x] Copy all65 rows and full contrast CSV without editing; append a complete printable table with failures/late/NA preserved.
- [x] Export vector and600dpi PNG; alignment, text size, collision and visual review.

### Task 3: Research writing

- [x] Establish S3 scope/canon/evidence/argument/contracts/terminology files from existing code and frozen data, not external claims.
- [x] Write five bounded S2 limitation paragraphs with traceable count evidence.
- [x] Write S3 main4 strategies plus gate×protection bridge,7 scenarios, source/transport separation, budgets, denominators, random-stream pairing, scale and gates. No trial runs.

### Task 4: Verification and delivery

- [x] Local S2/figure tests; compile new scripts; confirm no model/predict/scoring calls, no seed-generation entry. Final49 passed.
- [x] Freeze index and current code unchanged; new package PDF includes figures/tables/analysis/S3 plan and source manifest. Final r5 PDF14 pages inspected.
- [x] Report actual checks, no new research trials, no Commit/Push; user review precedes S3 implementation.
