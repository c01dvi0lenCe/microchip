"""Offline binary segmentation training contract; no camera/control dependencies."""
from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from .semantic_baselines import prepare_image


def prepare_training_sample(image, gt, ignore):
    """Return RGB float, nearest GT, conservative valid domain and G3 metadata."""
    if gt.shape != image.shape[:2] or ignore.shape != gt.shape:
        raise ValueError('native image, GT and Ignore must align')
    for mask in (gt, ignore):
        if mask.dtype != np.uint8 or mask.ndim != 2 or not np.isin(mask, [0, 255]).all():
            raise ValueError('GT/Ignore must be uint8 binary')
    prepared, meta = prepare_image(image)
    h, w = meta['resized_hw']
    x, y = meta['offset_xy']
    target = np.zeros((512, 512), np.float32)
    valid = np.zeros_like(target)
    target[y:y+h, x:x+w] = cv2.resize(gt, (w, h), interpolation=cv2.INTER_NEAREST) > 0
    # INTER_AREA is fractional coverage, not a GT interpolator. Any Ignore
    # contribution invalidates the reduced pixel; padding is always invalid.
    mode = cv2.INTER_AREA if meta['scale'] < 1 else cv2.INTER_NEAREST
    ignored = cv2.resize((ignore > 0).astype(np.float32), (w, h), interpolation=mode) > 0
    valid[y:y+h, x:x+w] = ~ignored
    if not valid.any():
        raise ValueError('sample has no valid pixels')
    return prepared[:, :, ::-1].astype(np.float32) / 255., target, valid, meta


def matched_transform(rgb, target, valid, seed, epoch, sample_id):
    """Model-independent joint geometry and image-only photometric perturbation."""
    key = f'{seed}:{epoch}:{sample_id}'.encode()
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(key).digest()[:8], 'big'))
    info = dict(horizontal=bool(rng.random() < .5), vertical=bool(rng.random() < .5),
                quarter_turns=int(rng.integers(4)), brightness=float(rng.uniform(-.05, .05)),
                contrast=float(rng.uniform(.9, 1.1)))
    values = [rgb, target, valid]
    if info['horizontal']:
        values = [np.flip(a, axis=1) for a in values]
    if info['vertical']:
        values = [np.flip(a, axis=0) for a in values]
    values = [np.ascontiguousarray(np.rot90(a, info['quarter_turns'])) for a in values]
    values[0] = np.clip((values[0] - .5) * info['contrast'] + .5 + info['brightness'], 0, 1)
    return *values, info


def image_tensor(rgb):
    mean = np.array([.485, .456, .406], np.float32)
    std = np.array([.229, .224, .225], np.float32)
    return torch.from_numpy(np.ascontiguousarray(((rgb - mean) / std).transpose(2, 0, 1)))


def masked_bce_dice(logits, target, valid):
    """Equal-image masked BCE/Dice, including empty GT; Ignore gradient is zero."""
    if logits.shape != target.shape or valid.shape != target.shape or logits.ndim != 4:
        raise ValueError('logits, targets and valid must align in NCHW')
    logits, target, valid = logits.float(), target.float(), valid.float()
    counts = valid.sum(dim=(1, 2, 3))
    if (counts <= 0).any():
        raise ValueError('every image needs valid pixels')
    safe_logits = torch.where(valid > 0, logits, torch.zeros_like(logits))
    safe_target = torch.where(valid > 0, target, torch.zeros_like(target))
    bce = (F.binary_cross_entropy_with_logits(safe_logits, safe_target, reduction='none') * valid)
    bce = bce.sum(dim=(1, 2, 3)) / counts
    p = torch.sigmoid(safe_logits) * valid
    y = safe_target * valid
    dice = (2 * (p * y).sum(dim=(1, 2, 3)) + 1) / (p.sum(dim=(1, 2, 3)) + y.sum(dim=(1, 2, 3)) + 1)
    return (.5 * bce + .5 * (1 - dice)).mean()


def epoch_order(count, seed, epoch):
    return np.random.default_rng(np.random.SeedSequence([seed, epoch])).permutation(count).tolist()


def is_improvement(score, best):
    if not math.isfinite(score):
        raise ValueError('nonfinite validation score')
    return score > best + 1e-8
