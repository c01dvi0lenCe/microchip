"""Pure offline all-foreground baselines and native-ROI semantic scoring.

Prediction functions accept only images and fixed method parameters, never GT,
Ignore, electrode maps, or controller state. No component selection is applied.
Coverage is a provisional map diagnostic, not calibrated metrology or an
instance/identity metric; callers must retain that qualification in reports.
"""
from collections.abc import Mapping
import math

import cv2
import numpy as np


def _image(image, name='image'):
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or
            image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 1):
        raise ValueError(f'{name} must be a nonempty uint8 BGR image')
    return image


def _binary(mask, name, shape=None):
    if (not isinstance(mask, np.ndarray) or mask.dtype != np.uint8 or
            mask.ndim != 2 or min(mask.shape) < 1 or
            (shape is not None and mask.shape != shape) or
            np.any((mask != 0) & (mask != 255))):
        raise ValueError(f'{name} must be a same-sized uint8 binary (0/255) mask')
    return mask


def _hw(value, name):
    if (not isinstance(value, (tuple, list)) or len(value) != 2 or
            any(type(n) is not int or n < 1 for n in value)):
        raise ValueError(f'{name} must contain two positive integers')
    return tuple(value)


def prepare_image(image, target_hw=(512, 512)):
    """Aspect-preserving BGR letterbox; native images/labels stay unchanged.

    Metadata uses (height, width) sizes and (left, top) ``offset_xy``. ``scale``
    is the nominal uniform scale; ``resized_hw`` records exact rounded pixels.
    Downsampling uses INTER_AREA; upsampling uses INTER_LINEAR. Padding is white.
    """
    image = _image(image)
    target_h, target_w = _hw(target_hw, 'target_hw')
    native_h, native_w = image.shape[:2]
    scale = min(target_h / native_h, target_w / native_w)
    resized_h = max(1, min(target_h, round(native_h * scale)))
    resized_w = max(1, min(target_w, round(native_w * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=interpolation)
    left, top = (target_w - resized_w) // 2, (target_h - resized_h) // 2
    prepared = np.full((target_h, target_w, 3), 255, np.uint8)
    prepared[top:top + resized_h, left:left + resized_w] = resized
    meta = dict(native_hw=(native_h, native_w), target_hw=(target_h, target_w),
                resized_hw=(resized_h, resized_w), scale=scale, offset_xy=(left, top))
    return prepared, meta


def restore_mask(binary, meta):
    """Discard letterbox padding then restore a binary mask by nearest neighbor."""
    if not isinstance(meta, Mapping):
        raise ValueError('letterbox metadata is required')
    try:
        native_h, native_w = _hw(meta['native_hw'], 'native_hw')
        target_h, target_w = _hw(meta['target_hw'], 'target_hw')
        resized_h, resized_w = _hw(meta['resized_hw'], 'resized_hw')
        offset = meta['offset_xy']
        if (not isinstance(offset, (tuple, list)) or len(offset) != 2 or
                any(type(n) is not int or n < 0 for n in offset)):
            raise ValueError('offset_xy must contain two nonnegative integers')
        left, top = offset
        if top + resized_h > target_h or left + resized_w > target_w:
            raise ValueError('resized content exceeds letterbox dimensions')
    except KeyError as exc:
        raise ValueError('incomplete letterbox metadata') from exc
    binary = _binary(binary, 'prediction', (target_h, target_w))
    content = binary[top:top + resized_h, left:left + resized_w]
    return cv2.resize(content, (native_w, native_h), interpolation=cv2.INTER_NEAREST)


def _parameters(blur_kernel, close_kernel, close_iterations):
    for name, value in (('blur_kernel', blur_kernel), ('close_kernel', close_kernel)):
        if type(value) is not int or value < 1 or value % 2 != 1:
            raise ValueError(f'{name} must be a positive odd integer')
    if type(close_iterations) is not int or close_iterations < 0:
        raise ValueError('close_iterations must be a nonnegative integer')


def _gray(image, blur_kernel):
    return cv2.GaussianBlur(cv2.cvtColor(_image(image), cv2.COLOR_BGR2GRAY),
                            (blur_kernel, blur_kernel), 0)


def _close(mask, close_kernel, close_iterations):
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            np.ones((close_kernel, close_kernel), np.uint8),
                            iterations=close_iterations)


def otsu_mask(image, blur_kernel=5, close_kernel=3, close_iterations=1):
    """Inverse Otsu after Gaussian gray blur, retaining every component/border."""
    _parameters(blur_kernel, close_kernel, close_iterations)
    gray = _gray(image, blur_kernel)
    mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    return _close(mask, close_kernel, close_iterations)


def background_mask(image, background, threshold=20, blur_kernel=5,
                    close_kernel=3, close_iterations=1):
    """Dark foreground from Gaussian-gray ``background - image > threshold``.

    The subtraction is signed, not uint8 modular arithmetic. The caller must
    separately establish reference provenance with ``assert_causal_background``.
    """
    _parameters(blur_kernel, close_kernel, close_iterations)
    if (isinstance(threshold, (bool, np.bool_)) or not isinstance(threshold, (int, float)) or
            not math.isfinite(threshold) or not 0 <= threshold <= 255):
        raise ValueError('threshold must be finite and between 0 and 255')
    image, background = _image(image), _image(background, 'background')
    if image.shape != background.shape:
        raise ValueError('image and background dimensions must match')
    difference = (_gray(background, blur_kernel).astype(np.int16) -
                  _gray(image, blur_kernel).astype(np.int16))
    mask = (difference > threshold).astype(np.uint8) * 255
    return _close(mask, close_kernel, close_iterations)


def assert_causal_background(sample, reference):
    """Reject unreviewed, mismatched, nonfinite, repeated, or future references.

    ``usable`` must be literal True. Review kinds describe reference inspection,
    not ground-truth creation. Both source frame and timestamp must be earlier.
    """
    if not isinstance(sample, Mapping) or not isinstance(reference, Mapping):
        raise ValueError('sample and reference metadata are required')
    for key in ('parent_video_id', 'source_sha256'):
        value = sample.get(key)
        if not isinstance(value, str) or not value.strip() or reference.get(key) != value:
            raise ValueError(f'background identity mismatch: {key}')
    rois = []
    for metadata in (sample, reference):
        roi = metadata.get('roi_xywh')
        if (not isinstance(roi, (list, tuple)) or len(roi) != 4 or
                any(type(n) is not int for n in roi) or min(roi[:2]) < 0 or min(roi[2:]) < 1):
            raise ValueError('background requires valid roi_xywh')
        rois.append(tuple(roi))
    if rois[0] != rois[1]:
        raise ValueError('background identity mismatch: roi_xywh')
    frame_ids = [metadata.get('source_frame_id') for metadata in (reference, sample)]
    if any(type(frame) is not int or frame < 0 for frame in frame_ids) or frame_ids[0] >= frame_ids[1]:
        raise ValueError('background source_frame_id must be strictly earlier')
    timestamps = [metadata.get('timestamp_s') for metadata in (reference, sample)]
    if (any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t)
            for t in timestamps) or timestamps[0] >= timestamps[1]):
        raise ValueError('background timestamp_s must be finite and strictly earlier')
    if reference.get('usable') is not True:
        raise ValueError('background must be explicitly reviewed usable')
    if reference.get('background_review_kind') not in {'assistant_visual_review', 'human_review'}:
        raise ValueError('background review kind is not an accepted visual reference review')


