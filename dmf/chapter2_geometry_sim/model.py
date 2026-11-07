"""Millimetre geometry and phenomenological overlap-gated point translation."""
from dataclasses import dataclass, asdict
import math
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from dmf.vision.design_registration import file_hash, load_design_map


@dataclass(frozen=True)
class DemoConfig:
    diameter_mm: float = 3.8
    spacer_height_mm: float = .8
    route: tuple = (190,191,192,172)
    dt_s: float = .01
    duration_s: float = 6.
    applied_delay_s: float = .04
    response_delay_s: float = .18
    speed_mm_s: float = 4.8
    camera_fps: float = 20.
    exposure_s: float = .008
    processing_delay_s: float = .04
    pixels_per_mm: float = 40.
    position_noise_mm: float = .03
    drop_probability: float = 0.
    seed: int = 264900
    demo_position_gate_mm: float = .3

    def __post_init__(self):
        for key in ('diameter_mm','spacer_height_mm','dt_s','duration_s','speed_mm_s','camera_fps','pixels_per_mm','demo_position_gate_mm'):
            v=getattr(self,key)
            if not math.isfinite(v) or v<=0:
                raise ValueError(f'{key} must be finite and positive')
        for key in ('applied_delay_s','response_delay_s','exposure_s','processing_delay_s','position_noise_mm'):
            v=getattr(self,key)
            if not math.isfinite(v) or v<0:
                raise ValueError(f'{key} must be finite and nonnegative')
        if not 0<=self.drop_probability<=1 or not math.isfinite(self.drop_probability):
            raise ValueError('invalid drop probability')
        if len(self.route)<2 or any(type(i) is not int or not 1<=i<=420 for i in self.route):
            raise ValueError('invalid route')
        if any(a==b for a,b in zip(self.route,self.route[1:])):
            raise ValueError('route must change electrode')
        if type(self.seed) is not int or self.seed<0 or self.exposure_s>=1/self.camera_fps:
            raise ValueError('invalid seed or exposure')

    def snapshot(self):
        return asdict(self)


class DesignGeometry:
    def __init__(self,path):
        self.path=Path(path).resolve()
        self.document=load_design_map(self.path)
        self.sha256=file_hash(self.path)
        self.pitch_mm=float(self.document['pitch_mm'])
        self.polygons={e['control_id']:Polygon(e['polygon_map_mm']) for e in self.document['electrodes']}
        if any(not p.is_valid or p.is_empty for p in self.polygons.values()):
            raise ValueError('invalid design polygon')
        self.bounds=unary_union(list(self.polygons.values())).bounds

    def center(self,electrode):
        p=self.polygons[electrode].centroid
        return np.array([p.x,p.y],dtype=float)


def footprint(position,diameter_mm):
    if not math.isfinite(diameter_mm) or diameter_mm<=0:
        raise ValueError('invalid diameter')
    position=np.asarray(position,dtype=float)
    if position.shape!=(2,) or not np.isfinite(position).all():
        raise ValueError('invalid footprint position')
    return Point(*position).buffer(diameter_mm/2,quad_segs=128)


def coverage_at(geometry,diameter_mm,source,target):
    drop=footprint(geometry.center(target),diameter_mm)
    src=geometry.polygons[source]; dst=geometry.polygons[target]
    intersection=drop.intersection(dst).area
    eta_source=drop.intersection(src).area/drop.area
    eta_target=intersection/drop.area
    return dict(diameter_mm=diameter_mm,projected_area_mm2=drop.area,
                electrode_area_mm2=dst.area,eta_source=eta_source,
                eta_target=eta_target,rho_target=intersection/dst.area,
                starting_neighbor_overlap_mm2=footprint(geometry.center(source),diameter_mm).intersection(dst).area,
                old_G_eligible=eta_target>=.85 and eta_source<=.08)


class GeometryWorld:
    """No friction/electric-field solver. Positive overlap is a model gate only."""
    def __init__(self,geometry,config):
        self.geometry,self.cfg=geometry,config
        self.position=geometry.center(config.route[0])
        self.active=config.route[0]
        self.time_s=0.
        self.pending=None
        self.response_at_s=0.
        self.activation_segment=0
        self.status='held'
        self.events=[]

    def request(self,target,time_s,action='Update'):
        if self.pending is not None:
            raise ValueError('pending transaction')
        if target not in self.geometry.polygons or abs(time_s-self.time_s)>1e-8:
            raise ValueError('invalid target or request time')
        self.pending=(target,time_s+self.cfg.applied_delay_s,action)
        self.events.append(dict(time_s=time_s,event='request',action=action,target=target,activation_segment=self.activation_segment))

    def advance(self,to_s):
        if not math.isfinite(to_s) or to_s<self.time_s-1e-10:
            raise ValueError('nonmonotone simulation clock')
        while self.time_s<to_s-1e-10:
            end=min(to_s,self.time_s+self.cfg.dt_s)
            if self.pending is not None and self.time_s<self.pending[1]<end-1e-10:
                end=self.pending[1]
            if self.pending is not None and self.time_s>=self.pending[1]-1e-10:
                target,applied,action=self.pending
                changed=target!=self.active
                if changed:
                    self.active=target
                    self.activation_segment+=1
                    self.response_at_s=applied+self.cfg.response_delay_s
                self.events.append(dict(time_s=applied,event='simulated_applied',action=action,target=target,activation_segment=self.activation_segment))
                self.pending=None
            delta=self.geometry.center(self.active)-self.position
            distance=float(np.linalg.norm(delta))
            if distance<1e-8:
                self.status='at_active_center'
            elif end<=self.response_at_s+1e-10:
                self.status='response_delay'
            elif footprint(self.position,self.cfg.diameter_mm).intersection(self.geometry.polygons[self.active]).area<=1e-8:
                self.status='blocked_no_overlap'
            else:
                usable=end-max(self.time_s,self.response_at_s)
                step=min(distance,self.cfg.speed_mm_s*max(0.,usable))
                self.position+=delta/distance*step
                self.status='moving' if step<distance else 'at_active_center'
            self.time_s=end

    def snapshot(self):
        overlap=footprint(self.position,self.cfg.diameter_mm).intersection(self.geometry.polygons[self.active]).area
        return dict(time_s=self.time_s,x_mm=float(self.position[0]),y_mm=float(self.position[1]),active=self.active,
                    activation_segment=self.activation_segment,response_at_s=self.response_at_s,
                    active_overlap_mm2=overlap,world_status=self.status)
