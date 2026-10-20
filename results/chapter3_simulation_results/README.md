# Chapter 3 simulation result pack

Generated from the current repository's production assignment, A*, reservation scheduling, and runtime-fault replanning functions.
These are deterministic/software simulation outputs, not physical droplet experiments.

## Files

| Figure | Scenario | Data |
|---|---|---|
| `01_normal_multidroplet.png` | Normal assignment -> A* -> scheduling | `01_normal_multidroplet.json`, `01_normal_assignments.csv` |
| `01b_initial_multidroplet.png` | User preset: six initial droplets with an obstacle/fault map | `01b_initial_multidroplet.json`, `01b_initial_assignments.csv` |
| `02_conflict_resolution.png` | Fluidic-spacing conflict, resolved with source wait | `02_conflict_resolution.json`, `02_conflict_assignments.csv` |
| `03_letter_CSE.png` | CSE pattern at four schedule snapshots | `03_letter_CSE.json`, `03_letter_CSE_assignments.csv` |
| `03_letter_ZJU.png` | ZJU pattern at four schedule snapshots | `03_letter_ZJU.json`, `03_letter_ZJU_assignments.csv` |
| `04_preplanned_fault_detour.png` | Known fault and A* detour | `04_preplanned_fault_detour.json`, `04_preplanned_fault_paths.csv` |
| `05_runtime_fault_global_replan.png` | Runtime fault -> global reroute/reschedule | `05_runtime_fault_global_replan.json`, before/after CSVs |

## Important interpretation

- Path length and makespan are discrete electrode/step counts, not seconds.
- Figure 01 prefers presets/复杂瓶颈并行运输.json, falling back to presets/多液滴正常路径调度.json. Figure 01b uses presets/多液滴正常路径调度2.json; its preconfigured faults do not intersect the corresponding nominal paths, so it is not fault-detour evidence.
- In Figure 02, red shading marks the unsafe first transition, green cells mark targets, and W marks inserted waiting. Other colored timeline blocks need no in-figure action abbreviations.
- Planning/replanning times are single-run local wall-clock measurements, not statistical performance claims.
- Letter snapshots use shared global schedule steps and the planner's original parallel schedules. All droplets already released at t=0 appear; arrows show each active droplet's scheduled next move.
- In letter figures, each source reservoir has a fixed color shared by all droplets it releases. IDs distinguish individual droplets; colors identify their source liquid.
- The simulation does not model real dispense volume, fluid shape, or voltage physics.
- Runtime fault is an offline invocation of the same replan function used by the multi-droplet simulation controller; no GUI/hardware is operated.
- Figure 04 shows one representative route pair; other independent fault trials appear in the per-droplet length chart. Independent static routes are not collision-safe when assumed simultaneous.
- Figure 05 replans two unfinished routes around two runtime faults, holds one completed droplet, and retains one unaffected route.
- Reservation scheduling can insert waits/delayed releases to satisfy vertex, edge-swap, and fluidic pull-risk constraints.
- Figure encoding: red cross = failed electrode; solid = nominal route; dashed = fault-aware route; muted routes = completed or unaffected droplets.
- Reservoir pads have straight borders. Routes use lines and arrows without background bands or artificial core-entry circles; filled circles denote actual droplets.

- `normal_multidroplet`: completed
- `initial_multidroplet_preset`: completed
- `fluidic_spacing_conflict_resolution`: see JSON
- `letter_CSE`: completed
- `letter_ZJU`: completed
- `preplanned_fault_detour`: success
- `runtime_fault_global_replan`: success