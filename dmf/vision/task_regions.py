"""Immutable observation domains; accepted geometry never arms electrode output."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType

import cv2
import numpy as np

from .design_registration import file_hash, load_design_map
from .image_io import read_image
from .registration_audit import validate_final_binding, homogeneous
from .whole_chip_geometry import plan_tiles


@dataclass(frozen=True)
class TaskRegion:
    region_id: str
    roi: tuple
    epoch: int = 0
    kind: str = 'pixel_observation'
    source_electrode: int | None = None
    target_electrode: int | None = None
    binding_sha256: str = ''
    bound_acquisition_id: str = ''
    bound_image_size: tuple | None = None

    def __post_init__(self):
        if not isinstance(self.region_id,str) or not re.fullmatch(r'[\w-]{1,64}',self.region_id):
            raise ValueError('region_id must be a safe nonempty identifier')
        object.__setattr__(self,'roi',tuple(self.roi))
        if (len(self.roi)!=4 or any(type(x) is not int for x in self.roi)
                or min(self.roi[:2])<0 or min(self.roi[2:])<=0):
            raise ValueError('ROI must be nonnegative x/y and positive integer width/height')
        if type(self.epoch) is not int or self.epoch<0:raise ValueError('invalid observation epoch')
        if self.kind=='pixel_observation':
            if (self.source_electrode is not None or self.target_electrode is not None or self.binding_sha256
                    or self.bound_acquisition_id or self.bound_image_size is not None):
                raise ValueError('pixel observation has no electrode binding')
        elif self.kind=='calibrated_task':
            if any(type(eid) is not int or not 1<=eid<=400 for eid in
                   (self.source_electrode,self.target_electrode)):
                raise ValueError('current calibrated transport supports core electrodes only')
            if not re.fullmatch('[0-9a-f]{64}',self.binding_sha256):raise ValueError('binding digest required')
            if not self.bound_acquisition_id or self.bound_image_size is None:raise ValueError('bound acquisition and full image size required')
            object.__setattr__(self,'bound_image_size',tuple(self.bound_image_size))
        else:raise ValueError('unknown region kind')

    @property
    def control_eligible(self):
        # This interface is deliberately sensing-only, even with valid H.
        return False

    def validate_shape(self,frame_shape):
        if self.bound_image_size is not None and tuple(frame_shape)!=(self.bound_image_size[1],self.bound_image_size[0],3):
            raise ValueError('full image differs from the calibrated domain')
        plan_tiles(frame_shape,self.roi)

    def validate_packet(self,packet):
        self.validate_shape(packet.image_bgr.shape)
        if self.kind=='calibrated_task' and packet.video_id!=self.bound_acquisition_id:
            raise ValueError('capture is not bound to this calibrated region')


@dataclass(frozen=True)
class TaskBinding:
    polygons_px: object
    image_size: tuple
    acquisition_id: str
    manifest_sha256: str

    @classmethod
    def load(cls,design_path,manifest_path,reference_path,current_conditions):
        design_path,manifest_path,reference_path=map(Path,(design_path,manifest_path,reference_path))
        manifest=json.loads(manifest_path.read_text(encoding='utf8'))
        validate_final_binding(manifest,current_conditions,file_hash(reference_path),file_hash(design_path))
        image=read_image(reference_path,cv2.IMREAD_COLOR)
        if image is None:raise ValueError('reference image unreadable')
        size=(image.shape[1],image.shape[0])
        if tuple(current_conditions['resolution'])!=size:raise ValueError('reference resolution mismatch')
        design=load_design_map(design_path,manifest['design_map_sha256'])
        inverse=np.linalg.inv(np.asarray(manifest['image_to_design_mm'],float))
        polygons={e['control_id']:tuple(map(tuple,homogeneous(e['polygon_map_mm'],inverse)))
                  for e in design['electrodes']}
        return cls(MappingProxyType(polygons),size,str(current_conditions['acquisition_id']),file_hash(manifest_path))

    def region(self,region_id,source,target,*,epoch,frame_shape,acquisition_id,margin_px=64):
        if tuple(frame_shape)!=(self.image_size[1],self.image_size[0],3):raise ValueError('bound image size mismatch')
        if acquisition_id!=self.acquisition_id:raise ValueError('capture is not bound to this calibration')
        if any(type(eid) is not int or not 1<=eid<=400 for eid in (source,target)):
            raise ValueError('peripheral transport neighborhoods require separate validation')
        if type(margin_px) is not int or margin_px<0:raise ValueError('margin must be nonnegative integer pixels')
        ids={source,target}
        for eid in (source,target):
            row,col=divmod(eid-1,20)
            for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)):
                if 0<=row+dr<20 and 0<=col+dc<20:ids.add((row+dr)*20+col+dc+1)
        points=np.concatenate([np.asarray(self.polygons_px[eid],float) for eid in sorted(ids)])
        low=np.floor(points.min(axis=0)).astype(int)-margin_px
        high=np.ceil(points.max(axis=0)).astype(int)+margin_px+1
        x,y=map(int,low);width,height=map(int,high-low)
        result=TaskRegion(region_id,(x,y,width,height),epoch,'calibrated_task',source,target,self.manifest_sha256,
                          self.acquisition_id,self.image_size)
        result.validate_shape(frame_shape)
        return result
