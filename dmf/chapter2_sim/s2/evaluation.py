"""Independent S2 reference and event scoring, never a prediction input.

All times are simulation seconds. A task is half-open [start_s, end_s);
truth coverage additionally requires the right endpoint as a logging witness.
Missing captures are records, not missing follow-up. No mask is read here.
"""
from collections.abc import Mapping
import math

from ..v2.reference import derive_reference


_EPS = 1e-9
_MISSING = object()


def _get(value, key, default=_MISSING):
    if isinstance(value, Mapping):
        result = value.get(key, default)
    else:
        result = getattr(value, key, default)
    if result is _MISSING:
        raise ValueError(f'missing required field: {key}')
    return result


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite numeric simulation time/value')
    return float(value)


def _equal(left, right):
    """Tolerance only identifies equal floating-point grid boundaries."""
    return abs(left - right) <= _EPS


def _before(left, right):
    return left < right and not _equal(left, right)


def _plan(value):
    result = {key: _get(value, key) for key in ('step_id', 'source', 'target')}
    for key in ('start_s', 'end_s', 'applied_s'):
        result[key] = _finite(_get(value, key), key)
    if not result['start_s'] <= result['applied_s'] < result['end_s']:
        raise ValueError('task requires start <= applied < end')
    if result['source'] == result['target']:
        raise ValueError('transport source and target must differ')
    return result


def build_reference(truth_rows, tasks, geometry, reference_spec, dt_s=.01):
    """Return one explicit reference status for every planned task.

    The existing v2 radius/speed/dwell implementation supplies intervals. Its
    input is a fresh adaptation; caller rows and historical reference code are
    unchanged. Incomplete truth is conservatively unassessable even when a
    locally complete segment happens to contain a possible arrival.
    """
    dt_s = _finite(dt_s, 'dt_s')
    if dt_s <= 0:
        raise ValueError('positive dt_s required')
    rows = list(truth_rows)
    plans = [_plan(task) for task in tasks]
    if len({p['step_id'] for p in plans}) != len(plans):
        raise ValueError('duplicate task identity')
    previous = None
    for row in rows:
        time = _finite(_get(row, 'time_s'), 'time_s')
        if previous is not None and time <= previous:
            raise ValueError('truth times must be strictly increasing without duplicates')
        previous = time
        for key in ('x', 'y', 'true_speed'):
            number = _finite(_get(row, key), key)
            if key == 'true_speed' and number < 0:
                raise ValueError('negative true speed')
    for earlier, later in zip(plans, plans[1:]):
        if later['start_s'] < earlier['end_s']:
            raise ValueError('tasks must be ordered and nonoverlapping')
    results = []
    for plan in plans:
        start, end, applied = (plan[k] for k in ('start_s', 'end_s', 'applied_s'))
        if plan['target'] not in geometry.centers or plan['source'] not in geometry.centers:
            raise ValueError('task electrode absent from geometry')
        for coordinate in geometry.centers[plan['target']]:
            _finite(coordinate, 'target center')
        coverage = [row for row in rows if not _before(_get(row, 'time_s'), start)
                    and not _before(end, _get(row, 'time_s'))]
        complete = bool(coverage and _equal(_get(coverage[0], 'time_s'), start)
                        and _equal(_get(coverage[-1], 'time_s'), end)
                        and all(_equal(_get(b, 'time_s') - _get(a, 'time_s'), dt_s)
                                for a, b in zip(coverage, coverage[1:])))
        adapted = []
        for row in coverage:
            time = _get(row, 'time_s')
            if not _before(time, end):
                continue  # Endpoint is a coverage witness, not this task's input.
            for key in ('step_id', 'source', 'target'):
                if _get(row, key, plan[key]) != plan[key]:
                    raise ValueError(f'inconsistent truth {key}')
            if not _equal(_finite(_get(row, 'applied_s', applied), 'applied_s'), applied):
                raise ValueError('inconsistent truth applied_s')
            if _before(time, applied):
                continue
            active = _get(row, 'world_active', _get(row, 'world.active', plan['target']))
            world = _get(row, 'world', None)
            if world is not None:
                active = _get(world, 'active', active)
            if active != plan['target']:
                if active is None and _equal(time, applied):
                    continue  # World applies at the next interval's start.
                raise ValueError('truth world.active does not match applied target')
            if _get(row, 'phase', 'transport') != 'transport':
                continue
            adapted.append(dict(time_s=time, x=_get(row, 'x'), y=_get(row, 'y'),
                                true_speed=_get(row, 'true_speed'), step=0, phase='transport',
                                epoch=_get(row, 'epoch', plan['step_id']), target=plan['target']))
        found = derive_reference(adapted, geometry, reference_spec, dt_s, 1) if complete else []
        interval = found[0] if found else {}
        results.append(dict(step_id=plan['step_id'], target=plan['target'],
            status='reference_right_censored' if not complete else 'arrived' if found else 'not_arrived',
            lower_s=interval.get('lower_s'), upper_s=interval.get('upper_s'),
            dwell_begin_s=interval.get('dwell_begin_s'),
            observation_start_s=_get(coverage[0], 'time_s') if coverage else None,
            observation_end_s=_get(coverage[-1], 'time_s') if coverage else None,
            truth_complete=complete, reference_version=reference_spec.version,
            simulation=True, source='independent_simulation_reference', provenance='simulation_scoring_only'))
    return results


