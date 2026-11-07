"""Scoring side only: independent intervals from simulated position and speed."""
import math


def derive_reference(truth,geometry,reference,dt_s,planned_steps):
    intervals=[]
    for step in range(planned_steps):
        since=None;found=None;previous_time=None;previous_context=None
        for row in truth:
            if row['step']!=step or row['phase']!='transport':
                since=None;previous_time=None;previous_context=None
                continue
            t=row['time_s'];context=(row.get('epoch'),row['target'])
            if (previous_context!=context or previous_time is None or
                    t<=previous_time or t-previous_time>dt_s+1e-9):
                since=None
            previous_time=t;previous_context=context
            center=geometry.centers[int(row['target'])]
            inside=(math.hypot(row['x']-center[0],row['y']-center[1])<=reference.radius_pitch and row['true_speed']<=reference.max_speed_pitch_s)
            if inside:
                if since is None:since=row['time_s']
                if row['time_s']-since>=reference.dwell_s-1e-9:
                    found=dict(step=step,target=int(row['target']),lower_s=max(0.,row['time_s']-dt_s),upper_s=row['time_s'],
                               dwell_begin_s=since,reference_version=reference.version,source='independent_simulation_reference',simulation=True)
                    break
            else:since=None
        if found:intervals.append(found)
    return intervals
