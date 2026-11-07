"""Hand-checkable read-only dataset acceptance primitives."""
import unittest
import numpy as np
from scripts.audit_real_segmentation_acceptance import inspect_pixels, split_structure


class PixelAcceptanceTests(unittest.TestCase):
    def test_ignore_does_not_become_negative_ground_truth(self):
        im=np.zeros((8,8,3),np.uint8);m=np.zeros((8,8),np.uint8);ig=m.copy()
        m[2:4,2:4]=255;ig[2,2]=255
        result=inspect_pixels(im,m,ig)
        self.assertEqual(result['raw_foreground_px'],4)
        self.assertEqual(result['valid_foreground_px'],3)
        self.assertEqual(result['ignore_px'],1)

    def test_non_binary_mask_rejected_not_thresholded(self):
        m=np.zeros((8,8),np.uint8);m[1,1]=127
        with self.assertRaises(ValueError):inspect_pixels(np.zeros((8,8,3),np.uint8),m,np.zeros_like(m))

    def test_empty_gt_is_valid_not_dropped(self):
        m=np.zeros((8,8),np.uint8)
        result=inspect_pixels(np.zeros((8,8,3),np.uint8),m,m.copy())
        self.assertEqual(result['valid_foreground_px'],0)
        self.assertEqual(result['components'],0)

    def test_tiny_component_is_warning_not_deleted(self):
        m=np.zeros((8,8),np.uint8);m[2,2]=255
        result=inspect_pixels(np.zeros((8,8,3),np.uint8),m,np.zeros_like(m))
        self.assertEqual(result['tiny_components_lt16px'],1)
        self.assertEqual(result['valid_foreground_px'],1)
        self.assertEqual(m[2,2],255)

    def test_full_ignore_is_not_a_valid_empty_background(self):
        m=np.zeros((8,8),np.uint8)
        with self.assertRaises(ValueError):inspect_pixels(np.zeros((8,8,3),np.uint8),m,np.full_like(m,255))

    def test_source_video_cannot_cross_proposed_sets(self):
        rows=[dict(parent_video_id='v',source_sha256='a'*64,operation_group='op',instance_id_draft='',proposed_split='train'),
              dict(parent_video_id='v',source_sha256='a'*64,operation_group='op2',instance_id_draft='',proposed_split='val')]
        self.assertTrue(split_structure(rows)['leaks'])

    def test_unknown_cross_video_lineage_not_claimed_independent(self):
        rows=[dict(parent_video_id='v1',source_sha256='a'*64,operation_group='op1',instance_id_draft='1',proposed_split='train'),
              dict(parent_video_id='v2',source_sha256='b'*64,operation_group='op2',instance_id_draft='1',proposed_split='val')]
        result=split_structure(rows)
        self.assertFalse(result['leaks'])
        self.assertFalse(result['independent_capture_groups_verified'])


if __name__=='__main__':unittest.main()
