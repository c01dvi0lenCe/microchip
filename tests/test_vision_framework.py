import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from dmf.vision import (
    ArrayGridCalibration,
    DropletDetector,
    DropletFeatureExtractor,
    ElectrodeMap,
    FramePacket,
    SimulatedCamera,
    VisionResult,
    detection_in_cell,
)
from dmf.vision.algorithms import (
    BackgroundConfig,
    BackgroundSegmenter,
    ThresholdConfig,
    ThresholdSegmenter,
    create_algorithm,
)
from dmf.vision.dataset import validate_dataset
from dmf.vision.electrode_map import polygon_centroid
from dmf.vision.constraints import SpatialConstraint, TemporalConstraint
from dmf.vision.metrics import boundary_f1, centroid_error, segmentation_metrics, state_classification_metrics
from dmf.vision.timebase import VideoTimestampResolver

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@unittest.skipIf(cv2 is None, "OpenCV is required")
class VisionFrameworkTests(unittest.TestCase):
    def setUp(self):
        calibration = ArrayGridCalibration(((0, 0), (200, 0), (200, 200), (0, 200)))
        self.electrode_map = ElectrodeMap.from_calibration(calibration)

    def test_existing_simulation_exports_remain_available(self):
        camera = SimulatedCamera(frame_size=(320, 320))
        detector = DropletDetector(camera)
        frame = camera.render((2, 3))
        detection = detector.detect(frame)
        self.assertIsNotNone(detection)
        self.assertTrue(detection_in_cell(detection, (2, 3)))

    def test_electrode_map_contains_all_420_ids_and_physical_mapping(self):
        self.assertEqual(len(self.electrode_map), 420)
        self.assertEqual((self.electrode_map[1].row, self.electrode_map[1].col), (0, 0))
        self.assertEqual((self.electrode_map[400].row, self.electrode_map[400].col), (19, 19))
        self.assertEqual((self.electrode_map[401].row, self.electrode_map[401].col), (-1, 6))
        self.assertEqual((self.electrode_map[420].row, self.electrode_map[420].col), (20, -1))
        self.assertEqual({region.electrode_id for region in self.electrode_map}, set(range(1, 421)))

    def test_corner_electrode_is_l_shaped_and_has_three_cell_area(self):
        region = self.electrode_map[417]
        polygon = np.asarray(region.polygon_mm)
        x = polygon[:, 0]
        y = polygon[:, 1]
        area = 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
        self.assertAlmostEqual(area, 3 * 3.2 * 3.2, places=5)
        polygon_px = np.asarray(region.polygon_px, dtype=np.float32)
        self.assertGreaterEqual(cv2.pointPolygonTest(polygon_px, (-5.0, -5.0), False), 0)
        self.assertLess(cv2.pointPolygonTest(polygon_px, (5.0, 5.0), False), 0)

    def test_pixel_override_marks_region_calibrated(self):
        calibration = self.electrode_map.calibration
        updated = ElectrodeMap.from_calibration(calibration, {401: ((1, 1), (3, 1), (3, 3), (1, 3))})
        self.assertEqual(updated[401].geometry_source, "calibrated")
        self.assertEqual(updated[402].geometry_source, "template")
        self.assertEqual(updated[401].center_px, (2.0, 2.0))

    def test_threshold_and_background_baselines_share_result_contract(self):
        background = np.full((100, 120, 3), 240, dtype=np.uint8)
        frame = background.copy()
        cv2.circle(frame, (60, 50), 12, (25, 25, 25), -1)
        packet = FramePacket("pilot", 0, 0.0, "video_pts", frame)
        threshold = ThresholdSegmenter(
            ThresholdConfig(color_space="gray", lower=(0,), upper=(80,), min_area_px=30)
        )
        subtraction = BackgroundSegmenter(background, BackgroundConfig(min_diff=15, min_area_px=30))
        for algorithm in (threshold, subtraction):
            result = algorithm.process(packet)
            self.assertTrue(result.detected)
            self.assertEqual(result.mask.shape, frame.shape[:2])
            self.assertEqual(set(np.unique(result.mask)), {0, 255})
            self.assertLess(abs(result.centroid_px[0] - 60), 1.0)
            self.assertLess(abs(result.centroid_px[1] - 50), 1.0)
            self.assertGreater(result.area_px, 400)
            self.assertGreaterEqual(result.processing_time_ms, 0)

    def test_empty_frame_returns_explicit_miss(self):
        frame = np.full((60, 60, 3), 240, dtype=np.uint8)
        algorithm = ThresholdSegmenter(ThresholdConfig(color_space="gray", lower=(0,), upper=(80,)))
        result = algorithm.process(FramePacket("pilot", 0, 0.0, "video_pts", frame))
        self.assertFalse(result.detected)
        self.assertEqual(result.mask.shape, frame.shape[:2])
        self.assertEqual(int(np.count_nonzero(result.mask)), 0)
        self.assertEqual(result.area_px, 0.0)
        self.assertEqual(result.error_code, "NO_CANDIDATE")

    def test_reserved_algorithm_fails_explicitly(self):
        for name in ("U-Net", "DeepLabV3+", "Hough Circle", "KCF"):
            with self.subTest(name=name), self.assertRaisesRegex(NotImplementedError, "later phase"):
                create_algorithm(name, {}, Path.cwd())

    def test_features_use_real_timestamp_intervals_without_poisoning_history(self):
        extractor = DropletFeatureExtractor(self.electrode_map)
        result_a = VisionResult(None, (5.0, 5.0), 100.0, 1.0, 0.1, True)
        result_b = VisionResult(None, (15.0, 5.0), 100.0, 1.0, 0.1, True)
        first = extractor.extract(FramePacket("v", 0, 1.0, "hardware", np.zeros((200, 200, 3))), result_a, 1, 2)
        second = extractor.extract(FramePacket("v", 1, 1.5, "hardware", np.zeros((200, 200, 3))), result_b, 1, 2)
        invalid = extractor.extract(FramePacket("v", 2, float("nan"), "missing", np.zeros((200, 200, 3))), result_b, 1, 2)
        self.assertIsNone(first.velocity_mm_s)
        self.assertAlmostEqual(second.velocity_mm_s, 6.4, places=5)
        self.assertIsNone(invalid.velocity_mm_s)

    def test_video_timestamp_resolver_falls_back_for_repeated_backward_and_missing_pts(self):
        resolver = VideoTimestampResolver(20.0)
        values = [
            resolver.resolve(0, 0.0),
            resolver.resolve(1, 50.0),
            resolver.resolve(2, 50.0),
            resolver.resolve(3, 25.0),
            resolver.resolve(4, None),
        ]
        timestamps = [value[0] for value in values]
        self.assertEqual([value[1] for value in values], [
            "video_pts",
            "video_pts",
            "fps_fallback",
            "fps_fallback",
            "fps_fallback",
        ])
        self.assertTrue(all(following > current for current, following in zip(timestamps, timestamps[1:])))

    def test_features_compute_mask_coverage_and_target_distance(self):
        extractor = DropletFeatureExtractor(self.electrode_map)
        mask = np.zeros((200, 200), dtype=np.uint8)
        mask[2:8, 2:8] = 255
        result = VisionResult(mask, (4.5, 4.5), 36.0, 1.0, 0.1, True)
        features = extractor.extract(
            FramePacket("v", 0, 0.0, "video_pts", np.zeros((200, 200, 3), dtype=np.uint8)),
            result,
            1,
            2,
        )
        self.assertEqual(features.source_coverage, 1.0)
        self.assertEqual(features.target_coverage, 0.0)
        self.assertGreater(features.distance_to_target_mm, 0.0)

    def test_spatial_and_temporal_constraints_reject_invalid_candidates(self):
        spatial = SpatialConstraint(self.electrode_map, {1})
        accepted = VisionResult(None, (5.0, 5.0), 30.0, 1.0, 0.1, True)
        rejected = VisionResult(None, (25.0, 25.0), 30.0, 1.0, 0.1, True)
        self.assertTrue(spatial.apply(accepted).detected)
        self.assertEqual(spatial.apply(rejected).error_code, "SPATIAL_REJECT")

        temporal = TemporalConstraint(self.electrode_map, max_speed_mm_s=6.0, tolerance_mm=0.0)
        first_packet = FramePacket("v", 0, 0.0, "video_pts", np.zeros((200, 200, 3), dtype=np.uint8))
        next_packet = FramePacket("v", 1, 0.1, "video_pts", np.zeros((200, 200, 3), dtype=np.uint8))
        self.assertTrue(temporal.apply(first_packet, accepted).detected)
        self.assertEqual(temporal.apply(next_packet, rejected).error_code, "TEMPORAL_REJECT")

    def test_mask_metrics_and_state_metrics_have_known_values(self):
        truth = np.zeros((20, 20), dtype=np.uint8)
        prediction = np.zeros_like(truth)
        truth[4:12, 4:12] = 255
        prediction[4:12, 4:12] = 255
        metrics = segmentation_metrics(prediction, truth)
        self.assertEqual(metrics["iou"], 1.0)
        self.assertEqual(metrics["dice"], 1.0)
        self.assertEqual(metrics["boundary_f1"], 1.0)
        self.assertIsNone(segmentation_metrics(None, truth)["dice"])
        self.assertEqual(centroid_error((1, 1), (4, 5)), 5.0)
        state = state_classification_metrics(
            ["Moving", "Arrived", "Moving"],
            ["Moving", "Arrived", "Stationary"],
        )
        self.assertEqual(state["confusion_matrix"]["Moving"]["Moving"], 1)
        self.assertEqual(state["confusion_matrix"]["Stationary"]["Moving"], 1)

    def test_dataset_validator_rejects_video_and_batch_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "video_id,batch_id,video_path,split\n"
                "v1,b1,v1.mp4,train\n"
                "v1,b1,v1.mp4,test\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "leaks across splits"):
                validate_dataset(manifest)

    def test_committed_synthetic_dataset_is_valid(self):
        fixture = Path(__file__).parent / "fixtures" / "vision"
        counts = validate_dataset(fixture / "dataset.csv", fixture / "annotations.csv")
        self.assertEqual(counts, {"videos": 1, "batches": 1, "annotations": 1})


if __name__ == "__main__":
    unittest.main()
