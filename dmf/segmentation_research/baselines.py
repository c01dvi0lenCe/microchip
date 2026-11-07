"""Image-only fixed-ROI baselines. No labels or controller state are accepted."""
from dataclasses import asdict, dataclass
import math
import time

import cv2
import numpy as np

from dmf.vision.algorithms.common import clean_mask, result_from_mask


@dataclass(frozen=True)
class Parameters:
    blur_kernel: int = 5
    morphology_kernel: int = 3
    open_iterations: int = 1
    close_iterations: int = 2
    min_area_px: float = 40.
    reject_border_components: bool = True
    adaptive_block: int = 51
    adaptive_c: float = 5.

    def __post_init__(self):
        for name in ('blur_kernel', 'morphology_kernel', 'adaptive_block'):
            n = getattr(self, name)
            if type(n) is not int or n < (3 if name == 'adaptive_block' else 1) or n % 2 != 1:
                raise ValueError(f'{name} must be a positive odd kernel size')
        for name in ('open_iterations', 'close_iterations'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if not math.isfinite(self.min_area_px) or self.min_area_px < 0 or not math.isfinite(self.adaptive_c):
            raise ValueError('invalid threshold or area parameter')
        if type(self.reject_border_components) is not bool:
            raise ValueError('reject_border_components must be boolean')


class ThresholdBaseline:
    def __init__(self, name, parameters=None):
        if name not in {'otsu', 'adaptive'}:
            raise ValueError('baseline must be otsu or adaptive')
        self.name = name
        self.parameters = Parameters(**(parameters or {}))

    def configuration(self):
        return dict(name=self.name, parameters=asdict(self.parameters),
                    foreground='dark', component_policy='largest external contour filled',
                    input='native BGR ROI, no resizing', backend='OpenCV CPU')

    def process(self, packet):
        start = time.perf_counter()
        image, p = packet.image_bgr, self.parameters
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('expected uint8 BGR image')
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (p.blur_kernel, p.blur_kernel), 0)
        if self.name == 'otsu':
            _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        else:
            mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY_INV, p.adaptive_block, p.adaptive_c)
        mask = clean_mask(mask, p.morphology_kernel, p.open_iterations, p.close_iterations)
        if p.reject_border_components:
            _, labels = cv2.connectedComponents(mask, connectivity=8)
            edge_ids = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
            mask[np.isin(labels, edge_ids[edge_ids != 0])] = 0
        result = result_from_mask(mask, start, p.min_area_px, None)
        result.validate(image.shape)
        return result
