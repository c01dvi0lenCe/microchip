# Chapter 2 software verification — 2026-10-04

Base commit: `b1e5059`, latest remote vision framework at start of work.
Branch: `codex/chapter2-single-droplet-experiment`.

## Results actually observed

| Check | Observed result |
|---|---|
| Unmodified baseline test suite | 213 passed |
| Full suite after main implementation and first review fixes | 238 passed |
| Final Chapter 2 tests (including added blocked-write deadline regression) | 26 passed |
| Python compile checks | passed |
| Existing independent closed-loop validator | move, mix, split, loop, CSE, ZJU, CSC all PASS |
| Synthetic two-step video | 16 processed frames; transport complete |
| Synthetic retry/recovery video | 15 processed frames; stopped at configured local recovery limit |
| Hardware commands sent in both offline demos | 0 |

The final focused suite covers five states and Unknown, confirmation duration,
causal prediction and rejected-history isolation, finite motion retries, recovery
confirmation, final completion, stale capture before/after actuation, measured
candidate polygons, preservation of completed-step records when next-start
fails, mode isolation, TorchScript binary-mask inference, camera timeout, ACK
deadline and blocked-write deadline. Model adapter tests use a tiny artificial
export to check the interface, not a trained U-Net or scientific performance.

An independent review found and the implementation fixed:
1. Recovery could confirm source using a frame older than recovery application.
2. Next-target command failure could overwrite a visually successful step.
3. Spatial prior could use template geometry despite measured pixel overrides.
4. Per-ACK waits and serial writes could outlast the total command deadline.
Each fix has a regression test observed failing before the correction.

## Acceptance interpretation

A: synthetic offline videos exercise all five states; real-video classification
accuracy is **not verified** without trained weights, labelled pilot data and
calibrated thresholds.

B: all four action decisions are verified in rule/policy and video tests. Actual
droplet response to AM actuation is **not verified**.

C: frame, step, command and timing CSVs, config/map snapshots and optional mask/
overlay images were generated and inspected in end-to-end tests.

No hardware camera, serial port or high-voltage AM output was opened in these
checks. TorchScript emits a Python 3.14 deprecation warning in the installed
PyTorch; the interface test passes. The configured ONNX route requires the
user's exported model and its matching preprocessing before real inference is
validated. Neither camera vendor SDK nor trained weights were supplied.

Local demo artifacts are in `results/chapter2-final-check/` (gitignored); reproduce
with the documented generator. No experiment video/model is bundled or uploaded.
Original checkout's 18 uncommitted changes and its branch are preserved.