def score_mask(prediction, gt, ignore, status='ok'):
    """Score native 0/255 masks only where Ignore is not 255.

    Unavailable backgrounds retain a planned row without invented predictions or
    scores. Inference errors are eligible empty predictions with an error flag.
    Empty-GT recall is 1; empty-prediction precision is 1 only if GT is also empty.
    Empty-mask and image-level-miss flags refer to the same valid-pixel domain.
    """
    if status not in {'ok', 'error', 'unavailable_background'}:
        raise ValueError('unknown prediction status')
    gt = _binary(gt, 'gt')
    ignore = _binary(ignore, 'ignore', gt.shape)
    valid = ignore != 255
    valid_pixels = int(np.count_nonzero(valid))
    if not valid_pixels:
        raise ValueError('no valid pixels: entire ROI is ignored')
    truth = (gt == 255) & valid
    positive_gt = bool(np.any(truth))
    row = dict(status=status, eligible=status != 'unavailable_background',
               error=status == 'error', valid_pixels=valid_pixels,
               ignored_pixels=int(gt.size - valid_pixels), positive_gt=positive_gt)
    if status == 'unavailable_background':
        row.update(dict.fromkeys(('tp', 'fp', 'fn', 'tn', 'dice', 'iou', 'precision',
                                  'recall', 'empty_mask', 'image_level_miss')))
        return row
    predicted = np.zeros_like(truth) if status == 'error' else (
        (_binary(prediction, 'prediction', gt.shape) == 255) & valid)
    tp = int(np.count_nonzero(predicted & truth))
    fp = int(np.count_nonzero(predicted & ~truth))
    fn = int(np.count_nonzero(~predicted & truth))
    tn = valid_pixels - tp - fp - fn
    pred_count, truth_count = tp + fp, tp + fn
    union = tp + fp + fn
    row.update(tp=tp, fp=fp, fn=fn, tn=tn,
               dice=2 * tp / (pred_count + truth_count) if pred_count + truth_count else 1.,
               iou=tp / union if union else 1.,
               precision=tp / pred_count if pred_count else (0. if truth_count else 1.),
               recall=tp / truth_count if truth_count else 1.,
               empty_mask=pred_count == 0, image_level_miss=positive_gt and pred_count == 0)
    return row


