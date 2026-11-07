"""Synthetic masks, exposure timing and causal spatial/temporal measurements."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SyntheticFrame:
    frame_id: int
    exposure_start_s: float
    exposure_end_s: float
    available_s: float
    mask: np.ndarray | None
    dropped: bool = False


class SyntheticCamera:
    def __init__(self, config, geometry, seed, scenario='normal'):
        self.cfg, self.map, self.scenario = config, geometry, scenario
        rng = np.random.default_rng(np.random.SeedSequence([seed, 202]))
        n = int(config.max_time_s*config.camera_fps)+1000
        self.errors = rng.normal(size=(n, 3))
        self.uniform = rng.random((n, 2))

    def expose(self, frame_id, exposure_start_s, position):
        cfg = self.cfg
        error, uniform = self.errors[frame_id], self.uniform[frame_id]
        drop = cfg.drop_probability
        if self.scenario == 'dropout':
            drop = max(drop, .35)
        burst = self.scenario == 'dropout' and .8 < exposure_start_s < 1.4
        dropped = bool(uniform[0] < drop or burst)
        noise = max(cfg.position_noise, .085) if self.scenario == 'jitter' else cfg.position_noise
        center = self.map.to_pixel(np.asarray(position) + error[:2]*noise)
        radius = max(.06, cfg.mask_radius + error[2]*cfg.mask_radius_noise)
        mask = None
        if not dropped:
            mask = np.zeros(self.map.shape, np.uint8)
            cv2.circle(mask, tuple(np.rint(center).astype(int)), max(1, int(round(radius*self.map.scale))), 255, -1)
        end = exposure_start_s + cfg.exposure_s
        return SyntheticFrame(frame_id, exposure_start_s, end,
                              end+cfg.processing_delay_s+uniform[1]*cfg.processing_jitter_s,
                              mask, dropped)


class FeatureExtractor:
    def __init__(self, config, geometry):
        self.cfg, self.map = config, geometry
        self.previous = None

    def reset(self):
        self.previous = None

    def extract(self, frame, source, target):
        if frame.mask is None or np.count_nonzero(frame.mask) < 10:
            self.previous = None
            return dict(valid=False, reason='NO_MASK')
        mask = frame.mask > 0
        ys, xs = np.nonzero(mask)
        point = self.map.to_world((xs.mean(), ys.mean()))
        area = int(mask.sum())
        direction = self.map.center(target)-self.map.center(source)
        length = np.linalg.norm(direction)
        u = direction/length
        displacement = point-self.map.center(source)
        p = float(displacement@u)
        lateral = float(u[0]*displacement[1]-u[1]*displacement[0])
        velocity = parallel = None
        t = frame.exposure_end_s
        if self.previous:
            old_t, old_p = self.previous
            dt = t-old_t
            if dt <= 0:
                return dict(valid=False, reason='NON_MONOTONE_EXPOSURE')
            if dt <= self.cfg.max_frame_gap_s:
                velocity = float(np.linalg.norm(point-old_p)/dt)
                parallel = float((point-old_p)@u/dt)
        self.previous = t, point.copy()
        overlap = {}
        for label, electrode in (('source', source), ('target', target)):
            region = self.map.masks[electrode] > 0
            intersection = int(np.count_nonzero(mask & region))
            overlap.update({f'eta_{label}': intersection/area,
                            f'rho_{label}': intersection/int(region.sum()),
                            f'intersection_{label}_px': intersection})
        return dict(valid=True, reason='', x=float(point[0]), y=float(point[1]), area_px=area,
                    distance=float(np.linalg.norm(point-self.map.center(target))),
                    progress=p/length, progress_pitch=p, lateral=lateral,
                    velocity=velocity, velocity_parallel=parallel, **overlap)
