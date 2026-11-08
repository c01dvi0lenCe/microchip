"""Read-only, batch1 whole-chip profiling; not GT accuracy or camera acceptance.

--frame is a zero-based source-video index and may be repeated. Every selected
frame gets a complete same-frame reference prediction and strict pixel check.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HOST_STAGES = ('preprocess_host_ms', 'h2d_host_ms', 'model_host_ms',
               'postprocess_host_ms', 'd2h_host_ms', 'restore_host_ms', 'total_host_ms')
CUDA_STAGES = tuple('cuda_'+name+'_event_ms' for name in
                    ('h2d', 'model', 'postprocess', 'd2h', 'stream_span'))


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def _write_csv(path, rows):
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['frame_id', 'tile_index'])
        writer.writeheader(); writer.writerows(rows)


def _validate_output(output, package, video):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('profiling output already exists; choose a fresh directory')
    for source in (package, video):
        source = Path(source).resolve()
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('profiling output must be separate from source inputs')
    return output


def _measure_gui_display(frame, mask):
    """Call the real preview method on a withdrawn, hardware-free Tk harness.

This measures conversion/thumbnail/PhotoImage/label update, not physical screen
presentation latency. No main application, camera or serial owner is created.
"""
    import cv2
    import tkinter as tk
    from controllers.camera_controller import CameraControllerMixin

    class Harness(CameraControllerMixin):
        def _camera_preview_target_size(self):
            return (960, 640)

        def _update_camera_label(self, photo):
            self.camera_label.configure(image=photo)
            self.camera_label.image = photo

    root = tk.Tk(); root.withdraw()
    result = dict(status='measured', harness='withdrawn_tk_960x640',
                  physical_display_latency_measured=False, modes={})
    try:
        harness = Harness(); harness.camera_label = tk.Label(root)
        for mode in ('raw', 'overlay', 'mask'):
            begin = time.perf_counter_ns()
            if mode == 'mask':
                rgb = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
            else:
                view = frame if mode == 'raw' else frame.copy()
                if mode == 'overlay':
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(view, contours, -1, (40, 190, 20), 2)
                rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            prepared = time.perf_counter_ns()
            harness._show_camera_frame(rgb)
            shown = time.perf_counter_ns()
            root.update_idletasks()
            ended = time.perf_counter_ns()
            result['modes'][mode] = dict(prepare_host_ms=(prepared-begin)/1e6,
                show_camera_frame_host_ms=(shown-prepared)/1e6,
                idle_flush_host_ms=(ended-shown)/1e6, total_host_ms=(ended-begin)/1e6)
        harness.camera_label.configure(image=''); harness.camera_label.image = None
        return result
    finally:
        root.destroy()


def run_profile(package, video, frames, output, device='auto', skip_gui=False,
                warmup=2, predictor_factory=None):
    """Profile selected offline frames without mutating the frozen implementation."""
    package = Path(package).resolve(); video = Path(video).resolve()
    output = _validate_output(output, package, video)
    frames = list(frames)
    if not frames or any(type(frame) is not int or frame < 0 for frame in frames):
        raise ValueError('frames must be nonempty zero-based integer indices')
    if len(set(frames)) != len(frames):
        raise ValueError('duplicate source frame indices are not accepted')
    if type(warmup) is not int or warmup < 1:
        raise ValueError('at least one warmup is required')
    if not package.is_dir() or not video.is_file():
        raise FileNotFoundError('model package and source video must exist')
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import cv2
    import numpy as np
    from dmf.vision.g4_model import G4UNetPredictor
    from dmf.vision.image_io import write_image
    from dmf.vision.inference_profile import profile_infer
    from dmf.vision.whole_chip_geometry import plan_tiles, extract_tile, stitch_core, components

    sources = [Path(__file__).resolve(), ROOT/'dmf/vision/inference_profile.py',
        ROOT/'dmf/vision/g4_model.py', ROOT/'dmf/vision/whole_chip.py',
        ROOT/'dmf/vision/whole_chip_geometry.py', ROOT/'controllers/camera_controller.py',
        ROOT/'dmf/segmentation_research/semantic_baselines.py',
        ROOT/'dmf/segmentation_research/deep_training.py', video,
        *[path for path in package.rglob('*') if path.is_file()]]
    before = {str(path): _sha256(path) for path in sources}
    output.mkdir(parents=True, exist_ok=False); (output/'masks').mkdir()
    report = dict(schema='whole_chip_inference_profile_v1', status='running',
        source_video=str(video), selected_source_frames=frames, batch_size=1,
        warmup_iterations_per_frame=warmup, training_performed=False, gt_used=False,
        accuracy_evaluated=False, camera_opened=False, serial_opened=False,
        camera_acceptance=False, closed_loop_acceptance=False, frames=[], error='',
        input_sha256_before=before,
        timing_scope='offline host diagnostic; CUDA event times overlap host times and are never added',
        model_semantics='frozen RGB/ImageNet/sigmoid>=0.5/threshold_then_nearest',
        python=sys.version, executable=sys.executable, platform=platform.platform())
    tile_rows = []
    try:
        predictor = predictor_factory() if predictor_factory else G4UNetPredictor(package, device=device, batch_size=1)
        if predictor.batch_size != 1:
            raise ValueError('independent profiler requires frozen delivery batch1')
        torch = predictor.torch
        report['backend'] = predictor.device
        report['model_manifest'] = predictor.manifest
        report['environment'] = dict(torch=str(torch.__version__), cuda_runtime=torch.version.cuda,
            cudnn_version=torch.backends.cudnn.version(), cudnn_benchmark=torch.backends.cudnn.benchmark,
            cudnn_deterministic=torch.backends.cudnn.deterministic,
            torch_threads=torch.get_num_threads(), opencv=cv2.__version__, numpy=np.__version__,
            gpu=torch.cuda.get_device_name(0) if predictor.device == 'cuda' else None,
            package_versions={name: importlib.metadata.version(name) for name in
                ('torch', 'numpy', 'Pillow', 'opencv-python')})
        for frame_id in frames:
            decode_started = time.perf_counter_ns()
            capture = cv2.VideoCapture(str(video))
            try:
                if not capture.isOpened() or not capture.set(cv2.CAP_PROP_POS_FRAMES, frame_id):
                    raise OSError('cannot open/seek source video')
                ok, image = capture.read()
                position = int(round(capture.get(cv2.CAP_PROP_POS_FRAMES))) - 1
                if not ok or image is None or position != frame_id:
                    raise ValueError('source frame decode/index mismatch')
            finally:
                capture.release()
            decode_ms = (time.perf_counter_ns()-decode_started)/1e6
            tiles = plan_tiles(image.shape)
            warmup_started = time.perf_counter_ns()
            for _ in range(warmup):
                predictor.predict_batch([extract_tile(image, tiles[0])])
            if predictor.device == 'cuda':
                torch.cuda.synchronize()
            warmup_ms = (time.perf_counter_ns()-warmup_started)/1e6
            pipeline_started = time.perf_counter_ns()
            full = np.zeros(image.shape[:2], np.uint8)
            extract_ms = stitch_ms = profile_calls_ms = 0.
            for index, tile in enumerate(tiles):
                started = time.perf_counter_ns(); tile_image = extract_tile(image, tile)
                extract = (time.perf_counter_ns()-started)/1e6; extract_ms += extract
                started = time.perf_counter_ns(); predicted, stages = profile_infer(predictor, [tile_image])
                profile_call_ms = (time.perf_counter_ns()-started)/1e6; profile_calls_ms += profile_call_ms
                started = time.perf_counter_ns(); stitch_core(full, predicted[0], tile)
                stitch = (time.perf_counter_ns()-started)/1e6; stitch_ms += stitch
                events = stages.pop('cuda_events_ms')
                tile_rows.append(dict(frame_id=frame_id, tile_index=index, core_x=tile.core_x,
                    core_y=tile.core_y, core_w=tile.core_w, core_h=tile.core_h,
                    extract_host_ms=extract, stitch_host_ms=stitch,
                    profile_call_host_ms=profile_call_ms, **stages,
                    **{'cuda_'+key+'_event_ms': value for key, value in
                       (events or dict(h2d=None, model=None, postprocess=None, d2h=None, stream_span=None)).items()}))
            started = time.perf_counter_ns(); parts = components(full)
            components_ms = (time.perf_counter_ns()-started)/1e6
            pipeline_ms = (time.perf_counter_ns()-pipeline_started)/1e6
            reference_started = time.perf_counter_ns()
            reference = np.zeros(image.shape[:2], np.uint8)
            for tile in tiles:
                ordinary = predictor.predict_batch([extract_tile(image, tile)])[0]
                stitch_core(reference, ordinary, tile)
            reference_parts = components(reference)
            reference_ms = (time.perf_counter_ns()-reference_started)/1e6
            different = int(np.count_nonzero(reference != full))
            stem = f'frame_{frame_id:06}'
            for suffix, mask in (('profile', full), ('reference', reference)):
                mask_path = output/'masks'/f'{stem}_{suffix}.png'
                if not write_image(mask_path, mask):
                    raise OSError(f'PNG write failed: {mask_path}')
            gui = dict(status='skipped_by_request') if skip_gui else _measure_gui_display(image, full)
            record = dict(source_frame_id=frame_id, native_shape=list(image.shape),
                decoded_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest(), tile_count=len(tiles),
                decode_host_ms=decode_ms, warmup_host_ms=warmup_ms,
                pipeline_host_ms=pipeline_ms, extract_host_ms=extract_ms,
                stitch_host_ms=stitch_ms, profile_calls_host_ms=profile_calls_ms,
                components_host_ms=components_ms, reference_pipeline_host_ms=reference_ms,
                different_pixels=different, components_equal=parts == reference_parts,
                components=parts, foreground_px=int(np.count_nonzero(full)), gui=gui)
            frame_rows = [row for row in tile_rows if row['frame_id'] == frame_id]
            record['host_stage_totals_ms'] = {
                key: sum(row[key] for row in frame_rows) for key in HOST_STAGES}
            record['cuda_event_stage_totals_ms'] = {
                key: sum(row[key] for row in frame_rows) for key in CUDA_STAGES
            } if predictor.device == 'cuda' else None
            report['frames'].append(record)
            if different or parts != reference_parts:
                raise ValueError(f'profile/reference strict parity failed: {different} pixels')
            print(f'profile frame {frame_id}: {len(tiles)} tiles, {pipeline_ms:.2f} ms, 0 differing pixels', flush=True)
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        after = {}
        for path in before:
            try:
                after[path] = _sha256(path)
            except OSError as exc:
                after[path] = f'unreadable:{type(exc).__name__}'
        report['input_sha256_after'] = after
        report['input_changes'] = [path for path in before if before[path] != after[path]]
        report['read_only_inputs_verified'] = not report['input_changes']
        if report['input_changes']:
            report['status'] = 'failed'; report['error'] = 'read-only source changed during profiling'
        _write_csv(output/'tiles.csv', tile_rows)
        report['tile_timing_summary'] = dict(sample_count=len(tile_rows),
            host_ms={}, cuda_events_ms={},
            warning='Host stages and CUDA event stages overlap; never add these clocks or sum total with its components')
        for group, keys in (('host_ms', HOST_STAGES), ('cuda_events_ms', CUDA_STAGES)):
            for key in keys:
                values = [row[key] for row in tile_rows if row[key] is not None]
                if values:
                    report['tile_timing_summary'][group][key] = dict(
                        sum=float(np.sum(values)), mean=float(np.mean(values)),
                        p95=float(np.percentile(values, 95)), min=float(np.min(values)),
                        max=float(np.max(values)))
        report['output_sha256'] = {path.relative_to(output).as_posix(): _sha256(path)
            for path in output.rglob('*') if path.is_file() and path.name != 'summary.json'}
        _write_json(output/'summary.json', report)
    if report['status'] != 'passed':
        raise RuntimeError(report['error'])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'video', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--frame', action='append', type=int, help='zero-based video frame index; repeatable; default 0')
    parser.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    parser.add_argument('--warmup', type=int, default=2)
    parser.add_argument('--skip-gui', action='store_true')
    args = parser.parse_args(argv)
    run_profile(args.package, args.video, args.frame or [0], args.output,
                args.device, args.skip_gui, args.warmup)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