def candidate_target_coverage(pred, gt, ignore, polygon_roi):
    """Provisional native-ROI target coverage with a complete, unignored target.

    Pixel coordinates have domain [0,width) x [0,height). Vertices outside that
    domain are rejected before rasterization, never clipped into a denominator.
    OpenCV's fixed-point polygon rasterization preserves fractional coordinates.
    """
    gt = _binary(gt, 'gt')
    pred, ignore = _binary(pred, 'prediction', gt.shape), _binary(ignore, 'ignore', gt.shape)
    unavailable = dict(available=False, reason='', target_area_px=None,
                       predicted_rho=None, gt_rho=None, absolute_error=None)

    def reject(reason):
        return dict(unavailable, reason=reason)

    try:
        polygon = np.asarray(polygon_roi, dtype=np.float64)
    except (ValueError, TypeError):
        return reject('invalid_polygon')
    if polygon.ndim != 2 or polygon.shape[1:] != (2,) or len(polygon) < 3 or not np.all(np.isfinite(polygon)):
        return reject('invalid_polygon')
    height, width = gt.shape
    if (np.any(polygon < 0) or np.any(polygon[:, 0] >= width) or np.any(polygon[:, 1] >= height)):
        return reject('outside_roi')
    if (len(np.unique(polygon, axis=0)) < 3 or
            abs(np.dot(polygon[:, 0], np.roll(polygon[:, 1], -1)) -
                np.dot(polygon[:, 1], np.roll(polygon[:, 0], -1))) <= 1e-12):
        return reject('degenerate_polygon')
    fixed_vertices = np.rint(polygon * 256).astype(np.int32)
    raster_vertices = (fixed_vertices.astype(np.int64) + 128) // 256
    if np.any(raster_vertices[:, 0] >= width) or np.any(raster_vertices[:, 1] >= height):
        return reject('outside_roi')
    target = np.zeros_like(gt)
    cv2.fillPoly(target, [fixed_vertices], 255, shift=8)
    target_pixels = target == 255
    area = int(np.count_nonzero(target_pixels))
    if not area:
        return reject('degenerate_polygon')
    if np.any(target_pixels & (ignore == 255)):
        return reject('ignore_overlap')
    predicted_rho = int(np.count_nonzero((pred == 255) & target_pixels)) / area
    gt_rho = int(np.count_nonzero((gt == 255) & target_pixels)) / area
    return dict(available=True, reason='', target_area_px=area,
                predicted_rho=predicted_rho, gt_rho=gt_rho,
                absolute_error=abs(predicted_rho - gt_rho))
