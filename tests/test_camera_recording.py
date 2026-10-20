import unittest
import tempfile
import threading
import time
import queue
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from controllers.camera_controller import CameraControllerMixin
from dmf.vision.image_io import read_image


class PhotoController(CameraControllerMixin):
    def __init__(self, frame):
        self.camera_running = True
        self.latest_camera_frame_bgr = frame
        self.logs = []
        self.callbacks = []
        self.states = []
        self.root = SimpleNamespace(after=lambda delay, callback: self.callbacks.append(callback))
        self.btn_camera_photo = SimpleNamespace(config=lambda **values: self.states.append(values))

    def is_simulation_mode(self):
        return False

    def log(self, message):
        self.logs.append(message)

    def wait_for_photo(self):
        deadline = time.monotonic() + 3
        while self.callbacks and time.monotonic() < deadline:
            self.callbacks.pop(0)()
            time.sleep(0.005)
        if self.callbacks:
            raise AssertionError("Photo writer did not finish")


class CameraRecordingDisplayTests(unittest.TestCase):
    def test_new_recordings_and_photos_use_capture_date_folder(self):
        fixed = datetime(2026, 10, 14, 23, 59, 59)
        controller = PhotoController(np.zeros((8, 8, 3), dtype=np.uint8))
        with tempfile.TemporaryDirectory() as temp:
            with patch("controllers.camera_controller.CAMERA_MEDIA_ROOT", Path(temp)), \
                    patch("controllers.camera_controller.datetime") as clock:
                clock.now.return_value = fixed
                recording = controller._camera_recording_output_path()
                self.assertEqual(recording.parent.name, "2026-10-14")
                self.assertTrue(recording.name.startswith("camera_20261014_"))
                controller.take_camera_photo()
                controller.wait_for_photo()
                image = next(Path(temp).rglob("*.png"))
                self.assertEqual(image.parent.name, "2026-10-14")
                self.assertTrue(image.name.startswith("camera_20261014_"))

    def test_elapsed_time_is_formatted_as_hours_minutes_seconds(self):
        self.assertEqual(CameraControllerMixin._format_recording_duration(0), "00:00:00")
        self.assertEqual(CameraControllerMixin._format_recording_duration(65.9), "00:01:05")
        self.assertEqual(CameraControllerMixin._format_recording_duration(3661), "01:01:01")

    def test_hardware_preview_converts_bgr_to_rgb_without_changing_photo_frame(self):
        bgr = np.full((4, 4, 3), [19, 101, 227], dtype=np.uint8)
        controller = PhotoController(None)
        controller.camera_running = False
        controller._hardware_camera_queue = queue.Queue()
        controller._hardware_camera_queue.put(SimpleNamespace(image_bgr=bgr))
        shown = []
        controller._show_camera_frame = shown.append
        controller._poll_hardware_camera()
        self.assertIs(controller.latest_camera_frame_bgr, bgr)
        np.testing.assert_array_equal(shown[0], np.full((4, 4, 3), [227, 101, 19], dtype=np.uint8))
        np.testing.assert_array_equal(bgr, np.full((4, 4, 3), [19, 101, 227], dtype=np.uint8))

    def test_photo_preserves_pixels_on_unicode_path_without_imwrite(self):
        frame = np.arange(48 * 64 * 3, dtype=np.uint8).reshape(48, 64, 3)
        controller = PhotoController(frame)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "\u5de5\u4e1a\u76f8\u673a"
            with patch("controllers.camera_controller.CAMERA_MEDIA_ROOT", folder), \
                    patch("controllers.camera_controller.cv2.imwrite", return_value=False) as imwrite:
                controller.take_camera_photo()
                controller.latest_camera_frame_bgr = np.zeros_like(frame)
                controller.wait_for_photo()
                imwrite.assert_not_called()
            images = list(folder.rglob("*.png"))
            self.assertEqual(len(images), 1)
            np.testing.assert_array_equal(read_image(images[0], cv2.IMREAD_COLOR), frame)
            self.assertEqual(controller.states[-1], {"state": "normal"})
            self.assertIn(str(images[0]), controller.logs[-1])

    def test_photo_encoding_failure_is_reported_and_button_restored(self):
        controller = PhotoController(np.zeros((8, 8, 3), dtype=np.uint8))
        with tempfile.TemporaryDirectory() as temp:
            with patch("controllers.camera_controller.CAMERA_MEDIA_ROOT", Path(temp)), \
                    patch("dmf.vision.image_io.cv2.imencode", return_value=(False, None)):
                controller.take_camera_photo()
                controller.wait_for_photo()
            self.assertEqual(list(Path(temp).rglob("*.png")), [])
        self.assertIn("OpenCV failed to write the image", controller.logs[-1])
        self.assertEqual(controller.states[-1], {"state": "normal"})

    def test_photo_directory_failure_is_reported_from_worker(self):
        controller = PhotoController(np.zeros((8, 8, 3), dtype=np.uint8))
        with patch("pathlib.Path.mkdir", side_effect=PermissionError("no write permission")):
            controller.take_camera_photo()
            controller.wait_for_photo()
        self.assertIn("failed to write", controller.logs[-1])
        self.assertEqual(controller.states[-1], {"state": "normal"})

    def test_slow_photo_encoding_does_not_block_controller_thread(self):
        controller = PhotoController(np.zeros((8, 8, 3), dtype=np.uint8))
        entered, release = threading.Event(), threading.Event()
        workers = []

        def slow_encoder(*args):
            workers.append(threading.get_ident())
            entered.set()
            if not release.wait(2):
                raise AssertionError("Photo encoder was called on the controller thread")
            return False, None

        with tempfile.TemporaryDirectory() as temp:
            with patch("controllers.camera_controller.CAMERA_MEDIA_ROOT", Path(temp)), \
                    patch("dmf.vision.image_io.cv2.imencode", side_effect=slow_encoder):
                try:
                    controller.take_camera_photo()
                    self.assertTrue(entered.wait(1))
                    self.assertTrue(controller.callbacks)
                    self.assertNotEqual(workers[0], threading.get_ident())
                finally:
                    release.set()
                    controller.wait_for_photo()


if __name__ == "__main__":
    unittest.main()
