import hashlib
import importlib.util
from pathlib import Path
import unittest
import numpy as np

P=Path(__file__).resolve().parents[1]/'scripts/audit_chapter2_s3_final.py'
def auditor(t):
    t.assertTrue(P.exists(),'formal independent audit missing')
    s=importlib.util.spec_from_file_location('s3_final_auditor_test',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

class FinalAuditTests(unittest.TestCase):
    def test_array_bytes_and_speed_factor_independently_match(self):
        m=auditor(self);arrays={k:np.ones((2,2)) for k in ('world_noise','camera_errors','camera_uniform')};arrays['speed_factor']=np.array(1.)
        ext={k:hashlib.sha256(arrays[k].tobytes()).hexdigest() for k in arrays if k!='speed_factor'};ext['speed_factor']=1.
        self.assertEqual(m.check_array_payload(arrays,ext),[])
        arrays['speed_factor']=np.array(1.1);self.assertTrue(m.check_array_payload(arrays,ext))
    def test_source_alias_does_not_hide_extra_frozen_scientific_mutation(self):
        m=auditor(self)
        self.assertEqual(m.core_hash_errors({'a':'1'},{'a':'1','b':'2'}),[])
        self.assertTrue(m.core_hash_errors({'a':'1'},{'a':'9','b':'2'}))
    def test_wilson_matches_hand_boundary_not_zero_uncertainty(self):
        m=auditor(self);lo,hi=m.independent_wilson(0,20)
        self.assertEqual(lo,0.);self.assertAlmostEqual(hi,0.161125158,places=7)

if __name__=='__main__':unittest.main()
