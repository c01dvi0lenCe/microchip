"""Offline review wrapper tests with small, disposable native images."""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from dmf.segmentation_research.roi_pilot import candidate_row
from dmf.vision.image_io import read_image, write_image
from dmf.vision.pilot_annotation import PilotWorkspace, sha256


class RoiReviewTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('scripts.review_real_segmentation_roi_pilot')
        except ModuleNotFoundError:
            self.fail('Dedicated dual-mask review wrapper is not implemented')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.semantic = np.zeros((32, 40), np.uint8)
        self.semantic[8:16, 8:16] = 255
        self.exclusion = np.zeros_like(self.semantic)
        self.exclusion[:, :3] = 255
        rows, clips = [], []
        for index in range(2):
            row = candidate_row(f's{index}', 'video', 'a' * 64, index,
                                [0, 0, 40, 32], index / 10, 'candidate', 'train', 'op')
            row.update(frame_path=f'frames/{index}.png', draft_mask_path=f'drafts/{index}.png',
                       exclusion_draft_path=f'exclusion_draft/{index}.png',
                       source_electrode=10, target_electrode=11)
            rows.append(row)
            image = np.full((32, 40, 3), 220, np.uint8)
            image[self.semantic > 0] = 10
            for key, pixels in [('frame_path', image), ('draft_mask_path', self.semantic),
                                ('exclusion_draft_path', self.exclusion)]:
                self.assertTrue(write_image(self.root / row[key], pixels))
            clips.append(dict(clip_id=row['video_id'], video_id='video', batch_id=row['batch_id'],
                              path=str(self.root / 'not_used.avi')))
        payload = dict(schema='dmf_pilot_review', version=1, rows=rows, clips=clips,
                       calibrations={}, references={}, input_sha256={}, dataset='unused')
        (self.root / 'workspace.json').write_text(json.dumps(payload), encoding='utf-8')
        self.workspace = PilotWorkspace(self.root)

    def test_save_writes_both_revision_masks_without_releasing_other_gates(self):
        old_draft = sha256(self.root / self.workspace.rows[0]['draft_mask_path'])
        before = copy.deepcopy(self.workspace.rows[0])
        self.api().save_review_artifacts(self.workspace, 0, self.semantic, self.exclusion,
            mask_reviewed=True, boundary_reviewed=True, exclusion_reviewed=True, notes='checked')
        row = PilotWorkspace(self.root).rows[0]
        for key in ['split', 'grouping_verified', 'instance_id', 'instances_reviewed',
                    'task_target_instance_id', 'source_electrode', 'target_electrode',
                    'proposed_split', 'source_sha256', 'source_frame_id', 'instance_id_draft']:
            self.assertEqual(row[key], before[key])
        self.assertIs(row['mask_reviewed'], True)
        self.assertIs(row['boundary_reviewed'], True)
        self.assertIs(row['exclusion_reviewed'], True)
        self.assertIs(row['state_reviewed'], False)
        self.assertEqual(row['state_gt'], 'Unknown')
        self.assertEqual(row['notes'], 'checked')
        for key, pixels in [('mask_path', self.semantic), ('exclusion_mask_path', self.exclusion)]:
            np.testing.assert_array_equal(read_image(self.root / row[key], cv2.IMREAD_UNCHANGED), pixels)
        self.assertEqual(sha256(self.root / before['draft_mask_path']), old_draft)

    def test_second_save_keeps_old_revisions_and_can_invalidate_reviews(self):
        fn = self.api().save_review_artifacts
        fn(self.workspace, 0, self.semantic, self.exclusion,
           mask_reviewed=True, boundary_reviewed=True, exclusion_reviewed=True)
        old = copy.deepcopy(self.workspace.rows[0])
        old_hash = sha256(self.root / old['mask_path'])
        old_exclusion_hash = sha256(self.root / old['exclusion_mask_path'])
        changed = self.semantic.copy(); changed[20, 20] = 255
        fn(self.workspace, 0, changed, self.exclusion)
        row = PilotWorkspace(self.root).rows[0]
        self.assertEqual(row['mask_path'], '')
        self.assertNotEqual(row['working_mask_path'], old['working_mask_path'])
        self.assertNotEqual(row['exclusion_mask_path'], old['exclusion_mask_path'])
        for flag in ['mask_reviewed', 'boundary_reviewed', 'exclusion_reviewed']:
            self.assertIs(row[flag], False)
        self.assertEqual(sha256(self.root / old['mask_path']), old_hash)
        self.assertEqual(sha256(self.root / old['exclusion_mask_path']), old_exclusion_hash)

    def test_invalid_images_or_boolean_flags_write_nothing(self):
        fn = self.api().save_review_artifacts
        before = (self.root / 'workspace.json').read_bytes()
        files = set(self.root.rglob('*'))
        for kwargs in [{'semantic': np.full((32, 40), 127, np.uint8)},
                       {'exclusion': np.zeros((12, 40), np.uint8)},
                       {'exclusion': np.zeros((32, 40, 3), np.uint8)},
                       {'mask_reviewed': 'False'}, {'boundary_reviewed': 1},
                       {'exclusion_reviewed': 'True'}]:
            args = dict(semantic=self.semantic, exclusion=self.exclusion); args.update(kwargs)
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                fn(self.workspace, 0, **args)
            self.assertEqual((self.root / 'workspace.json').read_bytes(), before)
            self.assertEqual(set(self.root.rglob('*')), files)

    def test_stale_window_is_rejected_before_writing(self):
        fn = self.api().save_review_artifacts
        second = PilotWorkspace(self.root)
        fn(self.workspace, 0, self.semantic, self.exclusion)
        files = set(self.root.rglob('*'))
        with self.assertRaisesRegex(OSError, 'another window'):
            fn(second, 0, self.semantic, self.exclusion)
        self.assertEqual(set(self.root.rglob('*')), files)

    def test_gui_starts_without_calibration_and_smoke_does_not_persist(self):
        api = self.api()
        before = (self.root / 'workspace.json').read_bytes()
        api.main(['--workspace', str(self.root), '--smoke'])
        self.assertEqual((self.root / 'workspace.json').read_bytes(), before)

    def gui(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        self.addCleanup(root.destroy)
        app = self.api().RoiPilotReviewApp(root, self.workspace)
        return root, app

    def test_brush_edits_selected_mask_and_invalidates_only_relevant_reviews(self):
        _, app = self.gui()
        app.mask_reviewed.set(True); app.boundary_reviewed.set(True); app.exclusion_reviewed.set(True)
        old_semantic = app.semantic.copy()
        app.mode.set('exclusion'); app._mode_changed()
        app._annotation_click(25, 25, False)
        np.testing.assert_array_equal(app.semantic, old_semantic)
        self.assertEqual(app.exclusion[25, 25], 255)
        self.assertIs(app.exclusion_reviewed.get(), False)
        self.assertIs(app.mask_reviewed.get(), True)
        self.assertIs(app.boundary_reviewed.get(), True)
        app.mode.set('semantic'); app._mode_changed()
        app._annotation_click(25, 25, False)
        self.assertIs(app.mask_reviewed.get(), False)
        self.assertIs(app.boundary_reviewed.get(), False)
        self.assertTrue(app.dirty)

    def test_draft_rebuild_preserves_multiple_components(self):
        _, app = self.gui()
        app.image[0:2, 0:2] = 0
        app.image[24:27, 30:33] = 0
        app._draft()
        self.assertEqual(app.semantic[0, 0], 255)
        self.assertEqual(app.semantic[25, 31], 255)
        self.assertTrue(app.dirty)

    def test_navigation_saves_both_masks_before_loading_next(self):
        from unittest.mock import patch
        _, app = self.gui()
        app.mode.set('exclusion'); app._mode_changed(); app._annotation_click(25, 25, False)
        with patch('scripts.review_real_segmentation_roi_pilot.messagebox.askyesnocancel', return_value=True):
            app._load_frame(1)
        row = PilotWorkspace(self.root).rows[0]
        saved = read_image(self.root / row['exclusion_mask_path'], cv2.IMREAD_GRAYSCALE)
        self.assertEqual(saved[25, 25], 255)
        self.assertEqual(app.index, 1)
        self.assertFalse(app.dirty)

    def test_cancel_navigation_keeps_edit_and_current_selection(self):
        from unittest.mock import patch
        _, app = self.gui()
        app._annotation_click(25, 25, False)
        with patch('scripts.review_real_segmentation_roi_pilot.messagebox.askyesnocancel', return_value=None):
            app._load_frame(1)
        self.assertEqual(app.index, 0)
        self.assertTrue(app.dirty)
        self.assertEqual(app.semantic[25, 25], 255)


if __name__ == '__main__':
    unittest.main()
