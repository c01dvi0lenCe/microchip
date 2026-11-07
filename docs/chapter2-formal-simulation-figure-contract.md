# Formal simulation figure contract

All figures are algorithm-simulation evidence only. They do not establish U-Net accuracy, real droplet performance, physical timing or measured millimetres.

Backend: the repository's existing Python/matplotlib workflow. Export editable SVG, PDF and PNG. Single-axes figures avoid unnecessary panel assembly; preserve alignment-not-applicable reports, perform PDF text/collision audits and inspect the final renders. Minimum font 6 pt, width 183 mm for comparisons. Raw CSV stays authoritative.

1. Prespecified normal / seed261000 / C_formal trajectory: show action-dependent motion in the local route region, coordinate unit pitch. It is an illustrative trial, not a selected best result.
2. The same trial's five-state sequence including Unknown: show intermittent evidence, without inventing single-frame baseline state labels.
3. All seven scenes' path/early/recall/delay/time/retry/recovery summaries: quantify differences and their uncertainty. Path rates use all trials; successful completion time and observed confirmation delay remain explicitly conditional. Missing values are not plotted at zero.
4. Paired C–A and C–B path-rate differences: preserve the matched-seed estimand rather than infer differences from marginal CI overlap.
5. S1–S4 and three ablations over the identical frozen inputs: recognition-event/path evaluation only, not physical control success. Retain all seven scenes and support counts.
6. Prespecified jitter threshold sensitivity: fixed independent physical reference, all20 paired seeds, no post-hoc favorable condition selection.

Statistical unit: seed within scene. Wilson95% for path rate; 2000 seed-cluster bootstrap repeats for ratios, conditional means and paired differences. No significance tests, p values, or multiplicity claims. All missing/failed/censored counts remain in source tables and captions.
