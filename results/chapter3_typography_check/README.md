# Chapter 3 simulation result pack

Generated from the current repository's production assignment, A*, reservation scheduling, and runtime-fault replanning functions.
These are deterministic/software simulation outputs, not physical droplet experiments.

## Files

| Figure | Scenario | Data |
|---|---|---|
| `01_normal_multidroplet.png` | Normal assignment -> A* -> scheduling | `01_normal_multidroplet.json`, `01_normal_assignments.csv` |
| `02_conflict_resolution.png` | Fluidic-spacing conflict, resolved with source wait | `02_conflict_resolution.json`, `02_conflict_assignments.csv` |
| `03_letter_CSE.png` | CSE pattern at four schedule snapshots | `03_letter_CSE.json`, `03_letter_CSE_assignments.csv` |
| `03_letter_ZJU.png` | ZJU pattern at four schedule snapshots | `03_letter_ZJU.json`, `03_letter_ZJU_assignments.csv` |
| `04_preplanned_fault_detour.png` | Known fault and A* detour | `04_preplanned_fault_detour.json`, `04_preplanned_fault_paths.csv` |
| `05_runtime_fault_global_replan.png` | Runtime fault -> global reroute/reschedule | `05_runtime_fault_global_replan.json`, before/after CSVs |

## Important interpretation

- Path length and makespan are discrete electrode/step counts, not seconds.
- Planning/replanning times are single-run local wall-clock measurements, not statistical performance claims.
- Letter snapshots align each droplet by normalized route progress; each arrow is that droplet's next scheduled move. They are not shared global-time states.
- The simulation does not model real dispense volume, fluid shape, or voltage physics.
- Runtime fault is an offline invocation of the same replan function used by the multi-droplet simulation controller; no GUI/hardware is operated.
- Reservation scheduling can insert waits/delayed releases to satisfy vertex, edge-swap, and fluidic pull-risk constraints.
- Figure encoding: red cross = failed electrode; solid = nominal route; dashed = fault-aware route; muted routes = completed or unaffected droplets.

- `normal_multidroplet`: completed
- `fluidic_spacing_conflict_resolution`: see JSON
- `letter_CSE`: completed
- `letter_ZJU`: completed
- `preplanned_fault_detour`: success
- `runtime_fault_global_replan`: success