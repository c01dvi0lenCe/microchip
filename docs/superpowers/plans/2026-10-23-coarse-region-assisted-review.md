# Coarse Region Assisted Review Plan

**Goal:** User sees a coarse image region, then independently clicks the actual precise vertex; preserve old study.

**Architecture:** New region precomputation/preparer, explicit assisted schema/summary identity and optional UI overlay. No runtime/calibration configuration changes.

**Tech Stack:** existing frozen map/H loader, NumPy, Tk ImageCanvas, unittest.

- [x] User approved coarse approximate region plus manual precise click; snapshot all old packages.
- [x] Tests RED→GREEN for missing helper;9 final tests cover bounds/provenance/raw clicks/mode labels/isolated GUI/source protection.
- [x] New helper, assisted schema/report labels and optional UI frame/scroll; original blind compatibility retained.
- [x] Separate real-photo auxiliary package created, rounds0/16+0/16; CRLF launchers. Local81 tests pass14.057s; compile/diff and real-photo hidden Tk smoke pass.
- [x] Original177 package files hash unchanged; actual status and commands saved. No fabricated clicks, no commit/push.
