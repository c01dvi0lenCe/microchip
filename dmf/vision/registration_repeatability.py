"""Blinded two-round raw-click records, independent from frozen calibration."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import random
import shutil

import numpy as np

from .design_registration import digest, file_hash


def new_review(catalog, image_size, *, seed=23):
    keys = ('point_id', 'control_id', 'vertex_index', 'map_mm')
    features = [{k:copy.deepcopy(p[k]) for k in keys} for p in catalog]
    if len(features) != 16 or len({p['point_id'] for p in features}) != 16:
        raise ValueError('the same 16 unique predeclared check points required')
    rounds = []
    for i in (1, 2):
        order = [p['point_id'] for p in features]
        random.Random(seed+i).shuffle(order)
        rounds.append(dict(round_id=i, order=order, observations={}, raw_actions=[], seal=None))
    return dict(schema='dmf_blinded_registration_repeatability_v1',
        simulation=False, use_scope='pre_experiment_only', image_size=list(image_size),
        catalog=features, catalog_sha256=digest(features), order_seed=seed, rounds=rounds,
        independent_acquisition_groups=1, blinding='display-blind only; reviewer has seen prior session')


def validate(data):
    forbidden = {'image_to_design_mm','design_mm_to_image','fit_freeze','initial_image_to_design_mm',
                 'observed_px','suggested_px','residuals','previous_points'}
    def reject_history(value):
        if isinstance(value,dict):
            if forbidden.intersection(value):raise ValueError('H or prior registration coordinates forbidden in blind payload')
            for v in value.values():reject_history(v)
        elif isinstance(value,list):
            for v in value:reject_history(v)
    reject_history(data)
    if (data.get('schema') not in ('dmf_blinded_registration_repeatability_v1','dmf_assisted_registration_repeatability_v1') or
            data.get('simulation') is not False or len(data.get('rounds', [])) != 2 or
            digest(data['catalog']) != data.get('catalog_sha256')):
        raise ValueError('invalid or changed blind catalog')
    if data['schema']=='dmf_assisted_registration_repeatability_v1':
        if data.get('review_mode')!='coarse_region_assisted':raise ValueError('assisted protocol label required')
        from .registration_guidance import validate_guidance
        validate_guidance(data)
    elif data.get('guidance') or data.get('review_mode')=='coarse_region_assisted':
        raise ValueError('coarse assistance cannot be silently labeled blind')
    ids = {p['point_id'] for p in data['catalog']}
    if len(ids) != 16: raise ValueError('16 point identities required')
    width, height = data['image_size']
    for index, round_data in enumerate(data['rounds'], 1):
        if round_data['round_id'] != index or set(round_data['order']) != ids or len(round_data['order']) != 16:
            raise ValueError('round identity/order mismatch')
        for name, obs in round_data['observations'].items():
            if name not in ids or not obs.get('reviewer') or not obs.get('recorded_at'):
                raise ValueError('raw observation provenance required')
            if obs['status'] == 'confirmed':
                xy = np.asarray(obs['pixel'], float)
                if xy.shape != (2,) or not np.isfinite(xy).all() or not (0 <= xy[0] < width and 0 <= xy[1] < height):
                    raise ValueError('raw click outside image')
            elif obs['status'] != 'excluded' or not obs.get('reason') or obs.get('pixel') is not None:
                raise ValueError('invisible point needs explicit reason and no coordinate')
        seal = round_data.get('seal')
        if seal and (set(round_data['observations']) != ids or
                     seal['observations_sha256'] != digest(round_data['observations']) or
                     seal['raw_actions_sha256'] != digest(round_data['raw_actions'])):
            raise ValueError('sealed round changed')
    if data['rounds'][1]['observations'] and not data['rounds'][0]['seal']:
        raise ValueError('round 1 seal required before round 2')


def _editable(data, round_id, point_id, reviewer):
    validate(data)
    if round_id not in (1, 2): raise ValueError('round 1 or 2 required')
    round_data = data['rounds'][round_id-1]
    if not reviewer.strip() or point_id not in round_data['order']:
        raise ValueError('reviewer and known point required')
    if round_data['seal'] or (round_id == 2 and not data['rounds'][0]['seal']):
        raise ValueError('sealed round, or first round not complete')
    return round_data


def record_click(data, round_id, point_id, pixel, reviewer):
    round_data = _editable(data, round_id, point_id, reviewer)
    xy = np.asarray(pixel, dtype=float); width, height = data['image_size']
    if xy.shape != (2,) or not np.isfinite(xy).all() or not (0 <= xy[0] < width and 0 <= xy[1] < height):
        raise ValueError('point outside native image')
    round_data['observations'][point_id] = dict(pixel=xy.tolist(), status='confirmed',
        reviewer=reviewer.strip(), recorded_at=datetime.now(timezone.utc).isoformat(),
        method=('manual_native_click_coarse_region_assisted_no_snap' if data.get('review_mode')=='coarse_region_assisted'
                else 'manual_native_click_no_H_or_prior_point_display'), reason='')
    round_data['raw_actions'].append(dict(point_id=point_id, **copy.deepcopy(round_data['observations'][point_id])))


def exclude(data, round_id, point_id, reason, reviewer):
    round_data = _editable(data, round_id, point_id, reviewer)
    if not reason.strip(): raise ValueError('invisibility reason required')
    round_data['observations'][point_id] = dict(pixel=None, status='excluded', reason=reason.strip(),
        reviewer=reviewer.strip(), recorded_at=datetime.now(timezone.utc).isoformat())
    round_data['raw_actions'].append(dict(point_id=point_id, **copy.deepcopy(round_data['observations'][point_id])))


def seal_round(data, round_id):
    validate(data)
    if round_id not in (1, 2): raise ValueError('invalid round')
    r = data['rounds'][round_id-1]
    if len(r['observations']) != 16: raise ValueError('review all 16 points first')
    if not r.get('seal'):
        r['seal'] = dict(observations_sha256=digest(r['observations']),
                         raw_actions_sha256=digest(r['raw_actions']),
                         sealed_at=datetime.now(timezone.utc).isoformat())


def summarize(data):
    validate(data)
    completed = all(r.get('seal') for r in data['rounds'])
    pairs = []
    if completed:
        for p in data['catalog']:
            a, b = [r['observations'][p['point_id']] for r in data['rounds']]
            if a['status'] == b['status'] == 'confirmed':
                delta = np.asarray(b['pixel'])-a['pixel']
                pairs.append(dict(point_id=p['point_id'], u_round1=a['pixel'][0],
                    v_round1=a['pixel'][1], u_round2=b['pixel'][0], v_round2=b['pixel'][1],
                    du_px=float(delta[0]), dv_px=float(delta[1]), distance_px=float(np.linalg.norm(delta))))
    errors = np.array([p['distance_px'] for p in pairs])
    return dict(status='completed_descriptive' if completed else 'pending_human_rounds',
        review_mode=data.get('review_mode','display_blind'),strict_blind=False,
        display_blind=data.get('review_mode')!='coarse_region_assisted',
        guidance_sha256=data.get('guidance_sha256'),blinding=data.get('blinding'),
        planned_points=16, planned_rounds=2, independent_acquisition_groups=1,
        observed_counts=[len(r['observations']) for r in data['rounds']],
        confirmed_counts=[sum(o['status']=='confirmed' for o in r['observations'].values()) for r in data['rounds']],
        excluded_counts=[sum(o['status']=='excluded' for o in r['observations'].values()) for r in data['rounds']],
        paired_points=len(pairs), missing_or_excluded_pairs=16-len(pairs),
        rmse_between_rounds_px=float(np.sqrt(np.mean(errors**2))) if len(errors) else None,
        mean_distance_px=float(np.mean(errors)) if len(errors) else None,
        p95_distance_px=float(np.percentile(errors, 95, method='linear')) if len(errors) else None,
        max_distance_px=float(np.max(errors)) if len(errors) else None,
        pairs=pairs, note='repeat-click differences only, not registration residuals or new independent acquisitions')


def save_new(path, data):
    validate(data)
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)


def load_review(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8')); validate(data)
    data['_loaded_sha256'] = file_hash(path)
    return data


def save_review(path, data):
    validate(data)
    if file_hash(path) != data.get('_loaded_sha256'): raise ValueError('review changed externally; reopen')
    clean = {k:v for k,v in data.items() if not k.startswith('_')}
    Path(path).write_text(json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    data['_loaded_sha256'] = file_hash(path)


def prepare_repeatability(workspace_path, output):
    from .registration_workspace import load_workspace
    import sys
    source = Path(workspace_path).resolve(); output = Path(output).resolve()
    w = load_workspace(source)
    if not w.get('evaluation_freeze'): raise ValueError('original evaluation must remain sealed')
    checks = [p for p in w['points'] if p['role'] == 'check']
    if len(checks) != 16: raise ValueError('16 original check features required')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source.parent/w['image_path'], output/'original.png')
    shutil.copyfile(source.parent/w['design_map_path'], output/'electrode_design_map.json')
    data = new_review(checks, w['image_size'])
    data.update(image_path='original.png', image_sha256=w['image_sha256'],
        design_map_path='electrode_design_map.json', design_map_sha256=w['design_map_sha256'],
        original_workspace_sha256=file_hash(source))
    save_new(output/'repeatability.json', data)
    repo = Path(__file__).resolve().parents[2]
    # Same proven CRLF format as existing launcher, but invoke the isolated UI.
    lines = ['@echo off', 'chcp 65001 >nul', f'cd /d "{repo}"',
        f'"{sys.executable}" "{repo / "run_registration_audit.py"}" review "{output / "repeatability.json"}"',
        'if errorlevel 1 pause']
    (output/'启动盲法两轮核对.cmd').write_bytes(('\r\n'.join(lines)+'\r\n').encode('utf-8'))
    report_lines=['@echo off','chcp 65001 >nul',f'cd /d "{repo}"',
        f'"{sys.executable}" "{repo / "run_registration_audit.py"}" repeat-report "{output / "repeatability.json"}"','pause']
    (output/'导出两轮重复性报告.cmd').write_bytes(('\r\n'.join(report_lines)+'\r\n').encode('utf-8'))
    for name, expected in [('original.png', w['image_sha256']), ('electrode_design_map.json', w['design_map_sha256'])]:
        if file_hash(output/name) != expected: raise ValueError('copied source hash mismatch')
    return output/'repeatability.json'
