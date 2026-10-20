# Figure Captions

## A_baseline_final
Error bars denote sample standard deviations; lower bounds are clipped at zero for non-negative metrics.

## B_scalability_final
Error bars denote sample standard deviations; lower bounds are clipped at zero for non-negative metrics.
Success-rate error bars denote Wilson 95% confidence intervals.

## C_congestion_final
Error bars denote sample standard deviations; lower bounds are clipped at zero for non-negative metrics.

## D_v2_robustness_final
Error bars denote sample standard deviations; lower bounds are clipped at zero for non-negative metrics.
Success-rate error bars denote Wilson 95% confidence intervals.
Makespan change is signed; its display range is not clipped at zero.

## B_planning_tails
Auxiliary high-load planning-time statistics for the scalability experiment. Median, P95 and Max come from the existing records; no theoretical distribution is asserted.

## D_identity_validation
Before identity check denotes the archived implementation; Identity-preserving denotes the fixed implementation. Aggregate outcomes come from the same 280 fault trials; protective pause is not counted as safe success.

# Definitions for Captions or Methods

Uncoordinated A* denotes independent spatial A* routing without cross-source temporal coordination; the original fixed dispensing interval remains unchanged.
Continuous metrics are reported as mean +/- sample SD; success/recovery rates are shown with Wilson 95% confidence intervals.
Wide (20), Medium (7), Narrow (3): the numbers denote the bottleneck channel width in electrode cells.
Conflict pair-steps: $C=\sum_t\sum_{i<j}\mathbf{1}[(i,j)\text{ violate a conflict constraint at }t]$. One violation is counted per pair and time step, including vertex, edge-swap, spacing and transition-spacing constraints; completed droplets remain occupied.
Wait fraction: $\rho_{\mathrm{wait}}=N_{\mathrm{wait}}/(L_{\mathrm{total}}+N_{\mathrm{wait}})$. Wait counts consecutive equal non-empty scheduled positions; None release prefixes and rendering-only terminal holds are excluded.
Spatial path overlap: $O_{\mathrm{path}}=\sum_{e\in E_{\mathrm{core}}}\binom{n_e}{2}$, where $n_e$ is the number of distinct spatial paths containing core cell $e$. The unit is pair-cells, not simultaneous conflicts.
Normalized path length: $R_L=L_{\mathrm{fault}}/L_0$, where both lengths are the total remaining edge counts of unfinished droplets from the identical fault-time state; $L_0$ comes from zero-fault replanning, not the initial full journey.
