# Digital Microfluidics Visual Platform

This context describes the concepts used to plan, simulate, observe, and control droplets on the active-matrix digital microfluidic chip.

## Language

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

**Splitting**:
Stretching one source droplet toward two opposite adjacent electrodes until two child droplets are visually confirmed.
