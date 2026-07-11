# Hardware Validation Checklist

This checklist is intentionally deferred until the user's hardware is available.

## STM32 and scan

- Build and flash the firmware branch in Keil.
- Verify 20-row x 21-column ID mapping, including IDs 401..420.
- Capture blank -> load -> drive transitions and frame-boundary atomic swap.
- Confirm no intermediate batch state appears on outputs.
- Confirm `ALL_OFF` latency and behavior after a lost ACK.

## External high voltage

- Record `DC_PULSE=0..400 V, 300 Hz` and `VREF/ITO=200 V`.
- Sweep independent scan/pulse phase drift with an oscilloscope.
- Measure selected RMS, inactive recovery, and VSTORE before revisit.
- Pay special attention to PCB coupling because the 1.22 pF model exceeds the provisional 50 V comparison level.

## Camera and vision

- Install the final industrial-camera SDK on the PC.
- Fix camera, lens, lighting, exposure, and frame rate.
- Calibrate the 20 x 20 core array corners and save the homography.
- Confirm centroid-to-cell mapping over the full field of view.
- Verify five-frame/0.25 s arrival confirmation under reflection and low contrast.

## Droplet tasks

- Single move and return.
- Four-cell mixing loop.
- Horizontal and vertical split with retry.
- Reservoir dispense sequence.
- Concurrent CSE/ZJU/CSC-style target filling at reduced scale first.

Store raw videos, serial logs, oscilloscope captures, calibration files, and task metrics together for later thesis figures.
