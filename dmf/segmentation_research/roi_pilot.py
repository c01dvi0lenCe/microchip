"""Offline ROI proposals and conservative review gates, never automatic GT.

The dark-pixel heuristic is only a starting point for human editing. The
semantic target is *all actual droplets*, including internal highlights;
reservoir exclusion and instance/task identities are separate annotations.
No function opens a camera, controls hardware, or trains a model.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

import cv2
import numpy as np

from dmf.vision.image_io import read_image


INTERNAL_PROTOCOL = 'same_capture_internal_research_only'
CAPTURE_GROUP = '2026-11-02_shared_or_unknown'
_REVIEW_FLAGS = ('mask_reviewed', 'state_reviewed', 'instances_reviewed',
                 'exclusion_reviewed', 'boundary_reviewed', 'capture_group_confirmed',
                 'grouping_verified')


def _integer(value, label, minimum=0):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f'{label} must be an integer')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f'{label} must be an integer') from exc
    if not math.isfinite(number) or number != math.floor(number) or number < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')
    return int(number)


def _sequence(value, length, label):
    try:
        result = list(value)
    except TypeError as exc:
        raise ValueError(f'{label} requires {length} values') from exc
    if len(result) != length:
        raise ValueError(f'{label} requires {length} values')
    return result


def _roi(value):
    values = _sequence(value, 4, 'ROI')
    return [_integer(item, 'ROI', 0 if index < 2 else 1)
            for index, item in enumerate(values)]


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError('Malformed source SHA256')
    return value.lower()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonblank text')
    return value


def native_roi(center_xy, size_wh, full_wh):
    """Return native integer [x,y,w,h], shifting at edges, never resizing.

    Centers must lie inside the source image. Dimensions must be positive
    integral pixel counts; an oversized request is rejected rather than scaled.
    Fractional top-left positions are rounded down before clamping.
    """
    center = _sequence(center_xy, 2, 'center')
    size = [_integer(item, 'ROI size', 1) for item in _sequence(size_wh, 2, 'size')]
    full = [_integer(item, 'source size', 1) for item in _sequence(full_wh, 2, 'full size')]
    try:
        center = [float(item) for item in center]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Center must be finite and inside source') from exc
    if any(not math.isfinite(c) or not 0 <= c < extent for c, extent in zip(center, full)):
        raise ValueError('Center must be finite and inside source')
    if any(wanted > extent for wanted, extent in zip(size, full)):
        raise ValueError('ROI cannot exceed source dimensions')
    origin = [min(max(math.floor(c - wanted / 2), 0), extent - wanted)
              for c, wanted, extent in zip(center, size, full)]
    return origin + size


def all_foreground_draft(image):
    """Propose ALL dark components; no largest-only or border exclusion.

    The fixed threshold (all BGR channels <=55) is not the annotation
    definition. Small enclosed holes (<=64 pixels) are filled as a convenience;
    humans still decide actual droplet boundaries and remove dark distractors.
    The input is not modified and the result is a binary uint8 0/255 mask.
    """
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.size == 0:
        raise ValueError('Draft input must be a nonempty uint8 image')
    if image.ndim == 2:
        selected = image <= 55
    elif image.ndim == 3 and image.shape[2] == 3:
        selected = np.all(image <= 55, axis=2)
    else:
        raise ValueError('Draft input must be grayscale or three-channel BGR')
    mask = selected.astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask == 0).astype(np.uint8), connectivity=8)
    height, width = mask.shape
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area <= 64 and x > 0 and y > 0 and x + w < width and y + h < height:
            mask[labels == label] = 255
    return mask


def candidate_row(sample_id, parent_video_id, source_sha256, source_frame_id,
                  roi_xywh, receive_s, category, proposed_split, operation_group,
                  track_draft=''):
    """Create a PilotWorkspace-compatible, entirely unreviewed candidate.

    Paths remain blank for the caller to supply after writing derived assets.
    ``track_draft`` is a video-local suggestion, not a confirmed instance ID.
    Actual split remains unassigned even when a proposal is present.
    """
    _text(sample_id, 'sample_id'); _text(parent_video_id, 'parent_video_id')
    _text(category, 'category'); _text(operation_group, 'operation_group')
    digest = _sha(source_sha256)
    frame = _integer(source_frame_id, 'source frame')
    x, y, width, height = _roi(roi_xywh)
    try:
        receive_s = float(receive_s)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Host receive time must be finite and nonnegative') from exc
    if not math.isfinite(receive_s) or receive_s < 0:
        raise ValueError('Host receive time must be finite and nonnegative')
    if proposed_split not in ('train', 'val'):
        raise ValueError('Proposed split must be train or val')
    if not isinstance(track_draft, str):
        raise ValueError('Draft track must be text')
    return dict(sample_id=sample_id, video_id=sample_id, experiment_id=parent_video_id,
        batch_id=CAPTURE_GROUP, frame_id=frame, timestamp_s=receive_s,
        timestamp_source='host_receive_relative_not_exposure', frame_path='', mask_path='',
        source_electrode='', target_electrode='', state_gt='Unknown', state_draft='Unknown',
        lighting_condition='', notes='', parent_video_id=parent_video_id,
        source_sha256=digest, source_frame_id=frame, roi_x=x, roi_y=y,
        roi_w=width, roi_h=height, width=width, height=height, roi_xywh=[x, y, width, height],
        draft_mask_path='', working_mask_path='', exclusion_mask_path='',
        mask_reviewed=False, state_reviewed=False, map_version='', split='unassigned',
        category=category, proposed_split=proposed_split, operation_group=operation_group,
        capture_group=CAPTURE_GROUP, capture_group_confirmed=False,
        instance_id='', task_target_instance_id='', instance_id_draft=track_draft,
        instances_reviewed=False, exclusion_reviewed=False, boundary_reviewed=False,
        grouping_verified=False, split_protocol='', semantic_definition='all_actual_droplets')


def validate_proposed_groups(rows):
    """Validate an explicit SAME-capture internal proposal, not a formal split.

    Draft tracks are qualified by video identity: an identical local label in
    unrelated files does not establish a shared droplet lineage. Known lineage
    spanning files must instead share an operation_group. Unknown lineage is
    never used to assert batch-disjoint generalization.
    """
    rows = list(rows)
    if not rows:
        raise ValueError('No candidate rows')
    groups, originals, samples, capture_splits = {}, set(), set(), {}
    for row in rows:
        sample = _text(row.get('sample_id'), 'sample_id')
        if sample in samples:
            raise ValueError('Duplicate sample_id')
        samples.add(sample)
        parent = _text(row.get('parent_video_id'), 'parent_video_id')
        digest = _sha(row.get('source_sha256'))
        frame = _integer(row.get('source_frame_id'), 'source frame')
        roi = _roi([row.get(key) for key in ('roi_x', 'roi_y', 'roi_w', 'roi_h')])
        original = (digest, frame, tuple(roi))
        if original in originals:
            raise ValueError('Duplicate original source/frame/ROI')
        originals.add(original)
        split = row.get('proposed_split')
        if split not in ('train', 'val'):
            raise ValueError('Proposed split must be train or val')
        for flag in _REVIEW_FLAGS:
            if flag in row and type(row[flag]) is not bool:
                raise ValueError(f'{flag} must be a literal boolean, not string truth')
        operation = _text(row.get('operation_group'), 'operation_group')
        track = row.get('instance_id_draft', '')
        if not isinstance(track, str):
            raise ValueError('Draft track must be text')
        identities = [('parent', parent), ('source', digest), ('operation', operation)]
        if track.strip():
            identities.append(('video_qualified_track', parent, track))
        for identity in identities:
            if identity in groups and groups[identity] != split:
                raise ValueError(f'Proposed split leakage in {identity[0]}')
            groups[identity] = split
        capture = _text(row.get('capture_group'), 'capture_group')
        capture_splits.setdefault(capture, set()).add(split)
    shared = {key for key, values in capture_splits.items() if len(values) > 1}
    for row in rows:
        if row['capture_group'] in shared and row.get('split_protocol') != INTERNAL_PROTOCOL:
            raise ValueError('Shared capture group requires explicit internal split protocol')
    return dict(valid=True, rows=len(rows), protocol=INTERNAL_PROTOCOL,
        grouping_verified=True, batch_disjoint=False,
        warning='NOT batch-disjoint; internal research proposal only; cross-file lineage may be unknown',
        shared_capture_groups=sorted(shared))


def training_readiness(rows):
    """Read-only gate; no training implementation and no mutation of annotations.

    Literal human-review flags, explicit actual splits and verified grouping are
    mandatory. Files must already exist and decode at the native ROI dimensions.
    State GT and task/instance identities are not needed for semantic training.
    A ready result is only internal-protocol readiness, never generalization
    evidence or authorization to run training.
    """
    rows = list(rows)
    reasons, grouping = [], None
    try:
        grouping = validate_proposed_groups(rows)
        actual_rows = [dict(row, proposed_split=row.get('split')) for row in rows]
        validate_proposed_groups(actual_rows)
    except (ValueError, TypeError) as exc:
        reasons.append(str(exc))
    if {row.get('split') for row in rows} != {'train', 'val'}:
        reasons.append('Explicit actual split train and val required; unassigned is blocked')
    for index, row in enumerate(rows):
        label = str(row.get('sample_id', index))
        for flag in ('mask_reviewed', 'exclusion_reviewed', 'boundary_reviewed', 'grouping_verified'):
            if row.get(flag) is not True:
                reasons.append(f'{label}: {flag} requires explicit literal True')
        if row.get('split_protocol') != INTERNAL_PROTOCOL:
            reasons.append(f'{label}: explicit internal split protocol required')
        if row.get('semantic_definition') != 'all_actual_droplets':
            reasons.append(f'{label}: all_actual_droplets semantic definition required')
        try:
            shape = (_integer(row.get('roi_h'), 'ROI height', 1),
                     _integer(row.get('roi_w'), 'ROI width', 1))
        except ValueError as exc:
            reasons.append(f'{label}: {exc}')
            continue
        for key in ('frame_path', 'mask_path', 'exclusion_mask_path'):
            raw = row.get(key)
            if not isinstance(raw, (str, Path)) or not str(raw).strip() or not Path(raw).is_file():
                reasons.append(f'{label}: valid existing {key} required')
                continue
            pixels = read_image(Path(raw), cv2.IMREAD_UNCHANGED)
            if pixels is None or pixels.shape[:2] != shape or pixels.dtype != np.uint8:
                reasons.append(f'{label}: {key} must decode at native ROI dimensions as uint8')
            elif key != 'frame_path' and (pixels.ndim != 2 or not np.isin(pixels, [0, 255]).all()):
                reasons.append(f'{label}: {key} must be single-channel binary 0/255')
    return dict(ready=not reasons, reasons=reasons, grouping=grouping,
                batch_disjoint=False, scope='internal_research_only', training_implemented=False)
