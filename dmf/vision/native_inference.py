"""Opt-in, bit-exact native 512 single-tile G4 preprocessing.

The original predictor, model package and thresholds remain untouched. Only a
single native uint8 BGR tile skips the no-op letterbox/restore and tensor stack;
every other input uses the original implementation. No speed claim is implied.
"""
from contextlib import nullcontext

import numpy as np

from .g4_model import G4UNetPredictor


_MEAN = np.array([.485, .456, .406], dtype=np.float32)
_STD = np.array([.229, .224, .225], dtype=np.float32)


def native_tensor(image, torch_module=None):
    """Return contiguous float32 CHW, exactly matching frozen image_tensor.

No algebraic reassociation: uint8 BGR -> float32 RGB -> /255 -> subtract
ImageNet mean -> divide ImageNet std, with a rounding step after each operation.
Only newly allocated storage is modified; input views and source frames stay
unchanged. Torch is imported on demand if the caller does not supply it.
"""
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.shape != (512, 512, 3)):
        raise ValueError('native_tensor requires a 512x512 uint8 BGR image')
    if torch_module is None:
        import torch as torch_module
    rgb = image[:, :, ::-1].astype(np.float32)
    np.divide(rgb, np.float32(255.), out=rgb)
    np.subtract(rgb, _MEAN, out=rgb)
    np.divide(rgb, _STD, out=rgb)
    return torch_module.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1)))


class NativeTileG4Predictor(G4UNetPredictor):
    """Independent single-tile implementation; not enabled in the legacy GUI."""

    runtime_implementation = 'g4_native_single_v1'

    def __init__(self, folder, device='auto', batch_size=1):
        if type(batch_size) is not int or batch_size != 1:
            raise ValueError('native G4 requires batch_size=1')
        super().__init__(folder, device=device, batch_size=1)

    def _infer(self, images):
        if not (isinstance(images, (list, tuple)) and len(images) == 1
                and isinstance(images[0], np.ndarray)
                and images[0].dtype == np.uint8 and images[0].shape == (512, 512, 3)):
            return super()._infer(images)
        torch = self.torch
        x = native_tensor(images[0], torch).unsqueeze(0).to(self.device)
        context = torch.autocast('cuda', dtype=torch.float16) if self.device == 'cuda' else nullcontext()
        with torch.inference_mode(), context:
            output = self.model(x)
        if not torch.isfinite(output).all():
            raise ValueError('nonfinite U-Net logits')
        masks = (output.float().sigmoid() >= .5).to(torch.uint8).cpu().numpy()[:, 0] * 255
        return [masks[0]]
