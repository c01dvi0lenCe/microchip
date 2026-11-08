# Approved Single-Electrode Cycle Implementation Plan

Goal: one manual-page start/stop button, fixed ON250ms/OFF250ms indefinitely,
APPLIED-paced only. The user's 2026-11-08 authorization overrides the historical
Chapter1-control removal restriction only for this button, not a restored test tab.

Architecture: retain the existing timed-task ownership flag, single transaction
worker/result queue and Tk polling. Add a focused cycle controller and recording
journal using the existing AsyncCsvLog/ElectrodeEventStream. No protocol change.

- [x] Write focused memory-serial GUI tests and observe missing-feature failures.
- [x] Add a blank explicit electrode-ID field and one toggle button on the manual
  page. Existing manual switching can fill this field; hover, active sets and task
  selections are not single-selection semantics and must not silently choose it.
- [x] Freeze ID 1..420 at start, require known/idle connected hardware and no other
  active electrodes, reuse BEGIN/SET/COMMIT and 250ms after each received APPLIED.
- [x] Keep ownership through stop/drain, explicit atomic selected-electrode OFF,
  one release ALL_OFF, and background journal flush. Reject all other task/manual
  control. Close/disconnect/emergency must not block Tk or schedule another ON.
- [x] Mark failures unknown, attempt release even after lost connection, release
  software ownership after bounded attempts without claiming physical OFF.
- [x] Run new and relevant tests with hardware/port enumeration blocked, compile,
  inspect changes and document UI/physical-verification limits. No commit/push.

Files: tests/test_single_electrode_cycle.py;
controllers/single_electrode_cycle.py; controllers/single_electrode_journal.py;
controllers/timed_mixing_controller.py; controllers/hardware_runtime.py;
controllers/ui_controller.py; app_controller.py; CONTEXT.md;
docs/implementation-status.md; docs/single-electrode-cycle-2026-11-08.md.

Final verification:14 focused checks; full1456 tests,1455 passed and1 skipped;
compileall and7 software control chains passed. First full run exposed canvas
compression; controls were moved into the existing legend band without weakening
the original300px canvas assertion. No hardware test. Git commit/push was
subsequently authorized by the user and is limited to this feature's files.
