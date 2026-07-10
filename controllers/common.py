"""Shared controller dependencies and UI timing constants."""

import csv
import json
import math
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk
import serial
import serial.tools.list_ports

from controllers.hardware_controller import HardwareProtocol
from dmf import (
    AStarPlanner,
    BOARD_FRAME_MM,
    CORE_CELLS,
    CORNER_RESERVOIRS,
    DropletDetector,
    ELECTRODE_PITCH_MM,
    GRID_COLS,
    GRID_ROWS,
    INITIAL_DROPLET_CAPACITY,
    LAYOUT_CELLS,
    MultiDropletAssignment,
    RESERVOIR_CELLS,
    RESERVOIR_CONNECTIONS,
    RESERVOIR_DROPLET_CAPACITY,
    SIDE_RESERVOIR_LARGE,
    SIDE_RESERVOIR_SMALL,
    SimulatedCamera,
    SimulatedDroplet,
    build_multi_droplet_assignments,
    cell_center_mm,
    cell_from_electrode_id,
    detection_in_cell,
    electrode_id,
    grid_polyline_cells,
    is_reservoir_cell,
    schedule_multi_paths,
)
from simulation.metrics import OperationMetrics, StepEvent
from simulation.profiles import MotionProfile, VisionNoiseProfile


try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow < 10 compatibility.
    RESAMPLE_FILTER = Image.LANCZOS

CAMERA_PREVIEW_MAX_PX = 520
AUTO_LOOP_INTERVAL_MS = 70
CAMERA_DISPLAY_INTERVAL_S = 0.08
MATRIX_DISPLAY_INTERVAL_S = 0.12
MAX_CANVAS_PATH_ARROWS = 80
