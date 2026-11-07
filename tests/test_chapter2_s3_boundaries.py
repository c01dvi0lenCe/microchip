"""Review-discovered counterexamples, fixed before the G2 batch."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from dmf.chapter2_sim.s3.spec import S3Spec
from dmf.chapter2_sim.geometry import SimulationMap
from dmf.chapter2_sim.world import DropletWorld
from dmf.chapter2_sim.s3.reference import physical_segments,support_at
from dmf.chapter2_sim.s3.evaluation import evaluate_trial
try:
    from dmf.chapter2_sim.s3.runner import flush_applications
except ImportError:flush_applications=None

class S3BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.spec=S3Spec();self.g=SimulationMap(self.spec.common.environment)
    def rows(self):
        x,y=self.g.center(191)
        return [dict(time_s=i*.01,x=float(x),y=float(y),true_speed=0.,world_active=191 if i<20 else 192,epoch=1) for i in range(26)]
    def test_switch_boundary_retains_pre_switch_physical_support_at_applied(self):
        s=physical_segments(self.rows(),self.g,self.spec.common.reference,.01)
        self.assertTrue(support_at(s,191,.19)['supported'])
        self.assertTrue(support_at(s,191,.20)['supported'])
        self.assertFalse(support_at(s,191,.21)['supported'])
    def test_recovery_switch_cannot_join_two_short_dwells_at_same_position(self):
        rows=self.rows()
        for i,r in enumerate(rows):r['world_active']=191 if i<10 or i>=16 else 190
        s=physical_segments(rows,self.g,self.spec.common.reference,.01)
        self.assertFalse(support_at(s,191,.25)['supported'])
    def test_unactivated_step_is_never_supported_even_with_physical_segment(self):
        rows=self.rows();r=SimpleNamespace(truth=rows,
            events=[dict(event='Complete',request_id='bad',step=0,time_s=.19)],phase_mode='transport_only',
            metrics=dict(source_prepared=True,transport_complete=True,execution_time_s=.25))
        evaluate_trial(r,self.g,self.spec)
        self.assertFalse(r.steps[0]['supported_confirmation'])
        self.assertEqual(r.event_evaluation[0]['request_label'],'unsupported_no_activation')
    def test_simulated_application_is_flushed_at_its_exact_timestamp(self):
        self.assertIsNotNone(flush_applications,'S3 application boundary coordinator missing')
        w=DropletWorld(self.spec.common.environment,self.g,'normal',264000)
        at=w.command(191,0.,'Start');w.advance(at)
        self.assertIsNone(w.active)
        flush_applications(w,at)
        self.assertEqual(w.active,191);self.assertEqual(w.pending,[])
        self.assertAlmostEqual(w.response_at,at+.18)
    def test_unactivated_step_cannot_be_supported_at_applied_either(self):
        rows=self.rows()
        for r in rows:r['world_active']=191
        r=SimpleNamespace(truth=rows,events=[dict(event='Update',request_id='bad',step=0,time_s=.19),
            dict(event='Applied',action='Update',request_id='bad',activation_step=1,time_s=.23)],
            phase_mode='transport_only',metrics=dict(source_prepared=True,transport_complete=False,execution_time_s=.25))
        evaluate_trial(r,self.g,self.spec)
        self.assertFalse(r.event_evaluation[0]['supported_at_applied'])

if __name__=='__main__':unittest.main()
