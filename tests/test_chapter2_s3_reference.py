"""Hand-calculable S3 references, independent of Mask/arrival thresholds."""
import unittest
from types import SimpleNamespace
from dmf.chapter2_sim.config import SimConfig
from dmf.chapter2_sim.geometry import SimulationMap
from dmf.chapter2_sim.v2.spec import ReferenceSpec
try:
    from dmf.chapter2_sim.s3.reference import physical_segments, support_at
    from dmf.chapter2_sim.s3.evaluation import evaluate_trial
except ImportError:
    physical_segments=support_at=evaluate_trial=None

class S3ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(physical_segments,'S3 independent reference interface missing')
        self.map=SimulationMap(SimConfig());self.ref=ReferenceSpec(dwell_s=.15)
    def truth(self,times,active=191,epoch=1):
        x,y=self.map.center(active)
        return [dict(time_s=t,x=float(x),y=float(y),true_speed=0.,world_active=active,epoch=epoch,step=0,phase='transport') for t in times]
    def derive(self,rows):return physical_segments(rows,self.map,self.ref,.05)
    def test_retry_epoch_does_not_reset_continuous_physical_dwell(self):
        r=self.truth([0,.05,.1,.15,.2]);r[2]['epoch']=2
        s=self.derive(r)
        self.assertEqual(len(s),1);self.assertAlmostEqual(s[0]['upper_s'],.15)
        self.assertTrue(support_at(s,191,.2)['supported'])
    def test_recovery_activation_breaks_target_dwell(self):
        r=self.truth([0,.05,.1]);r+=self.truth([.15],190);r+=self.truth([.2,.25,.3])
        self.assertEqual(self.derive(r),[])
    def test_leaving_target_invalidates_old_support(self):
        r=self.truth([0,.05,.1,.15,.2]);p=self.truth([.25])[0];p['x']+=.3;r.append(p)
        s=self.derive(r)
        self.assertTrue(support_at(s,191,.2)['supported'])
        self.assertFalse(support_at(s,191,.25)['supported'])
    def test_request_before_arrival_is_not_retroactively_safe_at_applied(self):
        s=self.derive(self.truth([0,.05,.1,.15,.2]))
        self.assertFalse(support_at(s,191,.1)['supported'])
        self.assertTrue(support_at(s,191,.2)['supported'])
    def test_truth_gap_cannot_donate_dwell(self):
        self.assertEqual(self.derive(self.truth([0,.05,.2,.25])),[])
    def test_reference_has_no_mask_or_algorithm_threshold_dependency(self):
        r=self.truth([0,.05,.1,.15,.2]);s=self.derive(r)
        for row in r:row.update(eta_target=0.,predicted_state='Deviation',epoch=99)
        self.assertEqual(s,self.derive(r))

if __name__=='__main__':unittest.main()
