# Chapter 2 single-droplet experiment mode

## Existing code and missing functions

Base: remote b1e5059 (offline vision framework). Reuse `dmf.vision` calibration,
420-region map, mask feature extractor, video timestamp resolver, and
`controllers.electrode_transaction.ElectrodeTransactionClient`.
Five state names exist but state prediction is Unknown. U-Net is reserved only.
The old GUI controller uses global replanning and is not this chapter's policy.

## Selected minimal approach

Add `dmf.experiment` and `run_experiment.py`; leave the GUI, multi-droplet planner,
firmware, and existing offline baseline API untouched. Modifying the shared GUI
FSM would couple Chapter 2 to Chapter 3; rewriting the entire acquisition and
protocol stack would duplicate existing tested code. Neither is needed.

The supplied user specification authorizes implementation after this structure
review and plan. Local uncommitted performance changes remain in the original
checkout; this worktree starts from the latest remote vision code.

## Data and behavior

Frame -> U-Net mask -> measured features and causal prediction -> rule state ->
event decision -> atomic AM transaction. The rule recognizer uses configurable
occupancy, speed, position tolerance, and consistency duration/frame count.
Invalid masks yield Unknown/Hold and a bounded detection timeout, never Update.
Candidate-neighborhood or temporal violations yield Deviation without erasing
the observation. Temporal prediction only uses accepted earlier frames.

Start by visually confirming the configured source. Recovery drives only the
last confirmed local source; source confirmation must precede reattempt. Retry
increments only after command acceptance (simulated acceptance outside hardware).
Each attempt restarts its wait timer, visual Update resets the per-step count,
and a confirmed recovery resets it. Recovery duration/count are bounded.
Final Arrived completes the route, without issuing another target command.

`offline` uses video timestamps and never constructs serial transport. `dry_run`
uses live capture and resolves identical commands without opening serial.
Only `experiment`, explicit output enablement and acknowledged calibration use
serial; APPLIED acknowledges electrical application only. Camera timeout,
command failure, emergency-stop file/Ctrl+C, and invalid-detection timeout end
the run. A final ALL_OFF is attempted on hardware shutdown and logged.

U-Net adapter accepts exported ONNX or TorchScript binary segmentation models;
preprocessing/output activation must match training configuration. No weights
are invented. Threshold is an explicit synthetic-smoke-test option only.
SDK cameras use a documented plugin seam; OpenCV-compatible cameras run directly.

## Evidence and limits

CSV frame/step/command logs and immutable config/map snapshots are mandatory.
Raw/mask/overlay PNGs are optional and synchronous, with recorded pipeline time;
no GUI is introduced. Synthetic videos verify software decisions, not scientific
accuracy. Real U-Net weights, pilot-calibrated thresholds, camera SDK/calibration,
serial settings and physical tests remain user-supplied experiment inputs.
