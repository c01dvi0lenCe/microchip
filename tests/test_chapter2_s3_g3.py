"""G3 auditor contract; no formal seeds or research trials."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/audit_chapter2_s3_g3.py'

def audit(test):
    test.assertTrue(SCRIPT.exists(),'G3 audit interface not implemented')
    s=importlib.util.spec_from_file_location('g3_audit_test',SCRIPT)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

class G3Tests(unittest.TestCase):
    def test_single_frame_quality_is_not_arrival_gate(self):
        a=audit(self)
        row=dict(stage='target',C0_passed='True',enabled='{"S":false,"W":false,"K":false,"Q":false}',
                 raw='{"S":true,"K":true,"Q":false}',coverage_passed='True',eligible='True')
        self.assertEqual(a.check_trace('B_single',row),[])
        self.assertTrue(a.check_trace('BTQ',row))
    def test_source_flags_are_not_confused_with_target_flags(self):
        a=audit(self)
        self.assertEqual(a.check_trace('B_single',dict(stage='source',enabled='{"Q":true}')),[])
    def test_tampered_eligibility_is_rejected(self):
        a=audit(self)
        row=dict(stage='target',C0_passed='True',enabled='{"S":false,"W":true,"K":false,"Q":true}',
                 raw='{"S":true,"K":true,"Q":false}',coverage_passed='True',eligible='True')
        self.assertTrue(a.check_trace('BTQ',row))
    def test_formal_seed_cannot_be_used_in_rng_development_audit(self):
        a=audit(self)
        with self.assertRaises(ValueError):a.assert_development_seed(265000)
    def test_rng_hash_checks_speed_factor_not_only_arrays(self):
        a=audit(self)
        self.assertEqual(a.compare_external({'world_noise':'a','speed_factor':1.},{'world_noise':'a','speed_factor':1.}),[])
        self.assertTrue(a.compare_external({'world_noise':'a','speed_factor':1.},{'world_noise':'a','speed_factor':1.1}))
    def test_formal_plan_has_fixed_cohorts_and_no_exploratory_extra(self):
        a=audit(self);p=a.planned_formal_identities()
        self.assertEqual(len(p),800)
        self.assertEqual([sum(r['cohort']==c for r in p) for c in ('main','bridge','diagnostic')],[560,80,160])
        self.assertTrue(all(r['seed_index'] in range(20) for r in p))

if __name__=='__main__':unittest.main()
