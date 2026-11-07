"""Synthetic fixtures validate software, never supply real research outcomes."""
import csv
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from dmf.vision.contracts import FramePacket, VisionResult
from dmf.vision.image_io import write_image


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def dataset(self, count=2):
        rows = []
        for i in range(count):
            image = np.full((80, 100, 3), 210, np.uint8)
            image[25:55, 35:65] = 10
            mask = np.zeros((80, 100), np.uint8)
            mask[25:55, 35:65] = 255
            write_image(self.root / f'image{i}.png', image)
            write_image(self.root / f'mask{i}.png', mask)
            rows.append(dict(video_id=f'clip{i}', parent_video_id=f'parent{i}',
                             source_frame_id=i, frame_id=i, source_sha256=str(i + 1) * 64,
                             frame_path=f'image{i}.png', mask_path=f'mask{i}.png',
                             mask_reviewed='True', state_gt='Unknown', state_reviewed='False',
                             roi_x=0, roi_y=0, split='unassigned'))
        return self.write_rows(rows), rows

    def write_rows(self, rows):
        path = self.root / 'reviewed.csv'
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_unknown_state_is_accepted_and_snapshot_is_exact(self):
        from dmf.segmentation_research.data import freeze_samples, load_reviewed, sha256
        path, _ = self.dataset()
        samples = load_reviewed(path)
        frozen = freeze_samples(samples, self.root / 'snapshot')
        copied = load_reviewed(frozen)
        self.assertEqual(len(copied), 2)
        self.assertEqual(sha256(samples[0].mask_path), sha256(copied[0].mask_path))
        self.assertEqual(copied[0].metadata['state_gt'], 'Unknown')

    def test_unreviewed_mask_is_rejected(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        rows[0]['mask_reviewed'] = 'False'
        with self.assertRaisesRegex(ValueError, 'reviewed'):
            load_reviewed(self.write_rows(rows))

    def test_duplicate_source_frame_alias_is_rejected(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        rows[1]['source_sha256'] = rows[0]['source_sha256']
        rows[1]['source_frame_id'] = rows[0]['source_frame_id']
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_reviewed(self.write_rows(rows))

    def test_same_parent_cannot_cross_splits(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        rows[1]['parent_video_id'] = rows[0]['parent_video_id']
        rows[0]['split'], rows[1]['split'] = 'train', 'test'
        with self.assertRaisesRegex(ValueError, 'leakage|identity'):
            load_reviewed(self.write_rows(rows))

    def test_source_hash_alias_cannot_cross_splits(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        rows[1]['source_sha256'] = rows[0]['source_sha256']
        rows[0]['split'], rows[1]['split'] = 'train', 'test'
        with self.assertRaisesRegex(ValueError, 'leakage'):
            load_reviewed(self.write_rows(rows))

    def test_known_session_cannot_cross_splits(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        for row in rows:
            row['session_id'] = 'actual_session_A'
        rows[0]['split'], rows[1]['split'] = 'train', 'val'
        with self.assertRaisesRegex(ValueError, 'leakage'):
            load_reviewed(self.write_rows(rows))

    def test_external_human_grouping_prevents_video_only_split_leakage(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        rows[0]['split'], rows[1]['split'] = 'train', 'test'
        groups = self.root / 'groups.json'
        groups.write_text(json.dumps(dict(schema='dmf_segmentation_source_groups_v1', sources=[
            dict(source_sha256=r['source_sha256'], chip_id='shared_chip_group_1',
                 session_id='shared_loading_round_1') for r in rows])), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'leakage'):
            load_reviewed(self.write_rows(rows), groups=groups)

    def test_grouping_requires_complete_source_coverage(self):
        from dmf.segmentation_research.data import load_reviewed
        path, _ = self.dataset()
        groups = self.root / 'groups.json'
        groups.write_text(json.dumps(dict(schema='dmf_segmentation_source_groups_v1', sources=[])), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'group'):
            load_reviewed(path, groups=groups)

    def test_unassigned_is_not_a_formal_split(self):
        from dmf.segmentation_research.data import load_reviewed
        path, _ = self.dataset()
        with self.assertRaisesRegex(ValueError, 'split'):
            load_reviewed(path, formal=True)

    def test_bad_mask_size_and_nonbinary_are_rejected(self):
        from dmf.segmentation_research.data import load_reviewed
        path, _ = self.dataset()
        for bad in (np.zeros((20, 20), np.uint8), np.full((80, 100), 127, np.uint8)):
            write_image(self.root / 'mask0.png', bad)
            with self.assertRaises(ValueError):
                load_reviewed(path)

    def test_blank_mask_path_is_not_silently_dropped(self):
        from dmf.segmentation_research.data import load_reviewed
        _, rows = self.dataset()
        rows[0]['mask_path'] = ''
        with self.assertRaises(ValueError):
            load_reviewed(self.write_rows(rows))

    def test_otsu_selects_dark_object_not_border_distractor(self):
        from dmf.segmentation_research.baselines import ThresholdBaseline
        image = np.full((100, 100, 3), 220, np.uint8)
        image[:15, :] = 0
        image[40:65, 40:65] = 5
        packet = FramePacket('fixture', 0, 0., 'synthetic_fixture', image)
        result = ThresholdBaseline('otsu').process(packet)
        self.assertTrue(result.detected)
        self.assertEqual(result.mask[50, 50], 255)
        self.assertEqual(result.mask[5, 50], 0)
        self.assertAlmostEqual(result.centroid_px[0], 52., delta=1)

    def test_baselines_empty_image_and_binary_shape(self):
        from dmf.segmentation_research.baselines import ThresholdBaseline
        for name in ('otsu', 'adaptive'):
            packet = FramePacket('fixture', 0, 0., 'synthetic_fixture',
                                 np.full((80, 100, 3), 220, np.uint8))
            result = ThresholdBaseline(name).process(packet)
            self.assertFalse(result.detected)
            result.validate(packet.image_bgr.shape)

    def test_invalid_baseline_parameters_are_rejected(self):
        from dmf.segmentation_research.baselines import ThresholdBaseline
        for parameters in ({'blur_kernel': 4}, {'adaptive_block': 2}, {'min_area_px': -1},
                           {'close_iterations': -1}, {'adaptive_c': float('nan')}):
            with self.assertRaises(ValueError):
                ThresholdBaseline('otsu', parameters)

    def test_missing_failed_and_empty_predictions_keep_denominator(self):
        from dmf.segmentation_research.evaluation import score_prediction, summarize_rows
        gt = np.zeros((12, 12), np.uint8)
        gt[3:7, 3:7] = 255
        empty = VisionResult(np.zeros_like(gt), None, 0, 0, 1, False, 'NO_CANDIDATE')
        rows = []
        for prediction in (None, empty):
            rows.append(dict(method='fixture', parent_video_id='p',
                             **score_prediction(prediction, gt)))
        stats = summarize_rows(rows)[0]
        self.assertEqual(stats['images'], 2)
        self.assertEqual(stats['mean_dice'], 0)
        self.assertEqual(stats['positive_gt_misses'], 2)
        self.assertEqual(stats['centroid_denominator'], 0)
        self.assertIsNone(stats['mean_centroid_error_px'])

    def test_centroid_uses_mask_pixels_not_model_reported_centroid(self):
        from dmf.segmentation_research.evaluation import score_prediction
        gt = np.zeros((12, 12), np.uint8)
        gt[3:6, 3:6] = 255
        pred = np.zeros_like(gt)
        pred[3:6, 6:9] = 255
        result = VisionResult(pred, (0, 0), 9, 1, 1, True)
        self.assertEqual(score_prediction(result, gt)['centroid_error_px'], 3.)

    def test_video_macro_does_not_weight_longer_video_more(self):
        from dmf.segmentation_research.evaluation import summarize_rows
        def row(parent, dice):
            return dict(method='m', parent_video_id=parent, dice=dice, iou=dice,
                        precision=dice, recall=dice, centroid_error_px=None,
                        detected=False, empty_mask=True, prediction_missing=True,
                        positive_gt=True, inference_error='fixture')
        rows = [row('a', 1), row('a', 1), row('a', 1), row('b', 0)]
        result = summarize_rows(rows)[0]
        self.assertEqual(result['mean_dice'], .75)
        self.assertEqual(result['video_macro_dice'], .5)
        self.assertIsNone(result['confidence_interval'])

    def test_runner_retains_inference_errors_and_refuses_overwrite(self):
        from dmf.segmentation_research.evaluation import run_pilot
        path, _ = self.dataset()
        class Broken:
            def process(self, packet):
                raise RuntimeError('fixture failure')
        config = dict(data_kind='synthetic_fixture', warmup=1, repeats=2, opencv_threads=1,
                      parameters={})
        output = self.root / 'results'
        manifest = run_pilot(path, output, config, methods={'broken': Broken()})
        self.assertEqual(manifest['summary'][0]['images'], 2)
        self.assertEqual(manifest['summary'][0]['positive_gt_misses'], 2)
        self.assertEqual(manifest['data_kind'], 'synthetic_fixture')
        self.assertFalse(manifest['formal_test'])
        self.assertTrue((output / 'per_image.csv').is_file())
        self.assertEqual(len(list((output / 'predictions').rglob('*.png'))), 2)
        with self.assertRaises(FileExistsError):
            run_pilot(path, output, config, methods={'broken': Broken()})

    def test_actual_cli_defaults_produce_two_methods_and_same_inputs(self):
        from run_segmentation_pilot import main
        path, _ = self.dataset()
        config = self.root / 'config.json'
        config.write_text(json.dumps(dict(data_kind='synthetic_fixture', warmup=0,
                                         repeats=1, opencv_threads=1, parameters={})), encoding='utf-8')
        out = self.root / 'cli_result'
        with contextlib.redirect_stdout(io.StringIO()):
            main(['--reviewed', str(path), '--output', str(out), '--config', str(config)])
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual({r['method'] for r in manifest['summary']}, {'otsu', 'adaptive'})
        self.assertTrue(all(r['images'] == 2 for r in manifest['summary']))
        self.assertEqual(manifest['unet']['status'], 'not_evaluated_no_real_weights')

    def test_review_page_has_all_methods_and_verifies_artifact_hashes(self):
        from dmf.segmentation_research.evaluation import run_pilot
        from dmf.segmentation_research.review import write_review
        path, _ = self.dataset()
        out = self.root / 'review_run'
        config = dict(data_kind='synthetic_fixture', warmup=0, repeats=1, opencv_threads=1, parameters={})
        run_pilot(path, out, config)
        html_path = write_review(out)
        html = html_path.read_text(encoding='utf-8')
        self.assertIn('not a held-out test', html)
        self.assertEqual(html.count('class="sample"'), 2)
        self.assertIn('predictions/otsu/sample_0000.png', html)
        self.assertIn('predictions/adaptive/sample_0000.png', html)
        with self.assertRaises(FileExistsError):
            write_review(out)
        (out / 'per_image.csv').write_text('corrupted', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash'):
            write_review(out, filename='another_review.html')


if __name__ == '__main__':
    unittest.main()
