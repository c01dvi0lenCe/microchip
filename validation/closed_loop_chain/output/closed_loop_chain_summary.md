# Closed-Loop Chain Software Validation

| Scenario | Droplets | Steps | Max active | Max changed | Max serial ms | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| move | 1 | 3 | 1 | 2 | 3.385 | PASS |
| mix | 2 | 7 | 2 | 4 | 5.122 | PASS |
| split | 1 | 2 | 2 | 3 | 4.514 | PASS |
| loop | 1 | 5 | 1 | 2 | 3.559 | PASS |
| CSE | 31 | 29 | 31 | 44 | 43.663 | PASS |
| ZJU | 30 | 43 | 30 | 29 | 28.993 | PASS |
| CSC | 29 | 61 | 29 | 42 | 41.406 | PASS |

Software PASS verifies atomic protocol, ID mapping, scan-event construction, serial budget, and the circuit proxy across independent 300 Hz phase offsets.
Circuit proxy uses the existing single-select waveform levels, VSTORE before revisit 3.80167 V, and a 23.529 V inactive edge peak under the 0.5 pF coupling assumption; RMS values are recomputed for every independent phase offset.
The existing 1.22 pF sensitivity case reaches 52.928 V, so PCB parasitic coupling remains a hardware risk rather than a software PASS claim.
It does not replace Keil build/flash, oscilloscope, logic-analyzer, camera calibration, or real-droplet validation.
