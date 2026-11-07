"""Read-only adapter around the existing complete 420-region electrode map."""
from pathlib import Path

import cv2
import numpy as np

from dmf.vision.calibration import ArrayGridCalibration
from dmf.vision.config import load_electrode_map
from dmf.vision.electrode_map import ElectrodeMap, polygon_centroid


class SimulationMap:
    def __init__(self, config):
        if config.map_path:
            original = load_electrode_map(Path(config.map_path))
            origin = 'user_supplied_map_not_independently_verified'
        else:
            original = ElectrodeMap.from_calibration(ArrayGridCalibration(
                ((0., 0.), (20., 0.), (20., 20.), (0., 20.)), pitch_mm=1.))
            origin = 'example_420_template_not_measured'
        corners = np.asarray(original.calibration.corners_px, np.float32)
        if not np.isfinite(corners).all() or not cv2.isContourConvex(corners) or abs(cv2.contourArea(corners)) < 1e-6:
            raise ValueError('degenerate or non-convex map calibration')
        self.polygons = {}
        self.sources = {}
        for region in original:
            # Normalize to pitch. Overrides are mapped from actual image polygons,
            # not the legacy region.polygon_mm template field.
            points = []
            for point in region.polygon_px:
                row, col = original.calibration.pixel_to_grid_position(point)
                points.append((col, row))
            p = np.asarray(points, float)
            if not np.isfinite(p).all() or abs(cv2.contourArea(p.astype(np.float32))) < 1e-7:
                raise ValueError(f'invalid polygon {region.electrode_id}')
            self.polygons[region.electrode_id] = p
            self.sources[region.electrode_id] = region.geometry_source
        self.metadata = dict(mode='simulation', origin=origin, coordinate_unit='pitch',
                             measured_geometry=False, electrode_count=420,
                             supplied_map=str(config.map_path),
                             calibrated_override_count=sum(v == 'calibrated' for v in self.sources.values()))
        self.centers = {i: np.asarray(polygon_centroid(tuple(map(tuple, p)))) for i, p in self.polygons.items()}
        route_points = np.array([self.center(i) for i in config.route])
        self.lower = route_points.min(axis=0) - 1.2
        self.upper = route_points.max(axis=0) + 1.2
        self.scale = config.pixels_per_pitch
        self.shape = tuple(np.ceil((self.upper-self.lower)[::-1]*self.scale).astype(int))
        self.masks = {}
        for i in config.route:
            mask = np.zeros(self.shape, np.uint8)
            cv2.fillPoly(mask, [self.to_pixel(self.polygons[i]).astype(np.int32)], 255)
            self.masks[i] = mask

    def center(self, electrode):
        return self.centers[electrode].copy()

    def to_pixel(self, points):
        return (np.asarray(points)-self.lower)*self.scale

    def to_world(self, point):
        return np.asarray(point)/self.scale + self.lower

    def snapshot(self):
        return dict(metadata=self.metadata, polygons={str(i): p.tolist() for i, p in self.polygons.items()})
