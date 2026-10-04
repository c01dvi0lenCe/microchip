import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from main import STM32MatrixController


class HardwareModeUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = STM32MatrixController(self.root)

    def tearDown(self):
        self.app.on_close()

    def hardware(self):
        self.app.mode_var.set("实物")
        self.app.on_mode_changed()
        self.root.update_idletasks()

    def test_hardware_hides_all_simulation_rows_and_restores_settings(self):
        app = self.app
        app.motion_profile_var.set("困难")
        app.toggle_debug_tests()
        self.hardware()
        for row in (app.btn_reset_sim.master, app.sim_param_row, app.debug_test_row):
            self.assertFalse(row.winfo_manager())
        self.assertTrue(app.metrics_row.winfo_manager())
        app.toggle_debug_tests()
        self.assertFalse(app.debug_test_row.winfo_manager())
        app.mode_var.set("仿真")
        app.on_mode_changed()
        self.assertTrue(app.btn_reset_sim.master.winfo_manager())
        self.assertTrue(app.sim_param_row.winfo_manager())
        self.assertEqual(app.motion_profile_var.get(), "困难")
        self.assertFalse(app.debug_test_row.winfo_manager())

    def test_hardware_discards_old_simulation_preview_and_detections(self):
        app = self.app
        app._render_sim_camera_frame()
        self.hardware()
        self.assertNotIn("仿真", self.root.title())
        self.assertNotIn("仿真", app.camera_label.cget("text"))
        self.assertEqual(app.camera_label.cget("image"), "")
        self.assertEqual(app.latest_detections, [])
        self.assertIsNone(app.detected_cell)
        with patch.object(app.sim_camera, "render") as render:
            app._render_sim_camera_frame()
            render.assert_not_called()

    def test_simulation_fault_actions_cannot_change_hardware_state(self):
        app = self.app
        self.hardware()
        position = app.sim_droplet.position
        app.operation_var.set(app.OP_SPLIT)
        with patch.object(app, "stop_auto_control") as stop, patch.object(app, "log") as log:
            app.reset_simulation()
            app.simulate_detection_dropout()
            app.simulate_drift_fault()
            app.simulate_fusion_fault()
            app.simulate_split_failure_fault()
            stop.assert_not_called()
            log.assert_not_called()
        self.assertEqual(app.sim_droplet.position, position)
        self.assertEqual(app.drop_frame_until, 0)
        self.assertEqual(app.split_forced_failures_remaining, 0)

    def test_hardware_preset_excludes_simulation_parameters_and_restores_mode_ui(self):
        app = self.app
        self.hardware()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hardware.json"
            app.save_settings_preset(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for key in ("motion_profile", "vision_noise", "fault_mode"):
                self.assertNotIn(key, payload)
            app.mode_var.set("仿真")
            app.on_mode_changed()
            self.assertTrue(app.load_settings_preset(path))
            self.assertEqual(app.mode_var.get(), "实物")
            self.assertFalse(app.sim_param_row.winfo_manager())


if __name__ == "__main__":
    unittest.main()
