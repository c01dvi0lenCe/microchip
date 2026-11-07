"""Read-only independent audit of persisted S3 development evidence.

No simulation, recognizer, reference builder, or original scorer is imported.
Only PNG decoding uses OpenCV/NumPy; all physical-support arithmetic is below.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1')
METHODS = ('A_fixed', 'B_single', 'BTQ', 'F_full')
SCENARIOS = ('normal', 'delayed', 'partial_stall', 'jitter', 'dropout', 'deviation', 'failure')
TERMINALS = ('infrastructure_invalid', 'source_preparation_failed', 'transport_aborted',
             'workflow_complete_without_supported_path', 'reference_supported_path_complete')
EPS = 1e-9


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def value(text):
    if text is None or text == '':
        return None
    if text in ('True', 'False'):
        return text == 'True'
    if text.startswith(('{', '[')):
        return json.loads(text)
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def read_csv(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('missing CSV: ' + str(path))
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return [{k: value(v) for k, v in row.items()} for row in csv.DictReader(stream)]


def expected_plan():
    plan = []
    def add(cohort, scenario, seed, method, protection=None):
        plan.append(dict(cohort=cohort, scenario=scenario, seed=seed, method=method,
                         protection=protection or ('P_F' if method == 'F_full' else 'P_B'),
                         phase_mode='transport_only' if cohort == 'diagnostic' else 'end_to_end'))
    for scenario in SCENARIOS:
        for seed in range(264000, 264003):
            for method in METHODS:
                add('main', scenario, seed, method)
    for scenario in ('partial_stall', 'deviation'):
        for seed in range(264000, 264003):
            add('bridge', scenario, seed, 'F_full', 'P_B')
            add('bridge', scenario, seed, 'BTQ', 'P_F')
    for scenario in ('jitter', 'dropout'):
        for seed in range(264000, 264003):
            for method in METHODS:
                add('diagnostic', scenario, seed, method)
    return plan


def identity(row):
    return tuple(row.get(k) if k != 'protection' else
                 row.get(k) or ('P_F' if row['method'] == 'F_full' else 'P_B')
                 for k in ('cohort', 'scenario', 'seed', 'method', 'protection', 'phase_mode'))


def scan_support(truth, centers, dt, radius=.09, max_speed=.06, dwell=.15):
    """Forward scan of actual-active-qualified physical residence.

    A software epoch/attempt never appears in this computation. The only
    continuity breaks are a physical predicate failure, actual-active change,
    or missing integration tick. A switch-time left limit may extend the old
    segment to that exact tick, never beyond it.
    """
    intervals = []
    run = None
    previous = None
    activation_target = None
    activation_begin = None

    def inside(row, target):
        if target not in centers:
            return False
        x, y = centers[target]
        return (math.hypot(row['x']-x, row['y']-y) <= radius+EPS
                and row['true_speed'] <= max_speed+EPS)

    def extend(row):
        t = row['time_s']
        run['last_inside_s'] = t
        if run['upper_s'] is None and t-run['dwell_begin_s'] >= dwell-EPS:
            run['upper_s'] = t
            run['lower_s'] = max(run['dwell_begin_s'], t-dt)

    def finish():
        if run is not None and run['upper_s'] is not None:
            intervals.append(dict(run))

    for row in truth:
        t = row['time_s']
        if previous is not None and t <= previous['time_s']:
            raise ValueError('truth timestamps are not strictly increasing')
        contiguous = previous is not None and abs(t-previous['time_s']-dt) <= EPS
        active = row.get('world_active')
        changed = previous is not None and active != previous.get('world_active')
        if not contiguous or changed:
            if (changed and contiguous and run is not None and inside(row, run['target'])):
                extend(row)
            finish()
            run = None
        if not contiguous or active != activation_target:
            activation_target, activation_begin = active, t
        if active is not None and inside(row, active):
            if run is None:
                run = dict(target=active, activation_begin_s=activation_begin,
                           dwell_begin_s=t, lower_s=None, upper_s=None, last_inside_s=t)
            extend(row)
        else:
            finish()
            run = None
        previous = row
    finish()
    return intervals


def support_at(intervals, target, t):
    candidates = [r for r in intervals if r['target'] == target
                  and r['activation_begin_s']-EPS <= t <= r['last_inside_s']+EPS]
    for ref in candidates:
        if t >= ref['upper_s']-EPS:
            return dict(supported=True, label='supported', reference=ref)
    if candidates:
        ref = min(candidates, key=lambda r: r['upper_s'])
        return dict(supported=False,
                    label='premature' if t < ref['lower_s']-EPS else 'timing_uncertain',
                    reference=ref)
    return dict(supported=False, label='unsupported_no_current_reference', reference=None)


def evaluate_events(events, intervals):
    applied = {e['request_id']: e for e in events if e['event'] == 'Applied'}
    rows = []
    for event in events:
        if event['event'] not in ('Update', 'Complete'):
            continue
        target, time = event['target'], event['time_s']
        request = support_at(intervals, target, time)
        application = applied.get(event['request_id'])
        at = application['time_s'] if application is not None else None
        result = support_at(intervals, target, at) if at is not None else None
        ref = request['reference']
        rows.append(dict(step=event['step'], target=target, request_id=event['request_id'],
                         action=event['event'], request_s=time, request_label=request['label'],
                         supported_at_request=request['supported'], applied_s=at,
                         applied_label=result['label'] if result else 'not_applicable_no_electrode_transaction',
                         supported_at_applied=result['supported'] if result else None,
                         reference_lower_s=ref['lower_s'] if ref else None,
                         reference_upper_s=ref['upper_s'] if ref else None,
                         delay_lower_s=time-ref['upper_s'] if ref else None,
                         delay_upper_s=time-ref['lower_s'] if ref else None))
    return rows


def check_transactions(events, truth, scenario, method):
    errors = []
    requests = {}
    applications = {}
    pending = None
    for e in events:
        kind = e['event']
        if kind in ('Prepare', 'Start', 'Update', 'Retry', 'Recovery'):
            rid = e['request_id']
            if pending is not None:
                errors.append('overlapping_pending: ' + str((pending, rid)))
            if rid in requests:
                errors.append('duplicate_request: ' + rid)
            requests[rid] = e
            pending = rid
        elif kind == 'Applied':
            rid = e['request_id']
            if rid != pending or rid not in requests:
                errors.append('unmatched_applied: ' + rid)
            else:
                request = requests[rid]
                if e.get('activated_target') != request.get('activated_target') or e.get('action') != request['event']:
                    errors.append('applied_target_or_action_mismatch: ' + rid)
                if abs(e['time_s']-request['time_s']-.04) > EPS:
                    errors.append('applied_delay_mismatch: ' + rid)
                if request.get('applied_s') is None or abs(request['applied_s']-e['time_s']) > EPS:
                    errors.append('request_applied_time_mismatch: ' + rid)
                if abs(e.get('applied_s', e['time_s'])-e['time_s']) > EPS:
                    errors.append('applied_notification_time_mismatch: ' + rid)
            if rid in applications:
                errors.append('duplicate_applied: ' + rid)
            applications[rid] = e
            pending = None
        if method == 'A_fixed':
            if kind == 'ArrivalEvent':
                errors.append('fixed_timer_arrival_event')
            if kind in ('Update', 'Complete'):
                started = e.get('attempt_applied_s')
                if started is None or e['time_s']-started < 1.2-EPS:
                    errors.append('fixed_timer_early: ' + str(e.get('request_id')))
                actual = max(applications.values(), key=lambda row: row['time_s'], default=None)
                if (actual is None or actual.get('activated_target') != e.get('target')
                        or e['time_s']-actual['time_s'] < 1.2-EPS
                        or started is None or abs(started-actual['time_s']) > EPS):
                    errors.append('fixed_timer_actual_applied_mismatch_or_early: ' + str(e.get('request_id')))
    if pending is not None:
        errors.append('pending_transaction_at_termination: ' + pending)
    apps = sorted(applications.values(), key=lambda e: e['time_s'])
    i = 0
    latest = None
    for row in truth:
        t = row['time_s']
        while i < len(apps) and apps[i]['time_s'] <= t+EPS:
            latest = apps[i]
            i += 1
        expected = latest.get('activated_target') if latest else None
        if row.get('world_active') != expected:
            errors.append('world_active_notification_mismatch: ' + str(t))
        if latest is not None:
            response = row.get('world_response_at_s')
            delay = 1.15 if scenario == 'delayed' else .18
            if response is None or abs(response-latest['time_s']-delay) > EPS:
                errors.append('world_response_delay_mismatch: ' + str(t))
        expected_pending = [rid for rid, r in requests.items()
                            if rid != 'initial' and r['time_s'] < t-EPS
                            and (rid not in applications or applications[rid]['time_s'] > t+EPS)]
        if row.get('pending_request') != (expected_pending[0] if expected_pending else None):
            errors.append('truth_pending_mismatch: ' + str(t))
    return errors


def mask_fork_witness(first, second):
    """Find an equal-frame-ID difference after differing Applied histories."""
    def history(data, time):
        return [(e['time_s'], e.get('activated_target')) for e in data['events']
                if e['event'] == 'Applied' and e['time_s'] <= time+EPS]
    right = {c['frame_id']: c for c in second['captures']}
    for c in first['captures']:
        other = right.get(c['frame_id'])
        if other is None:
            continue
        time = min(c['capture_sample_time_s'], other['capture_sample_time_s'])
        if (c.get('raw_mask_sha256') is not None and other.get('raw_mask_sha256') is not None
                and c['raw_mask_sha256'] != other['raw_mask_sha256']
                and history(first, time) != history(second, time)):
            return dict(frame_id=c['frame_id'], capture_sample_time_s=time,
                        first_mask_sha256=c['raw_mask_sha256'], second_mask_sha256=other['raw_mask_sha256'],
                        first_applied_history=history(first, time), second_applied_history=history(second, time))
    return None


def centers_from_map(geometry):
    # Polygon area centroids, independent of the runtime geometry API.
    centers = {}
    for key, vertices in geometry['polygons'].items():
        cross_sum = x_sum = y_sum = 0.
        for (x0, y0), (x1, y1) in zip(vertices, vertices[1:]+vertices[:1]):
            cross = x0*y1-x1*y0
            cross_sum += cross
            x_sum += (x0+x1)*cross
            y_sum += (y0+y1)*cross
        if abs(cross_sum) < 1e-12:
            raise ValueError('degenerate electrode polygon: ' + key)
        centers[int(key)] = x_sum/(3*cross_sum), y_sum/(3*cross_sum)
    return centers


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a-b) <= EPS
    return a == b


def compare_ledger(recorded, independent, keys):
    """Compare complete independent rows, retaining identity and duplicates."""
    identify = lambda row: tuple(row.get(k) for k in keys)
    errors = []
    old_ids, new_ids = Counter(map(identify, recorded)), Counter(map(identify, independent))
    if old_ids != new_ids or any(n != 1 for n in old_ids.values()) or any(n != 1 for n in new_ids.values()):
        errors.append('ledger_identity_missing_or_duplicated')
    old = {identify(row): row for row in recorded}
    for row in independent:
        original = old.get(identify(row), {})
        for key, expected in row.items():
            if not same(expected, original.get(key)):
                errors.append('ledger_value_mismatch: ' + repr(identify(row)) + ':' + key)
    return errors


def prefix_projection(data, source_s):
    captures = [{k: c.get(k) for k in ('frame_id', 'exposure_start_s', 'exposure_end_s', 'available_s',
                                      'capture_sample_time_s', 'dropped', 'raw_mask_sha256')}
                for c in data['captures'] if source_s is None or c['capture_sample_time_s'] <= source_s+EPS]
    frames = [{k: f.get(k) for k in ('frame_id', 'processing_s', 'state', 'action', 'valid', 'reason',
                                    'eta_source', 'eta_target', 'x', 'y', 'spatial_ok', 'temporal_ok')}
              for f in data['frames'] if f.get('processing_s') is not None
              and (source_s is None or f['processing_s'] <= source_s+EPS)]
    events = [{k: e.get(k) for k in ('event', 'time_s', 'activated_target', 'action', 'applied_s')}
              for e in data['events'] if source_s is None or e['time_s'] <= source_s+EPS]
    return dict(source_confirmation_s=source_s, captures=captures, frames=frames, events=events)


def verify_files(path, manifest):
    import cv2
    import numpy as np
    errors = []
    checked = 0
    files = {str(name).replace('\\', '/'): h for name, h in manifest['files'].items()}
    actual = {p.relative_to(path).as_posix() for p in path.rglob('*')
              if p.is_file() and p.name != 'trial_manifest.json'}
    if set(files) != actual:
        errors.append('manifest_file_inventory_mismatch')
    for name, expected in files.items():
        p = path/name
        if not p.is_file() or sha(p) != expected:
            errors.append('file_hash_mismatch: ' + name)
        checked += 1
    if len(manifest['source_hashes']) != 77:
        errors.append('expected_77_core_sources: ' + str(len(manifest['source_hashes'])))
    for name, expected in manifest['source_hashes'].items():
        archived = path/'source_code'/name
        if not archived.is_file() or sha(archived) != expected:
            errors.append('archived_source_hash_mismatch: ' + name)
        current = REPO/name
        if not current.is_file() or sha(current) != expected:
            errors.append('current_source_hash_mismatch: ' + name)
    masks = 0
    captures = read_csv(path/'observations/captures.csv')
    for c in captures:
        if c['mask_path'] is None:
            if c['raw_mask_sha256'] is not None or c['mask_sha256'] is not None or not c['dropped']:
                errors.append('missing_mask_contract: ' + str(c['frame_id']))
            continue
        p = path/c['mask_path']
        if not p.is_file():
            errors.append('missing_mask_file: ' + str(c['frame_id']))
            continue
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != c['mask_sha256']:
            errors.append('capture_png_hash_mismatch: ' + str(c['frame_id']))
        decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None or hashlib.sha256(decoded.tobytes()).hexdigest() != c['raw_mask_sha256']:
            errors.append('capture_raw_mask_hash_mismatch: ' + str(c['frame_id']))
        masks += 1
    return errors, checked, masks, captures


def audit_trial(path, aggregate_row):
    manifest = json.loads((path/'trial_manifest.json').read_text(encoding='utf-8'))
    errors, files, masks, captures = verify_files(path, manifest)
    metrics = read_csv(path/'trials.csv')
    if len(metrics) != 1:
        raise ValueError('trial metrics must contain exactly one row')
    m = metrics[0]
    for key, item in m.items():
        if not same(item, aggregate_row.get(key)):
            errors.append('aggregate_trial_mismatch: ' + key)
    data = dict(captures=captures, frames=read_csv(path/'observations/frames.csv'),
                events=read_csv(path/'observations/events.csv'), truth=read_csv(path/'evaluation/truth_ticks.csv'))
    steps = read_csv(path/'evaluation/step_outcomes.csv')
    recorded = read_csv(path/'evaluation/event_evaluation.csv')
    config = json.loads((path/'config_snapshot.json').read_text(encoding='utf-8'))
    environment = config['common']['environment']
    route = environment['route']
    if route != [190, 191, 192, 172] or m.get('planned_steps') != 3:
        errors.append('fixed_route_or_step_contract')
    if (environment.get('truth_radius') != .09 or environment.get('truth_max_speed') != .06
            or environment.get('truth_dwell_s') != .15 or environment.get('max_time_s') != 24.
            or config != manifest.get('config')):
        errors.append('frozen_reference_or_config_contract')
    if sorted(s.get('step') for s in steps) != [0, 1, 2]:
        errors.append('three_step_ledger_missing_or_duplicated')
    if m.get('terminal_outcome') not in TERMINALS:
        errors.append('invalid_terminal_outcome')
    if not data['truth']:
        errors.append('missing_truth_evidence')
    geometry = json.loads((path/'electrode_map_snapshot.json').read_text(encoding='utf-8'))
    centers = centers_from_map(geometry)
    # world_goal is deliberately displaced for partial_stall/deviation/failure;
    # electrode activation, not an unfaulted goal coordinate, is the contract.
    for e in data['events']:
        if e['event'] == 'Applied':
            at = [t for t in data['truth'] if abs(t['time_s']-e['time_s']) <= EPS]
            if len(at) != 1:
                errors.append('applied_truth_tick_missing_or_duplicated: ' + str(e.get('request_id')))
    errors.extend(check_transactions(data['events'], data['truth'], m['scenario'], m['method']))
    dt = environment['dt_s']
    if data['truth']:
        expected_ticks = round(m['execution_time_s']/dt)+1
        if len(data['truth']) != expected_ticks or any(abs(t['time_s']-i*dt) > EPS for i, t in enumerate(data['truth'])):
            errors.append('truth_tick_ledger_gap')
        for t in data['truth']:
            if abs(math.hypot(t['world_vx'], t['world_vy'])-t['true_speed']) > EPS:
                errors.append('truth_speed_vector_mismatch: ' + str(t['time_s']))
    intervals = scan_support(data['truth'], centers, dt)
    independent = evaluate_events(data['events'], intervals)
    by_id = {r['request_id']: r for r in recorded}
    if len(by_id) != len(recorded) or {r['request_id'] for r in independent} != set(by_id):
        errors.append('event_evaluation_identity_mismatch')
    for row in independent:
        original = by_id.get(row['request_id'], {})
        for key, expected in row.items():
            if not same(expected, original.get(key)):
                errors.append('event_scoring_mismatch: ' + row['request_id'] + ':' + key
                              + ':' + repr(original.get(key)) + ' != ' + repr(expected))
        row.update(trial_id=m['trial_id'], cohort=m['cohort'], scenario=m['scenario'], seed=m['seed'],
                   method=m['method'], protection=m['protection'], phase_mode=m['phase_mode'])
    source_supported = (m.get('source_confirmation_s') is not None
                        and support_at(intervals, route[0], m['source_confirmation_s'])['supported'])
    if source_supported != m.get('source_reference_supported'):
        errors.append('source_reference_support_mismatch')
    per_step = []
    for step, (source, target) in enumerate(zip(route, route[1:])):
        activations = [e for e in data['events'] if e['event'] == 'Applied' and e.get('action') in ('Start', 'Update')
                       and e.get('activation_step') == step]
        confirmations = [e for e in independent if e['step'] == step]
        active_s = min((e['time_s'] for e in activations), default=None)
        arrived = active_s is not None and any(r['target'] == target and r['upper_s'] >= active_s-EPS for r in intervals)
        supported = len(confirmations) == 1 and confirmations[0]['supported_at_request']
        per_step.append(dict(step=step, source=source, target=target, attempted=active_s is not None,
                             activation_s=active_s, confirmation_requested=bool(confirmations), reference_arrived=arrived,
                             supported_confirmation=supported, unsupported_requests=sum(not e['supported_at_request'] for e in confirmations),
                             duplicate_requests=max(0, len(confirmations)-1), missed_reference=arrived and not confirmations,
                             unattempted=active_s is None))
        recorded_step = next((s for s in steps if s.get('step') == step), {})
        for key, expected in per_step[-1].items():
            if not same(expected, recorded_step.get(key)):
                errors.append('step_scoring_mismatch: ' + str(step) + ':' + key)
    complete = any(e['event'] == 'Complete' for e in data['events'])
    strict = (complete and all(s['supported_confirmation'] for s in per_step)
              and (source_supported or m['phase_mode'] == 'transport_only'))
    terminal = ('infrastructure_invalid' if m.get('infrastructure_invalid') else
                'source_preparation_failed' if not m['source_prepared'] else
                'transport_aborted' if not complete else
                'reference_supported_path_complete' if strict else 'workflow_complete_without_supported_path')
    expected_metrics = dict(transport_complete=complete, path_complete=strict, terminal_outcome=terminal,
                            attempted_steps=sum(s['attempted'] for s in per_step),
                            unattempted_steps=sum(s['unattempted'] for s in per_step),
                            supported_confirmations=sum(s['supported_confirmation'] for s in per_step),
                            unsupported_requests=sum(not r['supported_at_request'] for r in independent),
                            reference_arrived_steps=sum(s['reference_arrived'] for s in per_step),
                            budgetized_completion_s=m['execution_time_s'] if strict else 24.)
    for key, expected in expected_metrics.items():
        if not same(expected, m.get(key)):
            errors.append('trial_scoring_mismatch: ' + key)
    budgets = Counter(e['activation_step'] for e in data['events'] if e['event'] == 'Applied' and e.get('action') != 'Prepare')
    if any(n > 7 for n in budgets.values()) or max(budgets.values(), default=0) != m['max_step_applied']:
        errors.append('applied_budget_contract')
    for key, condition in (('retries', lambda e: e.get('action') == 'Retry' and e.get('origin_phase') != 'recovering'),
                           ('recovery_resends', lambda e: e.get('action') == 'Retry' and e.get('origin_phase') == 'recovering'),
                           ('recoveries', lambda e: e.get('action') == 'Recovery')):
        if sum(condition(e) for e in data['events'] if e['event'] == 'Applied') != m[key]:
            errors.append('action_budget_count_mismatch: ' + key)
    ext = m['exogenous']
    if (ext != manifest['exogenous'] or digest(ext) != m['exogenous_hash']
            or ext.get('max_time_s') != 24. or ext.get('world_stream') != [m['seed'], 101]
            or ext.get('camera_stream') != [m['seed'], 202]):
        errors.append('exogenous_manifest_contract')
    for key in ('world_noise', 'camera_errors', 'camera_uniform'):
        if not isinstance(ext.get(key), str) or len(ext[key]) != 64:
            errors.append('missing_exogenous_array_hash: ' + key)
    data.update(metrics=m, source_hashes=manifest['source_hashes'], independent=independent,
                independent_steps=per_step,
                prefix_hash=digest(prefix_projection(data, m.get('source_confirmation_s'))))
    return dict(errors=errors, files=files, masks=masks, data=data)


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_audit(input_dir, qa_dir):
    input_dir, qa_dir = Path(input_dir).resolve(), Path(qa_dir).resolve()
    if qa_dir == input_dir or input_dir in qa_dir.parents:
        raise ValueError('QA output must not be inside frozen input directory')
    qa_dir.mkdir(parents=True, exist_ok=True)
    metrics = read_csv(input_dir/'development_trials.csv')
    planned = json.loads((input_dir/'planned_trials.json').read_text(encoding='utf-8'))
    errors = []
    expected = Counter(identity(r) for r in expected_plan())
    if Counter(map(identity, planned)) != expected or Counter(map(identity, metrics)) != expected:
        errors.append(dict(check='planned_identities', error='fixed 84+12+24 identities missing or duplicated'))
    agg_steps = read_csv(input_dir/'development_steps.csv')
    if len(agg_steps) != 360 or Counter((r['trial_id'], r['step']) for r in agg_steps) != Counter((m['trial_id'], s) for m in metrics for s in range(3)):
        errors.append(dict(check='360_step_ledger', error='missing or duplicated trial/step identities'))
    groups = defaultdict(list)
    all_events = []
    all_steps = []
    total_files = total_masks = 0
    trial_results = []
    source_set = None
    for i, m in enumerate(metrics):
        path = input_dir/m['relative_trial_path']
        try:
            result = audit_trial(path, m)
        except Exception as exc:
            errors.append(dict(trial_id=m['trial_id'], check='trial_load', error=type(exc).__name__+': '+str(exc)))
            continue
        total_files += result['files']; total_masks += result['masks']
        errors.extend(dict(trial_id=m['trial_id'], check='trial_audit', error=e) for e in result['errors'])
        data = result['data']
        if source_set is None:
            source_set = data['source_hashes']
        elif source_set != data['source_hashes']:
            errors.append(dict(trial_id=m['trial_id'], check='source_freeze', error='77-source hash sets differ'))
        groups[m['scenario'], m['seed'], m['phase_mode']].append(data)
        all_events.extend(data['independent'])
        all_steps.extend(dict(s, trial_id=m['trial_id'], cohort=m['cohort']) for s in data['independent_steps'])
        trial_results.append(dict(trial_id=m['trial_id'], error_count=len(result['errors']),
                                  events=len(data['independent']), masks=result['masks'], files=result['files'],
                                  trial_manifest_sha256=sha(path/'trial_manifest.json'),
                                  recomputed_p0_normalized_hash=data['prefix_hash']))
        if (i+1) % 20 == 0:
            print(f'independent persisted-data audit {i+1}/{len(metrics)}; errors={len(errors)}', flush=True)
    witnesses = []
    for key, group in groups.items():
        if len({digest(g['metrics']['exogenous']) for g in group}) != 1:
            errors.append(dict(check='shared_exogenous', group=key, error='world/camera hashes or speed factor differ'))
        if key[2] == 'end_to_end':
            if len({g['prefix_hash'] for g in group}) != 1 or len({g['metrics']['p0_prefix_hash'] for g in group}) != 1:
                errors.append(dict(check='common_P0', group=key, error='actual normalized capture/frame/action prefixes differ'))
        witness = None
        for j, first in enumerate(group):
            for second in group[j+1:]:
                candidate = mask_fork_witness(first, second)
                if candidate is not None:
                    candidate.update(first_trial=first['metrics']['trial_id'], second_trial=second['metrics']['trial_id'], group=key)
                    witness = candidate
                    break
            if witness:
                break
        if witness:
            witnesses.append(witness)
    if not witnesses:
        errors.append(dict(check='control_mask_divergence', error='no observed equal-frame-ID Mask difference after control fork'))
    ext_by_scenario_seed = defaultdict(set)
    for group in groups.values():
        for data in group:
            m = data['metrics']
            ext_by_scenario_seed[m['scenario'], m['seed']].add(digest(m['exogenous']))
    for key, hashes in ext_by_scenario_seed.items():
        if len(hashes) != 1:
            errors.append(dict(check='cross_cohort_exogenous', group=key, error='phase/cohort exogenous hashes differ'))
    aggregated_events = read_csv(input_dir/'request_applied_evaluation.csv')
    # Aggregate tables have fewer context fields than the independent output;
    # all score fields and numerical reference bounds still must agree.
    context_only = ('scenario', 'seed', 'method', 'protection', 'phase_mode')
    projected = [{k: v for k, v in row.items() if k not in context_only} for row in all_events]
    errors.extend(dict(check='aggregate_events', error=e)
                  for e in compare_ledger(aggregated_events, projected, ('trial_id', 'request_id')))
    errors.extend(dict(check='aggregate_steps', error=e)
                  for e in compare_ledger(agg_steps, all_steps, ('trial_id', 'step')))
    report = dict(schema='chapter2_s3_independent_persisted_data_audit_v1',
                  generated_at_utc=datetime.now(timezone.utc).isoformat(), passed=not errors,
                  input_directory=str(input_dir), read_only=True, simulation_or_algorithm_runs=0,
                  audit_script_sha256=sha(Path(__file__)),
                  audit_tests_sha256=sha(REPO/'tests/test_chapter2_s3_audit.py'),
                  input_index_hashes={name: sha(input_dir/name) for name in
                                      ('planned_trials.json', 'config_manifest.json', 'development_trials.csv',
                                       'development_steps.csv', 'request_applied_evaluation.csv')},
                  imports_original_reference_or_scorer=False, formal_seed_runs=0,
                  records=len(metrics), cohorts=dict(Counter(m['cohort'] for m in metrics)), planned_steps=len(agg_steps),
                  terminal_outcomes=dict(Counter(m['terminal_outcome'] for m in metrics)),
                  event_count=len(all_events), supported_requests=sum(e['supported_at_request'] for e in all_events),
                  unsupported_requests=sum(not e['supported_at_request'] for e in all_events),
                  supported_applied=sum(e['supported_at_applied'] is True for e in all_events),
                  core_source_files=len(source_set or {}), source_hashes=source_set,
                  files_hash_verified=total_files, decoded_masks_raw_hash_verified=total_masks,
                  paired_groups=len(groups), equal_frame_control_fork_witness_groups=len(witnesses),
                  independently_verified_common_P0_groups=sum(k[2] == 'end_to_end' for k in groups),
                  cross_cohort_exogenous_groups=len(ext_by_scenario_seed),
                  control_fork_witnesses=witnesses,
                  support_contract=dict(radius_pitch=.09, max_speed_pitch_s=.06, dwell_s=.15,
                                        strict_uses_interval_upper_bound=True, same_target_retry_preserves_physics=True,
                                        actual_activation_change_breaks_continuity=True, switch_time_left_limit_only=True,
                                        requests_and_applied_independent=True),
                  limitations=['SIMULATION only; no physical closed-loop validation.',
                               'Exogenous arrays are represented by persisted byte hashes and speed factor; array bytes were not saved and are not regenerated.',
                               'PNG decoding is not camera acquisition, detection, or algorithm execution.'],
                  trials=trial_results, error_count=len(errors), errors=errors)
    write_csv(qa_dir/'independent_event_evaluation.csv', all_events)
    write_csv(qa_dir/'independent_step_evaluation.csv', all_steps)
    (qa_dir/'independent_data_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'records', 'planned_steps', 'event_count', 'decoded_masks_raw_hash_verified', 'error_count')}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_OUT/'development_smoke')
    parser.add_argument('--qa', type=Path, default=DEFAULT_OUT/'QA')
    args = parser.parse_args()
    raise SystemExit(0 if run_audit(args.input, args.qa)['passed'] else 1)
