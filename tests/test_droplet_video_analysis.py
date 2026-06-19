import math
import unittest

import numpy as np

from droplet_video_analysis import (
    ArrayGridCalibration,
    DropletObservation,
    DropletVideoTracker,
    MotionCalibration,
    PathSwitchAdvisor,
    Roi,
    extract_step_events,
    summarize_speed_segments,
)

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@unittest.skipIf(cv2 is None, "OpenCV is required")
class DropletVideoAnalysisTests(unittest.TestCase):
    def test_motion_calibration_projects_virtual_steps(self):
        calibration = MotionCalibration.from_points((10, 10), (110, 10), step_px=20)
        self.assertAlmostEqual(calibration.project_px((50, 12)), 40.0)
        self.assertAlmostEqual(calibration.displacement_mm((50, 12)), 6.4)
        self.assertEqual(calibration.virtual_step((50, 12)), 2)

    def test_tracker_detects_synthetic_droplet_center_and_front(self):
        background = np.full((100, 140, 3), 245, dtype=np.uint8)
        frame = background.copy()
        cv2.circle(frame, (62, 50), 12, (40, 40, 40), -1)
        bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
        calibration = MotionCalibration.from_points((22, 50), (122, 50), step_px=20)
        tracker = DropletVideoTracker(
            calibration=calibration,
            roi=Roi(0, 0, 140, 100),
            background_gray=bg_gray,
            min_area_px=30,
        )

        observation = tracker.observe(frame, frame_index=5, time_s=0.5)

        self.assertEqual(observation.event, "detected")
        self.assertIsNotNone(observation.x_px)
        self.assertIsNotNone(observation.front_x_px)
        assert observation.x_px is not None
        assert observation.front_x_px is not None
        self.assertLess(abs(observation.x_px - 62), 1.0)
        self.assertGreater(observation.front_x_px, observation.x_px)
        self.assertEqual(observation.virtual_step, 2)
        self.assertGreater(observation.confidence, 0.6)

    def test_tracker_uses_motion_direction_for_front_marker(self):
        background = np.full((120, 120, 3), 245, dtype=np.uint8)
        bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
        calibration = MotionCalibration.from_points((20, 60), (100, 60), step_px=20)
        tracker = DropletVideoTracker(
            calibration=calibration,
            roi=Roi(0, 0, 120, 120),
            background_gray=bg_gray,
            min_area_px=30,
            front_mode="motion",
        )
        first_frame = background.copy()
        second_frame = background.copy()
        cv2.circle(first_frame, (60, 42), 10, (40, 40, 40), -1)
        cv2.circle(second_frame, (60, 62), 10, (40, 40, 40), -1)

        tracker.observe(first_frame, frame_index=0, time_s=0.0)
        observation = tracker.observe(second_frame, frame_index=1, time_s=0.1)

        self.assertIsNotNone(observation.y_px)
        self.assertIsNotNone(observation.front_y_px)
        assert observation.y_px is not None
        assert observation.front_y_px is not None
        self.assertGreater(observation.front_y_px, observation.y_px)

    def test_step_events_and_speed_segments_are_extracted(self):
        observations = [
            DropletObservation(0, 0.0, 20.0, 10.0, 22.0, 10.0, 100.0, 1.0, 0, 0.0, "detected"),
            DropletObservation(10, 1.0, 40.0, 10.0, 42.0, 10.0, 100.0, 1.0, 1, 3.2, "ok"),
            DropletObservation(20, 2.0, 60.0, 10.0, 62.0, 10.0, 100.0, 1.0, 2, 6.4, "ok"),
        ]

        events = extract_step_events(observations)
        segments = summarize_speed_segments(events)

        self.assertEqual([event.virtual_step for event in events], [0, 1, 2])
        self.assertEqual(len(segments), 2)
        self.assertTrue(all(math.isclose(segment.speed_mm_s, 3.2) for segment in segments))

    def test_array_grid_calibration_maps_pixel_to_cell(self):
        calibration = ArrayGridCalibration(((0, 0), (200, 0), (200, 200), (0, 200)))
        point = (75.0, 55.0)
        self.assertEqual(calibration.pixel_to_cell(point), (5, 7))
        row, col = calibration.pixel_to_grid_position(point)
        self.assertAlmostEqual(row, 5.5)
        self.assertAlmostEqual(col, 7.5)

    def test_path_switch_advisor_uses_break_before_make_next_cell_drive(self):
        advisor = PathSwitchAdvisor([(0, 0), (0, 1), (0, 2)], stable_frames_required=2)

        first = advisor.update((0, 0))
        self.assertEqual(first.event, "ok")
        self.assertEqual(first.commands, ("SET:2:1",))

        second = advisor.update((0, 1))
        self.assertEqual(second.event, "debounce")
        self.assertEqual(second.commands, tuple())

        third = advisor.update((0, 1))
        self.assertEqual(third.event, "advance")
        self.assertEqual(set(third.commands), {"SET:2:0", "SET:3:1"})


if __name__ == "__main__":
    unittest.main()
