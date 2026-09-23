"""Reusable simulation and offline vision interfaces for the DMF platform."""

from .calibration import ArrayGridCalibration, Roi
from .contracts import (
    DropletFeatures,
    DropletState,
    FramePacket,
    FrameRecord,
    VisionAlgorithm,
    VisionResult,
)
from .electrode_map import ElectrodeMap, ElectrodeRegion
from .features import DropletFeatureExtractor
from .simulation import DropletDetector, SimulatedCamera, detection_in_cell

__all__ = [
    "ArrayGridCalibration",
    "DropletDetector",
    "DropletFeatureExtractor",
    "DropletFeatures",
    "DropletState",
    "ElectrodeMap",
    "ElectrodeRegion",
    "FramePacket",
    "FrameRecord",
    "Roi",
    "SimulatedCamera",
    "VisionAlgorithm",
    "VisionResult",
    "detection_in_cell",
]
