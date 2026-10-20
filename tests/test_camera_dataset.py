import json
import os
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from scripts.prepare_camera_dataset import capture_date, crop_for_points, export_clips, export_previews, movement_windows, overlaps_crop, probe, sha, update_tracks
from dmf.vision.image_io import read_image


class CameraDatasetTests(unittest.TestCase):
    def test_capture_date_comes_from_valid_filename(self):
        self.assertEqual(capture_date(Path("camera_20261013_154518_384889.avi")), "2026-10-13")
        for name in ("unknown.avi", "camera_20260230_154518_384889.avi"):
            with self.assertRaises(ValueError):
                capture_date(Path(name))

    def test_stationary_track_has_no_movement_and_gaps_do_not_form_events(self):
        still = [dict(x=10, y=10, t=t) for t in (0, 0.5, 1)]
        self.assertEqual(movement_windows(still), [])
        self.assertEqual(movement_windows([dict(x=0, y=0, t=0), dict(x=50, y=0, t=2)]), [])
        moving = [dict(x=x, y=0, t=t) for x, t in ((0, 0), (10, 0.5), (20, 1))]
        self.assertEqual(movement_windows(moving), [[0, 1]])

    def test_fixed_reference_is_not_swapped_with_moving_track(self):
        tracks = [[dict(x=20, y=10, t=0)], [dict(x=40, y=10, t=0)]]
        update_tracks(tracks, [dict(x=40, y=10), dict(x=30, y=10)], 0.5)
        self.assertEqual(tracks[0][-1]["x"], 30)
        self.assertEqual(tracks[1][-1]["x"], 40)

    def test_roi_is_even_bounded_and_detects_other_objects(self):
        points = [dict(bbox=[215, 110, 12, 12]), dict(bbox=[230, 120, 14, 14])]
        crop = crop_for_points(points, 5472, 3648)
        self.assertTrue(all(value % 2 == 0 for value in crop))
        self.assertGreaterEqual(crop[0], 0)
        self.assertLessEqual(crop[0] + crop[2], 5472)
        self.assertTrue(overlaps_crop(points[0], crop, 5472, 3648))
        self.assertFalse(overlaps_crop(dict(bbox=[800, 500, 10, 10]), crop, 5472, 3648))

    def test_excluded_and_unknown_selections_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "candidates.json").write_text(json.dumps([dict(clip_id="excluded", review_status="rejected")]))
            selection = root / "selection.json"
            for chosen in (["excluded"], ["unknown"], ["excluded", "excluded"]):
                selection.write_text(json.dumps(dict(accepted_clip_ids=chosen)))
                with self.assertRaises(ValueError):
                    export_clips(root, selection, "unused")

    @unittest.skipUnless(os.environ.get("DMF_FFMPEG"), "Set DMF_FFMPEG for exact clip integration test")
    def test_lossless_clip_preserves_source_frames_offsets_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "camera_20261013_154518_384889.avi"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"FFV1"), 10, (64, 48))
            self.assertTrue(writer.isOpened())
            for i in range(20):
                writer.write(np.full((48, 64, 3), [i, 50, 200], np.uint8))
            writer.release()
            metadata = probe(source)
            candidate = dict(clip_id="test", video_id=source.stem, batch_id="2026-10-13",
                             source=str(source), source_sha256=metadata["sha256"],
                             start_frame=4, end_frame_exclusive=11, fps=10,
                             roi_xywh=[10, 12, 20, 18], review_status="pending")
            (root / "logs").mkdir()
            (root / "candidates.json").write_text(json.dumps([candidate]))
            selection = root / "selection.json"
            selection.write_text(json.dumps(dict(accepted_clip_ids=["test"])))
            export_clips(root, selection, os.environ["DMF_FFMPEG"])
            self.assertEqual(sha(source), metadata["sha256"])
            clips = json.loads((root / "clips_manifest.json").read_text())
            self.assertEqual(clips[0]["decoded_frames"], 7)
            self.assertEqual(clips[0]["group_id"], source.stem)
            first = read_image(Path(clips[0]["annotation_frames"][0]), cv2.IMREAD_COLOR)
            np.testing.assert_array_equal(first, np.full((18, 20, 3), [4, 50, 200], np.uint8))
            export_previews(root, os.environ["DMF_FFMPEG"])
            preview = json.loads((root / "previews_manifest.json").read_text())[0]
            self.assertTrue(preview["preview_only"])
            self.assertEqual(preview["decoded_frames"], 7)
            self.assertEqual(sha(source), metadata["sha256"])
            with self.assertRaises(FileExistsError):
                export_previews(root, os.environ["DMF_FFMPEG"])
