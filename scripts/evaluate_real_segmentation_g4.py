"""Native-grid internal validation; frozen traditional predictions are reused."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import torch

from dmf.segmentation_research.deep_training import image_tensor
from dmf.segmentation_research.semantic_baselines import prepare_image, restore_mask, score_mask
from scripts.run_real_segmentation_internal_baselines import _load_samples, _csv, _sha, _maps, _coverage
from scripts.train_real_segmentation_g4 import build_model, write_json


def decode_baseline_row(raw):
    result = dict(raw)
    for key in ('eligible', 'positive_gt', 'error', 'image_level_miss', 'empty_mask', 'target_coverage_available'):
        if key in raw:
            result[key] = raw[key] == 'True' if raw[key] else None
    for key in ('tp', 'fp', 'fn', 'tn', 'valid_pixels', 'ignored_pixels'):
        if key in raw:
            result[key] = int(raw[key]) if raw[key] else None
    for key in ('dice', 'iou', 'precision', 'recall', 'target_coverage_absolute_error'):
        if key in raw:
            result[key] = float(raw[key]) if raw[key] else None
    return result


def summarize(rows, method, subset='all36'):
    usable = [r for r in rows if r['eligible']]
    positive = [r for r in usable if r['positive_gt']]
    empty = [r for r in usable if not r['positive_gt']]
    result = dict(method=method, subset=subset, planned=len(rows), eligible=len(usable),
                  unavailable=len(rows)-len(usable), availability=len(usable)/len(rows) if rows else None,
                  positive_GT=len(positive), empty_GT=len(empty),
                  empty_GT_false_positive_images=sum(r['fp'] > 0 for r in empty),
                  image_level_misses=sum(bool(r.get('image_level_miss')) for r in positive),
                  runtime_errors=sum(bool(r.get('error')) for r in usable),
                  false_positive_area_px_mean=float(np.mean([r['fp'] for r in usable])) if usable else None,
                  false_positive_area_fraction_mean=float(np.mean([r['fp']/r['valid_pixels'] for r in usable])) if usable else None,
                  centroid_error='NA_unreviewed_instance_GT',
                  evaluation_role='same_day_internal_development_not_independent_test')
    for key in ('dice', 'iou', 'precision', 'recall'):
        result[key + '_mean'] = float(np.mean([r[key] for r in usable])) if usable else None
        result['positive_' + key + '_mean'] = float(np.mean([r[key] for r in positive])) if positive else None
    return result


def predict(model, image, config):
    prepared, meta = prepare_image(image)
    rgb = prepared[:, :, ::-1].astype(np.float32)/255.
    tensor = image_tensor(rgb)[None].cuda()
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
        logits = model(tensor)
    binary = (logits.float().sigmoid() >= config['threshold']).to(torch.uint8).cpu().numpy()[0, 0] * 255
    return restore_mask(binary, meta)


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def evaluate(root, run):
    output = run / 'evaluation'
    if output.exists():
        raise ValueError('evaluation exists; no overwrite allowed')
    output.mkdir()
    config = json.loads((run / 'frozen_protocol.json').read_text(encoding='utf-8'))
    sources = json.loads((run / 'source_sha256.json').read_text(encoding='utf-8'))
    repo = Path(__file__).resolve().parents[1]
    if any(_sha(repo / p) != h for p, h in sources.items()):
        raise ValueError('training source differs from recorded version')
    cv2.setNumThreads(1)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    paths = set()
    loaded = [item for item in _load_samples(root, paths) if item[0]['split'] == 'val']
    maps = _maps(root, paths)
    traditional = [decode_baseline_row(r) for r in read_csv(root / 'G3_initial_baselines_v1/per_image.csv') if r['split']=='val']
    all_rows, times, checkpoints = list(traditional), [], {}
    pretrained = torch.load(run / 'resnet34-b627a593.pth', map_location='cpu', weights_only=True)
    for name in config['models']:
        manifest = json.loads((run / name / 'training_manifest.json').read_text(encoding='utf-8'))
        file = run / name / 'best.pt'
        if _sha(file) != manifest['best_checkpoint_sha256']:
            raise ValueError('checkpoint hash differs')
        checkpoint = torch.load(file, map_location='cpu', weights_only=False)
        if checkpoint['config_sha256'] != _sha(run / 'frozen_protocol.json'):
            raise ValueError('checkpoint protocol differs')
        model = build_model(name, pretrained).cuda()
        model.load_state_dict(checkpoint['model_state'], strict=True)
        model.eval()
        prediction_dir = output / 'predictions' / name
        prediction_dir.mkdir(parents=True)
        for row, image, gt, ignore in loaded:
            sample_id = row['sample_id']
            for _ in range(config['warmup_inferences']):
                predict(model, image, config)
            torch.cuda.synchronize()
            first_prediction = None
            for repeat in range(config['timed_repeats_per_image']):
                torch.cuda.synchronize()
                start = time.perf_counter_ns()
                mask = predict(model, image, config)
                torch.cuda.synchronize()
                elapsed = (time.perf_counter_ns() - start)/1e6
                if repeat == 0:
                    first_prediction = mask
                elif not np.array_equal(mask, first_prediction):
                    raise RuntimeError(f'nondeterministic repeat {name}/{sample_id}')
                times.append(dict(method=name, sample_id=sample_id, repeat=repeat,
                                  timing_scope='GPU_pipeline_no_decode_score_disk', elapsed_ms=elapsed))
            # Separate CUDA-event forward cost; static input prepared outside it.
            prepared, _ = prepare_image(image)
            tensor = image_tensor(prepared[:, :, ::-1].astype(np.float32)/255.)[None].cuda()
            for repeat in range(config['timed_repeats_per_image']):
                a, b = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                a.record()
                with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
                    binary = model(tensor).float().sigmoid() >= config['threshold']
                b.record()
                b.synchronize()
                times.append(dict(method=name, sample_id=sample_id, repeat=repeat,
                                  timing_scope='CUDA_forward_sigmoid_threshold_no_transfer', elapsed_ms=a.elapsed_time(b)))
            path = prediction_dir / f'{sample_id}.png'
            encoded = cv2.imencode('.png', first_prediction)[1]
            path.write_bytes(encoded.tobytes())
            metrics = score_mask(first_prediction, gt, ignore)
            all_rows.append(dict(sample_id=sample_id, parent_video_id=row['parent_video_id'], split='val',
                                 method=name, **metrics, prediction_path=str(path.relative_to(output)),
                                 prediction_sha256=_sha(path),
                                 **_coverage(row, first_prediction, gt, ignore, maps),
                                 model_best_epoch=checkpoint['epoch'], source_model_sha256=_sha(file)))
        checkpoints[name] = dict(epoch=checkpoint['epoch'], sha256=_sha(file))
        del model, checkpoint
        torch.cuda.empty_cache()
    methods = ('otsu', 'unet', 'deeplabv3plus', 'background')
    summary = [summarize([r for r in all_rows if r['method']==m], m) for m in methods]
    common_ids = {r['sample_id'] for r in traditional if r['method']=='background' and r['eligible']}
    common = [summarize([r for r in all_rows if r['method']==m and r['sample_id'] in common_ids], m,
                        'common_background_eligible6') for m in methods]
    per_video = [summarize([r for r in all_rows if r['method']==m and r['parent_video_id']==v], m, v)
                 for m in methods for v in sorted({r['parent_video_id'] for r in all_rows})]
    time_summary = []
    for method in config['models']:
        for scope in sorted({r['timing_scope'] for r in times}):
            values = [r['elapsed_ms'] for r in times if r['method']==method and r['timing_scope']==scope]
            time_summary.append(dict(method=method, timing_scope=scope, images=36, repeats_per_image=10,
                                     mean_ms=float(np.mean(values)), p50_ms=float(np.percentile(values, 50)),
                                     p95_ms=float(np.percentile(values, 95))))
    _csv(output / 'per_image.csv', all_rows)
    _csv(output / 'summary.csv', summary)
    _csv(output / 'common_background_subset_summary.csv', common)
    _csv(output / 'per_video.csv', per_video)
    _csv(output / 'timings.csv', times)
    _csv(output / 'timing_summary.csv', time_summary)
    write_json(output / 'manifest.json', dict(models=checkpoints, planned_val=36, formal_test=0,
               background_eligible_val=6, background_planned_val=36,
               primary_comparison=['otsu', 'unet', 'deeplabv3plus'],
               joint_background_subset_ids=sorted(common_ids),
               original_traditional_results_reused_not_recomputed=True,
               input_sha256={str(p):_sha(p) for p in paths},
               output_sha256={str(p.relative_to(output)):_sha(p) for p in output.rglob('*') if p.is_file()},
               evaluator_sha256=_sha(Path(__file__)),
               uncertainty='descriptive_single_seed_internal_validation_no_independent_batch_CI'))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.root, args.run), ensure_ascii=False, indent=2))
