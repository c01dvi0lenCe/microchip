import unittest

import cv2
import numpy as np
import torch

from dmf.segmentation_research.deep_training import (
    matched_transform, masked_bce_dice, epoch_order, is_improvement,
    prepare_training_sample,
)


class DeepTrainingContractTests(unittest.TestCase):
    def test_ignored_pixel_survives_downsample(self):
        image = np.zeros((768, 768, 3), np.uint8)
        gt = np.zeros((768, 768), np.uint8)
        ignore = gt.copy()
        ignore[31, 31] = 255
        _, _, valid, _ = prepare_training_sample(image, gt, ignore)
        self.assertLess(valid.sum(), 512 * 512)

    def test_white_padding_is_invalid(self):
        image = np.zeros((200, 400, 3), np.uint8)
        mask = np.zeros((200, 400), np.uint8)
        _, _, valid, meta = prepare_training_sample(image, mask, mask)
        self.assertEqual(meta['offset_xy'], (0, 128))
        self.assertFalse(valid[:128].any())
        self.assertTrue(valid[128:384].all())

    def test_gt_nearest_grid_alignment(self):
        image = np.zeros((768, 768, 3), np.uint8)
        gt = np.zeros((768, 768), np.uint8)
        gt[150:450, 300:600] = 255
        _, target, valid, _ = prepare_training_sample(image, gt, np.zeros_like(gt))
        expected = cv2.resize(gt, (512, 512), interpolation=cv2.INTER_NEAREST) > 0
        np.testing.assert_array_equal(target, expected)
        self.assertTrue(valid.all())

    def test_ignore_target_changes_do_not_change_loss(self):
        logits = torch.zeros((1, 1, 2, 2), requires_grad=True)
        target = torch.zeros_like(logits)
        valid = torch.tensor([[[[1., 1.], [0., 0.]]]])
        a = masked_bce_dice(logits, target, valid)
        target[:, :, 1] = 1
        b = masked_bce_dice(logits, target, valid)
        self.assertEqual(float(a.detach()), float(b.detach()))

    def test_ignore_logit_has_zero_gradient(self):
        logits = torch.zeros((1, 1, 2, 2), requires_grad=True)
        target = torch.ones_like(logits)
        valid = torch.tensor([[[[1., 1.], [0., 0.]]]])
        masked_bce_dice(logits, target, valid).backward()
        self.assertTrue(torch.equal(logits.grad[:, :, 1], torch.zeros((1, 1, 2))))

    def test_all_ignore_rejected(self):
        with self.assertRaises(ValueError):
            masked_bce_dice(torch.zeros(1, 1, 2, 2), torch.zeros(1, 1, 2, 2),
                            torch.zeros(1, 1, 2, 2))

    def test_empty_gt_false_positives_are_penalized(self):
        target = torch.zeros(1, 1, 2, 2)
        valid = torch.ones_like(target)
        self.assertGreater(float(masked_bce_dice(torch.ones_like(target) * 8, target, valid)),
                           float(masked_bce_dice(torch.ones_like(target) * -8, target, valid)))

    def test_transform_geometry_stays_aligned(self):
        target = np.zeros((8, 8), np.float32)
        target[1:3, 3:6] = 1
        rgb = np.repeat(target[:, :, None], 3, axis=2)
        valid = np.ones((8, 8), np.float32)
        a, b, v, _ = matched_transform(rgb, target, valid, 269000, 4, 'ROI001')
        np.testing.assert_array_equal(a[:, :, 0] > .5, b > .5)
        self.assertTrue(v.all())

    def test_augment_independent_of_global_rng_and_repeatable(self):
        image = np.zeros((8, 8, 3), np.float32)
        mask = np.zeros((8, 8), np.float32)
        a = matched_transform(image, mask, mask + 1, 269000, 1, 'ROI001')
        np.random.seed(999)
        np.random.rand(100)
        torch.rand(100)
        b = matched_transform(image, mask, mask + 1, 269000, 1, 'ROI001')
        for x, y in zip(a[:3], b[:3]):
            np.testing.assert_array_equal(x, y)
        self.assertEqual(a[3], b[3])

    def test_epoch_order_shared_but_varies(self):
        a = epoch_order(144, 269000, 1)
        self.assertEqual(a, epoch_order(144, 269000, 1))
        self.assertEqual(sorted(a), list(range(144)))
        self.assertNotEqual(a, epoch_order(144, 269000, 2))

    def test_ties_keep_earlier_best(self):
        self.assertFalse(is_improvement(.9, .9))
        self.assertFalse(is_improvement(.9 + 1e-9, .9))
        self.assertTrue(is_improvement(.91, .9))

    def test_nonfinite_score_rejected(self):
        with self.assertRaises(ValueError):
            is_improvement(float('nan'), .9)


if __name__ == '__main__':
    unittest.main()
