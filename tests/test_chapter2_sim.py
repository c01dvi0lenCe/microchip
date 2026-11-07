"""Software-only Chapter 2 causal simulation contracts (not physical tests)."""
import importlib
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

import numpy as np


class Chapter2SimulationTests(unittest.TestCase):
    def api(self, name):
        try:
            return importlib.import_module('dmf.chapter2_sim.' + name)
        except ModuleNotFoundError as exc:
            self.fail('Chapter2 simulation feature not implemented: ' + str(exc))

    def config(self, **kwargs):
        return self.api('config').SimConfig(**kwargs)

    def test_example_map_has_420_and_non_rectangular_periphery(self):
        geometry = self.api('geometry').SimulationMap(self.config())
        self.assertEqual(len(geometry.polygons), 420)
        self.assertTrue(any(len(p) > 4 for i, p in geometry.polygons.items() if i > 400))
        self.assertEqual(geometry.metadata['coordinate_unit'], 'pitch')
        self.assertFalse(geometry.metadata['measured_geometry'])

    def test_external_map_preserves_supplied_pixel_polygon_not_mm_template(self):
        from dmf.vision.calibration import ArrayGridCalibration
        from dmf.vision.config import save_electrode_map
        from dmf.vision.electrode_map import ElectrodeMap
        calibration = ArrayGridCalibration(((100., 200.), (500., 200.),
                                            (500., 600.), (100., 600.)), pitch_mm=3.2)
        supplied = ((9.15, 9.2), (9.85, 9.2), (9.75, 9.85), (9.2, 9.8))
        electrode_map = ElectrodeMap.from_calibration(
            calibration, {190: calibration.grid_polygon_to_pixel(supplied)})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'supplied-example.json'
            save_electrode_map(path, electrode_map)
            cfg = self.config(map_path=str(path))
            geometry = self.api('geometry').SimulationMap(cfg)
            np.testing.assert_allclose(geometry.polygons[190], supplied, atol=1e-5)
            self.assertEqual(geometry.metadata['calibrated_override_count'], 1)
            self.assertFalse(geometry.metadata['measured_geometry'])
            self.assertEqual(len(geometry.polygons), 420)
            result = self.api('runner').run_trial(cfg, 'normal', 1, 'C')
            self.assertTrue(result.frames)

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError):
            self.config(camera_fps=0)
        with self.assertRaises(ValueError):
            self.config(arrival_frames=1)
        with self.assertRaises(ValueError):
            self.config(route=(190, 192))

    def test_counts_reject_fractional_and_boolean_values(self):
        for field in ('pixels_per_pitch', 'arrival_frames', 'deviation_frames',
                      'max_retries', 'max_recoveries'):
            for value in (2.5, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.config(**{field: value})
        with self.assertRaises(ValueError):
            self.config(camera_fps='20')

    def test_failure_exhausts_configured_retry_and_recovery_budgets(self):
        result = self.api('runner').run_trial(self.config(max_retries=1, max_recoveries=1),
                                            'failure', 1, 'C')
        self.assertEqual(result.metrics['retries'], 1)
        self.assertEqual(result.metrics['recoveries'], 1)
        self.assertEqual(result.metrics['status'], 'protective_stop')
        self.assertEqual(result.metrics['issued_updates'], 0)

    def test_no_command_no_motion_and_applied_not_arrival(self):
        cfg = self.config(process_noise=0)
        geometry = self.api('geometry').SimulationMap(cfg)
        world = self.api('world').DropletWorld(cfg, geometry, 'normal', 10)
        initial = world.position.copy()
        world.advance(0.2)
        np.testing.assert_array_equal(world.position, initial)
        world.command(cfg.route[1], 0.2, 'Update')
        world.advance(0.2 + cfg.ack_delay_s)
        np.testing.assert_array_equal(world.position, initial)
        world.advance(1.5)
        self.assertGreater(np.linalg.norm(world.position - initial), .5)

    def test_retry_changes_stalled_dynamics(self):
        cfg = self.config(process_noise=0)
        geometry = self.api('geometry').SimulationMap(cfg)
        world = self.api('world').DropletWorld(cfg, geometry, 'partial_stall', 1)
        world.command(cfg.route[1], 0., 'Update')
        world.advance(1.5)
        stalled = world.position.copy()
        self.assertGreater(np.linalg.norm(stalled - geometry.center(cfg.route[1])), .2)
        world.command(cfg.route[1], 1.5, 'Retry')
        world.advance(3.)
        self.assertLess(np.linalg.norm(world.position - geometry.center(cfg.route[1])), .11)

    def test_recovery_returns_to_source(self):
        cfg = self.config(process_noise=0)
        geometry = self.api('geometry').SimulationMap(cfg)
        world = self.api('world').DropletWorld(cfg, geometry, 'normal', 1)
        world.command(cfg.route[1], 0., 'Update')
        world.advance(.7)
        world.command(cfg.route[0], .7, 'Recovery')
        world.advance(2.)
        self.assertLess(np.linalg.norm(world.position - geometry.center(cfg.route[0])), .11)

    def test_truth_independent_of_recognition_thresholds(self):
        cfg = self.config()
        other = replace(cfg, arrival_coverage=.55, position_tolerance=.4)
        geometry = self.api('geometry').SimulationMap(cfg)
        World = self.api('world').DropletWorld
        a, b = World(cfg, geometry, 'normal', 2), World(other, geometry, 'normal', 2)
        for w in (a, b):
            w.command(cfg.route[1], 0., 'Update')
            w.advance(2.)
        np.testing.assert_array_equal(a.position, b.position)
        self.assertEqual(a.is_physically_settled(cfg.route[1]), b.is_physically_settled(cfg.route[1]))

    def test_camera_exposure_and_arrival_times_distinct_and_paired(self):
        cfg = self.config(drop_probability=0)
        geometry = self.api('geometry').SimulationMap(cfg)
        Camera = self.api('vision').SyntheticCamera
        a, b = Camera(cfg, geometry, 9), Camera(cfg, geometry, 9)
        fa = a.expose(4, .2, geometry.center(cfg.route[0]))
        fb = b.expose(4, .2, geometry.center(cfg.route[0]))
        self.assertAlmostEqual(fa.exposure_end_s - fa.exposure_start_s, cfg.exposure_s)
        self.assertGreater(fa.available_s, fa.exposure_end_s)
        np.testing.assert_array_equal(fa.mask, fb.mask)

    def test_two_area_denominators_and_direction(self):
        cfg = self.config()
        geometry = self.api('geometry').SimulationMap(cfg)
        vision = self.api('vision')
        features = vision.FeatureExtractor(cfg, geometry)
        camera = vision.SyntheticCamera(replace(cfg, position_noise=0, mask_radius_noise=0, drop_probability=0), geometry, 1)
        frame = camera.expose(0, 0., geometry.center(cfg.route[1]))
        f = features.extract(frame, cfg.route[0], cfg.route[1])
        self.assertAlmostEqual(f['eta_target'], 1., places=3)
        self.assertLess(f['rho_target'], .4)
        self.assertAlmostEqual(f['progress'], 1., delta=1/cfg.pixels_per_pitch)
        self.assertAlmostEqual(f['lateral'], 0., delta=1/cfg.pixels_per_pitch)

    def test_gap_old_frame_and_duplicate_break_or_do_not_advance_window(self):
        cfg = self.config()
        Window = self.api('control').StableWindow
        window = Window(cfg)
        for i, t in enumerate((0., .05, .10, .15)):
            self.assertFalse(window.observe(i, t, (0., 0.), True))
        self.assertFalse(window.observe(4, 2., (0., 0.), True))
        self.assertFalse(window.observe(4, 2., (0., 0.), True))
        self.assertEqual(window.count, 1)

    def test_missing_capture_ids_break_consecutive_confirmation(self):
        window = self.api('control').StableWindow(self.config())
        outputs = [window.observe(i, t, (0., 0.), True)
                   for i, t in ((0, 0.), (2, .1), (3, .15), (4, .2), (6, .3))]
        self.assertEqual(outputs, [False]*5)

    def test_dropout_closed_loop_updates_only_after_consecutive_capture_ids(self):
        cfg = self.config()
        result = self.api('runner').run_trial(cfg, 'dropout', 11, 'C')
        for event in result.events:
            if event['event'] not in ('Update', 'Complete'):
                continue
            rows = [f for f in result.frames if f.get('valid') and f['epoch'] == event['epoch']
                    and f.get('processing_s', float('inf')) <= event['time_s']]
            last = rows[-6:]
            self.assertGreaterEqual(len(last), 6)
            self.assertTrue(all(b['frame_id'] == a['frame_id']+1 for a, b in zip(last, last[1:])))
            self.assertGreaterEqual(last[-1]['exposure_s']-last[0]['exposure_s'], .25-1e-9)

    def test_normal_closed_loop_has_no_early_update_and_completes(self):
        cfg = self.config(position_noise=0, mask_radius_noise=0, process_noise=0, drop_probability=0)
        result = self.api('runner').run_trial(cfg, 'normal', 11, 'C')
        self.assertTrue(result.metrics['path_complete'])
        self.assertEqual(result.metrics['early_updates'], 0)
        updates = [e for e in result.events if e['event'] in ('Update', 'Complete')]
        self.assertEqual(len(updates), len(cfg.route) - 1)
        self.assertEqual(len({e['step'] for e in updates}), len(updates))
        self.assertTrue(all(e['exposure_s'] >= e['applied_s'] for e in updates))

    def test_controls_change_trajectory_and_failure_never_fakes_success(self):
        cfg = self.config(max_time_s=8.)
        runner = self.api('runner').run_trial
        a, c = runner(cfg, 'delayed', 12, 'A'), runner(cfg, 'delayed', 12, 'C')
        self.assertNotEqual(a.events, c.events)
        failed = runner(cfg, 'failure', 12, 'C')
        self.assertFalse(failed.metrics['path_complete'])
        self.assertGreater(failed.metrics['retries'], 0)

    def test_pre_ack_and_out_of_order_frames_cannot_update(self):
        cfg = self.config(processing_jitter_s=.25, processing_delay_s=.1)
        result = self.api('runner').run_trial(cfg, 'normal', 17, 'C')
        rejected = [f for f in result.frames if f.get('reason') in ('PRE_APPLIED_EXPOSURE', 'OUT_OF_ORDER_FRAME')]
        self.assertTrue(rejected)
        self.assertTrue(all(f['action'] == 'Hold' for f in rejected))

    def test_invalid_observation_is_not_deviation(self):
        control, vision = self.api('control'), self.api('vision')
        r = control.Recognizer(self.config())
        state, candidate = r.observe(vision.SyntheticFrame(0, 0., .008, .05, None), {'valid': False})
        self.assertEqual(state, 'Unknown')
        self.assertFalse(candidate)

    def test_deviation_confirmation_does_not_cross_observation_gap(self):
        cfg = self.config()
        r = self.api('control').Recognizer(cfg)
        Frame = self.api('vision').SyntheticFrame
        f = dict(valid=True, progress=.5, lateral=.8, x=1., y=1.)
        for i, t in enumerate((0., .05, 3.)):
            state, _ = r.observe(Frame(i, t, t+.008, t+.05, None), f)
        self.assertEqual(state, 'Unknown')

    def test_unconfirmed_true_arrival_is_counted_as_censored_not_zero_delay(self):
        cfg = self.config(max_time_s=1.3, position_noise=0, mask_radius_noise=0,
                          process_noise=0, drop_probability=0, stable_duration_s=.8)
        result = self.api('runner').run_trial(cfg, 'normal', 260600, 'C')
        self.assertIsNone(result.metrics['confirmation_delay_s'])
        self.assertEqual(result.metrics['delay_censored_steps'], 1)
        self.assertEqual(result.metrics['delay_unattempted_steps'], 2)


if __name__ == '__main__':
    unittest.main()
