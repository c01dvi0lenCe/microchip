"""End-to-end scoring arithmetic without running any simulated dynamics."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from dmf.chapter2_sim.config import SimConfig
from dmf.chapter2_sim.geometry import SimulationMap
from dmf.chapter2_sim.s3.spec import S3Spec
from dmf.chapter2_sim.s3.evaluation import evaluate_trial

class S3ScoringTests(unittest.TestCase):
    def spec(self):
        s=S3Spec();return replace(s,common=replace(s.common,environment=replace(s.common.environment,dt_s=.05)))
    def trial(self):
        g=SimulationMap(SimConfig());x,y=g.center(191)
        truth=[dict(time_s=i*.05,x=float(x),y=float(y),true_speed=0.,world_active=191,epoch=1,phase='transport',step=0) for i in range(5)]
        r=SimpleNamespace(truth=truth,events=[dict(event='Applied',action='Start',request_id='s',activation_step=0,time_s=0.),
            dict(event='Update',request_id='u',step=0,time_s=.1),
            dict(event='Applied',action='Update',request_id='u',activation_step=1,time_s=.2)],
            phase_mode='end_to_end',metrics=dict(execution_time_s=.2,source_prepared=True,transport_complete=False))
        return r,g
    def test_request_and_applied_scored_separately_and_missing_steps_retained(self):
        r,g=self.trial();evaluate_trial(r,g,self.spec())
        e=r.event_evaluation[0];self.assertFalse(e['supported_at_request']);self.assertTrue(e['supported_at_applied'])
        self.assertEqual(r.metrics['unsupported_requests'],1);self.assertEqual(r.metrics['unattempted_steps'],1)
        self.assertEqual(len(r.steps),3);self.assertEqual(r.metrics['terminal_outcome'],'transport_aborted')
    def test_no_source_means_all_three_unattempted_not_zero_planned(self):
        r,g=self.trial();r.events=[];r.metrics['source_prepared']=False
        evaluate_trial(r,g,self.spec());self.assertEqual(r.metrics['unattempted_steps'],3)
        self.assertEqual(r.metrics['terminal_outcome'],'source_preparation_failed')
    def test_duplicate_confirmation_prevents_strict_path(self):
        r,g=self.trial();r.events.insert(2,dict(event='Complete',request_id='dup',step=0,time_s=.2))
        evaluate_trial(r,g,self.spec());self.assertEqual(r.steps[0]['duplicate_requests'],1)
        self.assertFalse(r.steps[0]['supported_confirmation'])
    def test_missing_truth_is_unknown_infrastructure_not_algorithm_failure(self):
        r,g=self.trial();r.truth=[];evaluate_trial(r,g,self.spec())
        self.assertEqual(r.metrics['terminal_outcome'],'infrastructure_invalid')
        self.assertEqual(r.metrics['reference_unknown_steps'],3)
        self.assertEqual(r.metrics['unsupported_requests'],0)
        self.assertEqual(r.steps[0]['unsupported_requests'],0)
        self.assertEqual(r.metrics['missed_confirmations'],0)
        self.assertTrue(r.steps[0]['reference_unknown'])

if __name__=='__main__':unittest.main()
