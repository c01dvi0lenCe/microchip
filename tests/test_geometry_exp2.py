"""Deterministic development-contract tests, not performance trials."""
import importlib
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from shapely.geometry import Point, box
from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
from dmf.chapter2_geometry_sim.observation import CameraFrame


def api(name):
    try:
        return importlib.import_module('dmf.chapter2_geometry_sim.exp2.' + name)
    except ModuleNotFoundError:
        raise AssertionError('experiment2 implementation is absent: ' + name) from None


class Geometry:
    pitch_mm = 3.2
    def __init__(self):
        self.centers = {190: (0., 0.), 191: (3.2, 0.), 192: (6.4, 0.), 172: (6.4, 3.2)}
        self.polygons = {k: box(x-1.5, y-1.5, x+1.5, y+1.5) for k,(x,y) in self.centers.items()}
    def center(self, i): return np.array(self.centers[i])


def pool():
    p = Point(0, 0).buffer(2., quad_segs=32)
    return SavedOutlineReplay([0., 1.], [p, p])


def fixture():
    cfg = api('spec').Exp2Config()
    return Geometry(), pool(), cfg


def frame(c, i, t, **changes):
    f = CameraFrame(i,t,t+.008,t+.048,np.ones((2,2),np.uint8),c.context,round(t+.05,10))
    values = dict(valid=True,x_mm=3.2,y_mm=0.,rho_source=1.,rho_target=1.,
                  eta_source=0.,eta_target=1.,distance_mm=0.,source_distance_mm=0.,
                  components=1,touches_roi_border=False)
    values.update(changes)
    return f, values


def prepared(method='M3'):
    c = api('controller').ExperimentController(method,api('spec').Exp2Config(),'fixture')
    c.start(0.); c.on_applied(c.pending, .04)
    for i in range(6):
        f,v=frame(c,i,.05+i*.05);c.observe(f,v)
    c.on_applied(c.pending,.39)
    return c


class ConfigTests(unittest.TestCase):
    def test_default_three_step_route(self): self.assertEqual(api('spec').Exp2Config().route,(190,191,192,172))
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError): replace(api('spec').Exp2Config(), velocity_tau_s=math.nan)
    def test_nonadjacent_route_rejected(self):
        with self.assertRaises(ValueError): replace(api('spec').Exp2Config(), route=(190,192,191,172))
    def test_bad_budget_rejected(self):
        with self.assertRaises(ValueError): replace(api('spec').Exp2Config(),max_retries=-1)
    def test_config_is_immutable(self):
        with self.assertRaises(AttributeError): api('spec').Exp2Config().dt_s=.2
    def test_off_grid_applied_delay_rejected(self):
        with self.assertRaises(ValueError):replace(api('spec').Exp2Config(),applied_delay_s=.045)
    def test_off_grid_scheduler_times_rejected(self):
        cfg=api('spec').Exp2Config()
        for key,value in (('response_delay_s',.185),('horizon_s',40.005),('control_budget_s',39.995),
            ('fixed_wait_s',4.655),('source_timeout_s',2.005),('attempt_timeout_s',10.005),
            ('recovery_timeout_s',10.005),('camera_fps',19.),('dt_s',.03)):
            with self.subTest(key=key),self.assertRaises(ValueError):replace(cfg,**{key:value})


