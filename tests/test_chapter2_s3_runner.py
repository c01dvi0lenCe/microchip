import unittest
from dmf.chapter2_sim.s3.spec import S3Spec
try:
    from dmf.chapter2_sim.s3.runner import run_trial
    from dmf.chapter2_sim.s3.study import audit_development
except ImportError:
    run_trial=audit_development=None

class S3RunnerTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(run_trial,'S3 closed-loop runner missing')
    def test_three_steps_not_attempts_and_fixed_has_no_arrival_event(self):
        r=run_trial(S3Spec(),'normal',264000,'A_fixed')
        self.assertEqual(len(r.steps),3);self.assertEqual(r.metrics['planned_steps'],3)
        self.assertFalse(any(e['event']=='ArrivalEvent' for e in r.events))
        self.assertEqual(sum(s['unattempted'] for s in r.steps),r.metrics['unattempted_steps'])
        for e in r.events:
            if e['event']=='Update':self.assertGreaterEqual(e['time_s']-e['attempt_applied_s'],1.2-1e-9)
    def test_common_source_prefix_and_external_arrays_despite_control_fork(self):
        records=[run_trial(S3Spec(),'normal',264001,m) for m in ('A_fixed','B_single','BTQ','F_full')]
        self.assertEqual(len({r.metrics['exogenous_hash'] for r in records}),1)
        self.assertEqual(len({r.metrics['p0_prefix_hash'] for r in records}),1)
        self.assertGreater(len({r.metrics['capture_sequence_hash'] for r in records}),1)
    def test_failure_denominator_and_action_budget(self):
        r=run_trial(S3Spec(),'failure',264000,'BTQ')
        self.assertFalse(r.metrics['path_complete']);self.assertEqual(len(r.steps),3)
        self.assertEqual(r.metrics['unattempted_steps'],2)
        self.assertLessEqual(r.metrics['max_step_applied'],7)
        self.assertLessEqual(r.metrics['retries'],4);self.assertLessEqual(r.metrics['recovery_resends'],1)
        self.assertEqual(r.metrics['terminal_outcome'],'transport_aborted')
    def test_formal_seed_is_rejected_before_any_world_created(self):
        with self.assertRaises(ValueError):run_trial(S3Spec(),'normal',265000,'BTQ')

if __name__=='__main__':unittest.main()
