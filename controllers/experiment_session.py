"""Run an experiment outside Tk; transfer only the latest preview and final report."""
from datetime import datetime
from pathlib import Path
import threading
import time
import uuid

import cv2

from dmf.experiment.config import load_config
from dmf.experiment.overlay import render_overlay
from dmf.experiment.runner import run_experiment


class ExperimentSession:
    def __init__(self, runner=run_experiment):
        self._runner = runner
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._report = None
        self.output_dir = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, config_path, mode):
        if self.running:
            raise RuntimeError('An experiment is already running')
        self._stop = threading.Event()
        self.output_dir = None
        self._last_preview = 0.0
        with self._lock:
            self._latest = None
            self._report = None
        # Keep the process alive until the runner finishes its ALL_OFF/close path.
        self._thread = threading.Thread(target=self._run, args=(str(config_path), mode), daemon=False)
        self._thread.start()

    def _run(self, config_path, mode):
        try:
            config = load_config(config_path, mode)
            run_id = datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8]
            self.output_dir = str(Path(config['output_dir']) / run_id)
            report = self._runner(config_path, mode, stop_event=self._stop,
                                  on_frame=self._on_frame, output_dir=self.output_dir)
        except Exception as exc:
            report = {'status': 'error', 'reason': str(exc), 'mode': mode,
                      'frames': 0, 'output_dir': self.output_dir}
        with self._lock:
            self._report = report

    def _on_frame(self, row, packet, result, electrode_map):
        now = time.monotonic()
        preview = None
        terminal = row['event_action'] in {'Complete', 'Stop'} or not row['command_accepted']
        if terminal or now - self._last_preview >= .1:
            image = render_overlay(packet, result, electrode_map, row['source_electrode'],
                                   row['target_electrode'], row['recognized_state'], row['event_action'])
            height, width = image.shape[:2]
            scale = min(1., 640/max(height, width))
            if scale < 1:
                image = cv2.resize(image, (max(1, int(width*scale)), max(1, int(height*scale))))
            preview = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            self._last_preview = now
        with self._lock:
            if preview is None and self._latest is not None:
                preview = self._latest[1]
            self._latest = (dict(row), preview)

    def take_latest(self):
        with self._lock:
            latest, self._latest = self._latest, None
            return latest

    def take_report(self):
        with self._lock:
            report, self._report = self._report, None
            return report

    def stop(self):
        self._stop.set()

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)
