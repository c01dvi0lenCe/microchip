"""Final packaging/analysis tests, no formal research world runs."""
import importlib
import importlib.util
import unittest

def module(test,name):
    test.assertIsNotNone(importlib.util.find_spec('dmf.chapter2_sim.s3_final'),'formal namespace missing')
    return importlib.import_module('dmf.chapter2_sim.s3_final.'+name)

class FormalPlanTests(unittest.TestCase):
    def test_plan_exact_identities(self):
        m=module(self,'study');p=m.formal_plan()
        self.assertEqual(len(p),800)
        self.assertEqual([sum(r['cohort']==c for r in p) for c in ('main','bridge','diagnostic')],[560,80,160])
        self.assertEqual(set(r['seed'] for r in p),set(range(265000,265020)))
        self.assertEqual(len({tuple(r.values()) for r in p}),800)
    def test_admission_rejects_missing_or_false(self):
        m=module(self,'study')
        with self.assertRaises((ValueError,FileNotFoundError)):m.load_admission('not-a-gate.json')
    def test_statistics_keep_all_failures_and_zero_count(self):
        m=module(self,'statistics');r=m.wilson(0,20)
        self.assertEqual(r[0],0.);self.assertGreater(r[1],0.)
        self.assertIsNone(m.wilson(0,0))
    def test_pairing_rejects_mismatched_seeds(self):
        m=module(self,'statistics')
        with self.assertRaises(ValueError):m.paired_summary({1:1.},{2:0.},'x')
    def test_paired_equal_data_retains_zero_difference(self):
        m=module(self,'statistics');r=m.paired_summary({1:1.,2:2.},{1:1.,2:2.},'x')
        self.assertEqual((r['n'],r['difference'],r['ci_low'],r['ci_high']),(2,0.,0.,0.))
    def test_unknown_is_not_deleted_from_rate_denominator(self):
        m=module(self,'statistics');r=m.binary_outcome_bounds([True,False,None])
        self.assertEqual(r['planned'],3);self.assertEqual(r['unknown'],1)
        self.assertAlmostEqual(r['lower_yield'],1/3);self.assertAlmostEqual(r['upper_yield'],2/3)
    def test_constructor_capture_never_adds_rng_draw_or_changes_returned_world(self):
        m=module(self,'study')
        from unittest.mock import patch
        import numpy as np
        calls=[]
        class W:
            def __init__(self):self.noise=np.ones((2,2));self.speed_factor=1.;calls.append('W')
        class C:
            def __init__(self):self.errors=np.ones((2,3));self.uniform=np.zeros((2,2));calls.append('C')
        def call():return m.runner.DropletWorld(),m.runner.SyntheticCamera()
        with patch.object(m.runner,'DropletWorld',W),patch.object(m.runner,'SyntheticCamera',C):
            objects,arrays=m.capture_initial_arrays(call)
        self.assertEqual(calls,['W','C']);self.assertIsInstance(objects[0],W)
        self.assertTrue(np.array_equal(arrays['world_noise'],objects[0].noise))
        self.assertIsNot(arrays['world_noise'],objects[0].noise)

if __name__=='__main__':unittest.main()
