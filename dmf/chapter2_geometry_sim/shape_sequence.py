"""Empirical area-normalized shape interpolation, not fluid dynamics."""
import math
import cv2
import numpy as np
from shapely import contains_xy
from shapely.affinity import affine_transform,scale,translate
from shapely.geometry import Polygon


def _one_contour(mask):
    a=np.asarray(mask)
    if a.ndim!=2 or not np.isin(a,(0,255)).all() or not a.any():
        raise ValueError('nonempty binary2D mask required')
    contours,hierarchy=cv2.findContours(a.astype(np.uint8),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if len(contours)!=1 or hierarchy is None or hierarchy[0,0,2]!=-1:
        raise ValueError('exactly one component without holes required; no topology repair')
    points=contours[0][:,0,:]
    if len(points)<3:raise ValueError('degenerate contour')
    return points


def normalize_mask(mask,direction,diameter_mm=4.):
    p=Polygon(_one_contour(mask))
    axis=np.asarray(direction,dtype=float)
    if axis.shape!=(2,) or not np.isfinite(axis).all() or np.linalg.norm(axis)<=0:
        raise ValueError('finite nonzero direction required')
    if not p.is_valid or p.area<=0 or not math.isfinite(diameter_mm) or diameter_mm<=0:
        raise ValueError('valid positive-area contour and diameter required')
    ux,uy=axis/np.linalg.norm(axis)
    # Rotation, not a reflection: the observed migration axis becomes +x.
    p=translate(p,-p.centroid.x,-p.centroid.y)
    p=affine_transform(p,[ux,uy,-uy,ux,0,0])
    factor=math.sqrt((math.pi*diameter_mm**2/4)/p.area)
    return scale(p,factor,factor,origin=(0,0))


def local_mask(polygon,pixels_per_mm=80.,half_extent_mm=5.):
    n=round(2*half_extent_mm*pixels_per_mm)
    a=np.zeros((n,n),np.uint8)
    lo=np.array([-half_extent_mm,-half_extent_mm]);bounds=np.array(polygon.bounds)
    if np.any(bounds[:2]<=lo) or np.any(bounds[2:]>=-lo):
        raise ValueError('shape outside local interpolation ROI')
    low=np.maximum(np.floor((bounds[:2]-lo)*pixels_per_mm).astype(int)-1,0)
    high=np.minimum(np.ceil((bounds[2:]-lo)*pixels_per_mm).astype(int)+1,n)
    x=lo[0]+(np.arange(low[0],high[0])+.5)/pixels_per_mm
    y=lo[1]+(np.arange(low[1],high[1])+.5)/pixels_per_mm
    a[low[1]:high[1],low[0]:high[0]]=contains_xy(polygon,x[None,:],y[:,None]).astype(np.uint8)*255
    return a


class SDFShapeSequence:
    def __init__(self,phases,polygons,pixels_per_mm=80.,half_extent_mm=5.):
        self.phases=np.asarray(phases,dtype=float);self.polygons=list(polygons)
        if (len(self.phases)!=len(polygons) or len(polygons)<2 or not np.isfinite(self.phases).all()
                or self.phases[0]!=0 or self.phases[-1]!=1 or np.any(np.diff(self.phases)<=0)):
            raise ValueError('strictly increasing0–1 phases required; no silent sorting')
        self.scale=float(pixels_per_mm);self.half=float(half_extent_mm)
        if not all(math.isfinite(v) and v>0 for v in (self.scale,self.half)):
            raise ValueError('positive interpolation raster required')
        self.area=self.polygons[0].area;self.sdf=[];self.cache={};self.diagnostics={}
        for p in self.polygons:
            if (p.geom_type!='Polygon' or not p.is_valid or p.area<=0 or len(p.interiors)
                    or abs(p.area/self.area-1)>1e-6 or p.centroid.distance(self.polygons[0].centroid)>1e-6):
                raise ValueError('same-area centered simple polygons required')
            m=local_mask(p,self.scale,self.half)>0
            inside=cv2.distanceTransform(m.astype(np.uint8),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
            outside=cv2.distanceTransform((~m).astype(np.uint8),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
            self.sdf.append((inside-outside)/self.scale)

    def polygon(self,phase,position=(0.,0.)):
        q=float(phase);position=np.asarray(position,dtype=float)
        if not math.isfinite(q) or not 0<=q<=1 or position.shape!=(2,) or not np.isfinite(position).all():
            raise ValueError('finite0–1 phase and position required')
        key=round(q,12)
        if key not in self.cache:
            exact=np.flatnonzero(np.isclose(self.phases,q,atol=1e-12,rtol=0))
            if len(exact):
                p=self.polygons[int(exact[0])];raw_area=p.area
            else:
                i=int(np.searchsorted(self.phases,q)-1)
                weight=(q-self.phases[i])/(self.phases[i+1]-self.phases[i])
                m=(((1-weight)*self.sdf[i]+weight*self.sdf[i+1])>0).astype(np.uint8)*255
                points=_one_contour(m)
                p=Polygon(-self.half+(points+.5)/self.scale)
                if not p.is_valid or p.area<=0:raise ValueError('invalid interpolated polygon')
                raw_area=p.area
                p=translate(p,-p.centroid.x,-p.centroid.y)
                factor=math.sqrt(self.area/p.area)
                p=scale(p,factor,factor,origin=(0,0))
            self.cache[key]=p
            self.diagnostics[key]=dict(phase=q,pre_normalization_area_mm2=raw_area,
                normalization_scale=math.sqrt(self.area/raw_area),post_area_mm2=p.area,
                centered_centroid_error_mm=math.hypot(p.centroid.x,p.centroid.y),
                topology_repaired=False)
        return translate(self.cache[key],float(position[0]),float(position[1]))


def shape_metrics(polygon,pixels_per_mm=80.):
    a=local_mask(polygon,pixels_per_mm)>0
    ys,xs=np.nonzero(a);columns=np.arange(xs.min(),xs.max()+1)
    widths=a[:,columns].sum(axis=0)/pixels_per_mm
    smoothed=cv2.GaussianBlur(widths.reshape(1,-1).astype(np.float64),(5,1),1)[0]
    n=len(smoothed);middle=n//2
    left=int(.15*n)+int(np.argmax(smoothed[int(.15*n):middle]))
    right=middle+int(np.argmax(smoothed[middle:int(.85*n)]))
    neck_width=neck_fraction=None
    if right-left>=.25*n:
        valley=left+int(np.argmin(smoothed[left:right+1]))
        if left<valley<right and smoothed[valley]<.9*min(smoothed[left],smoothed[right]):
            neck_width=float(smoothed[valley]);neck_fraction=float(valley/(n-1))
    x0,y0,x1,y1=polygon.bounds
    return dict(area_mm2=polygon.area,aspect_ratio=(x1-x0)/(y1-y0),
                neck_width_mm=neck_width,neck_fraction=neck_fraction,
                neck_definition='interior valley below90% of both lobe widths; peaks separated≥25% support; no neck→NA')


def width_at_fraction(polygon,fraction,pixels_per_mm=80.):
    a=local_mask(polygon,pixels_per_mm)>0
    columns=np.flatnonzero(a.any(axis=0))
    i=int(round(columns[0]+float(fraction)*(columns[-1]-columns[0])))
    return float(a[:,i].sum()/pixels_per_mm)
