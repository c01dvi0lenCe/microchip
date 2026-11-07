"""Synthetic camera and Mask-only features in an explicit virtual mm raster."""
from dataclasses import dataclass
import cv2
import math
import numpy as np
from shapely import contains_xy
from shapely.affinity import translate


class Raster:
    def __init__(self,geometry,source,target,pixels_per_mm,diameter_mm):
        centers=np.array([geometry.center(source),geometry.center(target)])
        self.lower=centers.min(axis=0)-diameter_mm
        self.upper=centers.max(axis=0)+diameter_mm
        self.scale=pixels_per_mm
        self.shape=tuple(np.ceil((self.upper-self.lower)[::-1]*self.scale).astype(int))
        self.electrodes={i:self.mask(geometry.polygons[i]) for i in (source,target)}
        self.geometry=geometry

    def mask(self,polygon):
        out=np.zeros(self.shape,np.uint8)
        lo=np.floor((np.array(polygon.bounds[:2])-self.lower)*self.scale).astype(int)-1
        hi=np.ceil((np.array(polygon.bounds[2:])-self.lower)*self.scale).astype(int)+1
        x0,y0=np.maximum(lo,0);x1,y1=np.minimum(hi,np.array(self.shape[::-1]))
        if x1<=x0 or y1<=y0:return out
        xx=self.lower[0]+(np.arange(x0,x1)+.5)/self.scale
        yy=self.lower[1]+(np.arange(y0,y1)+.5)/self.scale
        out[y0:y1,x0:x1]=contains_xy(polygon,xx[None,:],yy[:,None]).astype(np.uint8)*255
        return out

    def snapshot(self):
        return dict(lower_mm=self.lower.tolist(),upper_mm=self.upper.tolist(),shape=[int(v) for v in self.shape],
                    pixels_per_mm=self.scale,pixel_convention='pixel_centers_at_lower_plus_index_plus_half')


@dataclass
class CameraFrame:
    frame_id: int
    exposure_start_s: float
    exposure_end_s: float
    available_s: float
    mask: np.ndarray
    context: object
    processed_at_s: float | None = None


class SyntheticCamera:
    def __init__(self,geometry,config):
        self.cfg=config
        self.raster=Raster(geometry,config.source,config.target,config.pixels_per_mm,config.diameter_mm)
        rng=np.random.default_rng(np.random.SeedSequence([config.seed,202]))
        self.position_errors=rng.normal(0,config.position_noise_mm,size=(int(config.duration_s*config.camera_fps),2))

    def expose(self,frame_id,t_s,polygon,context):
        error=self.position_errors[frame_id]
        observed=translate(polygon,float(error[0]),float(error[1]))
        end=t_s+self.cfg.exposure_s
        return CameraFrame(frame_id,t_s,end,end+self.cfg.processing_delay_s,self.raster.mask(observed),context)


def extract_features(frame,raster,source,target):
    mask=frame.mask>0
    if mask.shape!=raster.shape:raise ValueError('Mask/raster domain mismatch')
    ys,xs=np.nonzero(mask)
    if not len(xs):return dict(valid=False,reason='NO_MASK')
    point=raster.lower+(np.array([xs.mean(),ys.mean()])+.5)/raster.scale
    src=raster.geometry.center(source);dst=raster.geometry.center(target)
    axis=dst-src;length=float(np.linalg.norm(axis));unit=axis/length
    displacement=point-src
    progress=float(displacement@unit)
    overlap={}
    for name,eid in (('source',source),('target',target)):
        region=raster.electrodes[eid]>0
        intersection=int(np.count_nonzero(mask&region))
        overlap[f'eta_{name}']=intersection/len(xs)
        overlap[f'rho_{name}']=intersection/int(region.sum())
    return dict(valid=True,reason='',area_px=len(xs),area_mm2=len(xs)/raster.scale**2,
                x_mm=float(point[0]),y_mm=float(point[1]),distance_mm=float(np.linalg.norm(point-dst)),
                progress_mm=progress,progress_fraction=progress/length,
                lateral_mm=float(unit[0]*displacement[1]-unit[1]*displacement[0]),
                components=int(cv2.connectedComponents(mask.astype(np.uint8))[0]-1),
                touches_roi_border=bool(mask[0,:].any() or mask[-1,:].any() or mask[:,0].any() or mask[:,-1].any()),**overlap)
