"""Synthetic geometry verifies software only, never real-chip accuracy."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('dmf.vision.design_registration')
        self.assertIsNotNone(spec, 'offline design registration is not implemented')
        from dmf.vision import design_registration
        self.r = design_registration
        self.w = dict(image_size=[200, 200], points=[], fit_freeze=None)
        for i, (x, y) in enumerate([(10, 10), (110, 10), (110, 110), (10, 110),
                                    (60, 30), (80, 60), (60, 90), (30, 60)]):
            self.w['points'].append(self.point(f'F{i}', 'fit', x, y))
        for i, (x, y) in enumerate([(30, 30), (90, 30), (90, 90), (30, 90)]):
            p = self.point(f'C{i}', 'check', x, y)
            p.update(status='pending', observed_px=None)
            self.w['points'].append(p)
        self.r.seal_catalog(self.w)

    @staticmethod
    def point(name, role, x, y):
        return dict(point_id=name, role=role, control_id=int(x*200+y), vertex_index=0,
                    map_mm=[x, y], suggested_px=[x+1, y+1], observed_px=[x, y],
                    status='confirmed', observation_method='manual_native_click',
                    reviewer='test reviewer', reviewed_utc='2026-10-22T00:00:00+00:00',
                    exclusion_reason='')

    def test_identity_and_independent_errors(self):
        self.r.freeze_fit(self.w)
        for p in self.w['points'][8:]:
            self.r.record_observation(self.w, p['point_id'],
                [p['map_mm'][0]+3, p['map_mm'][1]+4], 'reviewer')
        result = self.r.evaluate_registration(self.w)
        self.assertEqual(result['status'], 'checked_descriptive_only')
        for unit in ('px', 'design_mm'):
            for metric in ('rmse', 'p95', 'max'):
                self.assertAlmostEqual(result[f'{metric}_{unit}'], 5, places=5)
        self.assertEqual(result['check_total'], 4)
        self.assertFalse(result['physical_mm_accuracy_verified'])

    def test_checks_cannot_affect_fit(self):
        before = self.r.fit_transform(self.w['points'])
        for p in self.w['points'][8:]: p['observed_px'] = [150, 150]
        np.testing.assert_allclose(before, self.r.fit_transform(self.w['points']))

    def test_projective_transform(self):
        h = np.array([[1.2, .1, 3], [.05, .9, 5], [.0003, .0001, 1.]])
        for p in self.w['points']:
            p['observed_px'] = list(self.r.project([p['map_mm']], np.linalg.inv(h))[0])
        self.r.seal_catalog(self.w)
        fitted = self.r.fit_transform(self.w['points'])
        np.testing.assert_allclose(fitted/fitted[2,2], h, atol=1e-5)

    def test_pending_does_not_use_navigation_as_truth(self):
        for p in self.w['points']:
            p.update(status='pending', observed_px=None)
        result = self.r.evaluate_registration(self.w)
        self.assertEqual(result['status'], 'pending_fit')
        self.assertIsNone(result['rmse_px'])
        self.assertEqual(result['check_missing'], 4)

    def test_missing_and_excluded_check_stay_in_denominator(self):
        self.r.freeze_fit(self.w)
        for p in self.w['points'][8:]:
            self.r.record_observation(self.w, p['point_id'], p['map_mm'], 'reviewer')
        self.w['points'][8].update(status='pending', observed_px=None)
        self.w['points'][9].update(status='excluded', observed_px=None,
                                   exclusion_reason='occluded', reviewer='reviewer')
        result = self.r.evaluate_registration(self.w)
        self.assertEqual(result['check_total'], 4)
        self.assertEqual(result['check_missing'], 1)
        self.assertEqual(result['check_excluded'], 1)
        self.assertEqual(result['check_confirmed'], 2)
        self.assertIsNone(result['rmse_px'])
        self.assertEqual(result['status'], 'pending_checks')

    def test_catalog_role_tampering_rejected(self):
        self.w['points'][8]['role'] = 'fit'
        with self.assertRaisesRegex(ValueError, 'catalog'):
            self.r.evaluate_registration(self.w)

    def test_frozen_fit_tampering_rejected(self):
        self.r.freeze_fit(self.w)
        self.w['points'][0]['observed_px'][0] += 1
        with self.assertRaisesRegex(ValueError, 'frozen'):
            self.r.evaluate_registration(self.w)

    def test_duplicate_feature_rejected(self):
        self.w['points'][8]['control_id'] = self.w['points'][0]['control_id']
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.r.seal_catalog(self.w)

    def test_coincident_check_and_fit_rejected(self):
        self.w['points'][8]['map_mm'] = list(self.w['points'][0]['map_mm'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.r.seal_catalog(self.w)

    def test_collinear_fit_rejected(self):
        for i, p in enumerate(self.w['points'][:8]):
            p['map_mm'] = [i, i]
        with self.assertRaisesRegex(ValueError, 'degenerate'):
            self.r.fit_transform(self.w['points'])

    def test_unreviewed_fit_not_accepted(self):
        for p in self.w['points'][:8]: p['reviewer'] = ''
        with self.assertRaisesRegex(ValueError, 'review'):
            self.r.freeze_fit(self.w)

    def test_point_outside_native_image_rejected(self):
        self.w['points'][0]['observed_px'] = [201, 10]
        with self.assertRaisesRegex(ValueError, 'image'):
            self.r.freeze_fit(self.w)

    def test_check_click_before_fit_freeze_rejected(self):
        with self.assertRaisesRegex(ValueError, 'freeze'):
            self.r.record_observation(self.w, 'C0', [30,30], 'reviewer')

    def test_record_observation_requires_actual_click_and_reviewer(self):
        with self.assertRaisesRegex(ValueError, 'reviewer'):
            self.r.record_observation(self.w, 'F0', [12,12], '')
        self.r.record_observation(self.w, 'F0', [12,12], 'reviewer')
        self.assertEqual(self.w['points'][0]['observed_px'], [12.,12.])
        self.assertEqual(self.w['points'][0]['observation_method'], 'manual_native_click')

    def test_fit_edit_after_freeze_rejected(self):
        self.r.freeze_fit(self.w)
        with self.assertRaisesRegex(ValueError, 'frozen'):
            self.r.record_observation(self.w, 'F0', [12,12], 'reviewer')

    def test_bad_projective_matrix_rejected(self):
        with self.assertRaises(ValueError): self.r.project([[1,2]], np.zeros((3,3)))
        with self.assertRaises(ValueError): self.r.project([[1,float('nan')]], np.eye(3))

    def test_invalid_design_map_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'map.json'; path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash'):
                self.r.load_design_map(path, '0'*64)

    def test_count_and_units_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'map.json'
            path.write_text(json.dumps(dict(electrode_count=0, electrodes=[],
                                            coordinate_system=dict(unit='pixel'))),encoding='utf-8')
            with self.assertRaises(ValueError): self.r.load_design_map(path)

    def test_hand_computable_nonconstant_percentile(self):
        self.r.freeze_fit(self.w)
        for p,dx,dy in zip(self.w['points'][8:],[0,3,6,0],[0,4,8,0]):
            self.r.record_observation(self.w,p['point_id'],
                [p['map_mm'][0]+dx,p['map_mm'][1]+dy],'reviewer')
        result=self.r.evaluate_registration(self.w)
        self.assertAlmostEqual(result['rmse_px'],np.sqrt(125/4),places=5)
        self.assertAlmostEqual(result['p95_px'],9.25,places=5)
        self.assertAlmostEqual(result['max_px'],10,places=5)

    def test_no_check_confirmation_before_fit_freeze(self):
        self.w['points'][8].update(status='confirmed',observed_px=[30,30])
        with self.assertRaisesRegex(ValueError,'after fit freeze'):self.r.freeze_fit(self.w)

    def test_published_checks_cannot_be_reclicked(self):
        self.r.freeze_fit(self.w)
        for p in self.w['points'][8:]:
            self.r.record_observation(self.w,p['point_id'],p['map_mm'],'reviewer')
        self.assertTrue(hasattr(self.r,'seal_evaluation'),'evaluation freeze is missing')
        self.r.seal_evaluation(self.w)
        with self.assertRaisesRegex(ValueError,'sealed'):
            self.r.record_observation(self.w,'C0',[31,31],'reviewer')

    def test_published_check_tampering_rejected(self):
        self.r.freeze_fit(self.w)
        for p in self.w['points'][8:]:
            self.r.record_observation(self.w,p['point_id'],p['map_mm'],'reviewer')
        self.assertTrue(hasattr(self.r,'seal_evaluation'),'evaluation freeze is missing')
        self.r.seal_evaluation(self.w)
        self.w['points'][8]['observed_px']=[31,31]
        with self.assertRaisesRegex(ValueError,'sealed'):self.r.evaluate_registration(self.w)


if __name__ == '__main__': unittest.main()
