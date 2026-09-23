# DMF unified offline vision framework

Phase 1 separates offline algorithm comparison from the existing Tkinter and STM32 control path. It implements threshold and explicit-background baselines without selecting a final neural network or inventing state thresholds.

## Commands

```powershell
python -m dmf.vision extract-frames --video input.mp4 --video-id pilot01 --output-dir data/frames/pilot01
python -m dmf.vision validate-dataset --manifest data/splits/manifest.csv --annotations data/annotations/pilot.csv
python -m dmf.vision run-baseline --config configs/experiment.yaml
python -m dmf.vision evaluate --results results/pilot/frame_results.csv --ground-truth data/annotations/pilot.csv --output-dir results/pilot/evaluation
```

For background subtraction, configure either `background_images` or a dedicated blank `background_video`. The test video itself is never sampled to create the background.

## Result contract

`frame_results.csv` stores the timestamp source, detection, pixel/mm centroid, area, source/target coverage, target distance, timestamp-derived velocity, state placeholders, algorithm time, pipeline time, mask path and error code. `run_manifest.json` stores the full configuration snapshot.

IDs 1-400 are the row-major core. IDs 401-420 retain the current physical peripheral mapping, including the four L-shaped corner electrodes. Runs that name a peripheral source or target fail until that electrode has a measured `pixel_overrides` polygon.

Threshold and background subtraction always emit a full-size binary mask, including an all-zero mask on a miss. `mask=None` is reserved for later localization-only algorithms. Evaluation reports both algorithm-only and end-to-end pipeline timing.
