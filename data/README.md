# Vision experiment data

Large experiment artifacts are intentionally not committed. Keep local data in:

- `raw_videos/`: immutable source videos
- `frames/`: extracted PNG frames and `frames.csv`
- `masks/`: binary ground-truth masks (0 background, 255 droplet)
- `annotations/`: frame-level CSV labels
- `splits/`: explicit video/batch train-validation-test manifests

The canonical annotation columns are:

```text
video_id,batch_id,frame_id,timestamp_s,mask_path,source_electrode,target_electrode,state_gt
```

Never place frames from the same video or experimental batch in different splits.