class WorldTests(unittest.TestCase):
    def make(self):
        g,p,c=fixture();return api('world').CausalWorld(g,p,c)
    def test_applied_exact_boundary(self):
        w=self.make();w.request(191,'Start');w.advance(.04)
        self.assertEqual(w.active,191);self.assertIsNone(w.pending)
        self.assertEqual(w.events[-1]['event'],'simulated_applied')
    def test_pending_preserves_active(self):
        w=self.make();w.request(191,'Start');w.advance(.03);self.assertEqual(w.active,190)
    def test_pending_rejects_second_transaction(self):
        w=self.make();w.request(191,'Start')
        with self.assertRaises(ValueError):w.request(192,'Update')
    def test_initial_stationary_response_delay(self):
        w=self.make();w.request(191,'Start');w.advance(.22)
        np.testing.assert_array_equal(w.position,[0.,0.]);w.advance(.23);self.assertGreater(w.position[0],0.)
    def test_switch_preserves_position_velocity(self):
        w=self.make();w.request(191,'Start');w.advance(1.);w.request(192,'Update');w.advance(1.039)
        w.advance(1.04);p=w.position.copy();v=w.velocity.copy();w.flush_due()
        np.testing.assert_array_equal(w.position,p);np.testing.assert_array_equal(w.velocity,v)
        event=w.events[-1];self.assertEqual(event['old_active'],191)
        np.testing.assert_allclose(event['left_limit']['vx_mm_s'],v[0])
    def test_same_active_retry_keeps_segment_response(self):
        w=self.make();w.request(191,'Start');w.advance(1.);seg=w.activation_segment;response=w.response_at_s
        w.request(191,'Retry');w.advance(1.04)
        self.assertEqual(w.activation_segment,seg);self.assertEqual(w.response_at_s,response)
    def test_no_overlap_freezes(self):
        w=self.make();w.request(172,'Update');w.advance(1.)
        self.assertEqual(w.status,'blocked_no_overlap');np.testing.assert_array_equal(w.position,[0.,0.])
    def test_shape_area_centroid(self):
        w=self.make();w.request(191,'Start');w.advance(1.2);s=w.snapshot()
        self.assertAlmostEqual(s['area_mm2'],w.pool.area,8)
        self.assertLess(math.dist(w.polygon.centroid.coords[0],w.position),1e-8)
    def test_turn_angle_rate_limited(self):
        w=self.make();w.request(191,'Start');w.advance(4.);w.request(192,'Update');w.advance(8.)
        w.request(172,'Update');w.advance(8.04);a=w.angle_rad;w.advance(8.05)
        self.assertLessEqual(abs(w.angle_rad-a),2*math.pi*.01+1e-8)
    def test_different_switch_time_changes_trajectory(self):
        a=self.make();b=self.make()
        for w in (a,b):w.request(191,'Start')
        a.advance(.3);a.request(192,'Update');a.advance(4.)
        b.advance(3.);b.request(192,'Update');b.advance(4.)
        self.assertGreater(np.linalg.norm(a.position-b.position),.5)


