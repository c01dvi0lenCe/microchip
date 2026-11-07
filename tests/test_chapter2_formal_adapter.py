"""Formal algorithm adapter contracts, entirely in simulation/pitch units."""
import importlib.util
import unittest
from dataclasses import replace

import cv2
import numpy as np

from dmf.chapter2_sim.config import SimConfig
from dmf.chapter2_sim.geometry import SimulationMap
from dmf.chapter2_sim.vision import SyntheticFrame
from dmf.vision.contracts import DropletState as S, VisionResult


class FormalAdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('dmf.chapter2_sim.formal_adapter'),
                             'formal adapter must be implemented')
        from dmf.chapter2_sim import formal_adapter as api
        self.api = api
        self.cfg = SimConfig(route=(190, 191, 192), position_noise=0., drop_probability=0.)
        self.geometry = SimulationMap(self.cfg)

    def frame(self, identity, t, electrode=191, mask=None):
        if mask is None:
            mask = np.zeros(self.geometry.shape, np.uint8)
            center = np.rint(self.geometry.to_pixel(self.geometry.center(electrode))).astype(int)
            cv2.circle(mask, tuple(center), 10, 255, -1)
        return SyntheticFrame(identity, t-.008, t, t+.04, mask)

    def started(self, method='C', ablation='full'):
        adapter = self.api.FormalAdapter(self.cfg, self.geometry, method, ablation, run_id='test')
        adapter.accept(adapter._decision(S.UNKNOWN,.3,source_confirmed=True), .3)
        return adapter

    def test_map_snapshot_is_pitch_not_physical_calibration(self):
        snapshot = self.geometry.snapshot()
        snapshot.update(lower=self.geometry.lower.tolist(), scale=self.geometry.scale, shape=self.geometry.shape)
        normalized = self.api.NormalizedMap.from_snapshot(snapshot)
        self.assertEqual(normalized.metadata['coordinate_unit'], 'pitch')
        self.assertFalse(normalized.metadata['physical_calibration_verified'])
        np.testing.assert_allclose(normalized[191].center_mm, self.geometry.center(191))

    def test_local_snapshot_reports_actual_region_count(self):
        snapshot=dict(metadata=dict(coordinate_unit='pitch',electrode_count=420),
            lower=[0.,0.],scale=20,shape=[40,60],
            polygons={'1':[[0,0],[1,0],[1,1],[0,1]],'2':[[1,0],[2,0],[2,1],[1,1]]})
        mapping=self.api.NormalizedMap.from_snapshot(snapshot)
        self.assertEqual(len(mapping),2)
        self.assertEqual(mapping.metadata['electrode_count'],2)

    def test_simulation_clock_never_fabricates_host_timestamps(self):
        adapter = self.started()
        packet = self.api.make_frame_packet(self.frame(1, .4))
        self.assertEqual(packet.timestamp_clock_domain, 'simulation')
        self.assertIsNone(packet.timing.receive_monotonic_ns)
        self.assertIsNone(adapter.context.applied_receive_ns)
        self.assertTrue(adapter.guard.check(packet, adapter.context, mode='simulation').accepted)
        old = self.api.make_frame_packet(self.frame(2, .2))
        self.assertFalse(adapter.guard.check(old, adapter.context, mode='simulation').accepted)

    def test_formal_state_matches_shared_recognizer_and_arrival_once(self):
        from dmf.experiment.perception import PriorFeatures, StateRecognizer
        adapter = self.started()
        features = PriorFeatures(self.api.NormalizedMap(self.geometry), self.api.state_config(self.cfg))
        recognizer = StateRecognizer(self.api.state_config(self.cfg))
        events = []
        for i in range(9):
            frame = self.frame(i, .4+i*.05)
            outcome = adapter.observe(frame, frame.available_s)
            result = VisionResult(frame.mask, (1., 1.), float(np.count_nonzero(frame.mask)), 1., 0., True)
            observation = features.extract(outcome.packet, result, 190, 191, [])
            expected = recognizer.recognize(observation, outcome.packet.timestamp_s,
                                           outcome.packet.capture_identity, adapter.context)
            self.assertEqual(outcome.state, expected)
            self.assertEqual(outcome.observation, observation)
            if outcome.arrival_event: events.append(outcome.arrival_event)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].confirmed_at_ns)

    def test_duplicate_invalid_gap_and_old_context_cannot_finish_window(self):
        adapter = self.started()
        for i in range(4): adapter.observe(self.frame(i, .4+i*.05), .6+i*.05)
        duplicate = adapter.observe(self.frame(3, .6), .8)
        self.assertEqual(duplicate.state, S.UNKNOWN)
        invalid = self.frame(4, .65, mask=np.zeros(self.geometry.shape, np.uint8))
        self.assertEqual(adapter.observe(invalid, .9).state, S.UNKNOWN)
        self.assertEqual(adapter.observe(self.frame(5, 1.2), 1.3).state, S.UNKNOWN)
        packet = self.api.make_frame_packet(self.frame(6, 1.25), task_epoch=adapter.context.epoch-1)
        self.assertFalse(adapter.guard.check(packet, adapter.context, mode='simulation').accepted)

    def test_acceptance_is_only_counter_and_epoch_mutation_point(self):
        from dmf.experiment.policy import Decision
        adapter = self.started()
        context = adapter.context
        retry = adapter._issue(Decision('Retry', 191, 'test'))
        self.assertFalse(adapter.accept(retry, .8, accepted=False))
        self.assertEqual(adapter.context, context)
        self.assertEqual(adapter.controller.retry_count, 0)
        self.assertTrue(adapter.accept(retry, 1.))
        self.assertEqual(adapter.controller.retry_count, 1)
        self.assertGreater(adapter.context.epoch, context.epoch)

    def test_recovery_changes_epoch_but_not_attempt_until_retry(self):
        from dmf.experiment.policy import Decision
        adapter=self.started()
        attempt=adapter.context.attempt_index
        adapter.accept(adapter._decision(S.DEVIATION,.5),.5)
        self.assertEqual(adapter.context.attempt_index,attempt)
        adapter.accept(adapter._decision(S.UNKNOWN,.7,source_confirmed=True),.7)
        self.assertEqual(adapter.context.attempt_index,attempt+1)

    def test_partial_stall_and_failure_have_bounded_protective_terminal(self):
        from dmf.chapter2_sim.formal_runner import run_formal_trial
        result=run_formal_trial(replace(self.cfg,max_time_s=24.),'failure',71)
        self.assertEqual(result.metrics['status'],'protective_stop')
        self.assertLessEqual(result.metrics['recoveries'],self.cfg.max_recoveries)
        self.assertLessEqual(result.metrics['retries'],self.cfg.max_retries*(self.cfg.max_recoveries+1))
        self.assertFalse(result.metrics['path_complete'])
        self.assertIsNone(result.metrics['completion_time_s'])

    def test_target_position_gate_prevents_coverage_only_arrival(self):
        from dmf.experiment.perception import Observation,StateRecognizer
        recognizer=StateRecognizer(self.api.state_config(self.cfg))
        observation=Observation(True,(1.,1.),100.,0.,1.,0.,0.,None,True,True,
                                target_position_ok=False)
        for i in range(10):state=recognizer.recognize(observation,i*.05,i,'same')
        self.assertNotEqual(state,S.ARRIVED)

    def test_no_validity_still_rejects_missing_mask(self):
        adapter=self.started(ablation='no_validity')
        frame=SyntheticFrame(0,.4,.408,.45,None)
        outcome=adapter.observe(frame,.5)
        self.assertFalse(outcome.observation.valid)
        self.assertEqual(outcome.state,S.UNKNOWN)

    def test_tick_does_not_refresh_last_observation(self):
        adapter = self.started()
        adapter.observe(self.frame(0, .4, electrode=190), .5)
        for t in (.8, 1., 1.5, 2.4): decision = adapter.tick(t)
        self.assertEqual(decision.action, 'Stop')
        self.assertEqual(decision.reason, 'observation quality timeout')

    def test_source_gate_shared_by_all_methods(self):
        for method in 'ABC':
            adapter = self.api.FormalAdapter(self.cfg, self.geometry, method=method)
            for i in range(7):
                outcome = adapter.observe(self.frame(i, .05+i*.05, electrode=190), .09+i*.05)
            self.assertEqual(outcome.decision.action, 'Start')
            self.assertEqual(adapter.phase, 'confirm_source')

    def test_ablations_change_actual_features_not_only_metadata(self):
        from dmf.experiment.perception import PriorFeatures
        mapping = self.api.NormalizedMap(self.geometry)
        frame = self.frame(0, .4, electrode=172)
        packet = self.api.make_frame_packet(frame)
        result = VisionResult(frame.mask, (1., 1.), 100., .01, 0., True)
        strict = PriorFeatures(mapping, self.api.state_config(self.cfg)).extract(packet, result, 190, 191, [])
        relaxed = PriorFeatures(mapping, self.api.state_config(self.cfg), spatial_prior=False,
                                temporal_prior=False, quality_checks=False).extract(packet, result, 190, 191, [])
        self.assertFalse(strict.valid)
        self.assertTrue(relaxed.valid)
        self.assertTrue(relaxed.spatial_ok)
        self.assertTrue(relaxed.target_position_ok)
        self.assertIsNone(relaxed.velocity)
        one = self.started(ablation='no_temporal').observe(self.frame(0, .4), .5)
        self.assertEqual(one.state, S.ARRIVED)

    def test_runner_is_action_dependent_versioned_and_reproducible(self):
        self.assertIsNotNone(importlib.util.find_spec('dmf.chapter2_sim.formal_runner'))
        from dmf.chapter2_sim.formal_runner import run_formal_trial
        cfg = replace(self.cfg, max_time_s=8., position_noise=0., mask_radius_noise=0.)
        a = run_formal_trial(cfg, 'normal', 71)
        b = run_formal_trial(cfg, 'normal', 71)
        self.assertEqual(a.metrics, b.metrics)
        self.assertEqual(a.metrics['method_version'], 'C_formal_b1b4_v1')
        self.assertTrue(a.metrics['path_complete'])
        self.assertEqual(a.metrics['coordinate_unit'], 'pitch')
        self.assertTrue(any(e['event']=='Applied' for e in a.events))
        self.assertTrue(any(e['event']=='Start' for e in a.events))
        self.assertGreater(max(row['x'] for row in a.truth)-min(row['x'] for row in a.truth), .5)

    def test_sub_nanosecond_tick_roundoff_does_not_move_policy_backwards(self):
        from dmf.experiment.policy import Decision
        adapter=self.started()
        adapter.accept(adapter._issue(Decision('Retry',191)),1.7000000000000002)
        self.assertNotEqual(adapter.tick(1.7).reason,'invalid progress timestamp')

    def test_update_logs_confirmed_and_next_activated_target_separately(self):
        from dmf.chapter2_sim.formal_runner import run_formal_trial
        result=run_formal_trial(self.cfg,'normal',71)
        update=next(event for event in result.events if event['event']=='Update')
        self.assertEqual(update['target'],191)
        self.assertEqual(update['activated_target'],192)
        applied=next(event for event in result.events if event['event']=='Applied' and event.get('action')=='Update')
        self.assertEqual(update['request_id'],applied['request_id'])
        self.assertLess(update['time_s'],applied['time_s'])

    def test_failed_update_acceptance_leaves_arrival_retryable(self):
        adapter=self.started()
        for i in range(6):outcome=adapter.observe(self.frame(i,.4+i*.05),.44+i*.05)
        self.assertEqual(outcome.decision.action,'Update')
        self.assertFalse(adapter.accept(outcome.decision,.8,accepted=False))
        self.assertEqual(adapter.controller.index,0)
        self.assertFalse(adapter.ledger.consumed_steps)
        fresh=adapter.observe(self.frame(6,.8),.9)
        self.assertEqual(fresh.decision.action,'Update')
        self.assertIsNone(fresh.arrival_event)  # telemetry event is emitted once
        self.assertTrue(adapter.accept(fresh.decision,.95))
        self.assertEqual(adapter.controller.index,1)
        self.assertEqual(adapter.ledger.consumed_steps,{('test',0)})

    def test_copied_and_old_epoch_decisions_cannot_apply_twice(self):
        adapter=self.started()
        retry=adapter.tick(1.8)
        old_other=adapter.tick(1.85)
        self.assertEqual(retry.action,'Retry')
        copied=replace(retry)
        self.assertTrue(adapter.accept(retry,1.9))
        self.assertFalse(adapter.accept(copied,2.))
        self.assertFalse(adapter.accept(old_other,2.))
        self.assertEqual(adapter.controller.retry_count,1)
        future=adapter.tick(3.4)
        self.assertEqual((future.action,future.target,future.reason),(retry.action,retry.target,retry.reason))
        self.assertTrue(adapter.accept(future,3.5))
        self.assertEqual(adapter.controller.retry_count,2)

    def test_unissued_modified_or_other_adapter_decision_is_rejected(self):
        from dmf.experiment.policy import Decision
        adapter=self.started()
        self.assertFalse(adapter.accept(Decision('Retry',191),.5))
        issued=adapter.tick(1.8)
        self.assertFalse(adapter.accept(replace(issued,target=192),1.9))
        other=self.started()
        other_request=other.tick(1.8)
        self.assertFalse(adapter.accept(other_request,1.9))
        self.assertEqual(adapter.controller.retry_count,0)
        self.assertTrue(adapter.accept(issued,1.9))

    def test_captured_frames_pending_at_stop_remain_censored_rows(self):
        from dmf.chapter2_sim.formal_runner import run_formal_trial
        result = run_formal_trial(replace(self.cfg, max_time_s=.12), 'normal', 71)
        self.assertEqual(len(result.frames), result.metrics['captured_frames'])
        self.assertEqual(len({row['frame_id'] for row in result.frames}), len(result.frames))
        self.assertGreater(result.metrics['pending_frames_at_termination'], 0)
        pending = [row for row in result.frames if row['reason']=='PROCESSING_PENDING_AT_TERMINATION']
        self.assertEqual(len(pending), result.metrics['pending_frames_at_termination'])
        self.assertTrue(all(row['processing_s'] is None and row['state']=='Unknown' for row in pending))

    def test_initial_preparation_applied_once_including_zero_and_subtick_delay(self):
        from dmf.chapter2_sim.formal_runner import run_formal_trial
        for delay in (0.,.004,.04):
            with self.subTest(ack_delay_s=delay):
                result=run_formal_trial(replace(self.cfg,ack_delay_s=delay,max_time_s=.2),'normal',71)
                applications=[e for e in result.events if e['event']=='Applied' and e.get('request_id')==0]
                self.assertEqual(len(applications),1)
                self.assertEqual(applications[0]['applied_s'],delay)
                self.assertTrue(applications[0]['accepted'])
                self.assertGreaterEqual(applications[0]['time_s'],delay)
                self.assertLessEqual(applications[0]['time_s']-delay,self.cfg.dt_s+1e-9)


if __name__ == '__main__': unittest.main()
