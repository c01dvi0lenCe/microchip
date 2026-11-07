import unittest
from shapely.geometry import Polygon,Point


class Exp1BCloseoutTests(unittest.TestCase):
    def test_nearest_phase_tie_lower_and_shape_not_interpolated(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
        a=Polygon([(-1,-1),(1,-1),(1,1),(-1,1)])
        b=Polygon([(-2,-.5),(2,-.5),(2,.5),(-2,.5)])
        replay=SavedOutlineReplay([0.,.5,1.],[a,b,a])
        p,info=replay.at(.25,(20,30))
        self.assertEqual(info['selected_index'],0)
        self.assertAlmostEqual(info['phase_error'],-.25)
        self.assertAlmostEqual(p.area,4.)
        self.assertAlmostEqual(p.centroid.x,20.);self.assertAlmostEqual(p.centroid.y,30.)
        self.assertAlmostEqual(p.bounds[2]-p.bounds[0],2.)

    def test_phase_endpoints_and_error_bound(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
        p=Point(0,0).buffer(2.)
        replay=SavedOutlineReplay([0.,.2,.8,1.],[p]*4)
        for q in [0.,.1,.35,.5,.65,.9,1.]:
            shape,info=replay.at(q,(0,0))
            self.assertLessEqual(abs(info['phase_error']),replay.max_phase_error_bound+1e-12)
            self.assertTrue(shape.is_valid)
        self.assertEqual(replay.at(1.)[1]['selected_index'],3)

    def test_invalid_or_nonmonotone_saved_pool_rejected(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
        p=Point(0,0).buffer(2.)
        with self.assertRaises(ValueError):SavedOutlineReplay([0.,.8,.7,1.],[p]*4)
        bad=Polygon([(0,0),(2,2),(0,2),(2,0)])
        with self.assertRaises(ValueError):SavedOutlineReplay([0.,1.],[p,bad])
        with self.assertRaises(ValueError):SavedOutlineReplay([0.,1.],[p,Point(0,0).buffer(3.)])

    def test_out_of_range_phase_is_not_clamped(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.replay import SavedOutlineReplay
        p=Point(0,0).buffer(2.);replay=SavedOutlineReplay([0.,1.],[p,p])
        for q in (-.01,1.01,float('nan')):
            with self.assertRaises(ValueError):replay.at(q)

    def test_exclusive_outcome_does_not_double_count_early_and_missed(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.semantics import exclusive_outcome
        r=dict(status='executed',category='premature',reference_arrivals=1,decision_s=4.65,missed_references=1)
        result=exclusive_outcome(r)
        self.assertEqual(result['primary_outcome'],'before_reference')
        self.assertEqual(result['primary_outcome_count'],1)
        self.assertEqual(result['unmatched_reference_diagnostic'],1)
        self.assertFalse(result['control_safety_evaluated'])
        self.assertIsNone(result['actual_wrong_advance'])

    def test_no_reference_confirmation_and_no_event_are_different(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.semantics import exclusive_outcome
        base=dict(status='executed',reference_arrivals=0,missed_references=0)
        a=exclusive_outcome(dict(base,category='unsupported',decision_s=2.))
        b=exclusive_outcome(dict(base,category='unconfirmed',decision_s=None))
        self.assertEqual(a['primary_outcome'],'no_reference_confirmation')
        self.assertEqual(b['primary_outcome'],'no_reference_no_confirmation')

    def test_nonexecution_and_censoring_keep_one_planned_record(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.semantics import exclusive_outcome
        self.assertEqual(exclusive_outcome(dict(status='world_generation_failed'))['primary_outcome'],'unattempted')
        x=exclusive_outcome(dict(status='executed',category='decision_censored',reference_arrivals=0,decision_s=11,missed_references=0))
        self.assertEqual(x['primary_outcome'],'censored')

    def test_independent_mask_expectations_and_delivery_schedule(self):
        import numpy as np
        from dmf.chapter2_geometry_sim.exp1b_closeout.audit import expected_mask,expected_deliveries
        mask=np.zeros((60,100),np.uint8);mask[10:50,20:80]=255
        cut=expected_mask('C4',mask,4.3,mask)
        self.assertEqual(np.count_nonzero(mask)-np.count_nonzero(cut),120)
        rows=expected_deliveries('D2')
        self.assertEqual(len(rows),195)
        self.assertFalse(any(r['frame_id'] in range(86,91) for r in rows))

    def test_one_outcome_per_step_including_reference_miss_diagnostic(self):
        from dmf.chapter2_geometry_sim.exp1b_closeout.semantics import exclusive_outcome
        rows=[dict(status='executed',category='premature',reference_arrivals=1,decision_s=2,missed_references=1),
              dict(status='executed',category='supported',reference_arrivals=1,decision_s=5,missed_references=0),
              dict(status='executed',category='unconfirmed',reference_arrivals=1,decision_s=None,missed_references=1)]
        derived=[exclusive_outcome(r) for r in rows]
        self.assertEqual(sum(r['primary_outcome_count'] for r in derived),3)
        self.assertEqual(sum(r['unmatched_reference_diagnostic'] for r in derived),2)


if __name__=='__main__':unittest.main()
