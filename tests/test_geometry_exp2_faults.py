"""Synthetic fixture contracts; these are not the ten real-map development runs."""
import importlib
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from tests.test_geometry_exp2 import fixture, prepared, frame


def api(name):
    try:
        return importlib.import_module('dmf.chapter2_geometry_sim.exp2_faults.' + name)
    except ModuleNotFoundError:
        raise AssertionError('independent fault harness absent: ' + name) from None


def case(name):
    return next(c for c in api('spec').CASES if c.case_id == name)


def run(name, horizon=5.):
    g,p,c = fixture()
    c = replace(c,horizon_s=horizon,control_budget_s=horizon,pixels_per_mm=10.)
    return api('runner').run_case(case(name),g,p,c,run_id='fault-fixture')


class DeclarationTests(unittest.TestCase):
    def test_exact_predeclared_cases_and_fixed_compact_phase(self):
        rows=api('spec').CASES
        self.assertEqual([c.case_id for c in rows],['early_M1','early_M2','stall_false_M2',
            'stall_false_M3','camera_gap_M2','late_duplicate_M2','applied_delay_M2',
            'stall_timeout_M2','turn_early_M1','turn_early_M2'])
        self.assertEqual(case('early_M1').fake_exposures_s,(2.05,))
        self.assertEqual(case('stall_false_M2').fake_exposures_s,tuple(round(2.2+i*.05,2) for i in range(12)))
        self.assertEqual(case('turn_early_M2').fake_electrode,192)
        self.assertEqual(case('turn_early_M2').fake_exposures_s,(4.8,))
        self.assertTrue(all(c.fake_phase==1. for c in rows))
        with self.assertRaises(FrozenInstanceError):rows[0].method='M3'

    def test_existing_suite_destination_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as d,patch.object(api('runner'),'load_inputs') as load:
            with self.assertRaises(FileExistsError):api('runner').run_suite(d)
            load.assert_not_called()


class StallTests(unittest.TestCase):
    def test_physical_pin_keeps_transactions_and_same_target_reference_segment(self):
        g,p,c=fixture();w=api('world').StalledWorld(g,p,c,stall_at_s=2.)
        w.request(191,'Start');w.advance(2.);position=w.position.copy();phase=w.phase
        self.assertEqual(np.linalg.norm(w.velocity),0.)
        w.request(191,'Retry');w.advance(2.04)
        self.assertEqual(w.active,191);self.assertEqual(w.activation_segment,1)
        w.request(192,'Update');w.advance(2.08);w.advance(3.)
        np.testing.assert_array_equal(w.position,position)
        np.testing.assert_array_equal(w.velocity,[0.,0.])
        self.assertGreater(phase,0.)
        self.assertEqual(w.phase,0.);self.assertEqual(w.active,192)
        self.assertEqual(w.events[-1]['event'],'simulated_applied')
        self.assertEqual(len(w.interventions),1)


