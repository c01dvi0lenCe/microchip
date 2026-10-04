# Upper-Computer Performance Optimization Design

## Goal

Remove visible UI stalls during simulation and multi-droplet planning without changing the closed-loop safety contract, electrode protocol, planning result semantics, or physical droplet timing.

## Measured Baseline

- The automatic simulation loop is scheduled every 70 ms.
- Rendering and detecting one 720 x 720 simulated frame takes about 90 ms on the current machine; a displayed frame takes about 136 ms.
- A complete redraw of both matrix canvases takes about 6 ms.
- Cold planning takes about 1.7 s for CSE, 1.9 s for ZJU, and 2.0 s for CSC, all currently on the Tkinter main thread.
- Detector profiling attributes nearly all detection time to the full-frame RGB distance mask.
- Scheduler profiling attributes most planning time to repeated pull-risk conflict checks.

## Non-Negotiable Behavior

- Stable visual arrival remains five consecutive target detections spanning at least 0.25 s.
- `ACK:<sequence>:APPLIED` remains electrical confirmation only.
- Target and hold electrodes remain active while waiting for vision.
- Single-droplet timeout, extension, replan, and protective-pause behavior is unchanged.
- Multi-droplet, mixing, and splitting retain their identity-safe recovery behavior.
- The PC remains the owner of all automatic work; the STM32 remains an atomic executor with fixed 300 Hz scanning.
- Industrial-camera resolution and SDK behavior are not changed by simulation optimizations.

## Considered Approaches

### A. Preview-only reduction

Reduce the simulated frame size and throttle redraws. This is the lowest-risk option and removes most continuous-loop overload, but planning still freezes the UI for roughly two seconds.

### B. Bounded optimization with asynchronous planning (selected)

Combine a smaller simulated frame, equivalent detector arithmetic, redraw coalescing, bounded logs, and background planning. Add only local scheduler caching where profiling proves repeated pure calculations. This addresses both continuous lag and click-time freezes while preserving architecture and behavior.

### C. Scheduler redesign

Replace the current scheduling search with a new reservation or conflict-graph algorithm. This could reduce total planning time further but risks changing valid schedules and closed-loop safety behavior. It is outside this optimization pass.

## Design

### Simulation vision

- Construct `SimulatedCamera` at 520 x 520 instead of 720 x 720. The GUI already displays at no more than 520 px, so the removed pixels are never shown at native resolution.
- Preserve the Euclidean color-distance decision exactly while comparing squared distance against squared tolerance, avoiding square-root work.
- Keep the 70 ms control-loop request and all stable-arrival rules. The optimization makes each callback fit the existing budget; it does not reduce the number of required detections.
- Keep real industrial-camera frames untouched. Any future real-camera optimization must use ROI or SDK acquisition settings explicitly.

### Matrix redraw

- Prevent the manual simulation loop from explicitly drawing the matrix immediately before the camera-render path performs its own rate-limited draw.
- Keep explicit redraws for user edits and state transitions.
- Do not replace the existing canvas representation or introduce a new rendering framework.

### Log retention

- Retain only a bounded recent log history in the Tk text widget.
- Preserve timestamps and throttled feedback messages.
- Trimming must happen in coarse batches rather than after every individual historical line.

### Simulation-only controls

- Motion realism, vision-noise injection, fault-mode selection, parameter help, and simulation fault buttons are visible only in simulation mode.
- Switching to hardware mode hides the entire simulation-parameter row and any expanded simulation fault-test row. Switching back restores the simulation row while keeping fault-test controls collapsed by default.
- Hardware mode continues to show real operation metrics, connection state, visual status, logs, and safety controls. Simulation probabilities must never be presented as measured hardware parameters.
- The simulation profiles remain available to automated tests and software-in-the-loop validation even while their GUI controls are hidden in hardware mode.

### Obstacle and failed-electrode controls

- The manual-electrode page does not show obstacle, weak-fault, or route-planning controls. Manual mode remains a direct disconnected electrode test surface with emergency release.
- Simulation automatic planning keeps the current obstacle and weak-fault concepts for rerouting and recovery tests.
- Hardware automatic planning keeps the same routing exclusion capability but labels it `屏蔽故障电极`, because it represents a confirmed unusable or hydrophobic-failure electrode rather than a simulated obstacle.
- A transient camera-observed stall is handled by closed-loop hold and recovery. It is not automatically persisted as a failed-electrode mask and does not require manual obstacle placement.

### Asynchronous planning

- Run CPU-heavy multi-droplet planning in one background worker at a time.
- Capture an immutable planning input snapshot on the UI thread. The worker may use only planner/domain objects and must not touch Tk widgets.
- Marshal completion back through `root.after(0, ...)` before updating controller state, logs, canvas, or buttons.
- Disable duplicate planning requests while a worker is active and expose a clear `正在规划` state.
- Discard stale results if task settings or operation generation change before the worker completes.
- Keep simple move, mixing, splitting, and single-loop planning synchronous because they do not show a measured stall.

### Scheduler hot path

- Cache or precompute pure pull-risk relationships used repeatedly during one scheduling invocation.
- Scope caches to one planning call so changed obstacles, settled targets, and merge regions cannot reuse stale values.
- Do not weaken same-cell, edge-swap, orthogonal, diagonal, settled-droplet, or contamination checks.

## Error Handling

- Worker exceptions return to the UI as a planning failure message and restore controls.
- Closing the application while planning must not schedule UI work onto a destroyed root.
- A second planning click during an active job is ignored with a concise status message.
- No partial assignment result is installed.

## Test Strategy

Tests are written and observed failing before implementation.

- Camera construction test: the controller uses a 520 x 520 simulated frame while real-camera interfaces remain unchanged.
- Detector equivalence test: squared-distance masking returns the same mask as the original Euclidean definition at inside, boundary, and outside colors.
- Redraw test: one manual movement tick requests no duplicate matrix redraw.
- Log test: the widget retains the configured recent-line bound.
- Mode-visibility test: hardware mode hides all simulation-only controls, while simulation mode restores the parameter row and leaves fault-test controls collapsed.
- Page-visibility test: the manual-electrode page exposes no obstacle tools; automatic simulation exposes obstacle/weak-fault tools; automatic hardware mode exposes `屏蔽故障电极`.
- Planning-worker tests: planning runs off the caller thread, duplicate requests are rejected, stale results are discarded, exceptions restore the UI, and successful results are applied on the UI callback.
- Scheduler regression tests: CSE, ZJU, CSC schedules retain all existing conflict-safety assertions.
- Performance harness: simulated render/detect must fit below the 70 ms mean budget on the current machine; UI planning dispatch must return promptly even though total planning continues in the worker.
- Full repository compilation, unit tests, and independent closed-loop-chain validation remain mandatory.

## Acceptance Criteria

- Mean 520 x 520 simulated render/detect time is below 70 ms on the current machine.
- Starting CSE, ZJU, or CSC planning returns control to Tkinter in under 100 ms.
- No duplicate matrix redraw occurs in one manual simulation movement tick.
- Long runs do not grow the visible log widget without bound.
- Hardware mode contains no simulation parameter or simulated-fault controls.
- Manual-electrode mode contains no obstacle or route-planning controls, while hardware automatic planning retains failed-electrode exclusion.
- Existing 164 tests plus new performance-regression tests pass.
- Independent move, mix, split, loop, CSE, ZJU, and CSC chain validation remains PASS.
- No claim of physical closed-loop completion is made.
