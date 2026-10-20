# DMF unified offline vision framework

Phase 1 separates offline algorithm comparison from the existing Tkinter and STM32 control path. It implements threshold and explicit-background baselines without selecting a final neural network or inventing state thresholds.

## Commands

```powershell
python -m dmf.vision extract-frames --video input.mp4 --video-id pilot01 --output-dir data/frames/pilot01
python -m dmf.vision validate-dataset --manifest data/splits/manifest.csv --annotations data/annotations/pilot.csv
python -m dmf.vision run-baseline --config configs/experiment.yaml
python -m dmf.vision evaluate --results results/pilot/frame_results.csv --ground-truth data/annotations/pilot.csv --electrode-map configs/electrode_map.yaml --output-dir results/pilot/evaluation
python -m dmf.vision render-map --image chip.png --electrode-map configs/electrode_map.yaml --output results/electrode_map_overlay.png --show-row-col --zoom-electrodes 1,20,190,191,381,400
python -m dmf.vision export-map --input configs/electrode_map.yaml --output results/electrode_map_calibrated.json
python -m dmf.vision export-timeseries --results results/pilot/frame_results.csv --experiment-id pilot_transport_horizontal_01 --output results/pilot/transport_timeseries.csv
```

For background subtraction, configure either `background_images` or a dedicated blank `background_video`. The test video itself is never sampled to create the background.

## Result contract

`frame_results.csv` stores the timestamp source, detection, pixel/mm centroid, area, source/target coverage, target distance, timestamp-derived velocity, state placeholders, algorithm time, pipeline time, mask path and error code. `run_manifest.json` stores the full configuration snapshot.

IDs 1-400 are the row-major core. IDs 401-420 retain the current physical peripheral mapping, including the four L-shaped corner electrodes. Runs that name a peripheral source or target fail until that electrode has a measured `pixel_overrides` polygon.

This is a 400-core-plus-20-peripheral physical layout, not a regular rectangular 20 x 21 image grid. Each region separately stores its ID, layout row/column, `geometry_type`, polygon, center and template/calibrated source. YAML and JSON map files use the same schema; no 3D calibration is assumed.

Threshold and background subtraction always emit a full-size binary mask, including an all-zero mask on a miss. `mask=None` is reserved for later localization-only algorithms. Evaluation reports both algorithm-only and end-to-end pipeline timing.

Pilot annotation CSV columns are:

```text
video_id,experiment_id,batch_id,frame_id,timestamp_s,frame_path,mask_path,source_electrode,target_electrode,state_gt,lighting_condition,notes
```

`validate-dataset` rejects split leakage, duplicate frame IDs/content, missing or non-monotonic timestamps, unreadable/non-binary masks, frame-mask size mismatch, invalid electrode IDs and manifest/annotation batch mismatches.

When `evaluate` receives `--electrode-map`, it additionally reports source/target coverage errors and electrode-assignment accuracy for all frames, non-Partial labeled frames, and Partial frames. `export-timeseries` emits the columns needed to plot source coverage, target coverage, target distance, velocity and state over time.

## Real Pilot sequence

1. Replace the example core corners and measured peripheral polygons in `configs/electrode_map.yaml`.
2. Render the map on an untouched chip image and inspect the full overlay plus selected crops.
3. Extract frames, create binary PNG masks and fill the Pilot annotation CSV.
4. Validate the dataset before running either baseline.
5. Run Threshold and Background with separate experiment configs against the same video list.
6. Evaluate both result CSVs with the same map and ground truth, then export transport time series.
