"""Inference adapter for an existing exported binary U-Net; no training/network changes."""
from pathlib import Path
import time
import cv2
import numpy as np
from dmf.vision.contracts import VisionResult
from dmf.vision.algorithms import create_algorithm


class UNetSegmenter:
    name='unet'

    def __init__(self,config):
        self.config=config;path=Path(config['model_path'])
        if not path.is_file():raise FileNotFoundError(f'U-Net export not found: {path}')
        self.backend=config.get('backend','onnx')
        self.size=tuple(config.get('input_size',[256,256])) # H,W
        if len(self.size)!=2 or any(type(x) is not int or x<=0 for x in self.size):raise ValueError('input_size must be [height,width]')
        self.mean=np.asarray(config.get('mean',[0,0,0]),np.float32).reshape(1,1,3)
        self.std=np.asarray(config.get('std',[1,1,1]),np.float32).reshape(1,1,3)
        if not np.isfinite(self.mean).all() or not np.isfinite(self.std).all() or (self.std<=0).any():raise ValueError('invalid normalization')
        self.threshold=float(config.get('threshold',.5))
        if not 0<self.threshold<1:raise ValueError('segmentation threshold must be between 0 and 1')
        if config.get('output','logits') not in {'logits','probabilities'}:raise ValueError('output must be logits or probabilities')
        if self.backend=='onnx':
            import onnxruntime as ort
            self.model=ort.InferenceSession(str(path),providers=['CPUExecutionProvider'])
            self.input_name=self.model.get_inputs()[0].name
        elif self.backend=='torchscript':
            import torch
            self.torch=torch;self.model=torch.jit.load(str(path),map_location='cpu').eval()
        else:raise ValueError('U-Net backend must be onnx or torchscript')

    def process(self,packet):
        start=time.perf_counter();frame=packet.image_bgr
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        rgb=cv2.resize(rgb,(self.size[1],self.size[0])).astype(np.float32)/255.
        x=((rgb-self.mean)/self.std).transpose(2,0,1)[None].copy()
        if self.backend=='onnx':output=self.model.run(None,{self.input_name:x})[0]
        else:
            with self.torch.inference_mode():output=self.model(self.torch.from_numpy(x))
            if isinstance(output,dict):output=output[self.config.get('output_key','out')]
            if isinstance(output,(tuple,list)):output=output[0]
            output=output.detach().cpu().numpy()
        output=np.asarray(output)
        if output.ndim!=4 or output.shape[:2]!=(1,1):raise ValueError('binary U-Net output must be NCHW [1,1,H,W]')
        p=output[0,0]
        if not np.isfinite(p).all():raise ValueError('non-finite U-Net output')
        if self.config.get('output','logits')=='logits':p=1/(1+np.exp(-np.clip(p,-80,80)))
        elif p.min()<0 or p.max()>1:raise ValueError('probabilities outside [0,1]')
        p=cv2.resize(p,(frame.shape[1],frame.shape[0]),interpolation=cv2.INTER_LINEAR)
        mask=(p>=self.threshold).astype(np.uint8)*255;area=int(np.count_nonzero(mask))
        m=cv2.moments(mask,binaryImage=True)
        center=(m['m10']/m['m00'],m['m01']/m['m00']) if area else None
        confidence=float(p[mask>0].mean()) if area else 0.
        return VisionResult(mask,center,float(area),confidence,(time.perf_counter()-start)*1000,bool(area),'' if area else 'NO_DROPLET')


def build_segmenter(config):
    seg=config['segmentation']
    if seg['name']=='unet':return UNetSegmenter(seg)
    if config['mode']=='offline' and config.get('synthetic_test_only') is True:
        return create_algorithm('threshold',seg.get('parameters',{}),Path(config['config_path']).parent)
    raise ValueError('real experimental perception requires U-Net')
