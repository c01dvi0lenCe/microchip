"""Small synthetic fixtures for pure offline all-foreground baselines."""
import importlib
import importlib.util
import unittest

import cv2
import numpy as np


class SemanticBaselinesTests(unittest.TestCase):
    def setUp(self):
        # Match the declared offline-run backend and restore external settings.
        previous_threads = cv2.getNumThreads()
        self.addCleanup(cv2.setNumThreads, previous_threads)
        cv2.setNumThreads(1)

    def api(self):
        name = 'dmf.segmentation_research.semantic_baselines'
        self.assertIsNotNone(importlib.util.find_spec(name), 'pure semantic baseline module is missing')
        return importlib.import_module(name)

    def function(self, name):
        module = self.api()
        self.assertTrue(hasattr(module, name), f'{name} is missing')
        return getattr(module, name)

    def test_letterbox_preserves_aspect_white_padding_and_restore_crop(self):
        prepare = self.function('prepare_image')
        restore = self.function('restore_mask')
        image = np.full((4, 8, 3), (5, 20, 80), np.uint8)
        prepared, meta = prepare(image, (8, 8))
        self.assertEqual(prepared.shape, (8, 8, 3))
        self.assertEqual(prepared.dtype, np.uint8)
        self.assertEqual(meta['native_hw'], (4, 8))
        self.assertEqual(meta['offset_xy'], (0, 2))
        self.assertEqual(meta['scale'], 1.)
        np.testing.assert_array_equal(prepared[2:6], image)
        self.assertTrue(np.all(prepared[:2] == 255))
        self.assertTrue(np.all(prepared[6:] == 255))
        padded_mask = np.full((8, 8), 255, np.uint8)
        padded_mask[2:6] = 0
        np.testing.assert_array_equal(restore(padded_mask, meta), np.zeros((4, 8), np.uint8))

    def test_square_768_downsizes_with_area_and_restores_native_binary(self):
        prepare = self.function('prepare_image')
        restore = self.function('restore_mask')
        rng = np.random.default_rng(4)
        image = rng.integers(0, 256, (768, 768, 3), dtype=np.uint8)
        prepared, meta = prepare(image)
        np.testing.assert_array_equal(prepared, cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA))
        mask = np.zeros((512, 512), np.uint8)
        mask[10:20, 30:40] = 255
        restored = restore(mask, meta)
        self.assertEqual(restored.shape, (768, 768))
        np.testing.assert_array_equal(restored, cv2.resize(mask, (768, 768), interpolation=cv2.INTER_NEAREST))
        same, same_meta = prepare(prepared)
        np.testing.assert_array_equal(same, prepared)
        self.assertEqual(restore(mask, same_meta).shape, (512, 512))

    def test_preprocessing_rejects_wrong_images_and_nonbinary_restore(self):
        prepare = self.function('prepare_image')
        restore = self.function('restore_mask')
        for image in (np.zeros((3, 3), np.uint8), np.zeros((3, 3, 3), float)):
            with self.subTest(shape=image.shape), self.assertRaises(ValueError):
                prepare(image)
        _, meta = prepare(np.zeros((4, 4, 3), np.uint8), (4, 4))
        for mask in (np.zeros((3, 3), np.uint8), np.ones((4, 4), np.uint8)):
            with self.assertRaises(ValueError):
                restore(mask, meta)

    def test_otsu_preserves_multiple_components_border_and_unfilled_hole(self):
        otsu = self.function('otsu_mask')
        image = np.full((80, 100, 3), 240, np.uint8)
        image[10:35, 0:20] = 0
        image[40:70, 60:90] = 0
        image[48:62, 68:82] = 240
        mask = otsu(image)
        self.assertEqual(mask.dtype, np.uint8)
        self.assertEqual(mask[20, 0], 255)
        self.assertEqual(mask[45, 65], 255)
        self.assertEqual(mask[55, 75], 0)
        self.assertEqual(cv2.connectedComponents(mask)[0] - 1, 2)

    def test_otsu_default_is_exact_declared_pipeline(self):
        otsu = self.function('otsu_mask')
        image = np.random.default_rng(7).integers(0, 256, (23, 31, 3), dtype=np.uint8)
        gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        expected = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        expected = cv2.morphologyEx(expected, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        np.testing.assert_array_equal(otsu(image), expected)

    def test_common_512_predictions_repeat_in_declared_single_thread_runtime(self):
        otsu = self.function('otsu_mask')
        background = self.function('background_mask')
        image = np.random.default_rng(8).integers(0, 256, (512, 512, 3), dtype=np.uint8)
        reference = np.full_like(image, 220)
        expected_otsu, expected_background = otsu(image), background(image, reference)
        for _ in range(5):
            np.testing.assert_array_equal(otsu(image), expected_otsu)
            np.testing.assert_array_equal(background(image, reference), expected_background)

    def test_background_signed_subtraction_and_strict_threshold(self):
        background = self.function('background_mask')
        reference = np.full((3, 4, 3), 100, np.uint8)
        image = np.full_like(reference, 100)
        image[0, :, :] = np.array([200, 80, 79, 0])[:, None]
        mask = background(image, reference, blur_kernel=1, close_kernel=1)
        np.testing.assert_array_equal(mask[0], np.array([0, 0, 255, 255], np.uint8))

    def test_background_default_keeps_both_dark_components_and_border(self):
        background = self.function('background_mask')
        reference = np.full((60, 80, 3), 220, np.uint8)
        image = reference.copy()
        image[:20, :20] = 10
        image[30:50, 50:70] = 10
        mask = background(image, reference)
        self.assertEqual(mask[5, 0], 255)
        self.assertEqual(mask[40, 60], 255)
        self.assertEqual(cv2.connectedComponents(mask)[0] - 1, 2)

    def test_method_parameters_reject_invalid_kernels_and_threshold(self):
        otsu = self.function('otsu_mask')
        background = self.function('background_mask')
        image = np.zeros((8, 8, 3), np.uint8)
        for kwargs in ({'blur_kernel': 2}, {'close_kernel': 0}, {'close_iterations': -1}):
            with self.assertRaises(ValueError):
                otsu(image, **kwargs)
        with self.assertRaises(ValueError):
            background(image, image, threshold=float('nan'))
        with self.assertRaises(ValueError):
            background(image, image[:4])

    def causal_pair(self):
        sample = dict(parent_video_id='video', source_sha256='a' * 64,
                      roi_xywh=[10, 20, 512, 512], source_frame_id=10, timestamp_s=2.)
        reference = dict(sample, source_frame_id=0, timestamp_s=1., usable=True,
                         background_review_kind='assistant_visual_review')
        return sample, reference

    def test_causal_reference_accepts_only_reviewed_strictly_earlier_identity(self):
        guard = self.function('assert_causal_background')
        sample, reference = self.causal_pair()
        self.assertIsNone(guard(sample, reference))
        self.assertIsNone(guard(sample, dict(reference, background_review_kind='human_review')))
        for field, value in (
            ('parent_video_id', 'other'), ('source_sha256', 'b' * 64),
            ('roi_xywh', [11, 20, 512, 512]), ('source_frame_id', 10),
            ('source_frame_id', 11), ('timestamp_s', 2.), ('timestamp_s', 3.),
            ('timestamp_s', float('nan')), ('usable', 1), ('usable', 'True'),
            ('background_review_kind', 'ground_truth'),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                guard(sample, dict(reference, **{field: value}))
        for value in (float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                guard(dict(sample, timestamp_s=value), reference)
        with self.assertRaises(ValueError):
            guard({}, {})

    def test_score_hand_counts_ignore_and_no_instance_surrogates(self):
        score = self.function('score_mask')
        pred = np.array([[255, 255, 255], [0, 0, 255]], np.uint8)
        gt = np.array([[255, 0, 0], [255, 0, 255]], np.uint8)
        ignore = np.array([[0, 0, 255], [0, 0, 255]], np.uint8)
        row = score(pred, gt, ignore)
        self.assertEqual((row['tp'], row['fp'], row['fn'], row['tn']), (1, 1, 1, 1))
        self.assertEqual(row['valid_pixels'], 4)
        self.assertEqual(row['dice'], .5)
        self.assertAlmostEqual(row['iou'], 1 / 3)
        self.assertEqual(row['precision'], .5)
        self.assertEqual(row['recall'], .5)
        self.assertTrue(row['positive_gt'])
        self.assertFalse(row['empty_mask'])
        self.assertFalse(row['image_level_miss'])
        self.assertTrue(row['eligible'])
        self.assertFalse(row['error'])
        self.assertFalse(any('centroid' in key or 'instance' in key for key in row))

    def test_empty_gt_and_empty_predictions_are_explicit(self):
        score = self.function('score_mask')
        empty = np.zeros((2, 2), np.uint8)
        positive = empty.copy()
        positive[0, 0] = 255
        both_empty = score(empty, empty, empty)
        self.assertEqual([both_empty[key] for key in ('dice', 'iou', 'precision', 'recall')], [1.] * 4)
        self.assertFalse(both_empty['positive_gt'])
        self.assertTrue(both_empty['empty_mask'])
        self.assertFalse(both_empty['image_level_miss'])
        miss = score(empty, positive, empty)
        self.assertTrue(miss['image_level_miss'])
        self.assertEqual(miss['recall'], 0.)
        false_positive = score(positive, empty, empty)
        self.assertEqual(false_positive['dice'], 0.)
        self.assertEqual(false_positive['precision'], 0.)
        self.assertEqual(false_positive['recall'], 1.)

    def test_missing_background_not_empty_prediction_but_error_is_scored_empty(self):
        score = self.function('score_mask')
        gt = np.full((2, 2), 255, np.uint8)
        ignore = np.zeros_like(gt)
        unavailable = score(None, gt, ignore, status='unavailable_background')
        self.assertFalse(unavailable['eligible'])
        self.assertEqual(unavailable['valid_pixels'], 4)
        self.assertTrue(unavailable['positive_gt'])
        for key in ('tp', 'fp', 'fn', 'tn', 'dice', 'iou', 'precision', 'recall', 'empty_mask', 'image_level_miss'):
            self.assertIsNone(unavailable[key], key)
        error = score(gt, gt, ignore, status='error')
        self.assertTrue(error['eligible'])
        self.assertTrue(error['error'])
        self.assertTrue(error['empty_mask'])
        self.assertTrue(error['image_level_miss'])
        self.assertEqual(error['fn'], 4)
        self.assertEqual(error['dice'], 0.)

    def test_scores_reject_all_ignored_missing_ok_invalid_binary_and_shape(self):
        score = self.function('score_mask')
        empty = np.zeros((2, 2), np.uint8)
        for pred, gt, ignore, status in (
            (empty, empty, np.full_like(empty, 255), 'ok'),
            (None, empty, empty, 'ok'),
            (np.ones_like(empty), empty, empty, 'ok'),
            (empty[:1], empty, empty, 'ok'),
            (empty, empty, empty, 'unknown'),
        ):
            with self.assertRaises(ValueError):
                score(pred, gt, ignore, status=status)

    def test_target_coverage_uses_full_raster_area_hand_calculation(self):
        coverage = self.function('candidate_target_coverage')
        pred = np.zeros((5, 5), np.uint8)
        gt = pred.copy()
        pred[1, 1:4] = 255
        gt[1:3, 1:4] = 255
        polygon = [[1, 1], [3, 1], [3, 3], [1, 3]]
        row = coverage(pred, gt, np.zeros_like(pred), polygon)
        self.assertTrue(row['available'])
        self.assertEqual(row['target_area_px'], 9)
        self.assertAlmostEqual(row['predicted_rho'], 1 / 3)
        self.assertAlmostEqual(row['gt_rho'], 2 / 3)
        self.assertAlmostEqual(row['absolute_error'], 1 / 3)

    def test_target_coverage_refuses_clipping_ignore_and_degenerate_geometry(self):
        coverage = self.function('candidate_target_coverage')
        mask = np.zeros((5, 5), np.uint8)
        cases = (
            ([[-.1, 1], [3, 1], [3, 3]], 'outside_roi'),
            ([[1, 1], [5, 1], [3, 3]], 'outside_roi'),
            ([[3, 1], [4.8, 1], [4.8, 3], [3, 3]], 'outside_roi'),
            ([[1, 1], [2, 2], [3, 3]], 'degenerate_polygon'),
            ([[1, 1], [1, 1], [3, 3]], 'degenerate_polygon'),
            ([[1, 1], [3, 1]], 'invalid_polygon'),
            ([[1, 1], [3, float('nan')], [3, 3]], 'invalid_polygon'),
        )
        for polygon, reason in cases:
            with self.subTest(polygon=polygon):
                row = coverage(mask, mask, mask, polygon)
                self.assertFalse(row['available'])
                self.assertEqual(row['reason'], reason)
                self.assertIsNone(row['absolute_error'])
        ignore = mask.copy()
        ignore[2, 2] = 255
        row = coverage(mask, mask, ignore, [[1, 1], [3, 1], [3, 3], [1, 3]])
        self.assertFalse(row['available'])
        self.assertEqual(row['reason'], 'ignore_overlap')


if __name__ == '__main__':
    unittest.main()
