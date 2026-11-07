"""Static geometric feasibility, not time-series frames or another trial."""
import math
import numpy as np


def static_geometry(geometry,shape,source=190,target=191):
    a=geometry.center(source);b=geometry.center(target)
    rows=[]
    for q in (0.,.25,.5,.75,1.):
        position=a+(b-a)*q
        polygon=shape.polygon(position,1.)
        dst=geometry.polygons[target];src=geometry.polygons[source]
        rho=polygon.intersection(dst).area/dst.area
        eta=polygon.intersection(src).area/polygon.area
        rows.append(dict(fraction=q,x_mm=float(position[0]),y_mm=float(position[1]),
                         area_mm2=polygon.area,rho_target=rho,eta_source=eta,
                         candidate_gate=bool(rho>=.9 and eta<=.08),polygon_mm=list(map(list,polygon.exterior.coords))))
    records={e['control_id']:e for e in geometry.document['electrodes']}
    ra,rb=records[source],records[target]
    adjacent=(ra['logical_row']==rb['logical_row'] and abs(ra['logical_col']-rb['logical_col'])==1)
    return dict(rows=rows,logical_adjacency_verified=adjacent,
                center_distance_mm=float(np.linalg.norm(b-a)),
                polygon_min_gap_mm=geometry.polygons[source].distance(geometry.polygons[target]),
                endpoint_gate_feasible=rows[-1]['candidate_gate'],
                meaning='static_compact_template_translation_not_dynamic_trial_frames')
