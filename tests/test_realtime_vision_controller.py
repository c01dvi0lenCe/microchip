from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import numpy as np
from app_controller import STM32MatrixController
from dmf.vision.contracts import FramePacket


class Predictor:
    device='software_fixture'; batch_size=4
    def predict_batch(self,images):return [np.where(im[:,:,0]<50,255,0).astype(np.uint8) for im in images]


class RealtimeControllerTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.app=STM32MatrixController(self.root,operator_only=True)
        self.temp=tempfile.TemporaryDirectory()

    def tearDown(self):
        if hasattr(self.app,'stop_realtime_detection'):
            self.app.stop_realtime_detection()
            d=self.app._vision_detector
            if d:d.worker.join(3)
        self.app.camera_running=False;self.app.on_close();self.temp.cleanup()

    def feature(self):self.assertTrue(hasattr(self.app,'start_realtime_detection'),'Realtime sensing UI missing')

    def start(self):
        self.feature();self.app.camera_running=True
        im=np.full((640,800,3),200,np.uint8);im[200:260,300:380]=0
        self.app._latest_camera_packet=FramePacket('fixture',0,0,'fixture',im)
        self.app.latest_camera_frame_bgr=im
        self.app.vision_package_var.set(self.temp.name)
        self.app._vision_output_root=Path(self.temp.name)/'sessions'
        with patch('controllers.realtime_vision_controller.G4UNetPredictor',return_value=Predictor()):
            self.assertTrue(self.app.start_realtime_detection())
            until=time.monotonic()+3
            while self.app._vision_latest_result is None and time.monotonic()<until:
                self.app._poll_realtime_vision();time.sleep(.01)
        self.assertIsNotNone(self.app._vision_latest_result)

    def test_no_automatic_camera_model_or_serial_connection(self):
        self.feature();self.assertIsNone(self.app._vision_detector)
        self.assertEqual(self.app._vision_settings['batch_size'],1,
            'Known G4 batch mismatch must remain batch1 after GUI restart')
        with patch.object(self.app,'start_camera') as camera,patch.object(self.app.electrode_transactions,'apply_changes') as tx:
            self.assertFalse(self.app.start_realtime_detection());camera.assert_not_called();tx.assert_not_called()
        self.assertEqual(str(self.app.visual_start_button['state']),'disabled')

    def test_real_result_does_not_update_control_detection_fields(self):
        self.start()
        self.assertIsNone(self.app.detected_cell)
        self.assertEqual(self.app.detected_cells,[])
        self.assertEqual(self.app._active_electrode_ids(),set())
        self.assertEqual(str(self.app.visual_start_button['state']),'disabled')

    def test_overlay_uses_result_frame_not_latest_raw(self):
        self.start();r=self.app._vision_latest_result
        self.app._latest_camera_packet=FramePacket('fixture',9,1,'fixture',np.full((640,800,3),255,np.uint8))
        self.app.latest_camera_frame_bgr=self.app._latest_camera_packet.image_bgr
        self.app.vision_view_var.set('叠加')
        with patch.object(self.app,'_show_camera_frame') as show:
            self.app._vision_view_changed()
        rendered=show.call_args.args[0]
        self.assertTrue(np.array_equal(rendered[10,10],r.packet.image_bgr[10,10,::-1]))
        self.assertEqual(self.app._vision_display_frame_id,0)

    def test_stopping_sensing_does_not_stop_camera_or_open_loop(self):
        self.start()
        with patch.object(self.app,'stop_camera') as camera,patch.object(self.app,'stop_timed_mixing') as tasks:
            self.app.stop_realtime_detection();camera.assert_not_called();tasks.assert_not_called()
        self.assertTrue(self.app.camera_running)

    def test_camera_stop_stops_sensing_and_clears_old_overlay(self):
        self.start();d=self.app._vision_detector
        self.app.stop_camera();d.worker.join(3)
        self.assertTrue(d.stopping.is_set());self.assertIsNone(self.app._vision_latest_result)
        self.assertEqual(self.app.vision_view_var.get(),'原图')

    def test_close_cancels_detection_poll_after_worker_has_settled(self):
        self.start();d=self.app._vision_detector
        self.app.stop_realtime_detection();d.worker.join(3)
        self.assertFalse(self.app._stop_realtime_for_close())
        self.assertIsNone(self.app._vision_poll_id)

    def test_invalid_local_vision_config_does_not_break_raw_gui_startup(self):
        root=tk.Tk();root.withdraw()
        try:
            with patch('controllers.realtime_vision_controller.load_yaml',return_value={'model_package':None}):
                app=STM32MatrixController(root,operator_only=True)
            self.assertIn('配置',app.vision_status_var.get())
            self.assertIsNone(app._vision_detector)
            app.on_close()
        finally:
            try:root.destroy()
            except tk.TclError:pass

    def test_start_cancels_pending_roi_selection(self):
        self.app._vision_selecting=True;self.app._vision_select_start=(1,2)
        self.start()
        self.assertFalse(self.app._vision_selecting)
        self.assertIsNone(self.app._vision_select_start)

    def test_late_roi_mouse_events_cannot_change_running_detector_domain(self):
        self.start();domain=self.app._vision_detector.roi
        self.app._vision_selecting=True;self.app._vision_select_start=(1,2)
        with patch.object(self.app,'_camera_native_point',return_value=(100,120)):
            self.app._vision_roi_press(object());self.app._vision_roi_release(object())
        self.assertEqual(self.app._vision_roi,domain)


if __name__=='__main__':unittest.main()
