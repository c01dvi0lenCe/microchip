"""B1 software counterexamples only; not real-droplet research ground truth."""
import importlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from dmf.experiment.config import StateConfig, ControlConfig, typed_config, load_config
from dmf.experiment.perception import StateRecognizer, PriorFeatures
from dmf.experiment.policy import EventController
from dmf.experiment.runner import Confirmation
from dmf.vision.calibration import ArrayGridCalibration
from dmf.vision.contracts import DropletState as S, FramePacket, VisionResult
from dmf.vision.electrode_map import ElectrodeMap
from tests.test_chapter2_policy import observation
from tests.test_chapter2_runner import make_inputs, read_rows
from dmf.experiment.runner import run_experiment


class AuditReproductionTests(unittest.TestCase):
    def test_p2_arrival_cannot_bridge_long_unobserved_gap(self):
        r = StateRecognizer(StateConfig())
        f = observation(eta_source=0., eta_target=.9)
        states = [r.recognize(f, t) for t in (0., .1, .2, .3, 10.)]
        self.assertNotEqual(states[-1], S.ARRIVED)

    def test_p3_source_confirmation_cannot_bridge_gap(self):
        gate = Confirmation(5, .25)
        values = [gate.observe(True, t) for t in (0., .1, .2, .3, 10.)]
        self.assertFalse(values[-1])

    def test_p4_p5_p6_all_nonarrival_labels_have_bounded_attempts(self):
        for state in (S.PARTIAL, S.MOVING, S.UNKNOWN):
            with self.subTest(state=state):
                c = EventController((190, 191), ControlConfig())
                c.accept(c.decide(S.STATIONARY, 0., source_confirmed=True), 0.)
                self.assertNotEqual(c.decide(state, 1000.).action, 'Hold')

    def test_p7_temporal_conflict_is_not_physical_deviation(self):
        r = StateRecognizer(StateConfig())
        self.assertEqual(r.recognize(observation(temporal_ok=False), 0.), S.UNKNOWN)

    def test_p10_real_feature_chain_gap_rebuilds_arrival_evidence(self):
        geometry = ElectrodeMap.from_calibration(ArrayGridCalibration(
            ((0., 0.), (400., 0.), (400., 400.), (0., 400.)), pitch_mm=1.))
        prior, recognizer = PriorFeatures(geometry, StateConfig()), StateRecognizer(StateConfig())
        mask = np.zeros((400, 400), np.uint8)
        cv2.circle(mask, (210, 190), 5, 255, -1)
        result = VisionResult(mask, (210., 190.), float(np.count_nonzero(mask)), 1., 0., True)
        for i, t in enumerate((0., .1, .2, .3, 10.)):
            packet = FramePacket('software-fixture', i, t, 'fixture', np.zeros((400, 400, 3), np.uint8))
            f = prior.extract(packet, result, 190, 191, [])
            state = recognizer.recognize(f, t)
        self.assertIsNone(f.velocity)
        self.assertNotEqual(state, S.ARRIVED)

    def test_p12_formal_timing_floor_cannot_be_lowered(self):
        with self.assertRaises(ValueError):
            typed_config(StateConfig, {'arrival_frames': 1, 'arrival_duration_s': 0.})
        with self.assertRaises(ValueError):
            typed_config(ControlConfig, {'source_frames': 1, 'source_duration_s': 0.})

    def test_formal_modes_and_experiment_cannot_use_synthetic_floor_bypass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for mode in ('offline','dry_run','experiment'):
                source = {'video':'sample.avi'} if mode=='offline' else {'backend':'opencv'}
                config = make_inputs(root, [], mode=mode, source=source, synthetic_test_only=False,
                    segmentation={'name':'unet','model_path':'fixture-only.onnx'})
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,'formal'):
                    load_config(config)
            config = make_inputs(root, [], mode='experiment', synthetic_test_only=True,
                source={'backend':'opencv'}, segmentation={'name':'unet','model_path':'fixture-only.onnx'})
            with self.assertRaisesRegex(ValueError,'formal'):
                load_config(config)

    def test_duplicate_timestamp_cannot_finish_arrival_or_source_gate(self):
        r, gate = StateRecognizer(StateConfig()), Confirmation(5, .25)
        f = observation(eta_source=0., eta_target=.9)
        for t in (0., .1, .2, .3):
            r.recognize(f, t)
            gate.observe(True, t)
        self.assertNotEqual(r.recognize(f, .3), S.ARRIVED)
        self.assertFalse(gate.observe(True, .3))


class EvidenceContractTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('dmf.experiment.evidence')
        except ModuleNotFoundError:
            self.fail('B1 EvidenceWindow/ProgressMonitor is not implemented')

    def window(self):
        return self.module().EvidenceWindow(min_frames=5, min_duration_s=.25,
            max_gap_s=.2, max_centroid_span_mm=.2, max_coverage_span=.15)

    def test_duplicate_id_and_context_change_rebuild_window(self):
        w = self.window()
        for i in range(4):
            self.assertFalse(w.observe('step-1', i, i*.1, True, (1., 1.), .9))
        self.assertFalse(w.observe('step-1', 3, .4, True, (1., 1.), .9))
        self.assertEqual(w.count, 0)
        self.assertFalse(w.observe('step-2', 4, .5, True, (1., 1.), .9))
        self.assertEqual(w.count, 1)

    def test_missing_id_cannot_hide_a_previously_seen_duplicate_id(self):
        w = self.module().EvidenceWindow(5,.25,.25)
        values = [w.observe('same-task',frame_id,i*.1,True)
                  for i,frame_id in enumerate((0,1,None,1,2))]
        self.assertFalse(any(values))

    def test_invalid_and_missing_capture_id_clear_confirmation(self):
        w = self.window()
        for i in range(4):
            w.observe(1, i, i*.1, True, (1., 1.), .9)
        self.assertFalse(w.observe(1, 4, .4, False, None, None))
        self.assertEqual(w.count, 0)
        w.observe(1, 5, .5, True, (1., 1.), .9)
        w.observe(1, 7, .6, True, (1., 1.), .9)
        self.assertEqual(w.count, 1)

    def test_position_and_coverage_spans_use_stable_recent_suffix(self):
        w = self.window()
        for i in range(5):
            self.assertFalse(w.observe(1, i, i*.1, True, (i*.15, 1.), .9))
        for i in range(5, 10):
            value = w.observe(1, i, i*.1, True, (.6, 1.), .9)
        self.assertTrue(value)
        self.assertFalse(w.observe(1, 10, 1., True, (.6, 1.), .5))

    def test_isolated_spatial_conflict_does_not_recover_but_persistent_does(self):
        r = StateRecognizer(StateConfig())
        f = observation(spatial_ok=False, temporal_ok=True)
        self.assertEqual(r.recognize(f, 0.), S.UNKNOWN)
        self.assertEqual(r.recognize(f, .1), S.DEVIATION)
        self.assertEqual(r.recognize(observation(temporal_ok=False), .2), S.UNKNOWN)

    def test_legal_stationary_to_arrived_jump_is_preserved(self):
        r = StateRecognizer(StateConfig(consistency_frames=1))
        self.assertEqual(r.recognize(observation(), 0.), S.STATIONARY)
        f = observation(eta_source=0., eta_target=.9)
        states = [r.recognize(f, t) for t in (.1, .2, .3, .4, .5)]
        self.assertEqual(states[-1], S.ARRIVED)

    def test_low_rate_and_spatial_outlier_gap_cannot_fake_consistency(self):
        f = observation(eta_source=0.,eta_target=.9)
        r = StateRecognizer(StateConfig())
        self.assertTrue(all(r.recognize(f,t) is S.UNKNOWN for t in (0.,.5,1.,1.5,2.)))
        r.reset()
        outside = observation(spatial_ok=False,temporal_ok=True)
        self.assertEqual(r.recognize(outside,0.),S.UNKNOWN)
        self.assertEqual(r.recognize(outside,.5),S.UNKNOWN)

    def test_temporal_conflicts_stop_for_quality_without_recovery(self):
        c = EventController((190,191),ControlConfig(wait_s=8.,no_detection_timeout_s=.5))
        c.accept(c.decide(S.STATIONARY,0.,source_confirmed=True),0.)
        conflict = observation(temporal_ok=False)
        self.assertEqual(c.decide(S.UNKNOWN,.1,observation=conflict).action,'Hold')
        decision = c.decide(S.UNKNOWN,.6,observation=conflict)
        self.assertEqual(decision.action,'Stop')
        self.assertIn('quality',decision.reason)

    def test_progress_is_net_target_approach_not_label_or_oscillation(self):
        cfg = ControlConfig(wait_s=1.)
        c = EventController((190, 191), cfg)
        c.accept(c.decide(S.STATIONARY, 0., source_confirmed=True), 0.)
        for i in range(10):
            f = observation(distance=3.2+(i%2)*.01, velocity=1.)
            self.assertEqual(c.decide(S.MOVING, i*.1, observation=f).action, 'Hold')
        self.assertEqual(c.decide(S.MOVING, 1.1, observation=f).action, 'Retry')
        self.assertEqual(c.retry_count, 0)

    def test_real_progress_extends_no_progress_timer_but_not_attempt_cap(self):
        cfg = ControlConfig(wait_s=1., attempt_timeout_s=2.5)
        c = EventController((190, 191), cfg)
        c.accept(c.decide(S.STATIONARY, 0., source_confirmed=True), 0.)
        for i in range(6):
            d = c.decide(S.MOVING, i*.4, observation=observation(distance=3.2-i*.3))
            self.assertEqual(d.action, 'Hold')
        self.assertEqual(c.decide(S.MOVING, 2.6,
                                 observation=observation(distance=1.)).action, 'Retry')

    def test_runner_partial_stall_logs_progress_reason_before_accept_resets_timer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_experiment(make_inputs(root, [(190,190,6,6)]+[(200,190,12,6)]*10))
            rows = read_rows(root/'results/frames.csv')
            retry = next(row for row in rows if row['event_action']=='Retry')
            self.assertEqual(retry['progress_status'], 'no_progress')
            self.assertIn('no target progress', retry['reason'])

    def test_partial_retry_and_recovery_budget_reaches_protective_stop(self):
        c = EventController((190,191), ControlConfig(wait_s=1.,max_retries=1,max_recoveries=1))
        c.accept(c.decide(S.STATIONARY,0.,source_confirmed=True),0.)
        for time_s, expected in ((1.,'Retry'),(2.,'Recovery')):
            d = c.decide(S.PARTIAL,time_s)
            self.assertEqual(d.action,expected)
            c.accept(d,time_s)
        d = c.decide(S.UNKNOWN,2.1,source_confirmed=True)
        c.accept(d,2.1)
        self.assertEqual(c.recovery_total,1)
        d = c.decide(S.PARTIAL,3.2)
        self.assertEqual(d.action,'Retry');c.accept(d,3.2)
        self.assertEqual(c.decide(S.PARTIAL,4.3).action,'Stop')


if __name__ == '__main__':
    unittest.main()
