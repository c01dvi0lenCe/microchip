# Closed-Loop Chain Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an atomic STM32 transaction client and a reproducible software-in-the-loop validator for the PC-to-electrode closed-loop chain.

**Architecture:** A serial transaction adapter sits below the existing hardware controller. A separate validation package models firmware frame application, scan waveforms, external-pulse phase, and circuit acceptance without coupling these tools to Tkinter.

**Tech Stack:** Python 3, pyserial, unittest, NumPy/OpenCV where already used, existing DMF planner and simulation modules.

---

### Task 1: Implement the atomic serial transaction client

**Files:**
- Create: `controllers/electrode_transaction.py`
- Modify: `controllers/hardware_controller.py`
- Modify: `controllers/hardware_runtime.py`
- Create: `tests/test_electrode_transaction.py`

- [ ] Write failing tests for command framing, monotonic sequences, ACK parsing, duplicate retry, timeout, and ALL_OFF.
- [ ] Implement a transport-independent transaction client.
- [ ] Integrate it into hardware mode while preserving legacy single SET commands for manual control.
- [ ] Run focused and full controller tests.

### Task 2: Separate electrical apply from visual arrival

**Files:**
- Modify: `controllers/closed_loop_controller.py`
- Modify: `controllers/multi_runtime.py`
- Modify: `controllers/task_control.py`
- Modify: `simulation/profiles.py`
- Modify: `tests/test_main_controller.py`

- [ ] Add failing tests proving ACK does not mean droplet arrival.
- [ ] Add five-frame and 0.25 s stable-arrival confirmation.
- [ ] Add 8 s hold, 4 s extension, one replan, and approximately 20 s protective pause.
- [ ] Verify multi-droplet steps submit one dynamic batch rather than a fixed droplet count.

### Task 3: Build the firmware scan digital twin

**Files:**
- Create: `validation/closed_loop_chain/__init__.py`
- Create: `validation/closed_loop_chain/protocol_model.py`
- Create: `validation/closed_loop_chain/scan_model.py`
- Create: `validation/closed_loop_chain/circuit_proxy.py`
- Create: `tests/test_closed_loop_chain.py`

- [ ] Model the 420-bit committed frame and transaction semantics.
- [ ] Generate 20-row by 21-column blank/load/drive scan events at 300 Hz.
- [ ] Sweep independent 300 Hz external-pulse phase over a full cycle.
- [ ] Evaluate VSTORE and differential-voltage acceptance using the existing single-select parameters.

### Task 4: Replay representative DMF tasks

**Files:**
- Create: `validation/closed_loop_chain/scenarios.py`
- Create: `validation/closed_loop_chain/run_validation.py`
- Create: `validation/closed_loop_chain/output/.gitkeep`
- Modify: `tests/test_closed_loop_chain.py`

- [ ] Replay move, mix, split, CSE, ZJU, and CSC schedules.
- [ ] Record maximum changed electrodes per step, transaction bytes, estimated serial duration, total scheduling steps, and safety violations.
- [ ] Keep only a concise Markdown summary and CSV in the output directory.
- [ ] Run `python -m validation.closed_loop_chain.run_validation` and require all software acceptance checks to pass.

### Task 5: Verify and ship upper-computer changes

**Files:**
- Modify: `README.md`
- Modify: `docs/implementation-status.md`

- [ ] Run `python -m compileall -q main.py app_controller.py controllers dmf simulation validation`.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Perform a Tkinter construction smoke test.
- [ ] Document that oscilloscope, logic-analyzer, and real-droplet validation remain user-run hardware steps.
- [ ] Commit and push `codex/closed-loop-chain-validation`.

