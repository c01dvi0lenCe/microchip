import unittest
import math
import numpy as np
import cv2
from shapely.geometry import Point


class SDFShapeTests(unittest.TestCase):
    def test_replay_ids_keep_integer_serialization_without_changing_coordinates(self):
        from dmf.chapter2_geometry_sim.sdf_trial import canonical_ids
        row=dict(active=191.,target=191.,activation_segment=1.,x_mm=30.4,time_s=.54)
        result=canonical_ids(row)
        self.assertIs(type(result['active']),int)
        self.assertIs(type(result['target']),int)
        self.assertEqual(result['x_mm'],30.4)
        self.assertEqual(result['time_s'],.54)
        with self.assertRaises(ValueError):canonical_ids(dict(active=191.5))

    def test_normalization_aligns_motion_and_preserves_area_centroid(self):
        from dmf.chapter2_geometry_sim.shape_sequence import normalize_mask
        mask=np.zeros((100,160),np.uint8)
        cv2.ellipse(mask,(80,50),(50,20),0,0,360,255,-1)
        polygon=normalize_mask(mask,(-1.,0.),4.)
        self.assertAlmostEqual(polygon.area,4*math.pi,places=8)
        self.assertLess(polygon.centroid.distance(Point(0,0)),1e-10)
        self.assertGreater(polygon.bounds[2]-polygon.bounds[0],polygon.bounds[3]-polygon.bounds[1])

    def test_rejects_disconnected_or_holed_masks_without_repair(self):
        from dmf.chapter2_geometry_sim.shape_sequence import normalize_mask
        for hole in (False,True):
            mask=np.zeros((80,120),np.uint8)
            cv2.circle(mask,(35,40),18,255,-1)
            if hole:cv2.circle(mask,(35,40),5,0,-1)
            else:cv2.circle(mask,(90,40),10,255,-1)
            with self.assertRaises(ValueError):normalize_mask(mask,(1.,0.),4.)

    def test_sdf_endpoint_identity_and_intermediate_centroid_area(self):
        from dmf.chapter2_geometry_sim.shape_sequence import normalize_mask,SDFShapeSequence
        compact=np.zeros((160,240),np.uint8);cv2.circle(compact,(120,80),45,255,-1)
        neck=compact.copy();neck[:]=0
        cv2.circle(neck,(80,80),38,255,-1);cv2.circle(neck,(165,80),30,255,-1)
        cv2.rectangle(neck,(80,68),(165,92),255,-1)
        a=normalize_mask(compact,(1.,0.),4.);b=normalize_mask(neck,(1.,0.),4.)
        seq=SDFShapeSequence([0.,1.],[a,b],pixels_per_mm=40.)
        self.assertLess(seq.polygon(0.).symmetric_difference(a).area,1e-10)
        self.assertLess(seq.polygon(1.).symmetric_difference(b).area,1e-10)
        for q in (.1,.3,.5,.7,.9):
            p=seq.polygon(q,(30.,20.))
            self.assertAlmostEqual(p.area,4*math.pi,places=7)
            self.assertLess(p.centroid.distance(Point(30.,20.)),1e-9)
            self.assertTrue(p.is_valid)
            self.assertEqual(len(p.interiors),0)

    def test_nonmonotonic_phase_and_out_of_range_rejected(self):
        from dmf.chapter2_geometry_sim.shape_sequence import SDFShapeSequence
        p=Point(0,0).buffer(2.)
        with self.assertRaises(ValueError):SDFShapeSequence([0,.6,.5,1],[p]*4)
        seq=SDFShapeSequence([0.,1.],[p,p])
        for q in (-.01,1.01,float('nan')):
            with self.assertRaises(ValueError):seq.polygon(q)

    def test_neck_metric_is_na_for_compact_shape(self):
        from dmf.chapter2_geometry_sim.shape_sequence import shape_metrics
        result=shape_metrics(Point(0,0).buffer(2.))
        self.assertIsNone(result['neck_width_mm'])
        self.assertGreater(result['aspect_ratio'],.95)


if __name__=='__main__':unittest.main()