class CaptureDeliveryTests(unittest.TestCase):
    def test_twelve_fake_captures_leave_true_world_stalled(self):
        r=run('stall_false_M2',2.9)
        changed=[c for c in r.captures if c['mask_injected']]
        self.assertEqual([c['frame_id'] for c in changed],list(range(44,56)))
        self.assertEqual(len({c['visible_mask_sha256'] for c in changed}),1)
        pinned=[w for w in r.world if w['time_s']>=2.]
        self.assertEqual(len({(w['x_mm'],w['y_mm'],w['speed_mm_s']) for w in pinned}),1)
        self.assertEqual(pinned[0]['speed_mm_s'],0.)
        # This is a stress fixture, not an expected winner assertion.
        self.assertEqual(len(r.steps),3)

    def test_single_mask_uses_fixed_pool_shape_and_saves_original(self):
        r=run('early_M1',2.3);changed=[c for c in r.captures if c['mask_injected']]
        self.assertEqual([c['frame_id'] for c in changed],[41])
        row=changed[0]
        self.assertNotEqual(row['source_mask_sha256'],row['visible_mask_sha256'])
        g,p,c=fixture();raster=api('runner').RouteRaster(g,replace(c,pixels_per_mm=10.))
        expected=raster.mask(p.at(1.,g.center(191))[0])
        np.testing.assert_array_equal(row['mask'],expected)
        self.assertEqual(row['captured_run_id'],'fault-fixture')
        self.assertEqual(row['captured_applied_s'],.39)

    def test_camera_gap_retains_all_generated_masks_and_explicit_drops(self):
        r=run('camera_gap_M2',1.8)
        drops=[c for c in r.captures if c['dropped']]
        self.assertEqual([c['frame_id'] for c in drops],list(range(20,33)))
        self.assertEqual(len(r.captures),36)
        self.assertEqual(r.metrics['dropped_frames'],13)
        self.assertTrue(all(not c['right_censored'] and c['delivery_censor_reason']=='DECLARED_CAMERA_DROP' for c in drops))
        self.assertFalse(set(range(20,33)) & {d['frame_id'] for d in r.deliveries})

    def test_delay_does_not_block_due_frames_and_duplicate_keeps_identity(self):
        r=run('late_duplicate_M2',4.6)
        deliveries=r.deliveries;ids=[d['frame_id'] for d in deliveries]
        self.assertLess(ids.index(69),ids.index(68))
        duplicates=[d for d in deliveries if d['frame_id']==69]
        self.assertEqual(len(duplicates),2)
        self.assertNotEqual(duplicates[0]['delivery_uid'],duplicates[1]['delivery_uid'])
        self.assertAlmostEqual(duplicates[1]['available_s']-duplicates[0]['available_s'],.02)
        self.assertEqual(duplicates[0]['exposure_start_s'],3.45)
        self.assertEqual(duplicates[1]['exposure_start_s'],3.45)
        self.assertEqual(duplicates[0]['captured_epoch'],duplicates[1]['captured_epoch'])
        self.assertTrue(duplicates[1]['duplicate_delivery'])
        frames=[f for f in r.frames if f['frame_id'] in (68,69)]
        self.assertTrue(any(f['c0_reason']=='DUPLICATE_OR_REVERSED' for f in frames))
        capture=next(c for c in r.captures if c['frame_id']==68)
        delivered=next(d for d in deliveries if d['frame_id']==68)
        self.assertEqual(capture['captured_epoch'],delivered['captured_epoch'])

    def test_delayed_frame_censoring_is_explicit(self):
        r=run('late_duplicate_M2',3.6)
        capture=next(c for c in r.captures if c['frame_id']==68)
        self.assertFalse(capture['delivered']);self.assertTrue(capture['right_censored'])
        self.assertEqual(capture['delivery_censor_reason'],'NOT_AVAILABLE_BY_HORIZON')
        self.assertIn(68,r.metrics['queued_frame_ids_at_horizon'])

    def test_applied_delay_is_only_config_difference_and_pending_is_respected(self):
        r=run('applied_delay_M2',1.)
        self.assertEqual(r.config.applied_delay_s,.3)
        applies=[e for e in r.events if e['event']=='simulated_applied']
        self.assertTrue(all(abs(e['time_s']-e['request_s']-.3)<1e-9 for e in applies))
        requests=[e for e in r.events if e['event']=='request']
        for first,second in zip(requests,requests[1:]):
            self.assertGreaterEqual(second['request_s'],first['request_s']+.3-1e-9)
        for request in requests:
            self.assertFalse(any(request['request_s']<f['processed_s']<request['request_s']+.3-1e-9
                                 for f in r.frames))
        old_context=[f for f in r.frames if f['processed_s']==.9 and f['exposure_start_s']<.9]
        self.assertTrue(old_context)
        self.assertTrue(all(f['c0_reason']=='OLD_TASK_FRAME' for f in old_context))

    def test_persistence_preserves_pngs_interventions_and_manifest(self):
        r=run('early_M1',2.2)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'fixture';api('persistence').persist_case(r,out)
            self.assertTrue((out/'unmodified_source_masks/0041.png').is_file())
            self.assertTrue((out/'masks/0041.png').is_file())
            self.assertTrue((out/'interventions.csv').is_file())
            manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['case']['case_id'],'early_M1')
            self.assertEqual(manifest['random_draws'],0)
            with self.assertRaises(FileExistsError):api('persistence').persist_case(r,out)