def score_step(plan, reference_status, events, followup, *, horizon_s=1.):
    """Score the first eligible event once, retaining independent error counts.

    S_H is supported confirmation yield per independently arrived reference.
    Planned steps remain a separate denominator. A late-supported
    first event is support descriptively, but does not repair a primary miss.
    A premature first event consumes the opportunity permanently.
    """
    plan = _plan(plan)
    horizon_s = _finite(horizon_s, 'horizon_s')
    if horizon_s <= 0:
        raise ValueError('positive confirmation horizon required')
    for key in ('step_id', 'target'):
        if _get(reference_status, key) != plan[key]:
            raise ValueError(f'reference {key} does not match task')
    status = _get(reference_status, 'status')
    if status not in ('arrived', 'not_arrived', 'reference_right_censored'):
        raise ValueError('unknown independent reference status')
    truth_complete = _get(reference_status, 'truth_complete')
    if type(truth_complete) is not bool:
        raise ValueError('truth_complete must be explicit boolean')
    ref_unknown = not truth_complete or status == 'reference_right_censored'
    arrived = status == 'arrived' and not ref_unknown
    lower = upper = None
    if arrived:
        lower = _finite(_get(reference_status, 'lower_s'), 'lower_s')
        upper = _finite(_get(reference_status, 'upper_s'), 'upper_s')
        if lower > upper or _before(lower, plan['applied_s']) or not _before(upper, plan['end_s']):
            raise ValueError('invalid arrival interval for task')
    entered = _get(followup, 'task_entered')
    generated = _get(followup, 'input_generated')
    if type(entered) is not bool or type(generated) is not bool:
        raise ValueError('followup flags must be explicit booleans')
    attempted = entered and generated
    records_end = _get(followup, 'records_end_s', None)
    truth_end = _get(followup, 'truth_end_s', None)
    for name, value in (('records_end_s', records_end), ('truth_end_s', truth_end)):
        if value is not None:
            _finite(value, name)
    first = None
    duplicate = wrong_target = wrong_step = outside = 0
    previous = None
    issued = 0
    for event in events:
        issued += 1
        time = _finite(_get(event, 'timestamp_s'), 'timestamp_s')
        if previous is not None and time < previous:
            raise ValueError('events must be sorted by timestamp_s')
        previous = time
        same_step = _get(event, 'step_id') == plan['step_id']
        same_target = _get(event, 'target') == plan['target']
        in_task = not _before(time, plan['start_s']) and _before(time, plan['end_s'])
        wrong_step += int(not same_step)
        wrong_target += int(not same_target)
        outside += int(not in_task)
        if same_step and same_target and in_task:
            if first is None:
                first = time
            else:
                duplicate += 1
    horizon_end = upper + horizon_s if arrived else None
    deadline = min(plan['end_s'], horizon_end) if arrived else None
    full_followup = bool(arrived and attempted and records_end is not None and truth_end is not None
                         and not _before(plan['end_s'], horizon_end)
                         and not _before(records_end, horizon_end) and not _before(truth_end, horizon_end))
    label = 'no_prediction'
    primary = all_supported = late = premature = uncertain = unsupported = 0
    if first is not None:
        if not attempted:
            label = 'infrastructure_unknown'
        elif ref_unknown:
            label = 'unassessable'
        elif not arrived:
            label = 'unsupported_no_reference'
            unsupported = 1
        elif _before(first, lower):
            label = 'premature'
            premature = 1
        elif _before(first, upper):
            label = 'timing_uncertain'
            uncertain = 1
        else:
            all_supported = 1
            late = int(_before(upper + horizon_s, first))
            primary = int(not late)
            label = 'late_supported' if late else 'supported'
    missed = int(arrived and attempted and not primary and full_followup)
    censored = int(arrived and attempted and not primary and not full_followup)
    result = dict(step_id=plan['step_id'], source=plan['source'], target=plan['target'],
        planned_steps=1, attempted_steps=int(attempted), unattempted_steps=int(not attempted),
        reference_status=status, reference_arrivals=int(arrived), truth_complete=truth_complete,
        supported_confirmations=primary, all_supported_confirmations=all_supported,
        late_supported_confirmations=late, premature_confirmations=premature,
        unsupported_confirmations=unsupported, timing_uncertain_confirmations=uncertain,
        unassessable_confirmations=int(label == 'unassessable'),
        missed_supported_confirmation=missed, no_prediction_reference=int(arrived and first is None),
        confirmation_right_censored=censored, reference_right_censored=int(ref_unknown),
        infrastructure_unknown=int(not attempted), duplicate_events=duplicate,
        wrong_target_events=wrong_target, wrong_step_events=wrong_step, outside_task_events=outside,
        issued_confirmation_events=issued, confirmation_label=label, confirmation_s=first,
        reference_lower_s=lower, reference_upper_s=upper, confirmation_deadline_s=deadline,
        full_confirmation_followup=full_followup, horizon_s=horizon_s,
        latency_lower_s=max(0., first - upper) if all_supported else None,
        latency_upper_s=max(0., first - lower) if all_supported else None,
        S_H_numerator=primary, S_H_denominator=int(arrived), S_H_yield=float(primary) if arrived else None,
        supported_per_planned=float(primary),
        simulation=True, provenance='simulation_scoring_only')
    result.update(supported=primary, all_supported=all_supported, late_supported=late,
                  premature=premature, unsupported=unsupported, timing_uncertain=uncertain,
                  missed=missed, censor=censored, unknown=int(ref_unknown or not attempted))
    return result
