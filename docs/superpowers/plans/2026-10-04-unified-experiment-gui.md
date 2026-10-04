# Unified chapter 2 experiment GUI implementation plan

**Goal:** Merge the chapter 2 experiment engine into the existing upper-computer
`main.py` GUI and remove the chapter 1 hardware-test feature.

**Architecture:** Retain the current locally modified GUI and planning/simulation
controllers. Import the experiment/vision modules from the experiment worktree,
preserving the optimized simulation camera in the new vision package. A dedicated
experiment page starts a worker thread with bounded latest-frame delivery; Tk is
updated only on its main thread. One cancellation event reaches the runner and
serial transaction adapter, including shutdown release. Manual/legacy operation
cannot own the camera or serial port during an experiment.

**Tech stack:** Python, Tkinter, OpenCV, PyYAML, existing AM transaction protocol.

## Scope

- One usable local entry: `上位机/main.py`, plus CLI compatibility.
- Three pages: manual electrodes, existing path simulation, chapter 2 experiment.
- Experiment modes: offline, dry_run, experiment. Only experiment sends AM commands.
- Load a YAML configuration, select mode, start/stop, preview and status, open logs.
- Generate a clearly labeled synthetic offline demonstration from the GUI.
- Remove chapter 1 scope-test page, controllers, protocol extensions and its tests
  from the merged distribution; retain general serial/manual electrode capability.
- Back up both source trees before reconciling. Do not alter firmware or user videos.
- Model weights, camera SDK and measured calibration remain user-supplied inputs.

## Tasks

- [x] Reconcile experiment/vision dependencies and preserve existing local changes.
- [x] Add cancellation/progress hooks to runner, shared editable overlay helper.
- [x] Add threaded GUI session adapter and tests for start/stop/errors/mode isolation.
- [x] Add experiment tab, resource ownership guards and orderly window close.
- [x] Remove chapter 1 code from experiment worktree and synchronize merged sources.
- [x] Verify synthetic transport/recovery, all tests and closed-loop validator.
- [x] Update entrypoint instructions and implementation status.

## Verification (2026-10-05)

- Full merged suite: 250 tests passed.
- Final GUI/session regression suite: 10 tests passed, including stop/release on close and terminal preview.
- All seven independent closed-loop validation scenarios passed.
- GUI synthetic demonstration completed both adjacent transfers with AM output disabled.
- No physical camera, trained U-Net or high-voltage experiment was run.
