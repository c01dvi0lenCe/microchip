"""Nearest saved valid outline. No contour interpolation or topology repair."""
import math
import numpy as np
from shapely.affinity import translate


class SavedOutlineReplay:
    def __init__(self,phases,polygons):
        self.phases=np.asarray(phases,dtype=float)
        self.polygons=list(polygons)
        if (len(self.phases)!=len(self.polygons) or len(self.phases)<2 or
            not np.isfinite(self.phases).all() or self.phases[0]!=0. or self.phases[-1]!=1. or
            np.any(np.diff(self.phases)<=0)):
            raise ValueError('strict finite phase pool from0 to1 required')
        self.area=self.polygons[0].area
        for p in self.polygons:
            if (p.geom_type!='Polygon' or not p.is_valid or p.is_empty or p.area<=0 or
                len(p.interiors) or abs(p.area/self.area-1)>1e-8):
                raise ValueError('same-area valid saved polygons required; no repair')
        self.max_phase_error_bound=float(np.diff(self.phases).max()/2)

    def at(self,phase,position=(0.,0.)):
        q=float(phase);position=np.asarray(position,dtype=float)
        if not math.isfinite(q) or not 0<=q<=1 or position.shape!=(2,) or not np.isfinite(position).all():
            raise ValueError('finite phase in0–1 and position required; no clamping')
        right=int(np.searchsorted(self.phases,q))
        if right==0:index=0
        elif right==len(self.phases):index=right-1
        else:index=right-1 if q-self.phases[right-1]<=self.phases[right]-q else right
        selected=self.polygons[index];center=selected.centroid
        result=translate(selected,float(position[0]-center.x),float(position[1]-center.y))
        info=dict(query_phase=q,selected_phase=float(self.phases[index]),selected_index=index,
            phase_error=float(self.phases[index]-q),phase_error_bound=self.max_phase_error_bound,
            contour_interpolated=False,topology_repaired=False)
        return result,info
