"""Single-active-electrode world. No observations, arrivals or scoring inputs."""
import math
import numpy as np
from shapely.affinity import rotate


def capped(vector, limit):
    norm=float(np.linalg.norm(vector))
    return vector*(min(1.,limit/norm) if norm else 1.)


class CausalWorld:
    def __init__(self,geometry,pool,config):
        self.geometry,self.pool,self.cfg=geometry,pool,config
        for a,b in zip(config.route,config.route[1:]):
            if a not in geometry.polygons or b not in geometry.polygons:
                raise ValueError('route electrode missing from design')
            if abs(np.linalg.norm(geometry.center(b)-geometry.center(a))-geometry.pitch_mm)>1e-4:
                raise ValueError('real geometry route is not pitch-adjacent')
        self.time_s=0.;self.position=geometry.center(config.route[0]).copy()
        self.velocity=np.zeros(2);self.active=config.route[0];self.pending=None
        self.activation_segment=0;self.response_at_s=0.;self.status='held'
        axis=geometry.center(config.route[1])-self.position
        self.base_angle_rad=math.atan2(axis[1],axis[0]);self.angle_rad=self.base_angle_rad
        self.goal_angle_rad=self.angle_rad;self.phase=0.;self.segment_anchor=self.position.copy()
        self.events=[];self._polygon=None;self.shape_info={};self._update_polygon()

    @property
    def polygon(self):return self._polygon

    def _update_polygon(self):
        p,info=self.pool.at(self.phase,self.position)
        p=rotate(p,self.angle_rad-self.base_angle_rad,origin=tuple(self.position),use_radians=True)
        if not p.is_valid or p.is_empty or len(p.interiors) or abs(p.area/self.pool.area-1)>1e-8:
            raise ValueError('invalid saved-outline transform; no repair')
        if math.dist(p.centroid.coords[0],self.position)>1e-8:raise ValueError('shape centroid mismatch')
        self._polygon,self.shape_info=p,info

    def request(self,target,action='Update'):
        if self.pending is not None:raise ValueError('pending transaction')
        if type(target) is not int or target not in self.geometry.polygons:raise ValueError('unknown electrode')
        self.pending=dict(target=target,action=action,request_s=self.time_s,
                          applied_s=round(self.time_s+self.cfg.applied_delay_s,12))
        self.events.append(dict(event='request',time_s=self.time_s,**self.pending))
        return dict(self.pending)

    def flush_due(self):
        if self.pending is None or self.pending['applied_s']>self.time_s+1e-10:return None
        transaction=self.pending;self.pending=None;old=self.active;left=self.snapshot()
        if transaction['target']!=old:
            self.active=transaction['target'];self.activation_segment+=1
            self.response_at_s=round(transaction['applied_s']+self.cfg.response_delay_s,12)
            self.segment_anchor=self.position.copy()
            axis=self.geometry.center(self.active)-self.geometry.center(old)
            self.goal_angle_rad=math.atan2(axis[1],axis[0])
        event=dict(event='simulated_applied',time_s=transaction['applied_s'],old_active=old,
                   activation_segment=self.activation_segment,left_limit=left,**transaction)
        self.events.append(event)
        return event

    def advance(self,to_s):
        if not math.isfinite(to_s) or to_s<self.time_s-1e-10:raise ValueError('nonmonotone simulation clock')
        self.flush_due()
        while self.time_s<to_s-1e-10:
            end=min(to_s,self.time_s+self.cfg.dt_s)
            if self.pending is not None:end=min(end,self.pending['applied_s'])
            if self.time_s<self.response_at_s<end:end=self.response_at_s
            dt=end-self.time_s
            overlap=self.polygon.intersection(self.geometry.polygons[self.active]).area
            if overlap<=0.:
                self.velocity[:]=0.;self.status='blocked_no_overlap'
            else:
                responding=self.time_s>=self.response_at_s-1e-10
                desired=capped((self.geometry.center(self.active)-self.position)/self.cfg.settle_time_s,
                               self.cfg.vmax_mm_s) if responding else np.zeros(2)
                acceleration=capped((desired-self.velocity)/self.cfg.velocity_tau_s,self.cfg.acceleration_mm_s2)
                self.velocity+=acceleration*dt;self.position+=self.velocity*dt
                self.status='moving' if np.linalg.norm(self.velocity)>1e-10 else 'held' if responding else 'response_delay'
            goal=self.geometry.center(self.active)-self.segment_anchor;den=float(goal@goal)
            q=float(np.clip((self.position-self.segment_anchor)@goal/den,0.,1.)) if den>1e-16 else self.phase
            self.phase+=float(np.clip(q-self.phase,-dt/self.cfg.phase_tau_s,dt/self.cfg.phase_tau_s))
            difference=math.atan2(math.sin(self.goal_angle_rad-self.angle_rad),math.cos(self.goal_angle_rad-self.angle_rad))
            self.angle_rad+=float(np.clip(difference,-self.cfg.angular_rate_rad_s*dt,self.cfg.angular_rate_rad_s*dt))
            self.time_s=round(end,12);self._update_polygon();self.flush_due()

    def snapshot(self):
        return dict(time_s=self.time_s,x_mm=float(self.position[0]),y_mm=float(self.position[1]),
            vx_mm_s=float(self.velocity[0]),vy_mm_s=float(self.velocity[1]),speed_mm_s=float(np.linalg.norm(self.velocity)),
            active=self.active,activation_segment=self.activation_segment,response_at_s=self.response_at_s,
            world_status=self.status,shape_phase=self.phase,angle_rad=self.angle_rad,
            area_mm2=self.polygon.area,active_overlap_mm2=self.polygon.intersection(self.geometry.polygons[self.active]).area,
            **self.shape_info)