class LifecycleTests(unittest.TestCase):
    def test_short_fixture_retries_recovery_and_budget_are_bounded(self):
        g,p,c=fixture()
        c=replace(c,horizon_s=4.,control_budget_s=4.,attempt_timeout_s=1.,
                  recovery_timeout_s=1.,pixels_per_mm=10.)
        r=api('runner').run_case(case('stall_timeout_M2'),g,p,c)
        self.assertEqual(r.steps[0]['retries'],2)
        self.assertEqual(r.steps[0]['recoveries'],1)
        self.assertLessEqual(r.steps[0]['applied_count'],c.max_step_applied)
        self.assertFalse(r.steps[1]['attempted']);self.assertFalse(r.steps[2]['attempted'])
        self.assertEqual(r.metrics['terminal'],'time_budget_exhausted')
        terminal=next(e['time_s'] for e in r.events if e['event']=='Stop')
        self.assertFalse(any(e['event']=='simulated_applied' and e['time_s']>terminal for e in r.events))

    def test_terminal_applied_rejected_without_state_change(self):
        c=prepared('M2');c.tick(10.39);tx=dict(c.pending)
        c._stop('transport_aborted',10.4)
        before=(c.epoch,c.phase,c.steps[0]['applied_count'])
        with self.assertRaises(ValueError):c.on_applied(tx,10.43)
        self.assertEqual((c.epoch,c.phase,c.steps[0]['applied_count']),before)

    def test_no_random_entrypoint_called(self):
        with patch('numpy.random.default_rng',side_effect=AssertionError('RNG forbidden')), \
             patch('numpy.random.seed',side_effect=AssertionError('seed forbidden')), \
             patch('random.random',side_effect=AssertionError('RNG forbidden')):
            r=run('early_M2',.5)
        self.assertEqual(r.metrics['random_draws'],0)

    def test_budget_preserves_three_plans_no_post_terminal_applied(self):
        r=run('stall_timeout_M2',3.)
        self.assertEqual(len(r.steps),3)
        stop=next(e for e in r.events if e['event']=='Stop')
        self.assertTrue(all(e['time_s']<=stop['time_s'] for e in r.events if e['event']=='simulated_applied'))
        self.assertTrue(r.metrics['terminal_holds_last_active'])
        self.assertIsNone(r.metrics['pending_transaction_at_horizon'])
        self.assertEqual(r.metrics['random_draws'],0)

    def test_complete_is_still_lifecycle_only(self):
        c=prepared('M1')
        for i,t in enumerate((.5,.65,.8)):
            f,v=frame(c,20+i,t);c.observe(f,v)
            if c.pending:c.on_applied(c.pending,t+.09)
        self.assertEqual(c.terminal,'complete');self.assertIsNone(c.pending)
        self.assertEqual(sum(s['applied_count'] for s in c.steps),3)

    def test_turn_applied_keeps_world_left_limit_continuous(self):
        r=run('turn_early_M1',5.1)
        turn=next(e for e in r.world_events if e['event']=='simulated_applied' and e['target']==172)
        sample=next(w for w in r.world if abs(w['time_s']-turn['time_s'])<1e-9)
        for key in ('x_mm','y_mm','vx_mm_s','vy_mm_s','shape_phase','angle_rad','area_mm2'):
            self.assertAlmostEqual(sample[key],turn['left_limit'][key],10)
        injected=[c for c in r.captures if c['mask_injected']]
        self.assertEqual([c['frame_id'] for c in injected],[96])


if __name__=='__main__':unittest.main()
