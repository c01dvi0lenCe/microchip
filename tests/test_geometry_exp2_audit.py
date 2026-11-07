import importlib
import contextlib
import io
import json
import tempfile
from pathlib import Path
from dataclasses import replace
import unittest


def api():
    try:
        return importlib.import_module('scripts.audit_geometry_exp2_mechanisms')
    except ModuleNotFoundError:
        raise AssertionError('independent saved-data audit is not implemented') from None


class IndependentExp2ReferenceTests(unittest.TestCase):
    def rows(self, switch=None, leave=None):
        values=[]
        for i in range(41):
            t=round(i*.01,2)
            values.append(dict(time_s=t,active=2 if switch is not None and t>=switch else 1,
                x_mm=1. if leave is not None and t>=leave else 0.,y_mm=0.,speed_mm_s=0.,
                epoch=i,activation_segment=i))
        return values

    def cfg(self):
        return dict(reference_radius_mm=.1,reference_speed_mm_s=.1,reference_dwell_s=.15,dt_s=.01)

    def test_same_active_retry_epoch_does_not_reset_dwell(self):
        a=api();spans=a.reference_intervals(self.rows(),{1:(0.,0.),2:(1.,0.)},self.cfg())
        self.assertTrue(a.support_at(spans,1,.15))

    def test_request_not_supported_but_later_applied_supported(self):
        a=api();spans=a.reference_intervals(self.rows(),{1:(0.,0.),2:(1.,0.)},self.cfg())
        self.assertFalse(a.support_at(spans,1,.14))
        self.assertTrue(a.support_at(spans,1,.16))

    def test_recovery_real_active_switch_breaks_dwell(self):
        a=api();spans=a.reference_intervals(self.rows(switch=.1),{1:(0.,0.),2:(0.,0.)},self.cfg())
        self.assertFalse(a.support_at(spans,2,.2))
        self.assertTrue(a.support_at(spans,2,.25))

    def test_old_target_has_left_limit_only_at_switch(self):
        a=api();spans=a.reference_intervals(self.rows(switch=.2),{1:(0.,0.),2:(1.,0.)},self.cfg())
        self.assertTrue(a.support_at(spans,1,.2,left_limit=True))
        self.assertFalse(a.support_at(spans,1,.2))
        self.assertFalse(a.support_at(spans,1,.21,left_limit=True))

    def test_leaving_region_invalidates_prior_support(self):
        a=api();spans=a.reference_intervals(self.rows(leave=.2),{1:(0.,0.),2:(1.,0.)},self.cfg())
        self.assertTrue(a.support_at(spans,1,.19))
        self.assertFalse(a.support_at(spans,1,.2))

    def test_window_requires_six_regular_frames_for_quarter_second(self):
        self.assertTrue(hasattr(api(),'rebuild_windows'),'independent W reconstruction missing')
        rows=[dict(epoch='1',phase='transport',frame_id=str(i),exposure_start_s=str(i*.05),
                   C0='True',G='True',Q='True',S='True',K='True',rho_source='1',source_distance_mm='0') for i in range(6)]
        result=api().rebuild_windows(rows,'M2')
        self.assertFalse(result[4]['new_event'])
        self.assertTrue(result[5]['new_event'])
        self.assertEqual(result[5]['window_ids'],'0;1;2;3;4;5')

    def test_missing_frame_rebuilds_confirmation_window(self):
        self.assertTrue(hasattr(api(),'rebuild_windows'),'independent W reconstruction missing')
        ids=[0,1,3,4,5,6]
        rows=[dict(epoch='1',phase='transport',frame_id=str(i),exposure_start_s=str(i*.05),
                   C0='True',G='True',Q='True',S='True',K='True',rho_source='1',source_distance_mm='0') for i in ids]
        self.assertFalse(any(r['new_event'] for r in api().rebuild_windows(rows,'M2')))

    def test_path_support_comes_from_events_and_truth_not_saved_step_flags(self):
        self.assertTrue(hasattr(api(),'derive_step_support'),'event-derived support join missing')
        spans=[dict(target=191,start_s=1.,end_s=2.,left_limit_end=True),
               dict(target=192,start_s=3.,end_s=4.,left_limit_end=True),
               dict(target=172,start_s=5.,end_s=6.,left_limit_end=False,horizon_inclusive=True)]
        events=[dict(event='request',action='Update',origin_step='0',time_s='.9'),
                dict(event='simulated_applied',action='Update',origin_step='0',time_s='1.0'),
                dict(event='request',action='Update',origin_step='1',time_s='3.2'),
                dict(event='simulated_applied',action='Update',origin_step='1',time_s='3.24'),
                dict(event='Complete',action='Complete',origin_step='2',time_s='5.2')]
        rows=api().derive_step_support(events,spans,[190,191,192,172])
        self.assertFalse(rows[0]['request_supported'])
        self.assertTrue(rows[0]['applied_supported'])
        self.assertIsNone(rows[2]['applied_supported'])

    def test_rehashed_contradictory_core_metrics_are_rejected(self):
        self.assertTrue(hasattr(api(),'derive_core_metrics'),'independent core metric reconstruction missing')
        from tests.test_geometry_exp2 import Geometry, pool
        from dmf.chapter2_geometry_sim.exp2.runner import run_trial
        from dmf.chapter2_geometry_sim.exp2.spec import Exp2Config
        from dmf.chapter2_geometry_sim.exp2.persistence import persist_trial
        geometry=Geometry();cfg=replace(Exp2Config(),horizon_s=.5,control_budget_s=.5)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);design=root/'design.json'
            design.write_text(json.dumps(dict(electrodes=[dict(control_id=k,polygon_map_mm=list(p.exterior.coords)) for k,p in geometry.polygons.items()])),encoding='utf-8')
            for method in ('A_fixed','M1','M2','M3'):
                result=run_trial(method,geometry,pool(),cfg,inputs=dict(map_path=str(design)))
                persist_trial(result,root/method)
            with contextlib.redirect_stdout(io.StringIO()):api().audit(root)
            path=root/'M1/metrics.json';values=json.loads(path.read_text(encoding='utf-8'))
            values.update(terminal='reference_supported_path_complete',transport_complete=True,
                          unsupported_requests=999,attempted_steps=3,terminal_holds_last_active=False)
            path.write_text(json.dumps(values),encoding='utf-8')
            path=root/'M1/manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'))
            manifest['artifacts']['metrics.json']=api().sha(root/'M1/metrics.json')
            path.write_text(json.dumps(manifest),encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SystemExit):api().audit(root)
