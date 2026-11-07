"""Portable frozen G4 U-Net inference. Optional Torch loads only on demand."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path

import numpy as np
from .image_io import read_image
from dmf.segmentation_research.semantic_baselines import prepare_image, restore_mask


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def package_contract():
    return dict(schema='dmf_g4_unet_inference_v1',architecture='Unet',encoder='resnet34',
        encoder_depth=5,in_channels=3,classes=1,activation=None,input_hw=[512,512],
        channel_order='RGB',mean=[.485,.456,.406],std=[.229,.224,.225],threshold=.5,
        output='logits',padding='white_letterbox',restore='threshold_then_nearest',
        postprocessing='none',training_performed=False)


def load_package_manifest(folder):
    folder=Path(folder).resolve()
    meta=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    for key,value in package_contract().items():
        if meta.get(key)!=value: raise ValueError(f'G4 contract mismatch: {key}')
    name=meta.get('weights_file','')
    path=(folder/name).resolve()
    if not name or Path(name).name!=name or not path.is_relative_to(folder):
        raise ValueError('unsafe weights path')
    if file_sha256(path)!=meta.get('weights_sha256'): raise ValueError('weights hash mismatch')
    return meta


def export_g4_unet(run,output):
    """Trusted local checkpoint -> CPU tensors only, never optimizer/RNG."""
    import torch
    run=Path(run); output=Path(output)
    if output.exists(): raise FileExistsError('model package already exists')
    checkpoint_path=run/'unet/best.pt'; protocol=run/'frozen_protocol.json'
    training=json.loads((run/'unet/training_manifest.json').read_text(encoding='utf-8'))
    expected=training['best_checkpoint_sha256']
    if file_sha256(checkpoint_path)!=expected: raise ValueError('source checkpoint hash mismatch')
    # weights_only=False is limited to the user's hash-verified training file.
    checkpoint=torch.load(checkpoint_path,map_location='cpu',weights_only=False)
    if checkpoint['config_sha256']!=file_sha256(protocol): raise ValueError('source protocol hash mismatch')
    cfg=json.loads(protocol.read_text(encoding='utf-8'))
    if cfg['threshold']!=.5: raise ValueError('unexpected frozen threshold')
    state={k:v.detach().cpu().clone() for k,v in checkpoint['model_state'].items()}
    output.mkdir(parents=True)
    torch.save(state,output/'unet_state.pt')
    meta=package_contract()
    meta.update(weights_file='unet_state.pt',weights_sha256=file_sha256(output/'unet_state.pt'),
        source_checkpoint_sha256=expected,source_protocol_sha256=file_sha256(protocol),
        source_epoch=checkpoint['epoch'],torch_version=torch.__version__,
        source_evaluation_scope='same_day_internal_development_not_independent_test')
    (output/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    if file_sha256(checkpoint_path)!=expected: raise RuntimeError('source checkpoint changed')
    return meta


class G4UNetPredictor:
    def __init__(self,folder,device='auto',batch_size=4):
        self.folder=Path(folder); self.manifest=load_package_manifest(self.folder)
        try:
            import torch
            import segmentation_models_pytorch as smp
            from dmf.segmentation_research.deep_training import image_tensor
        except ImportError as exc:
            raise RuntimeError('视觉依赖未安装，请使用独立视觉环境启动上位机') from exc
        if device not in ('auto','cpu','cuda'): raise ValueError('device must be auto/cpu/cuda')
        self.torch=torch; self.image_tensor=image_tensor
        self.device='cuda' if device=='auto' and torch.cuda.is_available() else 'cpu' if device=='auto' else device
        if self.device=='cuda' and not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable')
        torch.set_num_threads(4)
        torch.backends.cudnn.benchmark=False; torch.backends.cudnn.deterministic=True
        self.model=smp.Unet(encoder_name='resnet34',encoder_depth=5,encoder_weights=None,
                            in_channels=3,classes=1,activation=None)
        state=torch.load(self.folder/self.manifest['weights_file'],map_location='cpu',weights_only=True)
        self.model.load_state_dict(state,strict=True); self.model.to(self.device).eval()
        self.batch_size=4 if self.device=='cuda' and batch_size>=4 else 1
        self.batch_parity_checked=self.batch_size==1
        self.batch_parity_different_pixels=0
        self.last_error=''

    def _infer(self,images):
        torch=self.torch; inputs=[]; metas=[]
        for image in images:
            prepared,meta=prepare_image(image); metas.append(meta)
            inputs.append(self.image_tensor(prepared[:,:,::-1].astype(np.float32)/255.))
        x=torch.stack(inputs).to(self.device)
        context=torch.autocast('cuda',dtype=torch.float16) if self.device=='cuda' else nullcontext()
        with torch.inference_mode(),context:
            output=self.model(x)
        if not torch.isfinite(output).all(): raise ValueError('nonfinite U-Net logits')
        masks=(output.float().sigmoid()>=.5).to(torch.uint8).cpu().numpy()[:,0]*255
        return [restore_mask(mask,meta) for mask,meta in zip(masks,metas)]

    def predict_batch(self,images):
        images=list(images)
        if not images: return []
        if self.batch_size==1: return [self._infer([image])[0] for image in images]
        output=[]
        first=0
        while first<len(images):
            chunk=images[first:first+self.batch_size]
            try:
                values=self._infer(chunk)
                if not self.batch_parity_checked and len(chunk)>1:
                    single=[self._infer([im])[0] for im in chunk]
                    different=sum(int(np.count_nonzero(a!=b)) for a,b in zip(values,single))
                    self.batch_parity_different_pixels+=different
                    self.batch_parity_checked=True
                    if different:
                        self.batch_size=1
                        values=single
                output.extend(values)
                first+=len(chunk)
            except self.torch.cuda.OutOfMemoryError:
                self.batch_size=1; self.last_error='CUDA_OOM_batch_reduced_frame_rejected'
                self.torch.cuda.empty_cache()
                raise RuntimeError(self.last_error) from None
        return output

    def audit_batch_equivalence(self,images):
        """Acceptance audit: any observed mismatch locks batch1 for session."""
        images=list(images); differing=0
        for first in range(0,len(images),4):
            chunk=images[first:first+4]
            batch=self._infer(chunk)
            single=[self._infer([im])[0] for im in chunk]
            differing+=sum(int(np.count_nonzero(a!=b)) for a,b in zip(batch,single))
        if differing: self.batch_size=1
        self.batch_parity_different_pixels+=differing; self.batch_parity_checked=True
        return dict(samples=len(images),different_pixels=differing,selected_batch_size=self.batch_size)
