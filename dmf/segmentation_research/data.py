"""Reviewed Mask samples, leakage checks and byte-exact study snapshots."""
from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil

import cv2
import numpy as np

from dmf.vision.image_io import read_image


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        raise ValueError('cannot write an unspecified empty CSV schema')
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@dataclass(frozen=True)
class Sample:
    image_path: Path
    mask_path: Path
    parent_video_id: str
    source_frame_id: int
    source_sha256: str
    split: str
    image_sha256: str
    mask_sha256: str
    metadata: dict


def load_reviewed(path, *, formal=False, groups=None):
    """Validate segmentation GT only; state/map labels are deliberately unused.

    Filename dates / legacy batch_id are not asserted to be capture sessions.
    Known chip/session groups, parent IDs AND source hashes must not cross splits.
    `formal=True` validates assignment, not independent study readiness.
    """
    path = Path(path).resolve()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError('no reviewed samples')
    source_groups = {}
    if groups is not None:
        group_data = json.loads(Path(groups).read_text(encoding='utf-8'))
        if group_data.get('schema') != 'dmf_segmentation_source_groups_v1':
            raise ValueError('unsupported source grouping schema')
        for group in group_data.get('sources', []):
            digest = group.get('source_sha256', '').lower()
            if digest in source_groups or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('duplicate or invalid grouping source hash')
            if not all(isinstance(group.get(k), str) and group[k].strip() for k in ('chip_id', 'session_id')):
                raise ValueError('known source grouping requires chip/session aliases')
            source_groups[digest] = group
    workspace = path.parent / 'workspace.json'
    clips = {}
    if workspace.is_file():
        raw = json.loads(workspace.read_text(encoding='utf-8'))
        clips = {clip['clip_id']: clip for clip in raw.get('clips', [])}
    samples, seen, assignments, parent_hashes = [], set(), {}, {}
    for row in rows:
        if str(row.get('mask_reviewed', '')).lower() not in {'true', '1', 'yes'}:
            raise ValueError('only human-reviewed Masks are eligible')
        parent = row.get('parent_video_id', '').strip()
        clip = clips.get(row.get('video_id'), {})
        source_hash = row.get('source_sha256') or clip.get('source_sha256', '')
        source_hash = source_hash.lower()
        if not parent or not re.fullmatch('[0-9a-f]{64}', source_hash):
            raise ValueError('parent_video_id and original source SHA256 are required')
        row = dict(row)
        if groups is not None:
            if source_hash not in source_groups:
                raise ValueError('group manifest does not cover every source')
            for key in ('chip_id', 'session_id'):
                value = source_groups[source_hash][key].strip()
                if row.get(key, '').strip() and row[key].strip() != value:
                    raise ValueError('CSV identity conflicts with confirmed source grouping')
                row[key] = value
        if clip and (clip['video_id'] != parent or clip['source_sha256'] != source_hash):
            raise ValueError('source identity conflicts with Pilot workspace')
        if parent in parent_hashes and parent_hashes[parent] != source_hash:
            raise ValueError('parent identity maps to conflicting source hashes')
        parent_hashes[parent] = source_hash
        frame_id = int(row['source_frame_id'])
        if frame_id < 0 or any(int(row.get(k) or 0) < 0 for k in ('roi_x', 'roi_y')):
            raise ValueError('negative frame/ROI coordinates')
        identity = (source_hash, frame_id)
        if identity in seen:
            raise ValueError('duplicate original source frame, including parent aliases')
        seen.add(identity)
        split = row.get('split', '').strip() or 'unassigned'
        if split not in {'train', 'val', 'test', 'unassigned'} or (formal and split == 'unassigned'):
            raise ValueError('invalid or unassigned formal split')
        for key, value in [('parent', parent), ('source_hash', source_hash)] + [
            (key, row[key].strip()) for key in ('session_id', 'chip_id') if row.get(key, '').strip()
        ]:
            group = (key, value)
            if group in assignments and assignments[group] != split:
                raise ValueError(f'split leakage in {key}: {value}')
            assignments[group] = split
        for key in ('frame_path', 'mask_path'):
            if not row.get(key, '').strip():
                raise ValueError(f'missing {key}')
        image_path = (path.parent / row['frame_path']).resolve()
        mask_path = (path.parent / row['mask_path']).resolve()
        image = read_image(image_path, cv2.IMREAD_UNCHANGED)
        mask = read_image(mask_path, cv2.IMREAD_UNCHANGED)
        if image is None or mask is None:
            raise ValueError('unreadable image or reviewed Mask')
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('image must be uint8 BGR')
        if mask.ndim != 2 or mask.shape != image.shape[:2] or mask.dtype != np.uint8:
            raise ValueError('Mask must match native image shape and be uint8 grayscale')
        if not set(np.unique(mask)).issubset({0, 255}):
            raise ValueError('Mask must be binary 0/255')
        metadata = dict(row, source_sha256=source_hash, split=split,
                        width=image.shape[1], height=image.shape[0])
        samples.append(Sample(image_path, mask_path, parent, frame_id, source_hash, split,
                              sha256(image_path), sha256(mask_path), metadata))
    return samples


def freeze_samples(samples, output):
    """Copy reviewed bytes to a new immutable-by-convention evaluation input set."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for i, sample in enumerate(samples):
        row = dict(sample.metadata)
        for field, source, digest, folder in (
            ('frame_path', sample.image_path, sample.image_sha256, 'images'),
            ('mask_path', sample.mask_path, sample.mask_sha256, 'masks'),
        ):
            dest = output / folder / f'sample_{i:04d}{source.suffix}'
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, dest)
            if sha256(dest) != digest or sha256(source) != digest:
                raise ValueError('reviewed input changed while snapshotting')
            row[field] = dest.relative_to(output).as_posix()
            row[field + '_sha256'] = digest
            row['original_' + field] = str(source)
        rows.append(row)
    write_csv(output / 'samples.csv', rows)
    (output / 'snapshot_manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return output / 'samples.csv'
