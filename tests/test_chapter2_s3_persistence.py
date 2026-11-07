import tempfile
import unittest
from pathlib import Path
from dmf.chapter2_sim.s3.runner import run_trial
from dmf.chapter2_sim.s3.spec import S3Spec
try:
    from dmf.chapter2_sim.s3.persistence import save_trial,load_trial
except ImportError:
    save_trial=load_trial=None

class S3PersistenceTests(unittest.TestCase):
    def test_actual_mask_and_scoring_sources_are_saved_without_overwrite(self):
        self.assertIsNotNone(save_trial,'S3 persistence missing')
        s=S3Spec();r=run_trial(s,'normal',264000,'BTQ')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'trial';save_trial(r,p,s);loaded=load_trial(p)
            self.assertEqual(loaded['manifest']['schema'],'chapter2_s3_development_v1')
            self.assertTrue(any('s3/adapter.py' in k for k in loaded['manifest']['source_hashes']))
            for name in ('dmf/experiment/policy.py','dmf/experiment/perception.py','dmf/experiment/evidence.py','dmf/chapter2_sim/s2/spec.py','dmf/chapter2_sim/geometry.py'):
                self.assertIn(name,loaded['manifest']['source_hashes'])
                self.assertTrue((p/'source_code'/name).is_file())
            self.assertEqual(len(loaded['truth']),len(r.truth))
            self.assertTrue(all(c['mask_path'] for c in loaded['captures'] if c['dropped']=='False'))
            with self.assertRaises(FileExistsError):save_trial(r,p,s)
            (p/'evaluation/truth_ticks.csv').write_text('tampered',encoding='utf-8')
            with self.assertRaises(ValueError):load_trial(p)

if __name__=='__main__':unittest.main()
