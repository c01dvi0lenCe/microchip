from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from .dataset import validate_dataset, write_csv_rows
from .evaluation import evaluate_results
from .image_io import write_image
from .pipeline import run_baseline
from .timebase import VideoTimestampResolver
from .config import load_electrode_map, save_electrode_map
from .overlay import render_electrode_overlay
from .timeseries import export_transport_timeseries
from ..recording import load_recorded_timestamps

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def extract_frames(
    video_path: Path,
    video_id: str,
    output_dir: Path,
    every_n: int = 1,
    max_frames: Optional[int] = None,
    fps_fallback: Optional[float] = None,
) -> Path:
    if cv2 is None:
        raise RuntimeError("opencv-python is required to extract frames")
    if every_n < 1:
        raise ValueError("every_n must be positive")
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or float(fps_fallback or 0.0)
    if fps <= 0:
        cap.release()
        raise ValueError("video has no FPS metadata; --fps-fallback is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    frame_id = 0
    saved = 0
    timestamps = VideoTimestampResolver(fps)
    try:
        recorded_times = load_recorded_timestamps(video_path)
        if recorded_times is not None and len(recorded_times) != int(cap.get(cv2.CAP_PROP_FRAME_COUNT)):
            raise ValueError('video frame count does not match recorded timestamps')
        while max_frames is None or saved < max_frames:
            ok, frame = cap.read()
            if not ok:
                if recorded_times is not None and frame_id < len(recorded_times):
                    raise ValueError('video decode ended before recorded timestamps')
                break
            if recorded_times is not None:
                if frame_id >= len(recorded_times):
                    raise ValueError('video has extra frames without timestamps')
                timestamp_s, timestamp_source = recorded_times[frame_id], 'host_receive_perf_counter'
            else:
                timestamp_s, timestamp_source = timestamps.resolve(frame_id, cap.get(cv2.CAP_PROP_POS_MSEC))
            if frame_id % every_n == 0:
                relative = Path("frames") / f"{video_id}_{frame_id:06d}.png"
                path = output_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if not write_image(path, frame):
                    raise RuntimeError(f"could not write extracted frame: {path}")
                rows.append(
                    {
                        "video_id": video_id,
                        "frame_id": frame_id,
                        "timestamp_s": timestamp_s,
                        "timestamp_source": timestamp_source,
                        "frame_path": relative.as_posix(),
                    }
                )
                saved += 1
            frame_id += 1
    finally:
        cap.release()
    manifest = output_dir / "frames.csv"
    write_csv_rows(manifest, rows)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DMF offline vision experiment framework")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract-frames", help="Extract timestamped PNG frames from a video")
    extract.add_argument("--video", required=True, type=Path)
    extract.add_argument("--video-id", required=True)
    extract.add_argument("--output-dir", required=True, type=Path)
    extract.add_argument("--every-n", type=int, default=1)
    extract.add_argument("--max-frames", type=int)
    extract.add_argument("--fps-fallback", type=float)

    validate = subparsers.add_parser("validate-dataset", help="Validate group splits and PNG mask references")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--annotations", type=Path)

    run = subparsers.add_parser("run-baseline", help="Run one configured offline baseline")
    run.add_argument("--config", required=True, type=Path)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate unified frame results against PNG masks")
    evaluate.add_argument("--results", required=True, type=Path)
    evaluate.add_argument("--ground-truth", required=True, type=Path)
    evaluate.add_argument("--output-dir", required=True, type=Path)
    evaluate.add_argument("--boundary-tolerance-px", type=int, default=2)
    evaluate.add_argument("--electrode-map", type=Path)

    overlay = subparsers.add_parser("render-map", help="Overlay all 420 electrode polygons on a real chip image")
    overlay.add_argument("--image", required=True, type=Path)
    overlay.add_argument("--electrode-map", required=True, type=Path)
    overlay.add_argument("--output", required=True, type=Path)
    overlay.add_argument("--show-row-col", action="store_true")
    overlay.add_argument("--zoom-electrodes", default="")
    overlay.add_argument("--zoom-dir", type=Path)
    overlay.add_argument("--crop-padding-px", type=int, default=24)

    export_map = subparsers.add_parser("export-map", help="Save a calibrated electrode map as YAML or JSON")
    export_map.add_argument("--input", required=True, type=Path)
    export_map.add_argument("--output", required=True, type=Path)

    timeseries = subparsers.add_parser("export-timeseries", help="Export one transport sequence for plotting")
    timeseries.add_argument("--results", required=True, type=Path)
    timeseries.add_argument("--output", required=True, type=Path)
    timeseries.add_argument("--video-id")
    timeseries.add_argument("--experiment-id")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "extract-frames":
            path = extract_frames(
                args.video,
                args.video_id,
                args.output_dir,
                every_n=args.every_n,
                max_frames=args.max_frames,
                fps_fallback=args.fps_fallback,
            )
            print(f"frames_manifest={path}")
        elif args.command == "validate-dataset":
            counts = validate_dataset(args.manifest, args.annotations)
            print(" ".join(f"{key}={value}" for key, value in counts.items()))
        elif args.command == "run-baseline":
            results, manifest = run_baseline(args.config)
            print(f"results={results} manifest={manifest}")
        elif args.command == "evaluate":
            summary = evaluate_results(
                args.results,
                args.ground_truth,
                args.output_dir,
                args.boundary_tolerance_px,
                args.electrode_map,
            )
            print(f"matched_frames={summary['matched_frames']} output={args.output_dir}")
        elif args.command == "render-map":
            electrode_map = load_electrode_map(args.electrode_map)
            selected = [int(value) for value in args.zoom_electrodes.split(",") if value.strip()]
            outputs = render_electrode_overlay(
                args.image,
                electrode_map,
                args.output,
                args.show_row_col,
                selected,
                args.zoom_dir,
                args.crop_padding_px,
            )
            print(f"overlay={outputs[0]} crops={len(outputs) - 1}")
        elif args.command == "export-map":
            save_electrode_map(args.output, load_electrode_map(args.input))
            print(f"electrode_map={args.output}")
        elif args.command == "export-timeseries":
            path = export_transport_timeseries(
                args.results,
                args.output,
                args.video_id,
                args.experiment_id,
            )
            print(f"timeseries={path}")
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0
