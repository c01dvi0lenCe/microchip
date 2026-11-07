"""Synthetic interface tests, not measurements of real droplets."""
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from dmf.experiment.mask_cache import write_cache, load_cache
from dmf.experiment.benchmark import run_variant


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.map = dict(metadata=dict(coordinate_unit='pitch', mode='simulation'),
                        polygons={'1': [[0, 0], [1, 0], [1, 1], [0, 1]],
                                  '2': [[1, 0], [2, 0], [2, 1], [1, 1]]},
                        lower=[0, 0], scale=40, shape=[40, 80])
        self.tasks = [dict(step_id=0, source=1, target=2, start_s=0., end_s=2., applied_s=0.)]
        self.params = dict(centroid_tolerance=.2, eta_arr=.85, eta_release=.08,
                           arrival_frames=5, arrival_duration_s=.25,
                           evidence_max_gap_s=.18, arrival_max_centroid_span_mm=.11)

    def frames(self):
        rows = []
        for i in range(8):
            mask = np.zeros((40, 80), np.uint8)
            cv2.circle(mask, (60, 20), 8, 255, -1)
            rows.append(dict(frame_id=i, exposure_s=.1+i*.05, available_s=.14+i*.05,
                             mask=mask, confidence=1.))
        return rows

    def cache(self, **overrides):
        args = dict(map_snapshot=self.map, tasks=self.tasks, parameters=self.params,
                    frames=self.frames(), clock_domain='simulation', coordinate_unit='pitch')
        args.update(overrides)
        return write_cache(self.root/'cache', **args)

    def test_roundtrip_and_missing_preserved(self):
        rows = self.frames(); rows[2]['mask'] = None
        self.cache(frames=rows)
        cache = load_cache(self.root/'cache')
        self.assertEqual(len(cache['frames']), 8)
        self.assertIsNone(cache['frames'][2]['mask'])

    def test_duplicate_and_truth_rejected(self):
        rows = self.frames(); rows[1]['frame_id'] = 0
        with self.assertRaises(ValueError): self.cache(frames=rows)
        with self.assertRaises(ValueError): self.cache(parameters={'truth_radius': .1})

    def test_mixed_units_and_incomplete_task_rejected(self):
        with self.assertRaises(ValueError): self.cache(coordinate_unit='mm')
        with self.assertRaises(ValueError): self.cache(tasks=[dict(step_id=0)])

    def test_hash_corruption_and_overwrite_rejected(self):
        self.cache()
        with self.assertRaises(FileExistsError): self.cache()
        mask = next((self.root/'cache'/'masks').glob('*.npy'))
        mask.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): load_cache(self.root/'cache')

    def test_all_variants_shared_input_and_one_event(self):
        self.cache()
        outputs = [run_variant(self.root/'cache', v, self.root/v)
                   for v in ('S1', 'S2', 'S3', 'S4', 'no_spatial', 'no_temporal', 'no_validity')]
        self.assertEqual(len({o['input_sha256'] for o in outputs}), 1)
        self.assertTrue(all(len(o['events']) == 1 for o in outputs))
        self.assertLess(outputs[0]['events'][0]['timestamp_s'], outputs[3]['events'][0]['timestamp_s'])
        self.assertTrue(all(row['state'] == '' for row in outputs[0]['frames']))
        self.assertEqual(outputs[3]['clock_domain'], 'simulation')

    def test_old_frames_cannot_confirm_new_task(self):
        rows = self.frames()
        for row in rows: row['available_s'] += 1.
        tasks = [dict(step_id=0, source=1, target=2, start_s=1., end_s=2., applied_s=1.)]
        self.cache(frames=rows, tasks=tasks)
        result = run_variant(self.root/'cache', 'S4', self.root/'out')
        self.assertEqual(result['events'], [])
        self.assertEqual(len(result['frames']), 8)

    def test_prediction_has_no_reference_dependency(self):
        self.cache()
        first = run_variant(self.root/'cache', 'S4', self.root/'one')
        (self.root/'references.json').write_text(json.dumps({'arbitrary': 'changed truth'}))
        second = run_variant(self.root/'cache', 'S4', self.root/'two')
        self.assertEqual(first, second)

    def test_s2_keeps_source_release_gate(self):
        rows = self.frames()[:1]
        rows[0]['mask'][:] = 0
        cv2.rectangle(rows[0]['mask'], (37, 10), (78, 30), 255, -1)
        self.cache(frames=rows)
        result = run_variant(self.root/'cache', 'S2', self.root/'out')
        self.assertGreater(result['frames'][0]['eta_target'], .85)
        self.assertGreater(result['frames'][0]['eta_source'], .08)
        self.assertEqual(result['events'], [])

    def test_validity_ablation_keeps_motion_history(self):
        self.cache()
        result = run_variant(self.root/'cache', 'no_validity', self.root/'out')
        self.assertIsNotNone(result['frames'][1]['velocity'])

    def test_multiple_video_streams_cannot_pool_evidence(self):
        rows = self.frames()
        for i, row in enumerate(rows): row['video_id'] = 'A' if i < 3 else 'B'
        with self.assertRaises(ValueError): self.cache(frames=rows)

    def test_formal_thresholds_validated_before_ablation(self):
        params = dict(self.params, arrival_frames=1, arrival_duration_s=0.)
        self.cache(parameters=params)
        with self.assertRaises(ValueError): run_variant(self.root/'cache', 'S4', self.root/'out')


if __name__ == '__main__': unittest.main()