class ControllerTests(unittest.TestCase):
    def test_common_p0(self):
        for m in ('A_fixed','M1','M2','M3'):
            c=prepared(m);self.assertEqual(c.phase,'transport');self.assertEqual(c.events[2]['event'],'SourceReady')
    def test_three_planned_steps_even_unattempted(self):
        c=prepared();self.assertEqual(len(c.steps),3);self.assertFalse(c.steps[2]['attempted'])
    def test_pending_does_not_consume(self):
        c=prepared('M1');f,v=frame(c,10,.5);c.observe(f,v);self.assertIsNotNone(c.pending)
        before=len(c.frames);f,v=frame(c,11,.55);self.assertFalse(c.observe(f,v));self.assertEqual(len(c.frames),before)
    def test_old_context_is_rejected(self):
        c=prepared('M1');f,v=frame(c,10,.5);f.context=None;c.observe(f,v)
        self.assertEqual(c.frames[-1]['c0_reason'],'OLD_TASK_FRAME');self.assertIsNone(c.pending)
    def test_duplicate_does_not_confirm(self):
        c=prepared('M2')
        for i in range(8):f,v=frame(c,10,.5);c.observe(f,v)
        self.assertIsNone(c.pending);self.assertFalse(c.frames[-1]['C0'])
    def test_gap_rebuilds(self):
        c=prepared('M2')
        for i,t in enumerate((.5,.55,.6,.9,.95,1.)):f,v=frame(c,10+i,t);c.observe(f,v)
        self.assertIsNone(c.pending)
    def test_fixed_wait_has_no_arrival_event(self):
        c=prepared('A_fixed');c.tick(5.04)
        self.assertIsNotNone(c.pending);self.assertEqual(c.arrivals,[])
    def test_once_per_step_across_attempts(self):
        c=prepared('M1');f,v=frame(c,10,.5);c.observe(f,v)
        self.assertEqual(len(c.arrivals),1);self.assertIn(0,c.consumed_steps)
    def test_retry_only_counted_on_applied(self):
        c=prepared();c.tick(10.39);self.assertEqual(c.steps[0]['retries'],0)
        c.on_applied(c.pending,10.43);self.assertEqual(c.steps[0]['retries'],1)
    def test_source_timeout(self):
        c=api('controller').ExperimentController('M3',api('spec').Exp2Config(),'x')
        c.start(0.);c.on_applied(c.pending,.04);c.tick(2.04)
        self.assertEqual(c.terminal,'source_preparation_failed')
    def test_global_budget(self):
        c=prepared();c.tick(40.);self.assertEqual(c.terminal,'time_budget_exhausted')
    def test_identity_high_water_survives_retry_context(self):
        c=prepared('M2');f,v=frame(c,20,.5);c.observe(f,v)
        c.tick(10.39);c.on_applied(c.pending,10.43)
        f,v=frame(c,20,10.5);c.observe(f,v)
        self.assertEqual(c.frames[-1]['c0_reason'],'DUPLICATE_OR_REVERSED')
    def test_complete_is_lifecycle_only(self):
        c=prepared('M1')
        for i,t in enumerate((.5,.65,.8)):
            f,v=frame(c,20+i,t);c.observe(f,v)
            if c.pending:c.on_applied(c.pending,t+.09)
        self.assertEqual(c.phase,'complete');self.assertIsNone(c.pending)
        self.assertEqual(sum(s['applied_count'] for s in c.steps),3)
        self.assertIsNone(c.steps[2]['departure_applied_s'])
    def test_recovery_p0_resend_and_retry_exhaustion(self):
        c=prepared();c.cfg=replace(c.cfg,horizon_s=80.,control_budget_s=80.)
        for timeout,applied in ((10.39,10.43),(20.43,20.47),(30.47,30.51)):
            c.tick(timeout);c.on_applied(c.pending,applied)
        self.assertEqual(c.phase,'recovering');self.assertEqual(c.steps[0]['recoveries'],1)
        for i in range(6):f,v=frame(c,40+i,30.55+i*.05);c.observe(f,v)
        self.assertEqual(c.pending['action'],'Resend');c.on_applied(c.pending,30.89)
        self.assertEqual(c.steps[0]['applied_count'],5);self.assertEqual(c.steps[0]['retries'],2)
        c.tick(40.89);self.assertEqual(c.terminal,'transport_aborted')
    def test_prepare_bad_source_coverage_never_ready(self):
        c=api('controller').ExperimentController('M3',api('spec').Exp2Config(),'x')
        c.start(0.);c.on_applied(c.pending,.04)
        for i in range(10):f,v=frame(c,i,.05+i*.05,rho_source=.89);c.observe(f,v)
        self.assertEqual(c.phase,'prepare');self.assertIsNone(c.pending)
    def test_terminal_controller_rejects_applied_without_mutation(self):
        c=prepared();c.tick(10.39);pending=dict(c.pending)
        c._stop('transport_aborted',10.4);count=c.steps[0]['applied_count'];epoch=c.epoch
        with self.assertRaises(ValueError):c.on_applied(pending,10.43)
        self.assertEqual(c.phase,'stopped');self.assertEqual(c.epoch,epoch)
        self.assertEqual(c.steps[0]['applied_count'],count)


