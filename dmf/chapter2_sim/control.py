"""Pure observation-based recognition and bounded local control (no true state)."""
from collections import deque

import numpy as np


class StableWindow:
    def __init__(self, config):
        self.cfg = config
        self.samples = deque()
        self.last_frame = -1
        self.last_time = None

    @property
    def count(self):
        return len(self.samples)

    def reset(self):
        self.samples.clear()
        self.last_frame = -1
        self.last_time = None

    def observe(self, frame_id, t, position, eligible):
        if frame_id <= self.last_frame or (self.last_time is not None and t <= self.last_time):
            return False
        if self.last_time is not None and (t-self.last_time > self.cfg.max_frame_gap_s+1e-9 or frame_id != self.last_frame+1):
            self.samples.clear()
        self.last_frame, self.last_time = frame_id, t
        if not eligible:
            self.samples.clear()
            return False
        self.samples.append((t, position))
        # Sliding stable suffix: movement before settling must not poison the
        # window forever; retain enough recent points for duration and count.
        while len(self.samples) > self.cfg.arrival_frames and self.samples[-1][0]-self.samples[1][0] >= self.cfg.stable_duration_s:
            self.samples.popleft()
        points = np.asarray([p for _, p in self.samples])
        span = np.linalg.norm(points.max(axis=0)-points.min(axis=0))
        if span > self.cfg.stable_span:
            while len(self.samples) > 1:
                self.samples.popleft()
                points = np.asarray([p for _, p in self.samples])
                if np.linalg.norm(points.max(axis=0)-points.min(axis=0)) <= self.cfg.stable_span:
                    break
        return (len(self.samples) >= self.cfg.arrival_frames and
                t-self.samples[0][0] >= self.cfg.stable_duration_s-1e-9)


class Recognizer:
    def __init__(self, config):
        self.cfg = config
        self.window = StableWindow(config)
        self.deviations = 0

    def reset(self):
        self.window.reset()
        self.deviations = 0
        self.last_exposure = None
        self.last_frame = None

    def observe(self, frame, f):
        cfg = self.cfg
        t = frame.exposure_end_s
        if getattr(self, 'last_exposure', None) is not None and (t-self.last_exposure > cfg.max_frame_gap_s+1e-9
                                                              or frame.frame_id != self.last_frame+1):
            self.deviations = 0
        self.last_exposure = t
        self.last_frame = frame.frame_id
        if not f.get('valid'):
            self.window.observe(frame.frame_id, frame.exposure_end_s, (0., 0.), False)
            self.deviations = 0
            return 'Unknown', False
        spatial = -.45 <= f['progress'] <= 1.45 and abs(f['lateral']) <= cfg.corridor_width
        if not spatial:
            self.deviations += 1
            self.window.observe(frame.frame_id, frame.exposure_end_s, (f['x'], f['y']), False)
            return ('Deviation' if self.deviations >= cfg.deviation_frames else 'Unknown'), False
        self.deviations = 0
        candidate = (f['eta_target'] >= cfg.arrival_coverage and f['eta_source'] <= cfg.source_release
                     and f['distance'] <= cfg.position_tolerance)
        stable = self.window.observe(frame.frame_id, frame.exposure_end_s, (f['x'], f['y']), candidate)
        if stable:
            return 'Arrived', True
        if .12 < f['eta_target'] < cfg.arrival_coverage and f['eta_source'] > cfg.source_release:
            return 'Partial', candidate
        if f['velocity'] is None:
            return 'Unknown', candidate
        return ('Stationary' if f['velocity'] < cfg.stationary_speed else 'Moving'), candidate


class EventPolicy:
    """Task context changes on every applied command; each step consumed once."""
    def __init__(self, config, method):
        if method not in ('A', 'B', 'C'):
            raise ValueError('method must be A/B/C')
        self.cfg, self.method = config, method
        self.step = self.epoch = 0
        self.phase = 'transport'
        self.applied_s = 0.
        self.started = 0.
        self.last_valid = 0.
        self.best_progress = 0.
        self.progress_at = 0.
        self.retries = self.recoveries = 0
        self.step_retries = self.step_recoveries = 0
        self.consumed = set()

    def command_started(self, time_s, applied_s):
        self.epoch += 1
        self.started, self.applied_s = time_s, applied_s
        self.best_progress = 0.
        self.progress_at = self.last_valid = time_s

    def decide(self, time_s, state, candidate, f):
        cfg = self.cfg
        if self.method == 'A':
            return 'Update' if time_s-self.started >= cfg.fixed_interval_s else 'Hold'
        if f.get('valid'):
            self.last_valid = time_s
            if f['progress'] > self.best_progress+cfg.progress_epsilon:
                self.best_progress, self.progress_at = f['progress'], time_s
        if time_s-self.last_valid > cfg.observation_timeout_s:
            return 'Stop'
        if self.phase == 'recovering':
            if state == 'Arrived':
                self.phase = 'transport'
                return 'Resume'
            return 'Stop' if time_s-self.started >= cfg.recovery_timeout_s else 'Hold'
        arrived = state == 'Arrived' if self.method == 'C' else candidate
        if arrived and self.step not in self.consumed:
            self.consumed.add(self.step)
            return 'Update'
        expired = time_s-self.started >= cfg.attempt_timeout_s
        stalled = time_s-self.progress_at >= cfg.no_progress_s
        if state == 'Deviation' or expired or stalled:
            if state != 'Deviation' and self.step_retries < cfg.max_retries:
                self.step_retries += 1
                self.retries += 1
                return 'Retry'
            if self.step_recoveries < cfg.max_recoveries:
                self.step_recoveries += 1
                self.recoveries += 1
                self.phase = 'recovering'
                return 'Recovery'
            return 'Stop'
        return 'Hold'

    def advance_step(self):
        self.step += 1
        self.step_retries = self.step_recoveries = 0
