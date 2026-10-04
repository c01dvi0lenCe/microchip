import tempfile
import time
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from main import STM32MatrixController
from scripts.create_chapter2_demo import create_demo


class ExperimentGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = STM32MatrixController(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        if self.app.experiment_session.running:
            self.app.experiment_session.stop()
            self.app.experiment_session.join(10)
        try:
            self.app.on_close()
        except tk.TclError:
            pass

    def test_window_close_waits_for_worker_release(self):
        from controllers.experiment_session import ExperimentSession
        started, release = threading.Event(), threading.Event()
        def runner(config, mode, **kwargs):
            started.set()
            kwargs['stop_event'].wait(5)
            release.wait(5)
            return dict(status='stopped', reason='released', release_confirmed=True, mode=mode)
        with tempfile.TemporaryDirectory() as folder:
            config = create_demo(Path(folder))[0]
            self.app.experiment_session = ExperimentSession(runner=runner)
            self.app.experiment_config_var.set(str(config))
            self.assertTrue(self.app.start_experiment())
            self.assertTrue(started.wait(5))
            self.app.on_close()
            self.assertTrue(self.root.winfo_exists())
            self.assertTrue(self.app._experiment_active)
            release.set()
            self.app.experiment_session.join(5)
            self.app._poll_experiment()
            with self.assertRaises(tk.TclError):
                self.root.winfo_exists()

    def test_one_gui_has_experiment_page_and_no_chapter1_page(self):
        names = [self.app.main_notebook.tab(tab, 'text') for tab in self.app.main_notebook.tabs()]
        self.assertEqual(names, ['手动电极', '自动化路径规划', '第二章单液滴实验'])
        self.assertFalse(hasattr(self.app, 'scope_test_client'))
        self.app.main_notebook.select(self.app.experiment_page)
        self.root.update()
        self.assertFalse(self.app.system_control_card.winfo_manager())
        self.assertEqual(self.app.experiment_mode_var.get(), 'offline')

    def test_demo_runs_from_gui_and_unlocks_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            config = create_demo(Path(folder))[0]
            self.app.experiment_config_var.set(str(config))
            self.assertTrue(self.app.start_experiment())
            self.assertEqual(str(self.app.mode_combobox.cget('state')), 'disabled')
            with patch.object(self.app.sim_camera, 'render') as render:
                self.app._render_sim_camera_frame()
                render.assert_not_called()
            limit = time.monotonic() + 15
            while self.app._experiment_active and time.monotonic() < limit:
                self.root.update()
                time.sleep(.01)
            self.assertFalse(self.app._experiment_active)
            self.assertIn('完成', self.app.experiment_status_var.get())
            self.assertTrue((Path(self.app.experiment_output_dir)/'frames.csv').exists())
            self.assertEqual(str(self.app.btn_experiment_start.cget('state')), 'normal')
            self.assertEqual(str(self.app.main_notebook.tab(0, 'state')), 'normal')

    def test_existing_serial_connection_blocks_new_experiment(self):
        self.app.is_connected = True
        with patch('controllers.experiment_controller.messagebox.showwarning') as warning:
            self.assertFalse(self.app.start_experiment())
            warning.assert_called_once()
        self.app.is_connected = False

    def test_all_off_requests_experiment_stop_and_blocks_manual_writes(self):
        self.app._experiment_active = True
        with patch.object(self.app.experiment_session, 'stop') as stop:
            self.app.reset_all()
            stop.assert_called_once()
        with patch.object(self.app, 'log'):
            self.assertFalse(self.app.send_command('SET:190:1'))
            self.assertTrue(self.app._hardware_manual_control_blocked())
        self.app._experiment_active = False
