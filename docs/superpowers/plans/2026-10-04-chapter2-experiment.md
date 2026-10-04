# Chapter 2 experiment implementation plan

Goal: runnable isolated single-droplet experiment mode using existing vision/protocol code.
Architecture: small config, perception, policy, source, actuator, logger and runner modules.
Tech: Python, OpenCV, NumPy, YAML; optional ONNX Runtime / PyTorch; pyserial.

- [x] Write failing state/policy tests: five states, unknown, causal prediction,
  delayed confirmation, finite retries, recovery confirmation, final completion.
- [x] Implement typed configuration, perception rules and local controller.
- [x] Write failing mode/adapter tests: offline/dry-run zero hardware writes,
  duplicate Hold suppression, Retry resend, APPLIED failure and camera timeout.
- [x] Implement source and transaction adapters, U-Net inference, experiment logs.
- [x] Test a synthetic video end to end, covering every state and action, invalid
  frames and CSV contents. Test exported TorchScript inference independently.
- [x] Implement CLI, example config, sample-video generator and run documentation.
- [x] Run existing tests, compile checks and independent closed-loop validator;
  inspect changes and record actual results, with physical-test limits.

Commands: `python -m unittest discover -s tests -p 'test_chapter2*.py' -v`,
`python -m unittest discover -s tests -q`,
`python -m validation.closed_loop_chain.run_validation`.
