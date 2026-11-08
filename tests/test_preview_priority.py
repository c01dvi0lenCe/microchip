from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from controllers.camera_controller import CameraControllerMixin


class NativePreviewTests(unittest.TestCase):
    def test_shrinks_display_only_before_pillow_without_changing_source_coordinates(self):
        image=np.full((1000,1500,3),123,np.uint8);before=image.copy()
        harness=SimpleNamespace(camera_label=object(),_camera_preview_target_size=lambda:(200,150),
                                _update_camera_label=lambda photo:None)
        with patch('controllers.camera_controller.Image.fromarray',wraps=Image.fromarray) as convert,\
             patch('controllers.camera_controller.ImageTk.PhotoImage'):
            CameraControllerMixin._show_camera_frame(harness,image)
        passed=convert.call_args.args[0]
        self.assertLessEqual(passed.shape[1],200,'Do not create a full native Pillow image for a small preview')
        self.assertLessEqual(passed.shape[0],150)
        self.assertEqual(harness._camera_display_geometry,(1500,1000,200,133))
        self.assertTrue(np.array_equal(image,before))


if __name__=='__main__':unittest.main()
