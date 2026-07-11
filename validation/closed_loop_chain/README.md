# Closed-Loop Chain Validator

This package is an independent engineering tool used by Codex and is intentionally not exposed in the Tkinter GUI.

It verifies:

- atomic 420-electrode frame semantics;
- 20-row x 21-column blank/load/drive scan construction;
- 115200-baud transaction-time budget;
- move, mix, split, loop, CSE, ZJU, and CSC schedules;
- a phase-independent single-select circuit proxy at the fixed 300 Hz operating point.

Run:

```powershell
python -m validation.closed_loop_chain.run_validation
```

Outputs are written to `validation/closed_loop_chain/output/` as one CSV and one Markdown summary.

## Circuit proxy provenance

The default snapshot comes from the existing local single-select simulation outputs:

- selected-state `VOUT-VREF` RMS: 195.935 V;
- `VSTORE` immediately after write: approximately 4.99867 V;
- `VSTORE` before revisit/hold end: 3.80167 V;
- inactive-node deviation: 23.529 V for the 0.5 pF coupling case.

The existing sensitivity sweep also reports 52.928 V at 1.22 pF and 80 V at 2 pF. Therefore a default proxy PASS only means the low-coupling design assumption passes the provisional comparison limits. PCB parasitics, independent-clock phase drift, inactive recovery, and real electrode voltage still require oscilloscope and logic-analyzer validation.
