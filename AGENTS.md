# Upper-Computer Handoff

## Workspace boundary

This repository contains only the PC upper computer:

`D:\Learn\ZJU\有源矩阵\上位机`

STM32 firmware is a separate repository:

`D:\Learn\ZJU\有源矩阵\Droplet代码\Droplet-20x21`

Never mix commits or files between these workspaces.

## Control ownership

- PC: all automatic tasks, camera acquisition, detection, planning, stable-arrival decisions, recovery, logging, and reports.
- STM32: atomic electrode execution and fixed 300 Hz 20 x 21 scanning only.
- STM32 LCD/touch: disconnected manual electrode test only.
- Industrial camera: direct PC USB3/SDK connection; never send camera commands over STM32 serial.
- External DC_PULSE/VREF supplies are recorded, not controlled by the upper computer.

## Closed-loop contract

1. Submit one delta transaction with `BEGIN/SET/COMMIT`.
2. Wait for `ACK:<sequence>:APPLIED`; retry the same sequence at most twice.
3. Treat `APPLIED` as electrical confirmation only.
4. Keep the target electrode active while waiting for vision.
5. Advance only after five consecutive target detections spanning at least 0.25 s.
6. Single-droplet transport uses an 8 s initial wait, a 4 s extension, one replan, then protective pause near 20 s. Multi-droplet, mixing, and splitting use their operation-specific identity-safe hold/retry logic instead of a blind global replan.
7. Use `ALL_OFF` only as an immediate emergency/release operation.

## Key modules

- `app_controller.py`: composition root and shared state.
- `controllers/electrode_transaction.py`: serial atomic transaction client.
- `controllers/arrival_confirmation.py`: stable vision gate.
- `controllers/closed_loop_controller.py`: single/mix/split state machines.
- `controllers/multi_runtime.py`: concurrent droplet runtime.
- `dmf/planning/`: A*, assignment, conflict-safe scheduling.
- `validation/closed_loop_chain/`: independent validator used by Codex, not GUI.

## Before changing code

Read `CONTEXT.md`, `docs/implementation-status.md`, and the design documents under `docs/superpowers/specs/`. Preserve the existing domain language and add tests before protocol or scheduling changes.

## Verification

```powershell
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

Do not claim physical closed-loop completion until the user runs firmware build/flash, logic-analyzer, oscilloscope, camera-calibration, and real-droplet tests.
