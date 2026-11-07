"""One active electrode, overlap-gated finite motion, area-preserving shape."""
import math
import numpy as np


class DeformingWorld:
    def __init__(self,geometry,shape,config):
        self.geometry,self.shape,self.cfg=geometry,shape,config
        self.position=geometry.center(config.source)
        self.source_position=self.position.copy()
        self.active=config.source
        self.time_s=0.
        self.stretch=1.
        self.speed_mm_s=0.
        self.response_at_s=0.
        self.activation_segment=0
        self.pending=None
        self.events=[]
        self.status='held_at_source'
        self.motion_start=self.position.copy()
        self.motion_elapsed_s=0.
        self.motion_duration_s=0.

    @property
    def polygon(self):
        return self.shape.polygon(self.position,self.stretch)

    def request(self,target):
        if self.pending is not None:raise ValueError('pending transaction')
        if target not in self.geometry.polygons:raise ValueError('unknown target')
        self.pending=(target,self.time_s+self.cfg.applied_delay_s)
        self.events.append(dict(time_s=self.time_s,event='request',target=target,action='ActivateTarget'))

    def _apply_due(self):
        if self.pending is not None and self.pending[1]<=self.time_s+1e-10:
            target,time=self.pending
            if target!=self.active:
                self.active=target
                self.activation_segment+=1
                self.response_at_s=time+self.cfg.response_delay_s
                self.motion_start=self.position.copy()
                self.motion_elapsed_s=0.
                self.motion_duration_s=1.875*float(np.linalg.norm(self.geometry.center(target)-self.position))/self.cfg.speed_mm_s
            self.events.append(dict(time_s=time,event='simulated_applied',target=target,action='Hold'))
            self.pending=None

    def advance(self,to_s):
        if not math.isfinite(to_s) or to_s<self.time_s-1e-10:
            raise ValueError('nonmonotone world time')
        self._apply_due()
        while self.time_s<to_s-1e-10:
            end=min(to_s,self.time_s+self.cfg.dt_s)
            if self.pending is not None and self.time_s<self.pending[1]<end:
                end=self.pending[1]
            if self.time_s<self.response_at_s<end:
                end=self.response_at_s
            dt=end-self.time_s
            goal=self.geometry.center(self.active)
            delta=goal-self.position
            distance=float(np.linalg.norm(delta))
            overlap=self.polygon.intersection(self.geometry.polygons[self.active]).area
            old=self.position.copy()
            if distance<=1e-9:
                self.status='held_at_source' if self.active==self.cfg.source else 'at_target_center'
            elif self.time_s<self.response_at_s-1e-10:
                self.status='response_delay'
            elif overlap<=1e-8:
                self.status='blocked_no_overlap'
            else:
                self.motion_elapsed_s+=dt
                u=min(1.,self.motion_elapsed_s/self.motion_duration_s)
                q=10*u**3-15*u**4+6*u**5
                self.position=self.motion_start+(goal-self.motion_start)*q
                self.status='moving' if u<1-1e-10 else 'at_target_center'
            self.speed_mm_s=float(np.linalg.norm(self.position-old)/dt)
            length=float(np.linalg.norm(goal-self.source_position))
            if self.active!=self.cfg.source and length>0 and overlap>1e-8 and end>self.response_at_s:
                direction=(goal-self.source_position)/length
                q=float(np.clip((self.position-self.source_position)@direction/length,0,1))
                desired=1+(self.cfg.max_stretch-1)*math.sin(math.pi*q)
            else:
                desired=1.
            self.stretch+=(desired-self.stretch)*(1-math.exp(-dt/self.cfg.shape_tau_s))
            self.time_s=end
            self._apply_due()

    def snapshot(self):
        polygon=self.polygon
        return dict(time_s=self.time_s,x_mm=float(self.position[0]),y_mm=float(self.position[1]),
                    speed_mm_s=self.speed_mm_s,stretch=self.stretch,area_mm2=polygon.area,
                    active=self.active,activation_segment=self.activation_segment,
                    response_at_s=self.response_at_s,active_overlap_mm2=polygon.intersection(self.geometry.polygons[self.active]).area,
                    world_status=self.status,polygon_mm=list(map(list,polygon.exterior.coords)))
