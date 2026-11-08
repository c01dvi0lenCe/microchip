# Digital Microfluidics Visual Platform

This context describes the concepts used to plan, simulate, observe, and control droplets on the active-matrix digital microfluidic chip.

## Language

**Single-electrode cyclic ON/OFF test** (2026-11-08):
One explicitly selected pixel repeats ON250ms/OFF250ms through the existing atomic
transaction client until stopped. A single manual-page toggle button owns the shared
timed-task worker and excludes other electrode tasks. Dwell starts after APPLIED
receipt, not at physical OFF write. Stop drains in-flight work, writes target OFF
and releases with ALL_OFF; failures mark state unknown. No external HV control or
physical recovery measurement is implied. See
[operator/test note](docs/single-electrode-cycle-2026-11-08.md).

**Core electrode**:
One addressable electrode in the central 20 x 20 transport array.

**Dispense reservoir**:
A side reservoir that can repeatedly provide droplets up to its configured capacity.
_Avoid_: Sample point, loading electrode

**Waste reservoir**:
One of the four corner reservoirs used to receive discarded liquid and never used as a droplet source.

**Initial droplet**:
A single droplet already present on a core electrode when a simulated task begins.
_Avoid_: Infinite source

**Target electrode**:
A core electrode that must contain a droplet when a task completes.

**Transport step**:
One visually confirmed move from the current electrode to the next electrode.

**Electrical apply**:
The STM32 acknowledgement that an atomic electrode frame reached the scan front buffer. This does not prove droplet arrival.

**Stable visual arrival**:
The target cell is detected for at least five consecutive frames and at least 0.25 seconds. Only this event may advance an automatic path.

**Hold electrode**:
An energized electrode used to retain a waiting or settled droplet while other droplets move.

**Pull-risk zone**:
The same, orthogonally adjacent, or diagonally adjacent area in which energizing an electrode may unintentionally attract another droplet.

**Closed-loop operation**:
An operation whose next transport step is released only after visual confirmation of the current droplet state.

**PC automatic ownership**:
All automatic task logic belongs to the upper computer. The STM32 LCD/touch interface is manual-test-only and must not alter electrodes during a PC automatic session.

**Mixing**:
Bringing droplets together and circulating the merged droplet through a four-electrode route.
_Avoid_: Merge-only operation

**Timed four-electrode single-droplet motion**:
A separate single-droplet fixed-dwell 2x2 circulation mode, not droplet mixing or merging. Each real step waits
for APPLIED before its dwell; it does not claim stable visual arrival or replace
the existing merge-and-visual-mixing operation.

**Hardware fault reminder**:
User-reported stuck-on faults (90, 337, 393) plus their orthogonal core neighbors,
and stuck-off faults (399, 400) without neighbor expansion, shown in red as a
visual reminder only. These are not simulation fault injections or routing
obstacles; manual electrode activation remains permitted by explicit choice.
An acknowledged off command is not proof of physical isolation of a stuck-on electrode.

**Splitting**:
Stretching one source droplet toward two opposite adjacent electrodes until two child droplets are visually confirmed.

**Chapter 2 research baseline**:
The chapter titled “基于视觉反馈的单液滴运动状态识别与闭环控制”, organized as system design, visual recognition and electrode mapping, spatiotemporal state/event control, and validation. Its canonical section and evidence arrangement is recorded in [the chapter baseline](docs/chapter2-chapter-evidence-baseline-2026-10-25.md).

**Simplified two-dimensional single-droplet visual closed-loop algorithm simulation**:
An algorithm-level model of single-droplet point motion, synthetic visual masks, task evidence and control feedback, using simulation time and pitch units. It is not CFD, physical electrowetting dynamics, real U-Net inference or a real-droplet experiment.

**Mechanism validation**:
Evidence that state, arrival and control rules execute as specified under declared inputs. It does not establish real-world recognition accuracy or an independent performance advantage.

**Independent arrival reference**:
An arrival event or interval defined independently of the evaluated recognition rule, using separately reviewed human observations or internal simulated motion. It is scoring evidence, not an algorithm input or electrical acknowledgement.

**Synchronized multi-group four-cell open-loop motion** (2026-11-06):
Each group is one existing droplet with a user-selected ordered core2x2 ring and start/end inside it.
All groups share one atomic active-set transaction, APPLIED-paced dwell and pause/step lifecycle;
completed groups and extra electrodes remain held. This new automatic entry rejects the16 reminder
electrodes while manual testing still permits them. It neither merges droplets nor consumes vision.
The normal operator GUI no longer includes the Chapter2 research configuration/run tab; research
CLI, algorithms and historical data remain available independently. See
[operator guide](docs/multi-four-cell-open-loop-2026-11-06.md).

**Real-experiment operator profile** (2026-11-07):
`main.py` explicitly selects the real-only profile, starts disconnected, creates no simulated camera/droplets
and schedules no simulation loop. Direct switching and all timed open-loop tasks belong to the manual tab;
the automatic planning tab is reserved for real visual feedback, currently not accepted/enabled.
`run_planning_simulator.py` is a research-only serial-inert entry. Both reuse the same420 layout, perimeter
shapes/IDs/connectors and planning geometry. This UI split is not real visual closed-loop acceptance.

**Shared timed-task/manual switching** (2026-11-07):
During operator open-loop execution, original task-route electrodes are protected from manual ON/OFF.
Safe external electrodes share the existing single transaction worker; acknowledged extra holds persist,
and manual OFF removes them without changing the frozen plan. Manual ACK does not advance task phase.
Conflicts are refused, not pause-confirm overrides (latest user decision). Colors follow APPLIED; pending
intents are outlines only. Stop/release cancels unsent intents and drains in-flight work before ALL_OFF.
See [operator rules](docs/shared-open-loop-manual-2026-11-07.md). No physical high-voltage claim is implied.

**Whole-chip sensing stage A** (2026-11-07):
Full native image is tiled512/core384/halo64 with unique core writes. The frozen G4 U-Net outputs
all connected components in original pixel coordinates; local component IDs are neither persistent
droplet IDs nor electrode IDs. Latest-only worker queues own their source frames. Overlay uses the
processed source frame, never a newer raw preview. Detection does not write control perception fields
or own serial output. CUDA batch output differing from single-image reference falls back to batch1.
SDK delivered-number gaps, upstream/UI/inference replacements and unknown capture loss remain distinct.
See [deployment and target-camera acceptance](docs/whole-chip-realtime-vision.md).
