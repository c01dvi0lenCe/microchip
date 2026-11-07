"""Independent offline internal-position reference; no Mask/gate imports."""
import math


def evaluate_reference(rows,target_position,target,applied_s):
    start=confirmed=None
    previous=None
    intervals=[]
    for row in rows:
        t=float(row['time_s'])
        if not math.isfinite(t) or (previous is not None and t<=previous):raise ValueError('nonmonotone reference ticks')
        gap=previous is not None and t-previous>.0100001
        previous=t
        distance=math.hypot(float(row['x_mm'])-target_position[0],float(row['y_mm'])-target_position[1])
        valid=t>=applied_s and int(row['active'])==target and distance<=.288 and float(row['speed_mm_s'])<=.192
        if not valid or gap:
            if start is not None:intervals.append(dict(start_s=start,end_s=t,confirmed_s=confirmed))
            start=confirmed=None
        if valid:
            if start is None:start=t
            if confirmed is None and t-start>=.15-1e-9:confirmed=t
    if start is not None:intervals.append(dict(start_s=start,end_s=previous,confirmed_s=confirmed))
    supported=[r for r in intervals if r['confirmed_s'] is not None]
    return dict(intervals=intervals,confirmed_s=supported[0]['confirmed_s'] if supported else None,
                reference_definition=dict(radius_mm=.288,max_speed_mm_s=.192,dwell_s=.15))
