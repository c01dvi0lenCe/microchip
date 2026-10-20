import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np

try:
    from .test_chapter2_runner import make_inputs, read_rows
except ImportError:
    from test_chapter2_runner import make_inputs, read_rows
from dmf.experiment.runner import run_experiment


class ExperimentIntegrationTests(unittest.TestCase):
    def test_terminal_preview_is_not_lost_to_rate_limit(self):
        from controllers.experiment_session import ExperimentSession
        session = ExperimentSession()
        session._last_preview = 0
        row = dict(source_electrode=190, target_electrode=191, recognized_state='Moving',
                   event_action='Hold', command_accepted=True)
        with patch('controllers.experiment_session.render_overlay',
                   return_value=np.zeros((10, 10, 3), np.uint8)) as render, \
             patch('controllers.experiment_session.time.monotonic', side_effect=[100, 100.01]):
            session._on_frame(row, None, None, None)
            row.update(event_action='Complete', recognized_state='Arrived')
            session._on_frame(row, None, None, None)
            self.assertEqual(render.call_count, 2)
        self.assertEqual(session.take_latest()[0]['event_action'], 'Complete')

    def test_runner_cancel_releases_and_records_a_stopped_run(self):
        from dmf.experiment.actuator import AMActuator
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = make_inputs(root, [(190, 190, 6, 6)] * 10)
            stop = threading.Event()
            actuator = AMActuator('offline', {})
            close = Mock(wraps=actuator.close)
            actuator.close = close
            frames = []

            def update(row, *args):
                frames.append(row)
                stop.set()

            report = run_experiment(config, stop_event=stop, on_frame=update,
                                    actuator_factory=lambda *args: actuator)
            self.assertEqual(report['status'], 'stopped')
            self.assertEqual(report['frames'], 1)
            self.assertEqual(len(frames), 1)
            close.assert_called_once()
            self.assertFalse(read_rows(root/'results/steps.csv')[0]['success'] == 'True')

    def test_session_is_restartable_and_preserves_each_run(self):
        from controllers.experiment_session import ExperimentSession
        from scripts.create_chapter2_demo import create_demo
        with tempfile.TemporaryDirectory() as folder:
            config = create_demo(Path(folder))[0]
            session = ExperimentSession()
            outputs = []
            for _ in range(2):
                session.start(config, 'offline')
                session.join(15)
                self.assertFalse(session.running)
                report = session.take_report()
                self.assertEqual(report['status'], 'complete', report)
                self.assertIsNotNone(session.take_latest())
                outputs.append(report['output_dir'])
                rows = read_rows(Path(report['output_dir'])/'frames.csv')
                self.assertTrue(all(row['command_sent'] == 'False' for row in rows))
            self.assertNotEqual(*outputs)

    def test_missing_config_is_reported_without_crashing_ui(self):
        from controllers.experiment_session import ExperimentSession
        session = ExperimentSession()
        session.start('missing-experiment-config.yaml', 'offline')
        session.join(5)
        report = session.take_report()
        self.assertEqual(report['status'], 'error')
        self.assertTrue(report['reason'])

    def test_session_refuses_double_start_and_stop_is_thread_safe(self):
        from controllers.experiment_session import ExperimentSession
        started = threading.Event()
        def fake_runner(config, mode, **kwargs):
            started.set()
            kwargs['stop_event'].wait(5)
            return {'status': 'stopped', 'reason': 'stop'}
        with tempfile.TemporaryDirectory() as folder:
            config = make_inputs(Path(folder), [])
            session = ExperimentSession(runner=fake_runner)
            session.start(config, 'offline')
            self.assertTrue(started.wait(5))
            with self.assertRaises(RuntimeError):
                session.start(config, 'offline')
            session.stop()
            session.join(5)
            self.assertFalse(session.running)
            self.assertEqual(session.take_report()['status'], 'stopped')
