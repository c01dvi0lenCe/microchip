"""Reviewed silhouette as an area-normalized synthetic template, not live GT."""
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Polygon


class AreaFootprint:
    def __init__(self,vertices,diameter_mm,source_sha256):
        self.vertices=np.asarray(vertices,dtype=float)
        self.diameter_mm=float(diameter_mm)
        self.source_sha256=source_sha256
        self.base=Polygon(self.vertices)
        self.area_mm2=math.pi*self.diameter_mm**2/4
        if not self.base.is_valid or abs(self.base.area-self.area_mm2)>1e-8:
            raise ValueError('invalid normalized footprint')

    @classmethod
    def from_mask(cls,path,diameter_mm):
        if not math.isfinite(diameter_mm) or diameter_mm<=0:
            raise ValueError('invalid equivalent diameter')
        raw=Path(path).read_bytes()
        mask=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_GRAYSCALE)
        if mask is None or not set(np.unique(mask)).issubset({0,255}):
            raise ValueError('binary mask required')
        contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        if len(contours)!=1 or hierarchy is None or hierarchy[0,0,2]!=-1:
            raise ValueError('exactly one contour without holes required')
        polygon=Polygon(contours[0][:,0,:])
        if not polygon.is_valid or polygon.area<=0:
            raise ValueError('invalid mask contour')
        centroid=polygon.centroid
        scale=math.sqrt((math.pi*diameter_mm**2/4)/polygon.area)
        vertices=(np.asarray(polygon.exterior.coords)[:-1]-[centroid.x,centroid.y])*scale
        return cls(vertices,diameter_mm,hashlib.sha256(raw).hexdigest())

    def polygon(self,position,stretch):
        p=np.asarray(position,dtype=float)
        if p.shape!=(2,) or not np.isfinite(p).all() or not math.isfinite(stretch) or stretch<=0:
            raise ValueError('invalid footprint transform')
        return affine_transform(self.base,[stretch,0,0,1/stretch,float(p[0]),float(p[1])])

    def snapshot(self):
        return dict(source_sha256=self.source_sha256,equivalent_diameter_mm=self.diameter_mm,
                    area_mm2=self.area_mm2,normalized_vertices_mm=self.vertices.tolist(),
                    interpretation='video_informed_synthetic_template_not_real_video_prediction')
