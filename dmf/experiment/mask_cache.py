"""Versioned, hash-checked prediction inputs. References never belong here."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _no_truth(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if any(token in str(key).lower() for token in ('truth', 'reference', 'ground_truth')) or str(key).lower() == 'gt':
                raise ValueError('prediction inputs cannot contain truth/reference fields')
            _no_truth(item)
    elif isinstance(value, (list, tuple)):
        for item in value: _no_truth(item)


def _validate(manifest):
    _no_truth(manifest)
    if manifest.get('schema') != 'chapter2_mask_cache_v1': raise ValueError('unsupported cache')
    if manifest['clock_domain'] not in {'simulation', 'video_relative'}: raise ValueError('explicit relative clock required')
    if manifest['coordinate_unit'] != 'pitch': raise ValueError('this cache version requires explicit normalized pitch units')
    if manifest['map']['metadata']['coordinate_unit'] != manifest['coordinate_unit']: raise ValueError('mixed units')
    if manifest['clock_domain'] == 'simulation' and manifest['coordinate_unit'] != 'pitch':
        raise ValueError('simulation must not claim measured millimetres')
    ids = set(); last_end = -math.inf
    for task in manifest['tasks']:
        if not {'step_id', 'source', 'target', 'start_s', 'end_s', 'applied_s'} <= task.keys():
            raise ValueError('incomplete task')
        if set(task) - {'step_id', 'source', 'target', 'start_s', 'end_s', 'applied_s'}:
            raise ValueError('unexpected task input field')
        if task['step_id'] in ids: raise ValueError('duplicate task')
        ids.add(task['step_id'])
        if not all(math.isfinite(task[k]) for k in ('start_s', 'end_s', 'applied_s')): raise ValueError('invalid task time')
        if not last_end <= task['start_s'] <= task['applied_s'] < task['end_s']: raise ValueError('overlapping or invalid task window')
        last_end = task['end_s']
        if any(str(task[k]) not in manifest['map']['polygons'] for k in ('source', 'target')): raise ValueError('unknown electrode')
    if not ids: raise ValueError('empty tasks')
    keys = set(); streams = set()
    for row in manifest['frames']:
        if set(row)-{'frame_id', 'video_id', 'exposure_s', 'exposure_start_s', 'available_s',
                     'confidence', 'clock_domain', 'mask_path', 'mask_sha256'}:
            raise ValueError('unexpected frame input field')
        key = (row.get('video_id', 'cache'), row['frame_id'])
        streams.add(key[0])
        if not isinstance(key[0], str) or not key[0] or len(streams)>1:
            raise ValueError('cache v1 requires one explicitly identified video stream')
        if type(row['frame_id']) is not int or row['frame_id'] < 0 or key in keys: raise ValueError('duplicate/invalid frame key')
        keys.add(key)
        if not all(math.isfinite(row[k]) for k in ('exposure_s', 'available_s')) or not 0 <= row['exposure_s'] <= row['available_s']:
            raise ValueError('invalid frame time')
        if row.get('clock_domain', manifest['clock_domain']) != manifest['clock_domain']: raise ValueError('mixed frame clocks')
        if 'exposure_start_s' in row and not 0 <= row['exposure_start_s'] <= row['exposure_s']:
            raise ValueError('invalid exposure interval')
        if not 0 <= row['confidence'] <= 1: raise ValueError('invalid confidence')


def write_cache(directory, *, map_snapshot, tasks, parameters, frames,
                clock_domain, coordinate_unit):
    """Freeze a cache once. Existing paths are never overwritten."""
    directory = Path(directory)
    if directory.exists(): raise FileExistsError(directory)
    manifest = dict(schema='chapter2_mask_cache_v1', clock_domain=clock_domain,
                    coordinate_unit=coordinate_unit, map=map_snapshot, tasks=tasks,
                    parameters=parameters, frames=[])
    masks = []
    for index, frame in enumerate(frames):
        row = {key: value for key, value in frame.items() if key != 'mask'}
        row.setdefault('confidence', 1.)
        mask = frame.get('mask')
        row['mask_path'] = None; row['mask_sha256'] = None
        if mask is not None:
            mask = np.asarray(mask)
            if mask.dtype != np.uint8 or mask.ndim != 2 or not np.isin(mask, [0, 255]).all(): raise ValueError('binary uint8 mask required')
            if list(mask.shape) != list(map_snapshot['shape']): raise ValueError('mask/map shape mismatch')
            row['mask_path'] = f'masks/{index:08d}.npy'
            masks.append((row, mask.copy()))
        manifest['frames'].append(row)
    _validate(manifest)
    directory.mkdir(parents=True); (directory/'masks').mkdir()
    for row, mask in masks:
        path = directory/row['mask_path']; np.save(path, mask, allow_pickle=False)
        row['mask_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = _json(manifest)
    (directory/'manifest.json').write_bytes(payload)
    (directory/'input.sha256').write_text(hashlib.sha256(payload).hexdigest(), encoding='ascii')
    return load_cache(directory)


def load_cache(directory):
    directory = Path(directory).resolve()
    payload = (directory/'manifest.json').read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != (directory/'input.sha256').read_text(encoding='ascii').strip(): raise ValueError('manifest hash mismatch')
    manifest = json.loads(payload); _validate(manifest)
    for row in manifest['frames']:
        row['mask'] = None
        if row['mask_path'] is not None:
            path = (directory/row['mask_path']).resolve()
            if not path.is_relative_to(directory): raise ValueError('mask path outside cache')
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['mask_sha256']: raise ValueError('mask hash mismatch')
            mask = np.load(path, allow_pickle=False)
            if mask.dtype != np.uint8 or mask.ndim != 2 or not np.isin(mask, [0, 255]).all() or list(mask.shape) != manifest['map']['shape']:
                raise ValueError('invalid cached mask')
            mask.setflags(write=False); row['mask'] = mask
    manifest['input_sha256'] = digest
    return manifest
