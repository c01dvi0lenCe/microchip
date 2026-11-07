import math
import unittest
import numpy as np


class VideoGeometryEstimateTests(unittest.TestCase):
    def test_area_and_equivalent_diameter_use_two_axis_pixel_scale(self):
        from scripts.measure_chapter2_video_geometry import mask_dimensions
        m=np.zeros((30,40),np.uint8);m[5:15,5:25]=255
        r=mask_dimensions(m,100,100,3.2)
        self.assertAlmostEqual(r['area_mm2'],200*.032**2)
        self.assertAlmostEqual(r['equivalent_diameter_mm'],math.sqrt(4*r['area_mm2']/math.pi))
        self.assertAlmostEqual(r['bbox_width_mm'],.64)
        self.assertAlmostEqual(r['bbox_height_mm'],.32)

    def test_empty_mask_rejected(self):
        from scripts.measure_chapter2_video_geometry import mask_dimensions
        with self.assertRaises(ValueError):
            mask_dimensions(np.zeros((20,20),np.uint8),100,100,3.2)

    def test_period_estimate_finds_repeating_grid(self):
        from scripts.measure_chapter2_video_geometry import grid_period
        y,x=np.mgrid[:650,:1000]
        a=128+20*np.cos(2*np.pi*x/112)+20*np.cos(2*np.pi*y/110)
        px,py=grid_period(a.astype(np.float64))
        self.assertAlmostEqual(px['period_px'],112,delta=1)
        self.assertAlmostEqual(py['period_px'],110,delta=1)


if __name__=='__main__':
    unittest.main()