class ReferenceTests(unittest.TestCase):
    def make(self):return api('reference').IndependentReference(Geometry(),api('spec').Exp2Config())
    def snap(self,t,active=191,x=3.2,speed=0.,segment=1):
        return dict(time_s=t,active=active,x_mm=x,y_mm=0.,speed_mm_s=speed,activation_segment=segment)
    def test_retry_same_active_dwell_continuous(self):
        r=self.make();r.observe(self.snap(0.));r.observe(self.snap(.1));r.observe(self.snap(.15))
        self.assertTrue(r.supported(191));self.assertEqual(len(r.segments),1)
    def test_recovery_resets_segment(self):
        r=self.make();r.observe(self.snap(0.));r.observe(self.snap(.2));r.observe(self.snap(.21,190,0.,segment=2))
        self.assertFalse(r.supported(191));self.assertEqual(len(r.segments),2)
    def test_leaving_target_invalidates_support(self):
        r=self.make();r.observe(self.snap(0.));r.observe(self.snap(.2));r.observe(self.snap(.3,x=2.))
        self.assertFalse(r.supported(191))
    def test_request_not_retrospectively_supported(self):
        r=self.make();r.observe(self.snap(0.));request=r.mark('request',.14,191,0,'Update')
        r.observe(self.snap(.16));applied=r.mark('applied',.18,191,0,'Update')
        self.assertFalse(request['supported']);self.assertTrue(applied['supported'])
    def test_exclusive_complete_categories(self):
        fn=api('reference').exclusive_terminal
        self.assertEqual(fn('complete',True),'reference_supported_path_complete')
        self.assertEqual(fn('complete',False),'workflow_complete_without_supported_path')
        self.assertEqual(fn('transport_aborted',True),'transport_aborted')
    def test_world_segment_label_cannot_reset_reference(self):
        r=self.make();r.observe(self.snap(0.));r.observe(self.snap(.1,segment=99));r.observe(self.snap(.15,segment=100))
        self.assertTrue(r.supported(191));self.assertEqual(len(r.segments),1)
    def test_reference_interval_closed_on_active_change(self):
        r=self.make();r.observe(self.snap(0.));r.observe(self.snap(.2));r.observe(self.snap(.21,190,0.,segment=2))
        self.assertEqual(r.segments[0]['intervals'][0]['end_s'],.21)
    def test_reference_status_completed_not_censored(self):
        r=self.make();r.observe(self.snap(0.));r.observe(self.snap(.2));c=prepared()
        rows,_=r.score(c,[])
        self.assertEqual(rows[0].get('reference_status'),'completed')
        self.assertFalse(rows[0]['reference_censored'])
    def test_reference_status_closed_noncompletion_not_censored(self):
        r=self.make();r.observe(self.snap(0.,speed=1.));r.observe(self.snap(.2,192,6.4,segment=2));c=prepared()
        rows,_=r.score(c,[])
        self.assertEqual(rows[0].get('reference_status'),'observed_closed_noncompletion')
        self.assertFalse(rows[0]['reference_censored'])
    def test_reference_status_unattempted_not_censored(self):
        r=self.make();r.observe(self.snap(0.,190,0.,segment=0));c=prepared()
        rows,_=r.score(c,[])
        self.assertEqual(rows[2].get('reference_status'),'unattempted')
        self.assertFalse(rows[2]['reference_censored'])
    def test_reference_status_ongoing_at_horizon_is_censored(self):
        r=self.make();r.observe(self.snap(0.,speed=1.));r.observe(self.snap(.2,speed=1.));c=prepared()
        rows,_=r.score(c,[])
        self.assertEqual(rows[0].get('reference_status'),'ongoing_at_horizon')
        self.assertTrue(rows[0]['reference_censored'])


