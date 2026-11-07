"""Scoring only. Independent physical dwell is not reset by software epochs."""
import math

def physical_segments(truth,geometry,reference,dt_s):
    segments=[];current={};previous=None;previous_active=None;activation_begin=None
    targets=tuple(geometry.masks)  # Declared route electrodes, not algorithm gates.
    def finish(value):
        if value and value.get('upper_s') is not None:segments.append(dict(value))
    def extend(value,t):
        value['last_inside_s']=t
        if value['upper_s'] is None and t-value['dwell_begin_s']>=reference.dwell_s-1e-9:
            value['lower_s']=max(value['dwell_begin_s'],t-dt_s);value['upper_s']=t
    for row in truth:
        t=float(row['time_s']);active=row.get('world_active')
        active=int(active) if active is not None else None
        contiguous=previous is not None and 0<t-previous<=dt_s+1e-9
        switched=previous is not None and active!=previous_active
        if previous is None or switched:activation_begin=t
        for target in targets:
            center=geometry.center(target)
            inside=(math.hypot(row['x']-center[0],row['y']-center[1])<=reference.radius_pitch+1e-12
                    and row['true_speed']<=reference.max_speed_pitch_s+1e-12)
            value=current.get(target)
            if value and switched and inside and contiguous:
                # Position is continuous at application. Preserve left-limit
                # support for scoring the *old* target at this exact instant.
                extend(value,t)
            if not inside or not contiguous or switched:
                finish(value);current.pop(target,None);value=None
            if inside and value is None:
                value=dict(target=target,activation_target=active,activation_begin_s=activation_begin,
                    dwell_begin_s=t,lower_s=None,upper_s=None,last_inside_s=t,
                    source='independent_simulation_position_speed_dwell_then_activation_assignment',simulation=True)
                current[target]=value
            if value:extend(value,t)
        previous=t;previous_active=active
    for value in current.values():finish(value)
    return segments

def support_at(segments,target,time_s,*,not_before_s=None):
    candidates=[r for r in segments if r['target']==target and r.get('activation_target',target)==target and r['dwell_begin_s']<=time_s+1e-9 and r['last_inside_s']>=time_s-1e-9
                and (not_before_s is None or r['upper_s']>=not_before_s-1e-9)]
    if not candidates:return dict(supported=False,label='unsupported_no_current_reference',reference_lower_s=None,reference_upper_s=None)
    r=candidates[-1]
    label=('premature' if time_s<r['lower_s']-1e-9 else 'timing_uncertain' if time_s<r['upper_s']-1e-9 else 'supported')
    return dict(supported=label=='supported',label=label,reference_lower_s=r['lower_s'],reference_upper_s=r['upper_s'])
