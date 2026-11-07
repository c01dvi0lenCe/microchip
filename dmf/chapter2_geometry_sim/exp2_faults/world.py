"""Synthetic permanent stall; baseline dynamics remain in the frozen World."""
import math
import numpy as np
from ..exp2.world import CausalWorld


class StalledWorld(CausalWorld):
    def __init__(self,geometry,pool,config,stall_at_s=2.):
        if not math.isfinite(stall_at_s) or stall_at_s<0:
            raise ValueError('finite nonnegative stall boundary required')
        self.stall_at_s=stall_at_s
        self.stalled=False
        self.interventions=[]
        super().__init__(geometry,pool,config)

    def advance(self,to_s):
        if not math.isfinite(to_s) or to_s<self.time_s-1e-10:
            raise ValueError('nonmonotone simulation clock')
        if not self.stalled:
            super().advance(min(to_s,self.stall_at_s))
            if to_s<self.stall_at_s-1e-10:
                return
            before=self.snapshot()
            self.velocity[:]=0.
            self.status='synthetic_permanent_stall'
            self.stalled=True
            self.interventions.append(dict(operation='world_stall',time_s=self.time_s,
                pinned_x_mm=float(self.position[0]),pinned_y_mm=float(self.position[1]),
                prior_vx_mm_s=before['vx_mm_s'],prior_vy_mm_s=before['vy_mm_s'],
                resulting_speed_mm_s=0.,phase_pinned=False,angle_pinned=False))
        self.flush_due()
        while self.time_s<to_s-1e-10:
            end=min(to_s,self.time_s+self.cfg.dt_s)
            if self.pending is not None:
                end=min(end,self.pending['applied_s'])
            if self.time_s<self.response_at_s<end:
                end=self.response_at_s
            dt=end-self.time_s
            # Only translation/velocity are overridden. These two shape-state
            # equations are the unchanged baseline equations at the pinned
            # physical position, including rate-limited direction after a tx.
            goal=self.geometry.center(self.active)-self.segment_anchor
            den=float(goal@goal)
            q=float(np.clip((self.position-self.segment_anchor)@goal/den,0.,1.)) if den>1e-16 else self.phase
            self.phase+=float(np.clip(q-self.phase,-dt/self.cfg.phase_tau_s,dt/self.cfg.phase_tau_s))
            difference=math.atan2(math.sin(self.goal_angle_rad-self.angle_rad),math.cos(self.goal_angle_rad-self.angle_rad))
            self.angle_rad+=float(np.clip(difference,-self.cfg.angular_rate_rad_s*dt,self.cfg.angular_rate_rad_s*dt))
            self.time_s=round(end,12)
            self._update_polygon()
            self.flush_due()
        # Transactions still change active/response/segments, never the pin.
        self.status='synthetic_permanent_stall'

