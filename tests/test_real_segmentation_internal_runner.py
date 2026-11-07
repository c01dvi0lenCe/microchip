"""Offline runner contract on tiny independent train/val fixtures."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np


RUNNER = Path(__file__).resolve().parents[1] / 'scripts/run_real_segmentation_internal_baselines.py'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class InternalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.out = Path(self.temp.name) / 'results'
        self.rows = []
        for index, split in enumerate(('train', 'val')):
            image = np.full((12, 20, 3), 255, np.uint8)
            image[3:8, 5:10] = 0
            gt = np.zeros((12, 20), np.uint8)
            gt[3:8, 5:10] = 255
            ignore = np.zeros_like(gt)
            ignore[3, 5] = 255
            row = dict(sample_id=f'S{index}', parent_video_id=f'V{index}',
                       source_sha256=str(index + 1) * 64, source_frame_id='10',
                       timestamp_s='1.0', roi_xywh='[2, 4, 20, 12]',
                       roi_x='2', roi_y='4', roi_w='20', roi_h='12', width='20', height='12',
                       split=split, proposed_split=split, operation_group=f'O{index}',
                       capture_group='same_unknown', instance_id_draft='local1',
                       split_protocol='same_capture_internal_research_only',
                       semantic_definition='all_actual_droplets',
                       mask_reviewed='True', exclusion_reviewed='True', boundary_reviewed='True',
                       traditional_baseline_released='True', formal_test='False')
            for key, array, folder in [('frame_path', image, 'images'), ('mask_path', gt, 'semantic_masks'),
                                        ('exclusion_mask_path', ignore, 'ignore_masks')]:
                path = self.root / 'G2/reviewed_snapshot' / folder / f'S{index}.png'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(cv2.imencode('.png', array)[1].tobytes())
                row[key] = path.relative_to(self.root / 'G2').as_posix()
                row[key + '_sha256'] = digest(path)
            self.rows.append(row)
        self.write_rows()
        bg = self.root / 'backgrounds/bg.png'
        bg.parent.mkdir()
        bg.write_bytes(cv2.imencode('.png', np.full((12, 20, 3), 255, np.uint8))[1].tobytes())
        self.refs = [dict(reference_id='B0', parent_video_id='V0', source_sha256='1' * 64,
                          source_frame_id=0, timestamp_s=0., roi_xywh=[2, 4, 20, 12],
                          background_path='bg.png', background_sha256=digest(bg), usable=True,
                          background_review_kind='assistant_visual_review', linked_sample_ids=['S0'])]
        self.write_refs()
        self.config = dict(common_input_hw=16, warmup=0, repeats=1, opencv_threads=1,
                           blur_kernel=5, close_kernel=3, close_iterations=1,
                           background_threshold=20, hardware_label='IntelUltra9CPU')
        (self.root / 'baseline_config.json').write_text(json.dumps(self.config))

    def module(self):
        self.assertTrue(RUNNER.is_file(), 'the internal baseline runner is not implemented')
        spec = importlib.util.spec_from_file_location('internal_baseline_runner_test', RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def write_rows(self):
        with (self.root / 'G2/frozen_samples.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def write_refs(self):
        (self.root / 'backgrounds/reviewed_references.json').write_text(json.dumps(self.refs))

    def csv(self, name):
        with (self.out / name).open(encoding='utf-8-sig', newline='') as stream:
            return list(csv.DictReader(stream))

    def test_planned_rows_unavailable_denominators_and_native_predictions(self):
        module = self.module()
        before = {str(p): digest(p) for p in self.root.rglob('*') if p.is_file()}
        previous_threads = cv2.getNumThreads()
        result = module.run(self.root, self.out)
        rows = self.csv('per_image.csv')
        self.assertEqual(len(rows), 4)
        unavailable = next(r for r in rows if r['status'] == 'unavailable_background')
        self.assertEqual(unavailable['prediction_path'], '')
        self.assertEqual(unavailable['dice'], '')
        self.assertEqual(unavailable['image_level_miss'], '')
        for row in rows:
            self.assertEqual(row['centroid_error_px'], '')
            self.assertEqual(row['centroid_reason'], 'instance_GT_not_reviewed')
            if row['prediction_path']:
                path = (self.out / row['prediction_path']).resolve()
                self.assertTrue(path.is_relative_to(self.out.resolve()))
                array = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
                self.assertEqual(array.shape, (12, 20))
                self.assertTrue(np.isin(array, [0, 255]).all())
                self.assertEqual(digest(path), row['prediction_sha256'])
        total = next(r for r in self.csv('summary.csv') if r['method'] == 'background' and r['split'] == 'all')
        self.assertEqual((total['planned'], total['eligible'], total['unavailable']), ('2', '1', '1'))
        self.assertEqual(total['positive_gt_eligible'], '1')
        self.assertEqual(total['positive_gt_planned'], '2')
        self.assertEqual(len(self.csv('common_background_subset.csv')), 2)
        self.assertEqual(len(self.csv('timings.csv')), 3)
        self.assertEqual(cv2.getNumThreads(), previous_threads)
        self.assertEqual(before, {str(p): digest(p) for p in self.root.rglob('*') if p.is_file()})
        manifest = json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['input_hashes_before'], manifest['input_hashes_after'])
        self.assertFalse(manifest['formal_test'])
        self.assertFalse(manifest['simulation'])
        self.assertTrue(result['inputs_unchanged'])

    def test_future_background_rejected_before_output(self):
        self.refs[0]['source_frame_id'] = 11
        self.write_refs()
        with self.assertRaisesRegex(ValueError, 'earlier'):
            self.module().run(self.root, self.out)
        self.assertFalse(self.out.exists())

    def test_review_false_string_and_unassigned_are_rejected(self):
        module = self.module()
        for field, value in [('mask_reviewed', 'False'), ('exclusion_reviewed', 'false'),
                             ('boundary_reviewed', '1'), ('split', 'unassigned'), ('split', 'test')]:
            with self.subTest(field=field, value=value):
                old = self.rows[0][field]
                self.rows[0][field] = value
                self.write_rows()
                with self.assertRaises(ValueError):
                    module.run(self.root, self.out)
                self.assertFalse(self.out.exists())
                self.rows[0][field] = old

    def test_leakage_and_duplicate_original_rejected(self):
        module = self.module()
        for change in [dict(parent_video_id='V0'), dict(source_sha256='1' * 64),
                       dict(operation_group='O0'), dict(sample_id='S0')]:
            old = dict(self.rows[1])
            self.rows[1].update(change)
            self.write_rows()
            with self.assertRaises(ValueError):
                module.run(self.root, self.out)
            self.rows[1] = old

    def test_hash_roi_binary_and_path_escape_rejected(self):
        module = self.module()
        for change in [dict(frame_path_sha256='0' * 64), dict(roi_xywh='[2,4,19,12]'),
                       dict(source_frame_id='1.5'), dict(timestamp_s='nan'),
                       dict(frame_path='../outside.png')]:
            old = dict(self.rows[0])
            self.rows[0].update(change)
            self.write_rows()
            with self.assertRaises(ValueError):
                module.run(self.root, self.out)
            self.rows[0] = old

    def test_error_is_scored_empty_and_all_repeats_retained(self):
        module = self.module()
        config = dict(self.config, warmup=1, repeats=2)
        with mock.patch.object(module, 'otsu_mask', side_effect=RuntimeError('fixture failure')):
            module.run(self.root, self.out, config=config)
        rows = [r for r in self.csv('per_image.csv') if r['method'] == 'otsu']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['status'] == 'error' and r['dice'] == '0.0' and
                            r['image_level_miss'] == 'True' for r in rows))
        calls = [r for r in self.csv('timings.csv') if r['method'] == 'otsu']
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(r['status'] == 'error' for r in calls))

    def test_ignore_scoring_and_prediction_has_no_gt_arguments(self):
        module = self.module()
        def prediction(image, **kwargs):
            self.assertFalse({'gt', 'ignore', 'mask', 'target', 'polygon'} & set(kwargs))
            return np.full(image.shape[:2], 255, np.uint8)
        with mock.patch.object(module, 'otsu_mask', side_effect=prediction):
            module.run(self.root, self.out)
        row = next(r for r in self.csv('per_image.csv') if r['method'] == 'otsu')
        self.assertEqual(row['valid_pixels'], '239')
        self.assertEqual(row['tp'], '24')
        self.assertEqual(row['fp'], '215')

    def test_causal_gate_called_for_each_eligible_and_threads_forced(self):
        module = self.module()
        original = module.assert_causal_background
        with mock.patch.object(module, 'assert_causal_background', wraps=original) as causal:
            with mock.patch.object(module, 'otsu_mask', wraps=module.otsu_mask) as predict:
                module.run(self.root, self.out)
        self.assertGreaterEqual(causal.call_count, 1)
        self.assertEqual(predict.call_count, 2)

    def test_video_map_diagnostic_offsets_native_roi_and_hashes_calibration(self):
        folder = self.root / 'maps'
        folder.mkdir()
        polygon_path = folder / 'polygons.json'
        polygon_path.write_text(json.dumps(dict(electrodes=[dict(control_id=7,
            polygon_native_px=[[12, 5], [16, 5], [16, 8], [12, 8]])])))
        calibration = folder / 'calibration.json'
        calibration.write_text('{}')
        mapping = dict(videos=dict(V0=dict(polygon_path='polygons.json', polygon_sha256=digest(polygon_path),
                       calibration_manifest='calibration.json', calibration_sha256=digest(calibration),
                       mapping_candidate=True)))
        (folder / 'mapping_sources.json').write_text(json.dumps(mapping))
        self.rows[0]['task_target_electrode_recorded'] = '7'
        self.rows[1]['task_target_electrode_recorded'] = ''
        self.write_rows()
        self.module().run(self.root, self.out)
        row = next(r for r in self.csv('per_image.csv') if r['sample_id'] == 'S0')
        self.assertEqual(row['target_coverage_available'], 'True')
        manifest = json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('maps/calibration.json', manifest['input_hashes_before'])

    def test_repeat_nondeterminism_is_flagged_without_best_of_n_selection(self):
        module = self.module()
        count = [0]
        def alternating(image, **kwargs):
            count[0] += 1
            return np.full(image.shape[:2], 0 if count[0] % 2 else 255, np.uint8)
        with mock.patch.object(module, 'otsu_mask', side_effect=alternating):
            module.run(self.root, self.out, dict(self.config, repeats=2))
        rows = [r for r in self.csv('per_image.csv') if r['method'] == 'otsu']
        self.assertTrue(all(r['deterministic'] == 'False' and r['dice'] == '0.0' for r in rows))

    def test_first_timed_success_is_scored_even_when_later_repeat_errors(self):
        module = self.module()
        count = [0]
        def later_error(image, **kwargs):
            count[0] += 1
            if count[0] % 2 == 0:
                raise RuntimeError('later repeat failed')
            return np.full(image.shape[:2], 255, np.uint8)
        with mock.patch.object(module, 'otsu_mask', side_effect=later_error):
            module.run(self.root, self.out, dict(self.config, repeats=2))
        rows = [r for r in self.csv('per_image.csv') if r['method'] == 'otsu']
        self.assertTrue(all(r['status'] == 'ok' and r['empty_mask'] == 'False' for r in rows))
        self.assertTrue(all(r['timed_error_calls'] == '1' and r['timed_repeat_has_errors'] == 'True'
                            and r['deterministic'] == 'False' for r in rows))
        for row in rows:
            prediction = cv2.imdecode(np.frombuffer((self.out / row['prediction_path']).read_bytes(), np.uint8), 0)
            self.assertTrue(np.all(prediction == 255))

    def test_first_timed_error_is_empty_even_when_later_repeat_succeeds(self):
        module = self.module()
        count = [0]
        def first_error(image, **kwargs):
            count[0] += 1
            if count[0] % 2:
                raise RuntimeError('first repeat failed')
            return np.full(image.shape[:2], 255, np.uint8)
        with mock.patch.object(module, 'otsu_mask', side_effect=first_error):
            module.run(self.root, self.out, dict(self.config, repeats=2))
        rows = [r for r in self.csv('per_image.csv') if r['method'] == 'otsu']
        self.assertTrue(all(r['status'] == 'error' and r['empty_mask'] == 'True' for r in rows))

    def test_split_manifest_hash_validation_and_artifact_ledger(self):
        split_manifest = self.root / 'G2/split_manifest.json'
        split_manifest.write_text(json.dumps(dict(frozen_samples_sha256=digest(self.root / 'G2/frozen_samples.csv'))))
        self.module().run(self.root, self.out)
        manifest = json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('G2/split_manifest.json', manifest['input_hashes_before'])
        self.assertEqual(manifest['source_code_hashes_before'], manifest['source_code_hashes_after'])
        for relative, expected in manifest['output_artifact_sha256'].items():
            self.assertEqual(digest(self.out / relative), expected)
        self.assertEqual(set(manifest['output_artifact_sha256']),
                         {p.relative_to(self.out).as_posix() for p in self.out.rglob('*')
                          if p.is_file() and p.name != 'manifest.json'})

    def test_split_manifest_csv_mismatch_rejected_before_output(self):
        (self.root / 'G2/split_manifest.json').write_text(json.dumps(dict(frozen_samples_sha256='0' * 64)))
        with self.assertRaisesRegex(ValueError, 'split manifest'):
            self.module().run(self.root, self.out)
        self.assertFalse(self.out.exists())

    def test_source_code_change_during_run_invalidates_manifest(self):
        module = self.module()
        original = module._sha
        calls = [0]
        def changing_digest(path):
            if Path(path).resolve() == RUNNER.resolve():
                calls[0] += 1
                if calls[0] > 1:
                    return '0' * 64
            return original(path)
        with mock.patch.object(module, '_sha', side_effect=changing_digest):
            with self.assertRaisesRegex(RuntimeError, 'source code changed'):
                module.run(self.root, self.out)
        manifest = json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))
        self.assertFalse(manifest['source_code_unchanged'])

    def test_input_mutation_is_detected_and_manifest_invalidated(self):
        module = self.module()
        original = module.otsu_mask
        def mutate(image, **kwargs):
            path = self.root / 'G2' / self.rows[0]['mask_path']
            path.write_bytes(path.read_bytes() + b'changed')
            return original(image, **kwargs)
        with mock.patch.object(module, 'otsu_mask', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'inputs changed'):
                module.run(self.root, self.out)
        manifest = json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))
        self.assertFalse(manifest['inputs_unchanged'])


if __name__ == '__main__':
    unittest.main()
