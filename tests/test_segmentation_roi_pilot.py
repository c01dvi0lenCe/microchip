"""Small synthetic checks for the isolated native ROI preparation helpers."""
import importlib
from pathlib import Path
import tempfile
import unittest

import numpy as np


class RoiPilotTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('dmf.segmentation_research.roi_pilot')
        except ModuleNotFoundError:
            self.fail('ROI pilot helpers have not been implemented')

    def row(self, sample='s1', parent='v1', digest='a' * 64, split='train', frame=1):
        row = self.api().candidate_row(sample, parent, digest, frame,
            [0, 0, 20, 12], .5, 'transport_candidate', split, parent + '_op', 'track_1')
        row['split_protocol'] = 'same_capture_internal_research_only'
        return row

    def test_native_roi_clamps_position_without_resizing(self):
        fn = self.api().native_roi
        self.assertEqual(fn((2, 3), (20, 12), (100, 80)), [0, 0, 20, 12])
        self.assertEqual(fn((99, 79), (20, 12), (100, 80)), [80, 68, 20, 12])
        self.assertEqual(fn((50.5, 40.5), (20, 12), (100, 80)), [40, 34, 20, 12])

    def test_native_roi_rejects_bad_geometry(self):
        fn = self.api().native_roi
        for center, size, full in [((float('nan'), 2), (20, 12), (100, 80)),
                ((100, 1), (20, 12), (100, 80)), ((-1, 1), (20, 12), (100, 80)),
                ((1, 1), (101, 12), (100, 80)), ((1, 1), (20.5, 12), (100, 80)),
                ((1, 1), (0, 12), (100, 80)), ((1, 1), (20, 12), (100, float('inf')))]:
            with self.subTest(center=center, size=size), self.assertRaises(ValueError):
                fn(center, size, full)

    def test_draft_retains_all_dark_components_including_border_and_tiny(self):
        image = np.full((30, 40, 3), 220, np.uint8)
        image[0:4, 0:5] = 0
        image[12:20, 12:20] = 10
        image[25, 35] = 0
        original = image.copy()
        result = self.api().all_foreground_draft(image)
        self.assertEqual(result.shape, image.shape[:2])
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(set(np.unique(result)), {0, 255})
        self.assertTrue(all(result[y, x] == 255 for y, x in [(1, 1), (15, 15), (25, 35)]))
        np.testing.assert_array_equal(image, original)

    def test_draft_fills_small_internal_highlight_but_not_external_background(self):
        image = np.full((30, 40, 3), 220, np.uint8)
        image[5:20, 5:20] = 0
        image[10:12, 10:12] = 255
        mask = self.api().all_foreground_draft(image)
        self.assertEqual(mask[10, 10], 255)
        self.assertEqual(mask[25, 25], 0)

    def test_draft_rejects_bad_images(self):
        for image in [np.zeros((0, 2, 3), np.uint8), np.zeros((2, 2, 4), np.uint8),
                      np.zeros((2, 2, 3), float)]:
            with self.assertRaises(ValueError):
                self.api().all_foreground_draft(image)

    def test_candidate_has_no_ground_truth_or_invented_identity(self):
        row = self.row()
        for flag in ['mask_reviewed', 'state_reviewed', 'instances_reviewed',
                     'exclusion_reviewed', 'boundary_reviewed', 'capture_group_confirmed']:
            self.assertIs(row[flag], False)
        for key in ['instance_id', 'task_target_instance_id', 'source_electrode', 'target_electrode',
                    'frame_path', 'mask_path', 'draft_mask_path', 'working_mask_path',
                    'exclusion_mask_path']:
            self.assertEqual(row[key], '')
        self.assertEqual(row['state_gt'], 'Unknown')
        self.assertEqual(row['state_draft'], 'Unknown')
        self.assertEqual(row['split'], 'unassigned')
        self.assertEqual(row['timestamp_source'], 'host_receive_relative_not_exposure')
        self.assertEqual(row['capture_group'], '2026-11-02_shared_or_unknown')
        self.assertEqual((row['width'], row['height'], row['roi_w'], row['roi_h']), (20, 12, 20, 12))
        self.assertEqual(row['instance_id_draft'], 'track_1')

    def test_candidate_rejects_invalid_provenance(self):
        fn = self.api().candidate_row
        base = ['s', 'v', 'a' * 64, 1, [0, 0, 20, 12], .1, 'candidate', 'train', 'op']
        for index, bad in [(2, 'z' * 64), (3, -1), (4, [0, 0, 0, 12]),
                           (5, float('nan')), (7, 'test')]:
            args = base.copy(); args[index] = bad
            with self.subTest(index=index), self.assertRaises(ValueError):
                fn(*args)

    def test_shared_capture_group_needs_explicit_internal_protocol(self):
        rows = [self.row(), self.row('s2', 'v2', 'b' * 64, 'val')]
        rows[1].pop('split_protocol')
        with self.assertRaisesRegex(ValueError, 'protocol'):
            self.api().validate_proposed_groups(rows)
        rows[1]['split_protocol'] = 'same_capture_internal_research_only'
        report = self.api().validate_proposed_groups(rows)
        self.assertTrue(report['valid'])
        self.assertFalse(report['batch_disjoint'])
        self.assertIn('NOT batch-disjoint', report['warning'])

    def test_proposal_rejects_parent_hash_and_operation_leakage(self):
        for field in ['parent_video_id', 'source_sha256', 'operation_group']:
            rows = [self.row(), self.row('s2', 'v2', 'b' * 64, 'val', frame=2)]
            rows[1][field] = rows[0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'leakage'):
                self.api().validate_proposed_groups(rows)

    def test_video_qualified_track_labels_do_not_conflate_different_videos(self):
        rows = [self.row(), self.row('s2', 'v2', 'b' * 64, 'val')]
        self.assertTrue(self.api().validate_proposed_groups(rows)['valid'])

    def test_proposal_rejects_duplicate_original_bad_sha_split_and_string_flags(self):
        for change in [{'sample_id': 's2'}, {'source_sha256': 'q' * 64},
                       {'proposed_split': 'test'}, {'mask_reviewed': 'False'},
                       {'capture_group_confirmed': 'False'}]:
            rows = [self.row()]
            if change == {'sample_id': 's2'}:
                rows.append(dict(rows[0], **change))
            else:
                rows[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.api().validate_proposed_groups(rows)

    def test_training_is_blocked_for_candidates_and_string_truth(self):
        row = self.row()
        report = self.api().training_readiness([row])
        self.assertIs(report['ready'], False)
        self.assertTrue(any('split' in reason for reason in report['reasons']))
        for key in ['mask_reviewed', 'exclusion_reviewed', 'boundary_reviewed', 'grouping_verified']:
            row[key] = 'True'
        self.assertIs(self.api().training_readiness([row])['ready'], False)

    def test_training_requires_real_binary_same_size_files_and_verified_groups(self):
        from dmf.vision.image_io import write_image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [self.row(), self.row('s2', 'v2', 'b' * 64, 'val')]
            for row in rows:
                for name in ['frame_path', 'mask_path', 'exclusion_mask_path']:
                    path = root / (row['sample_id'] + name + '.png')
                    pixels = np.zeros((12, 20, 3), np.uint8) if name == 'frame_path' else np.zeros((12, 20), np.uint8)
                    self.assertTrue(write_image(path, pixels))
                    row[name] = str(path)
                row.update(mask_reviewed=True, exclusion_reviewed=True, boundary_reviewed=True,
                           grouping_verified=True, split=row['proposed_split'])
            self.assertTrue(self.api().training_readiness(rows)['ready'])
            rows[0]['split'] = 'unassigned'
            self.assertFalse(self.api().training_readiness(rows)['ready'])
            rows[0]['split'] = 'train'
            rows[0]['mask_path'] = str(root / 'missing.png')
            self.assertFalse(self.api().training_readiness(rows)['ready'])
            rows[0]['mask_path'] = rows[1]['mask_path']
            write_image(Path(rows[0]['mask_path']), np.full((12, 20), 127, np.uint8))
            self.assertFalse(self.api().training_readiness(rows)['ready'])

    def test_training_rechecks_actual_not_only_proposed_grouping(self):
        rows = [self.row(), self.row('s2', 'v2', 'b' * 64, 'val')]
        rows[0].update(split='train', grouping_verified=True)
        rows[1].update(split='val', grouping_verified=True)
        rows[1]['operation_group'] = rows[0]['operation_group']
        report = self.api().training_readiness(rows)
        self.assertFalse(report['ready'])
        self.assertTrue(any('leakage' in reason for reason in report['reasons']))


if __name__ == '__main__':
    unittest.main()
