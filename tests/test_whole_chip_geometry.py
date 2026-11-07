"""Native-resolution tiling: hand-computed geometry and exact reconstruction."""
from dataclasses import FrozenInstanceError
import importlib
import unittest

import numpy as np


class WholeChipGeometryTests(unittest.TestCase):
    def setUp(self):
        try:
            self.geometry = importlib.import_module("dmf.vision.whole_chip_geometry")
        except ModuleNotFoundError as exc:
            self.fail(f"whole-chip geometry API is missing: {exc}")

    def test_small_frame_has_one_frozen_tile_with_negative_input_origin(self):
        tiles = self.geometry.plan_tiles((3, 5, 3))
        self.assertEqual(tiles, (self.geometry.Tile(0, 0, 5, 3),))
        self.assertEqual((tiles[0].input_x, tiles[0].input_y), (-64, -64))
        with self.assertRaises(FrozenInstanceError):
            tiles[0].core_x = 1

    def test_non_square_edges_are_row_major_without_shifted_last_core(self):
        tiles = self.geometry.plan_tiles((385, 769, 3))
        self.assertEqual([(t.core_x, t.core_y, t.core_w, t.core_h) for t in tiles], [
            (0, 0, 384, 384), (384, 0, 384, 384), (768, 0, 1, 384),
            (0, 384, 384, 1), (384, 384, 384, 1), (768, 384, 1, 1),
        ])

    def test_full_native_camera_frame_requires_150_tiles(self):
        tiles = self.geometry.plan_tiles((3648, 5472, 3))
        self.assertEqual(len(tiles), 150)
        self.assertEqual(tiles[-1], self.geometry.Tile(5376, 3456, 96, 192))

    def test_roi_is_global_and_covered_once_with_zero_unobserved_area(self):
        shape, roi = (901, 1301, 3), (107, 53, 805, 701)
        writes = np.zeros(shape[:2], np.uint8)
        tiles = self.geometry.plan_tiles(shape, roi)
        self.assertEqual(tiles[0], self.geometry.Tile(107, 53, 384, 384))
        self.assertEqual(tiles[-1], self.geometry.Tile(875, 437, 37, 317))
        for t in tiles:
            writes[t.core_y:t.core_y+t.core_h, t.core_x:t.core_x+t.core_w] += 1
        expected = np.zeros(shape[:2], np.uint8)
        expected[53:754, 107:912] = 1
        np.testing.assert_array_equal(writes, expected)

    def test_every_native_frame_pixel_is_written_exactly_once(self):
        for shape in [(1, 1, 3), (384, 384, 3), (768, 769, 3), (3648, 5472, 3)]:
            with self.subTest(shape=shape):
                writes = np.zeros(shape[:2], np.uint8)
                for t in self.geometry.plan_tiles(shape):
                    writes[t.core_y:t.core_y+t.core_h, t.core_x:t.core_x+t.core_w] += 1
                self.assertTrue(np.all(writes == 1))

    def test_extract_top_left_preserves_bgr_and_pads_only_outside_original(self):
        frame = np.arange(3*5*3, dtype=np.uint8).reshape(3, 5, 3)
        original = frame.copy()
        tile = self.geometry.extract_tile(frame, self.geometry.plan_tiles(frame.shape)[0])
        expected = np.full((512, 512, 3), 255, np.uint8)
        expected[64:67, 64:69] = frame
        np.testing.assert_array_equal(tile, expected)
        tile[64, 64] = 0
        np.testing.assert_array_equal(frame, original)

    def test_roi_halo_reads_real_pixels_outside_roi_not_white_padding(self):
        frame = np.full((900, 1000, 3), (13, 27, 41), np.uint8)
        t = self.geometry.plan_tiles(frame.shape, (200, 200, 50, 20))[0]
        np.testing.assert_array_equal(self.geometry.extract_tile(frame, t), frame[136:648, 136:648])

    def test_extract_bottom_right_padding_and_global_origin(self):
        frame = np.full((385, 769, 3), 17, np.uint8)
        t = self.geometry.plan_tiles(frame.shape)[-1]
        tile = self.geometry.extract_tile(frame, t)
        self.assertEqual((t.input_x, t.input_y), (704, 320))
        self.assertTrue(np.all(tile[:65, :65] == 17))
        self.assertTrue(np.all(tile[65:] == 255))
        self.assertTrue(np.all(tile[:, 65:] == 255))

    def test_stitch_uses_core_only_not_or_overlap(self):
        full = np.zeros((390, 800), np.uint8)
        t = self.geometry.Tile(384, 0, 384, 384)
        prediction = np.full((512, 512), 255, np.uint8)
        prediction[64:448, 64:448] = 0
        self.geometry.stitch_core(full, prediction, t)
        self.assertFalse(full.any())

    def test_stitch_rejects_noncanonical_binary_one_encoding(self):
        full = np.zeros((2, 3), np.uint8)
        prediction = np.zeros((512, 512), np.uint8)
        prediction[64:66, 64:67] = 1
        with self.assertRaises(ValueError):
            self.geometry.stitch_core(full, prediction, self.geometry.Tile(0, 0, 3, 2))
        self.assertFalse(full.any())

    def test_pointwise_predictor_reconstructs_exact_mask_across_seams(self):
        expected = np.zeros((803, 1171), np.uint8)
        expected[360:410, 350:800] = 255
        expected[380:387, 250:1000] = 255  # thin bridge crossing two vertical seams
        expected[700:710, 1100:1110] = 255
        expected[10, 20] = 255
        expected[802, 1170] = 255
        frame = np.full((*expected.shape, 3), 255, np.uint8)
        frame[expected > 0] = (10, 20, 30)
        actual = np.zeros_like(expected)
        for t in self.geometry.plan_tiles(frame.shape):
            tile = self.geometry.extract_tile(frame, t)
            prediction = np.where(tile[:, :, 0] < 100, 255, 0).astype(np.uint8)
            self.geometry.stitch_core(actual, prediction, t)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(sorted(c["area_px"] for c in self.geometry.components(actual)),
                         [1, 1, 100, 24600])

    def test_roi_stitch_keeps_full_frame_shape_and_zero_outside(self):
        frame = np.zeros((800, 900, 3), np.uint8)
        actual = np.zeros(frame.shape[:2], np.uint8)
        for t in self.geometry.plan_tiles(frame.shape, (100, 70, 500, 600)):
            prediction = np.where(self.geometry.extract_tile(frame, t)[:, :, 0] == 0, 255, 0).astype(np.uint8)
            self.geometry.stitch_core(actual, prediction, t)
        expected = np.zeros_like(actual)
        expected[70:670, 100:600] = 255
        np.testing.assert_array_equal(actual, expected)

    def test_components_return_all_domains_in_global_coordinates(self):
        mask = np.zeros((600, 800), np.uint8)
        mask[100, 700] = 255
        mask[380:390, 380:390] = 255
        found = self.geometry.components(mask)
        self.assertEqual(len(found), 2)
        by_area = {c["area_px"]: c for c in found}
        self.assertEqual(by_area[1]["centroid_px"], (700.0, 100.0))
        self.assertEqual(by_area[1]["bbox_xywh"], (700, 100, 1, 1))
        self.assertEqual(by_area[100]["centroid_px"], (384.5, 384.5))
        self.assertEqual(by_area[100]["bbox_xywh"], (380, 380, 10, 10))
        self.assertEqual({c["component_id"] for c in found}, {1, 2})

    def test_components_use_eight_connectivity_and_keep_holes(self):
        mask = np.zeros((5, 7), np.uint8)
        mask[1, 1] = mask[2, 2] = 255
        mask[1:4, 4:7] = 255
        mask[2, 5] = 0
        self.assertEqual(sorted(c["area_px"] for c in self.geometry.components(mask)), [2, 8])
        self.assertEqual(self.geometry.components(np.zeros((1, 1), np.uint8)), [])

    def test_invalid_shapes_are_rejected(self):
        for shape in [None, (), (3,), (0, 3, 3), (-1, 4, 3), (3, 4),
                      (3, 4, 1), (3, 4, 4), (True, 4, 3), (3.0, 4, 3), (3, 4, 3, 1)]:
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                self.geometry.plan_tiles(shape)

    def test_invalid_roi_is_never_clipped_or_coerced(self):
        for roi in [(0, 0, 0, 1), (0, 0, 1, -1), (-1, 0, 1, 1), (0, -1, 1, 1),
                    (9, 0, 2, 1), (0, 9, 1, 2), (0.0, 0, 1, 1),
                    (False, 0, 1, 1), (0, 0, True, 1), (0, 0, 1), "0,0,1,1"]:
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                self.geometry.plan_tiles((10, 10, 3), roi)

    def test_invalid_tiles_are_rejected(self):
        for values in [(-1, 0, 1, 1), (0, -1, 1, 1), (0, 0, 0, 1), (0, 0, 1, 385),
                       (0, 0, 385, 1), (False, 0, 1, 1), (0, 0, 1.0, 1)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.geometry.Tile(*values)

    def test_invalid_frames_and_out_of_frame_core_are_rejected(self):
        t = self.geometry.Tile(0, 0, 1, 1)
        for frame in [None, np.zeros((2, 2), np.uint8), np.zeros((2, 2, 4), np.uint8),
                      np.zeros((2, 2, 3), np.float32), np.zeros((0, 2, 3), np.uint8)]:
            with self.subTest(frame=getattr(frame, "shape", None)), self.assertRaises(ValueError):
                self.geometry.extract_tile(frame, t)
        with self.assertRaises(ValueError):
            self.geometry.extract_tile(np.zeros((2, 2, 3), np.uint8), self.geometry.Tile(1, 1, 2, 2))

    def test_invalid_masks_fail_before_modifying_destination(self):
        t = self.geometry.Tile(0, 0, 2, 2)
        for bad in [None, np.zeros((512, 512), bool), np.zeros((511, 512), np.uint8),
                    np.full((512, 512), 2, np.uint8), np.zeros((512, 512, 1), np.uint8)]:
            full = np.zeros((2, 2), np.uint8)
            with self.subTest(mask=getattr(bad, "shape", None)), self.assertRaises(ValueError):
                self.geometry.stitch_core(full, bad, t)
            self.assertFalse(full.any())
        with self.assertRaises(ValueError):
            self.geometry.stitch_core(np.zeros((1, 1), np.uint8), np.zeros((512, 512), np.uint8), t)
        readonly = np.zeros((2, 2), np.uint8)
        readonly.flags.writeable = False
        with self.assertRaises(ValueError):
            self.geometry.stitch_core(readonly, np.zeros((512, 512), np.uint8), t)

    def test_stitch_rejects_invalid_destination_dtype_or_shape(self):
        tilemask = np.zeros((512, 512), np.uint8)
        t = self.geometry.Tile(0, 0, 1, 1)
        for full in [None, np.zeros((2, 2), np.float32), np.zeros((2, 2, 1), np.uint8),
                     np.zeros((0, 2), np.uint8), np.zeros((2, 2), bool)]:
            with self.subTest(shape=getattr(full, "shape", None)), self.assertRaises(ValueError):
                self.geometry.stitch_core(full, tilemask, t)

    def test_components_reject_nonbinary_or_non_uint8_masks(self):
        mixed = np.array([[0, 1, 255]], np.uint8)
        for mask in [None, np.zeros((0, 1), np.uint8), np.zeros((2, 2, 1), np.uint8),
                     np.zeros((2, 2), bool), np.array([[2]], np.uint8), mixed]:
            with self.subTest(mask=getattr(mask, "shape", None)), self.assertRaises(ValueError):
                self.geometry.components(mask)


if __name__ == "__main__":
    unittest.main()
