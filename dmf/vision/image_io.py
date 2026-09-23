from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def read_image(path: Path, flags: int) -> np.ndarray | None:
    """Read an image without relying on OpenCV's Windows Unicode path handling."""
    if cv2 is None:
        raise RuntimeError("opencv-python is required for image I/O")
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if encoded.size == 0:
        return None
    return cv2.imdecode(encoded, flags)


def write_image(path: Path, image: np.ndarray) -> bool:
    """Write an image through imencode so non-ASCII Windows paths are supported."""
    if cv2 is None:
        raise RuntimeError("opencv-python is required for image I/O")
    suffix = path.suffix or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded.tofile(path)
    except OSError:
        return False
    return True
