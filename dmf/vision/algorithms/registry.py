from __future__ import annotations

from pathlib import Path
import re
from typing import Mapping

from ..contracts import VisionAlgorithm
from .background import (
    BackgroundConfig,
    BackgroundSegmenter,
    median_background_from_images,
    median_background_from_video,
)
from .threshold import ThresholdConfig, ThresholdSegmenter


AVAILABLE_ALGORITHMS = ("threshold", "background")
RESERVED_ALGORITHMS = ("hough", "houghcircle", "kcf", "unet", "deeplabv3", "deeplabv3plus")


def create_algorithm(name: str, parameters: Mapping[str, object], base_dir: Path) -> VisionAlgorithm:
    normalized = re.sub(r"[^a-z0-9]+", "", name.strip().lower())
    values = dict(parameters)
    if normalized == "threshold":
        return ThresholdSegmenter(ThresholdConfig.from_mapping(values))
    if normalized in {"background", "backgroundsubtraction"}:
        image_values = values.pop("background_images", None)
        video_value = values.pop("background_video", None)
        if bool(image_values) == bool(video_value):
            raise ValueError("background requires exactly one of background_images or background_video")
        if image_values:
            if isinstance(image_values, (str, bytes)):
                image_values = [image_values]
            background = median_background_from_images([_resolve(base_dir, value) for value in image_values])
        else:
            background = median_background_from_video(
                _resolve(base_dir, video_value),
                int(values.pop("background_sample_count", 25)),
            )
        return BackgroundSegmenter(background, BackgroundConfig.from_mapping(values))
    if normalized in RESERVED_ALGORITHMS:
        raise NotImplementedError(f"algorithm '{normalized}' is reserved for a later phase")
    raise ValueError(f"unknown algorithm '{name}'; available={', '.join(AVAILABLE_ALGORITHMS)}")


def _resolve(base_dir: Path, value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base_dir / path).resolve()
