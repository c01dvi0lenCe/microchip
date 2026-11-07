"""Matched first development training, with read-only G2/G3 and GPU preflight."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import time
import traceback

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import torch

from scripts.run_real_segmentation_internal_baselines import _load_samples, _sha, _csv, _read
from dmf.segmentation_research.deep_training import (
    prepare_training_sample, matched_transform, image_tensor, masked_bce_dice,
    epoch_order, is_improvement,
)
from dmf.segmentation_research.semantic_baselines import restore_mask, score_mask


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def reset_rng(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def state_hash(state):
    digest = hashlib.sha256()
    for key, value in sorted(state.items()):
        array = value.detach().cpu().contiguous().numpy()
        digest.update(key.encode())
        digest.update(str(array.dtype).encode())
        digest.update(str(array.shape).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def build_model(name, pretrained):
    import segmentation_models_pytorch as smp
    common = dict(encoder_name='resnet34', encoder_depth=5, encoder_weights=None,
                  in_channels=3, classes=1, activation=None)
    if name == 'unet':
        model = smp.Unet(**common)
    elif name == 'deeplabv3plus':
        model = smp.DeepLabV3Plus(**common, encoder_output_stride=16)
    else:
        raise ValueError('unknown model')
    model.encoder.load_state_dict(dict(pretrained), strict=True)
    return model


def get_batch(items, indices, epoch, seed, augment):
    xs, ys, vs = [], [], []
    for i in indices:
        item = items[i]
        rgb, gt, valid, _ = item['prepared']
        if augment:
            rgb, gt, valid, _ = matched_transform(rgb, gt, valid, seed, epoch, item['row']['sample_id'])
        xs.append(image_tensor(rgb))
        ys.append(torch.from_numpy(np.ascontiguousarray(gt[None])))
        vs.append(torch.from_numpy(np.ascontiguousarray(valid[None])))
    return tuple(torch.stack(values).cuda() for values in (xs, ys, vs))


def evaluate_epoch(model, items, config):
    model.eval()
    losses, metrics = [], []
    with torch.inference_mode():
        for first in range(0, len(items), config['batch_size']):
            batch = items[first:first + config['batch_size']]
            x, y, v = get_batch(batch, range(len(batch)), 0, config['seed'], False)
            with torch.autocast('cuda', dtype=torch.float16):
                logits = model(x)
                loss = masked_bce_dice(logits, y, v)
            if not torch.isfinite(loss):
                raise RuntimeError('nonfinite validation loss')
            losses.extend([float(loss)] * len(batch))
            masks = (logits.float().sigmoid() >= config['threshold']).to(torch.uint8).cpu().numpy()[:, 0] * 255
            for item, mask in zip(batch, masks):
                native = restore_mask(mask, item['prepared'][3])
                metrics.append(score_mask(native, item['gt'], item['ignore']))
    return dict(loss=float(np.mean(losses)),
                dice=float(np.mean([r['dice'] for r in metrics])),
                iou=float(np.mean([r['iou'] for r in metrics])))


def checkpoint(path, model, optimizer, scaler, epoch, best, config_hash, sources):
    value = dict(model_state=model.state_dict(), optimizer_state=optimizer.state_dict(),
                 scaler_state=scaler.state_dict(), epoch=epoch, best_native_val_dice=best,
                 config_sha256=config_hash, source_sha256=sources,
                 python_rng=random.getstate(), numpy_rng=np.random.get_state(),
                 torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state_all())
    tmp = path.with_suffix('.tmp')
    torch.save(value, tmp)
    tmp.replace(path)


def gpu_preflight(name, pretrained, train, config):
    reset_rng(config['seed'])
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    model = build_model(name, pretrained).cuda()
    encoder_hash = state_hash(model.encoder.state_dict())
    optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
    scaler = torch.amp.GradScaler('cuda')
    model.train()
    x, y, v = get_batch(train, range(config['batch_size']), 1, config['seed'], True)
    with torch.autocast('cuda', dtype=torch.float16):
        logits = model(x)
        loss = masked_bce_dice(logits, y, v)
    if not torch.isfinite(loss):
        raise RuntimeError('preflight loss nonfinite')
    scaler.scale(loss).backward()
    scaler.unscale_(optimizer)
    if not all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None):
        raise RuntimeError('preflight gradients nonfinite')
    scaler.step(optimizer)
    scaler.update()
    torch.cuda.synchronize()
    result = dict(model=name, passed=True, batch_size=config['batch_size'],
                  output_shape=list(logits.shape), loss=float(loss.detach()),
                  initial_encoder_sha256=encoder_hash,
                  parameters=sum(p.numel() for p in model.parameters()),
                  peak_allocated_mb=torch.cuda.max_memory_allocated() / 1024**2,
                  peak_reserved_mb=torch.cuda.max_memory_reserved() / 1024**2,
                  model_repr=str(model))
    del model, optimizer, scaler, x, y, v, logits, loss
    gc.collect()
    torch.cuda.empty_cache()
    return result


def train_model(name, pretrained, train, val, config, output, sources):
    model_dir = output / name
    model_dir.mkdir()
    reset_rng(config['seed'])
    model = build_model(name, pretrained).cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
    scaler = torch.amp.GradScaler('cuda')
    initial_hash = state_hash(model.encoder.state_dict())
    logs, best, stale = [], -1., 0
    started = time.perf_counter()
    for epoch in range(1, config['max_epochs'] + 1):
        tick = time.perf_counter()
        model.train()
        losses = []
        order = epoch_order(len(train), config['seed'], epoch)
        for first in range(0, len(order), config['batch_size']):
            x, y, v = get_batch(train, order[first:first + config['batch_size']], epoch, config['seed'], True)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast('cuda', dtype=torch.float16):
                logits = model(x)
                loss = masked_bce_dice(logits, y, v)
            if not torch.isfinite(loss):
                raise RuntimeError(f'nonfinite train loss {name} epoch{epoch}')
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            if not all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None):
                raise RuntimeError(f'nonfinite train gradient {name} epoch{epoch}')
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach()))
        val_result = evaluate_epoch(model, val, config)
        improved = is_improvement(val_result['dice'], best)
        stale = 0 if improved else stale + 1
        if improved:
            best = val_result['dice']
            checkpoint(model_dir / 'best.pt', model, optimizer, scaler, epoch, best, _sha(output / 'frozen_protocol.json'), sources)
        checkpoint(model_dir / 'last.pt', model, optimizer, scaler, epoch, best, _sha(output / 'frozen_protocol.json'), sources)
        row = dict(epoch=epoch, optimizer_steps=len(losses), train_loss=float(np.mean(losses)),
                   val_loss=val_result['loss'], native_val_dice=val_result['dice'], native_val_iou=val_result['iou'],
                   improved=improved, stale_epochs=stale, elapsed_s=time.perf_counter() - tick,
                   order_sha256=hashlib.sha256(json.dumps(order).encode()).hexdigest(),
                   grad_scale=float(scaler.get_scale()))
        logs.append(row)
        _csv(model_dir / 'epochs.csv', logs)
        print(json.dumps(dict(model=name, **row)), flush=True)
        if stale >= config['early_stop_patience']:
            break
    result = dict(model=name, status='completed', epochs=len(logs), seed=config['seed'],
                  stop_reason='early_stopping' if stale >= config['early_stop_patience'] else 'max_epochs',
                  initial_encoder_sha256=initial_hash, best_native_val_dice=best,
                  best_epoch=next(r['epoch'] for r in logs if abs(r['native_val_dice'] - best) <= 1e-8),
                  total_elapsed_s=time.perf_counter() - started,
                  best_checkpoint_sha256=_sha(model_dir / 'best.pt'),
                  last_checkpoint_sha256=_sha(model_dir / 'last.pt'))
    write_json(model_dir / 'training_manifest.json', result)
    del model, optimizer, scaler
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/chapter2_segmentation_g4_development_v1.json'))
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('new output directory required; never overwrite a run')
    args.output.mkdir(parents=True)
    config = json.loads(args.config.read_text(encoding='utf-8'))
    write_json(args.output / 'frozen_protocol.json', config)
    frozen = {str(p.resolve()): _sha(p) for p in args.root.rglob('*') if p.is_file()}
    repo = Path(__file__).resolve().parents[1]
    protected = {str(p.resolve()): _sha(p) for folder in ('controllers', 'dmf/experiment', 'dmf/vision', 'configs')
                 for p in (repo / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    write_json(args.output / 'frozen_inputs_before.json', frozen)
    write_json(args.output / 'protected_sources_before.json', protected)
    try:
        paths = set()
        loaded = _load_samples(args.root, paths)
        counts = Counter(row['split'] for row, *_ in loaded)
        if counts != {'train': 144, 'val': 36}:
            raise ValueError('frozen split count differs')
        items, audits, review = [], [], []
        for row, image, gt, ignore in loaded:
            prepared = prepare_training_sample(image, gt, ignore)
            item = dict(row=row, image=image, gt=gt, ignore=ignore, prepared=prepared)
            items.append(item)
            audits.append(dict(sample_id=row['sample_id'], split=row['split'],
                               native_hw=list(gt.shape), gt_valid_native=int(((gt > 0) & (ignore == 0)).sum()),
                               gt_valid_model=int((prepared[1] * prepared[2]).sum()),
                               valid_model=int(prepared[2].sum()), ignore_native=int((ignore > 0).sum()),
                               image_sha256=row['frame_path_sha256'], gt_sha256=row['mask_path_sha256'],
                               ignore_sha256=row['exclusion_mask_path_sha256']))
            if row['split'] == 'val':
                number = int(row['sample_id'][3:])
                flags = []
                if not ((gt > 0) & (ignore == 0)).any(): flags.append('empty_GT_grid_texture')
                if number in (149, 150, 161, 162, 163, 164): flags.append('bridge_or_split_reflection_boundary')
                if int(row.get('tiny_components_lt16px') or 0): flags.append('tiny_fragments')
                if ignore.any(): flags.append('fixed_reservoir_ignore_boundary')
                if row.get('foreground_touches_roi_edge') == 'True': flags.append('edge_truncated_foreground')
                review.append(dict(sample_id=row['sample_id'], flags=';'.join(flags) or 'normal_or_multidroplet',
                                   reviewer='assistant_targeted_visual_screen_not_new_human_GT',
                                   original_human_review=True, original_GT_unchanged=True,
                                   disposition='retain_frozen_annotation_no_definite_label_error_identified',
                                   uncertainty='subpixel_boundaries_and_tiny_fragment_identity_not_independently_reannotated'))
        if any(r['gt_valid_native'] > 0 and r['gt_valid_model'] == 0 for r in audits):
            raise ValueError('positive sample lost entirely at model scale')
        _csv(args.output / 'data_alignment_audit.csv', audits)
        _csv(args.output / 'targeted_validation_review.csv', review)
        write_json(args.output / 'data_check.json', dict(passed=True, train=144, val=36, formal_test=0,
                   independent_batches=False, human_GT_corrections=0, assistant_visual_review=36,
                   training_authorized_by_current_user=True,
                   historical_deep_training_release_flag_unchanged=True,
                   empty_val_ids=[r['sample_id'] for r in audits if r['split']=='val' and r['gt_valid_native']==0]))
        shutil.copy2(repo / 'docs/superpowers/specs/2026-11-05-real-segmentation-g4-design.md', args.output / 'G4匹配训练协议.md')
        if args.prepare_only:
            return
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; no automatic CPU training')
        import segmentation_models_pytorch as smp
        import torchvision
        if smp.__version__ != config['smp_version']:
            raise ValueError('SMP version differs from frozen config')
        cv2.setNumThreads(config['opencv_threads'])
        torch.set_num_threads(config['torch_cpu_threads'])
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True, warn_only=True)
        environment = dict(python=sys.version, executable=sys.executable, torch=torch.__version__,
                           torchvision=torchvision.__version__, smp=smp.__version__, cuda=torch.version.cuda,
                           cudnn=torch.backends.cudnn.version(), gpu=torch.cuda.get_device_name(0),
                           gpu_total_memory=torch.cuda.get_device_properties(0).total_memory,
                           platform=platform.platform(), numpy=np.__version__, opencv=cv2.__version__,
                           git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
                           git_dirty=True, deterministic='warn_only; not_cross_environment_bitwise_guaranteed')
        write_json(args.output / 'environment.json', environment)
        (args.output / 'pip_freeze.txt').write_text(subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True), encoding='utf-8')
        weights = torchvision.models.ResNet34_Weights.IMAGENET1K_V1
        pretrained = weights.get_state_dict(progress=True, check_hash=True)
        pretrained_path = Path(torch.hub.get_dir()) / 'checkpoints' / weights.url.split('/')[-1]
        shutil.copy2(pretrained_path, args.output / pretrained_path.name)
        write_json(args.output / 'pretrained_source.json', dict(source_url=weights.url,
                   official_file_sha256=_sha(pretrained_path), enum='IMAGENET1K_V1'))
        sources = {str(p.relative_to(repo)): _sha(p) for p in [Path(__file__).resolve(),
                   repo / 'dmf/segmentation_research/deep_training.py',
                   repo / 'dmf/segmentation_research/semantic_baselines.py',
                   repo / 'scripts/run_real_segmentation_internal_baselines.py', args.config.resolve()]}
        write_json(args.output / 'source_sha256.json', sources)
        train = [i for i in items if i['row']['split']=='train']
        val = [i for i in items if i['row']['split']=='val']
        preflights = []
        for name in config['models']:
            print('GPU preflight ' + name, flush=True)
            preflights.append(gpu_preflight(name, pretrained, train, config))
            write_json(args.output / 'gpu_preflight.json', preflights)
        if len({p['initial_encoder_sha256'] for p in preflights}) != 1:
            raise RuntimeError('different pretrained encoder initializations')
        write_json(args.output / 'run_status.json', dict(stage='training', preflight_passed=True))
        results = []
        for name in config['models']:
            results.append(train_model(name, pretrained, train, val, config, args.output, sources))
            write_json(args.output / 'run_status.json', dict(stage='training' if len(results)<2 else 'training_completed', results=results))
    except BaseException as exc:
        write_json(args.output / 'failure.json', dict(error=repr(exc), traceback=traceback.format_exc()))
        raise
    finally:
        changed = [p for p, h in {**frozen, **protected}.items() if not Path(p).is_file() or _sha(Path(p)) != h]
        write_json(args.output / 'read_only_verification.json', dict(passed=not changed,
                   frozen_files=len(frozen), protected_files=len(protected), changed=changed))
        if changed:
            raise RuntimeError('protected inputs changed')


if __name__ == '__main__':
    main()
