import tempfile
import tkinter as tk
from pathlib import Path
import unittest

import numpy as np

from dmf.vision.pilot_annotation import prepare_pilot, PilotWorkspace
from dmf.vision.pilot_annotation_gui import PilotAnnotationApp
from tests import test_pilot_annotation as fixtures


class PilotGuiTests(unittest.TestCase):
    def test_map_and_explicit_review_save_without_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);prepare_pilot(fixtures.PilotAnnotationTests().make_input(path),path/'review')
            workspace=PilotWorkspace(path/'review')
            root=tk.Tk();root.withdraw()
            try:
                app=PilotAnnotationApp(root,workspace)
                root.update_idletasks()
                app.corners=[(0,0),(80,0),(80,80),(0,80)]
                app.pitch.set('3.2');app.map_confirmed.set(True)
                self.assertTrue(app.save_calibration())
                app.mask_reviewed.set(True);app.state_reviewed.set(True)
                app.source.set('1');app.target.set('2');app.state.set('Stationary')
                self.assertTrue(app.save_frame())
                reopened=PilotWorkspace(path/'review')
                self.assertEqual(reopened.report()['state_counts']['Stationary'],1)
            finally:root.update();root.destroy()

    def test_high_zoom_raster_is_bounded_by_viewport(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);prepare_pilot(fixtures.PilotAnnotationTests().make_input(path),path/'review')
            root=tk.Tk();root.withdraw()
            try:
                app=PilotAnnotationApp(root,PilotWorkspace(path/'review'))
                surface=app.calibration_canvas
                surface.zoom.set('400%')
                surface.show(np.full((1000,1500,3),100,np.uint8))
                self.assertLessEqual(surface.photo.width(),surface.canvas.winfo_width()+12)
                self.assertLessEqual(surface.photo.height(),surface.canvas.winfo_height()+12)
            finally:root.update();root.destroy()


if __name__=='__main__':unittest.main()
