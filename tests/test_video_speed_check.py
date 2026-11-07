import math
import unittest


class VideoSpeedCheckTests(unittest.TestCase):
    def test_receive_time_not_container_time_and_sdk_gaps_preserved(self):
        from scripts.measure_chapter2_video_speed import audit_timing
        rows = [dict(video_frame_index=i, receive_relative_s=t, sdk_frame_number=s)
                for i, (t, s) in enumerate([(0., 10), (.1, 12), (.3, 16)])]
        result = audit_timing(rows, 20., 3)
        self.assertAlmostEqual(result['host_receive_duration_s'], .3)
        self.assertAlmostEqual(result['container_first_to_last_s'], .1)
        self.assertAlmostEqual(result['playback_speedup_vs_receive'], 3.)
        self.assertEqual(result['sdk_missing_between_saved_frames'], 4)
        self.assertFalse(result['exposure_timing_verified'])

    def test_duplicate_time_missing_index_and_nonfinite_are_rejected(self):
        from scripts.measure_chapter2_video_speed import audit_timing
        base = [dict(video_frame_index=0, receive_relative_s=0., sdk_frame_number=10),
                dict(video_frame_index=1, receive_relative_s=.1, sdk_frame_number=11)]
        for key, value in [('receive_relative_s', 0.), ('receive_relative_s', math.nan),
                           ('video_frame_index', 2), ('sdk_frame_number', 10)]:
            bad = [dict(r) for r in base]
            bad[1][key] = value
            with self.assertRaises(ValueError):
                audit_timing(bad, 20., 2)

    def test_interval_uses_host_time_and_anisotropic_nominal_grid_scale(self):
        from scripts.measure_chapter2_video_speed import interval_measurement
        points = [dict(frame_id=10, receive_s=2., x_px=100., y_px=100.),
                  dict(frame_id=30, receive_s=4., x_px=218., y_px=219.)]
        result = interval_measurement(points, 10, 30, 20., (118., 119.), 3.2)
        self.assertAlmostEqual(result['receive_duration_s'], 2.)
        self.assertAlmostEqual(result['container_duration_s'], 1.)
        self.assertAlmostEqual(result['displacement_pitch'], math.sqrt(2))
        self.assertAlmostEqual(result['approx_chord_speed_mm_s'], math.sqrt(2)*1.6)
        self.assertEqual(result['measurement_status'], 'rough_unreviewed_centroid_not_arrival_gt')

    def test_interval_missing_detection_and_reverse_time_rejected(self):
        from scripts.measure_chapter2_video_speed import interval_measurement
        rows = [dict(frame_id=1, receive_s=1., x_px=0., y_px=0.),
                dict(frame_id=2, receive_s=2., x_px=None, y_px=None)]
        for a, b in [(1, 2), (2, 1), (1, 3)]:
            with self.assertRaises(ValueError):
                interval_measurement(rows, a, b, 20., (100., 100.), 3.2)

    def test_transition_uses_sample_brackets_not_fabricated_crossing_time(self):
        from scripts.analyze_chapter2_video_speed import transition_measurement
        positions = [0,0,0,25,50,75,100,100,100]
        rows = [dict(frame_id=i, receive_s=i*.1, x_px=x, y_px=0.)
                for i,x in enumerate(positions)]
        result = transition_measurement(rows, 0, 8, 10., (100.,100.), 3.2, 2)
        self.assertEqual(result['crossing_10_frame_bracket'], [2,3])
        self.assertEqual(result['crossing_90_frame_bracket'], [5,6])
        self.assertAlmostEqual(result['duration_10_90_bounds_s'][0], .2)
        self.assertAlmostEqual(result['duration_10_90_bounds_s'][1], .4)
        self.assertAlmostEqual(result['progress_distance_10_90_mm'], 2.56)

    def test_transition_does_not_bridge_missing_detections(self):
        from scripts.analyze_chapter2_video_speed import transition_measurement
        rows = [dict(frame_id=i, receive_s=i, x_px=x, y_px=0.)
                for i,x in enumerate([0.,0.,None,100.,100.])]
        with self.assertRaises(ValueError):
            transition_measurement(rows, 0, 4, 10., (100.,100.), 3.2, 2)

    def test_minimum_jerk_compares_same_10_90_speed_not_mean_to_peak(self):
        from scripts.analyze_chapter2_video_speed import minimum_jerk_conversion
        result = minimum_jerk_conversion(3.2, 1.4)
        self.assertAlmostEqual(result['motion_duration_s'], 1.875*3.2/1.4)
        q = lambda u: 10*u**3-15*u**4+6*u**5
        self.assertAlmostEqual(q(result['u10']), .1)
        self.assertAlmostEqual(q(result['u90']), .9)
        self.assertAlmostEqual(result['mean_progress_speed_10_90_mm_s'],
                               .8*3.2/result['duration_10_90_s'])
        self.assertLess(result['mean_progress_speed_10_90_mm_s'], 1.4)


if __name__ == '__main__':
    unittest.main()
