"""Small deterministic checks for the offline candidate selection script."""
import unittest

from scripts.prepare_real_segmentation_roi_pilot import spread_select, native_crop
import numpy as np


class SelectionTests(unittest.TestCase):
    def test_spread_includes_temporal_endpoints(self):
        self.assertEqual(spread_select(list(range(11)), 3), [0, 5, 10])

    def test_refuses_to_duplicate_candidates_to_fill_quota(self):
        with self.assertRaises(ValueError):
            spread_select([1, 2], 3)

    def test_native_crop_is_byte_exact_and_not_resized(self):
        image = np.arange(12 * 16 * 3, dtype=np.uint16).reshape(12, 16, 3)
        result = native_crop(image, [2, 3, 5, 4])
        np.testing.assert_array_equal(result, image[3:7, 2:7])
        self.assertEqual(result.shape, (4, 5, 3))

    def test_crop_rejects_out_of_bounds_instead_of_silent_truncation(self):
        with self.assertRaises(ValueError):
            native_crop(np.zeros((12, 16, 3), np.uint8), [14, 10, 4, 4])


if __name__ == '__main__':
    unittest.main()
