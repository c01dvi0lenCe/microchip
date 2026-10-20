from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from .electrode_map import ElectrodeMap
from .image_io import read_image, write_image

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def render_electrode_overlay(
    image_path: Path,
    electrode_map: ElectrodeMap,
    output_path: Path,
    show_row_col: bool = False,
    zoom_electrodes: Iterable[int] = (),
    zoom_dir: Path | None = None,
    crop_padding_px: int = 24,
) -> list[Path]:
    if cv2 is None:
        raise RuntimeError("opencv-python is required to render the electrode map")
    image = read_image(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"could not read chip image: {image_path}")
    overlay = image.copy()
    scale = max(0.28, min(0.7, min(image.shape[:2]) / 1200.0))
    for region in electrode_map:
        polygon = np.rint(np.asarray(region.polygon_px)).astype(np.int32)
        color = (60, 200, 60) if region.geometry_source == "calibrated" else (30, 170, 255)
        cv2.polylines(overlay, [polygon], True, color, 1, cv2.LINE_AA)
        center = tuple(np.rint(region.center_px).astype(int))
        cv2.circle(overlay, center, 2, (255, 80, 40), -1, cv2.LINE_AA)
        label = str(region.electrode_id)
        if show_row_col:
            label += f" ({region.row},{region.col})"
        cv2.putText(overlay, label, (center[0] + 2, center[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
    if not write_image(output_path, overlay):
        raise RuntimeError(f"could not write overlay: {output_path}")

    outputs = [output_path]
    selected = [int(value) for value in zoom_electrodes]
    if selected:
        target_dir = zoom_dir or output_path.with_name(f"{output_path.stem}_zooms")
        target_dir.mkdir(parents=True, exist_ok=True)
        height, width = overlay.shape[:2]
        for electrode_id in selected:
            region = electrode_map[electrode_id]
            polygon = np.asarray(region.polygon_px)
            x0 = max(0, int(np.floor(polygon[:, 0].min())) - crop_padding_px)
            y0 = max(0, int(np.floor(polygon[:, 1].min())) - crop_padding_px)
            x1 = min(width, int(np.ceil(polygon[:, 0].max())) + crop_padding_px + 1)
            y1 = min(height, int(np.ceil(polygon[:, 1].max())) + crop_padding_px + 1)
            if x1 <= x0 or y1 <= y0:
                raise ValueError(f"electrode {electrode_id} polygon is outside the chip image")
            crop_path = target_dir / f"electrode_{electrode_id:03d}.png"
            if not write_image(crop_path, overlay[y0:y1, x0:x1]):
                raise RuntimeError(f"could not write electrode crop: {crop_path}")
            outputs.append(crop_path)
    return outputs
