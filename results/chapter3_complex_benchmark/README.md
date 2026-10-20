# Shared-channel coordination case

Import presets/复杂瓶颈并行运输.json in the existing GUI. It uses four source reservoirs, eight targets, and 39 static obstacles.

The barrier has a three-column passage at ROW 11 / COL 10-12 (one-based); staggered obstacle clusters force multi-turn approaches.

All comparators use the same source-target assignment. Static A* uses independent shortest obstacle-avoiding routes and a fixed three-step interval between emissions from the same reservoir, without inter-source coordination. Its geometric replay fails the safety audit and is not a successful transport run.

The safe serial reference releases one task at a time and reroutes around completed targets and their pull-risk zones. The next source may be enabled on the previous arrival step. The proposed result is exported unchanged from build_multi_droplet_assignments. No algorithm settings are tuned in the exporter.

Conflicts are counted once per droplet pair and discrete time step, classified as vertex, edge swap, spacing, or transition spacing. The audit includes completed-goal holds through the entire horizon. The coordinate snapshots all use one shared schedule clock. W indicates waiting; red shading in the comparison marks implicated cells. Colors identify source reservoirs, and IDs identify individual drops.

Makespan is a discrete schedule-step count, not elapsed hardware time. This is a deliberately constructed bottleneck example supporting coordination and parallelism claims against these explicit references, not a proof of global optimality or general superiority across datasets.
