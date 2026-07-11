# Closed-Loop Chain Validation Design

## Scope

The upper computer sends numbered atomic electrode transactions to the STM32 and advances a droplet only after both electrical acknowledgement and stable visual arrival. The validation tool is an independent Python module; it is not added to the Tkinter interface.

## Runtime Sequence

1. Compute the complete desired active-electrode set for the next control step.
2. Send only changed electrodes inside `BEGIN/SET/COMMIT` with a monotonic sequence.
3. Wait for `ACK:<sequence>:APPLIED`; retry the same idempotent sequence twice on communication timeout.
4. Hold the applied electrodes while waiting for vision.
5. Accept arrival only after the centroid remains in the target center region for five consecutive frames and at least 0.25 s.
6. At 8 s extend the hold by 4 s; if still absent, replan once from the detected position.
7. Protectively pause at about 20 s if recovery fails.

## Offline Validation

The validator replays move, mix, split, loop, CSE, ZJU, and CSC schedules. It checks protocol atomicity, 420-channel mapping, batch size, serial-time budget, break-before-make scan timing, and absence of unintended intersections. A circuit proxy consumes the existing single-select weak-pullback simulation assumptions and sweeps the independent phase between the 300 Hz external pulse and 300 Hz scan.

Acceptance criteria are selected RMS differential voltage at least 150 V, inactive recovery below 50 V, VSTORE after write at least 4.0 V, VSTORE before revisit at least 3.0 V, no unintended selected pixel, and no observable partial transaction state.

Only concise engineering artifacts are retained now. Thesis-ready plots are generated after hardware measurements exist.