class RunnerTests(unittest.TestCase):
    def test_short_fixture_preserves_all_captures_and_three_steps(self):
        g,p,c=fixture();c=replace(c,horizon_s=.5,control_budget_s=.5)
        result=api('runner').run_trial('M3',g,p,c)
        self.assertEqual(len(result.captures),10);self.assertEqual(len(result.steps),3)
        self.assertEqual(result.world[-1]['time_s'],.5)
        self.assertEqual(result.metrics['random_draws'],0)
    def test_persistence_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileExistsError):api('persistence').persist_trial(None,Path(d))
    def test_fixture_persistence_has_actual_mask_hashes(self):
        g,p,c=fixture();c=replace(c,horizon_s=.2,control_budget_s=.2)
        result=api('runner').run_trial('M3',g,p,c)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'fixture';api('persistence').persist_trial(result,out)
            self.assertEqual(len(list((out/'masks').glob('*.png'))),4)
            self.assertTrue((out/'manifest.json').is_file())
    def test_due_frame_consumed_before_exact_budget_timeout(self):
        g,p,c=fixture();c=replace(c,horizon_s=.5,control_budget_s=.45)
        values=dict(valid=True,x_mm=3.2,y_mm=0.,rho_source=1.,rho_target=1.,eta_source=0.,
            eta_target=1.,distance_mm=0.,source_distance_mm=0.,components=1,touches_roi_border=False)
        runner=api('runner')
        with patch.object(runner,'observed_features',return_value=values):
            result=runner.run_trial('M1',g,p,c)
        self.assertEqual(len(result.arrivals),1)
        self.assertEqual(result.arrivals[0]['decision_s'],.45)
    def test_capture_keeps_full_bound_task_identity(self):
        g,p,c=fixture();c=replace(c,horizon_s=.2,control_budget_s=.2)
        result=api('runner').run_trial('M3',g,p,c,run_id='bound-fixture')
        capture=result.captures[1]
        self.assertEqual(capture.get('captured_run_id'),'bound-fixture')
        self.assertEqual(capture.get('captured_applied_s'),.04)
        self.assertEqual(capture.get('captured_source'),190)
        self.assertEqual(capture.get('captured_target'),190)
    def test_one_synthetic_integration_fixture_to_complete(self):
        g,p,c=fixture();c=replace(c,horizon_s=15.,control_budget_s=15.,pixels_per_mm=20.)
        result=api('runner').run_trial('M3',g,p,c)
        self.assertTrue(result.metrics['transport_complete'])
        self.assertEqual(len(result.arrivals),3)
        self.assertEqual(sum(s['attempted'] for s in result.steps),3)
        self.assertEqual(result.world[-1]['time_s'],15.)
        self.assertEqual(result.world[-1]['active'],172)
    def test_transaction_cannot_apply_after_global_budget(self):
        g,p,c=fixture();c=replace(c,horizon_s=.5,control_budget_s=.37)
        result=api('runner').run_trial('M3',g,p,c)
        self.assertFalse(any(e.get('action')=='Start' and e['event']=='request' for e in result.events))
        self.assertTrue(all(r['active']==190 for r in result.world))
        self.assertTrue(result.metrics['terminal_holds_last_active'])
        self.assertIsNone(result.metrics.get('pending_transaction_at_horizon','MISSING'))
    def test_applied_exactly_at_global_budget_is_admitted(self):
        g,p,c=fixture();c=replace(c,horizon_s=.5,control_budget_s=.39)
        result=api('runner').run_trial('M3',g,p,c)
        applied=[e for e in result.events if e['event']=='simulated_applied' and e['action']=='Start']
        self.assertEqual(len(applied),1);self.assertEqual(applied[0]['time_s'],.39)
        self.assertEqual(result.steps[0]['applied_count'],1)
        self.assertEqual(result.world[-1]['active'],191)
        self.assertIsNone(result.metrics.get('pending_transaction_at_horizon','MISSING'))
    def test_unavailable_capture_is_explicitly_censored(self):
        g,p,c=fixture();c=replace(c,horizon_s=.17,control_budget_s=.17)
        result=api('runner').run_trial('M3',g,p,c)
        last=result.captures[-1]
        self.assertTrue(last.get('right_censored'));self.assertFalse(last.get('delivered'))
        self.assertEqual(last.get('delivery_censor_reason'),'NOT_AVAILABLE_BY_HORIZON')


if __name__=='__main__':unittest.main()
