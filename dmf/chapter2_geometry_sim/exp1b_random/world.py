"""Minimum-jerk point motion with saved-outline-only shape replay."""
import math
import numpy as np


def _phase(u):
    u = min(1., max(0., u))
    return 10*u**3-15*u**4+6*u**5


def _inverse_phase(q):
    low, high = 0., 1.
    for _ in range(70):
        mid = (low+high)/2
        if _phase(mid) < q: low = mid
        else: high = mid
    return (low+high)/2


def make_world(config, motion_draw, kind, geometry, pool, source_ticks):
    if kind not in ('normal', 'slow', 'pause', 'stall'):
        raise ValueError('Undeclared world kind')
    p = motion_draw['parameters']; clock = config['time']; geo = config['geometry']
    source = geometry.center(geo['source']); target = geometry.center(geo['target'])
    axis = target-source; length = float(np.linalg.norm(axis)); dt = clock['dt_s']
    peak = p['slow_peak_speed_mm_s'] if kind == 'slow' else p['normal_peak_speed_mm_s']
    duration = 1.875*length/peak
    applied = clock['request_s']+clock['simulated_applied_delay_s']
    response = applied+p['response_delay_s']
    pause_clock = duration*_inverse_phase(p['pause_progress'])
    stall_clock = duration*_inverse_phase(p['stall_progress'])
    rows = []; polygons = []; diagnostics = []; min_overlap = math.inf; max_area_error = 0.
    stall_start = math.ceil((response+stall_clock)/dt-1e-9)*dt if kind == 'stall' else None
    for i in range(round(clock['horizon_s']/dt)+1):
        t = round(i*dt, 10); moving_clock = max(0., t-response)
        if kind == 'pause' and moving_clock >= pause_clock:
            moving_clock = max(pause_clock, moving_clock-p['pause_duration_s'])
        if kind == 'stall': moving_clock = min(moving_clock, stall_clock)
        q = _phase(moving_clock/duration); point = source+q*axis
        speed = float(np.linalg.norm(point-np.array([rows[-1]['x_mm'], rows[-1]['y_mm']]))/dt) if rows else 0.
        active = geo['target'] if t >= applied-1e-10 else geo['source']
        polygon, info = pool.at(q, point)
        if speed > 1e-8:
            if t <= response+1e-10 or t < applied: raise ValueError('Motion before Applied/response')
            overlap = polygons[-1].intersection(geometry.polygons[active]).area
            min_overlap = min(min_overlap, overlap)
            if overlap <= 1e-8: raise ValueError('Motion without previous actual-outline active overlap')
        area_error = abs(polygon.area/pool.area-1); max_area_error = max(max_area_error, area_error)
        if area_error > 1e-8 or math.dist(polygon.centroid.coords[0], point) > 1e-8:
            raise ValueError('Saved-outline translation violated area/centroid preservation')
        rows.append(dict(time_s=t, x_mm=float(point[0]), y_mm=float(point[1]), speed_mm_s=speed,
            progress=q, active=active, response_at_s=response, shape_phase=q,
            area_mm2=polygon.area, active_overlap_mm2=polygon.intersection(geometry.polygons[active]).area,
            permanent_stall=kind == 'stall' and t >= stall_start-1e-10))
        polygons.append(polygon)
        diagnostics.append(dict(time_s=t, source_tick=source_ticks[info['selected_index']], **info))
    return dict(rows=rows, polygons=polygons, diagnostics=diagnostics, manifest=dict(
        seed=motion_draw['seed'], kind=kind, ticks=len(rows), request_s=clock['request_s'], applied_s=applied,
        response_s=response, peak_speed_mm_s=peak, duration_s=duration,
        raw_motion_uniforms=motion_draw['raw_uniforms'], permanent_stall_started_s=stall_start,
        permanent_stall_time_definition='first progress-clamped tick; finite-difference speed becomes zero on next tick',
        first_exactly_stationary_stall_tick_s=round(stall_start+dt,10) if stall_start is not None else None,
        pause_started_s=response+pause_clock if kind == 'pause' else None,
        pause_duration_s=p['pause_duration_s'] if kind == 'pause' else None,
        shape_provider='nearest_saved_valid_outline_translation_only', saved_pool_count=len(pool.phases),
        maximum_phase_error=max(abs(r['phase_error']) for r in diagnostics),
        maximum_phase_error_bound=pool.max_phase_error_bound, maximum_area_relative_error=max_area_error,
        minimum_moving_previous_overlap_mm2=min_overlap if math.isfinite(min_overlap) else None,
        topology_repaired=False, new_SDF_interpolation=False))
