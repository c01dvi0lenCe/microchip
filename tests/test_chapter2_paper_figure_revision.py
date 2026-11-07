import unittest
import math
try:
    from scripts import chapter2_paper_figure_revision_v2 as r
except ImportError:
    r=None

class AcademicFigureRevisionTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(r,'independent v2 figure module missing')

    def test_request_resend_uses_logged_phase_only(self):
        self.assertEqual(r.action_kind({'event':'Retry','phase':'recovering'}),'resend')
        self.assertEqual(r.action_kind({'event':'Retry','phase':'transport'}),'Retry')

    def test_applied_resend_uses_origin_phase(self):
        self.assertEqual(r.action_kind({'event':'Applied','action':'Retry','phase':'transport','origin_phase':'recovering'}),'resend')
        self.assertEqual(r.action_kind({'event':'Applied','action':'Retry','origin_phase':'transport'}),'Retry')

    def test_no_new_action_is_inferred_from_empty_row(self):
        self.assertIsNone(r.action_kind({'event':'ArrivalEvent'}))

    def test_wilson_preserves_zero_and_hundred_intervals(self):
        lo,hi=r.wilson_check(0,20);self.assertAlmostEqual(lo,0);self.assertGreater(hi,.16)
        lo,hi=r.wilson_check(20,20);self.assertLess(lo,.84);self.assertAlmostEqual(hi,1)

    def test_action_summary_reports_actual_group_variation(self):
        self.assertEqual(r.group_description([3]*20),dict(n=20,mean=3.,minimum=3.,maximum=3.,unique=1))
        self.assertEqual(r.group_description([0,1])['unique'],2)

    def test_failed_trial_cost_is_penalty_not_execution_time(self):
        self.assertEqual(r.expected_cost({'path_complete':'False','execution_time_s':'2.0'}),24.)
        self.assertEqual(r.expected_cost({'path_complete':'True','execution_time_s':'4.2'}),4.2)

    def test_unknown_does_not_get_relabelled(self):
        self.assertEqual(r.state_points([{'processing_s':'1','state':'Unknown'},{'processing_s':'','state':'Moving'}],'Unknown'),[1.])

    def test_method_offsets_separate_endpoint_markers(self):
        xs=r.method_x_positions(0)
        self.assertEqual(len(set(xs)),4);self.assertGreater(min(b-a for a,b in zip(xs,xs[1:])),.17)

if __name__=='__main__':unittest.main()
