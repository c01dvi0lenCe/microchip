"""Independent finite-difference WORLD reference, never a recognizer input."""
import math


def build_reference(rows, target_position, target=191, applied_s=.54, spec=None,
                    horizon=10., permanent_stall=False):
    spec = spec or dict(radius_mm=.288, max_speed_mm_s=.192, dwell_s=.15)
    intervals = []; start = confirmed = previous = None; last = None; final_good = False
    for row in rows:
        t = float(row['time_s'])
        if not math.isfinite(t) or (previous is not None and t <= previous):
            raise ValueError('Strictly increasing finite reference ticks required')
        if t > horizon + 1e-9:
            break
        distance = math.hypot(float(row['x_mm'])-target_position[0], float(row['y_mm'])-target_position[1])
        good = (t >= applied_s-1e-10 and int(row['active']) == target
            and distance <= spec['radius_mm'] and float(row['speed_mm_s']) <= spec['max_speed_mm_s'])
        gap = previous is not None and t-previous > .0100001
        if start is not None and (not good or gap):
            intervals.append(dict(start_s=start, end_s=t if not gap else previous,
                                  confirmed_s=confirmed, terminal_inclusive=False, actual_exit=not good))
            start = confirmed = None
        if good:
            if start is None: start = t
            if confirmed is None and t-start >= spec['dwell_s']-1e-9: confirmed = t
        previous = t; last = row; final_good = good
    if start is not None:
        intervals.append(dict(start_s=start, end_s=previous, confirmed_s=confirmed,
            terminal_inclusive=abs(previous-horizon) <= 1e-9, actual_exit=False))
    complete = [r for r in intervals if r['confirmed_s'] is not None]
    if complete: status = 'completed_by_H'
    elif final_good: status = 'dwell_incomplete_at_H'
    elif permanent_stall: status = 'permanent_stall_without_reference'
    elif last and float(last['speed_mm_s']) > 1e-10: status = 'approaching_at_H'
    else: status = 'no_reference_by_H'
    return dict(intervals=intervals, confirmed_s=complete[0]['confirmed_s'] if complete else None,
        status=status, reference_definition=dict(spec), horizon_s=horizon,
        permanent_stall=bool(permanent_stall), reference_right_censored=status in
        ('dwell_incomplete_at_H', 'approaching_at_H', 'no_reference_by_H'))
