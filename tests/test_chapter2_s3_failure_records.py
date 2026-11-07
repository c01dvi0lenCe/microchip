import tempfile
import unittest
from pathlib import Path
from dmf.chapter2_sim.s3.spec import S3Spec,development_plan
from dmf.chapter2_sim.s3.persistence import save_trial,load_trial
try:
    from dmf.chapter2_sim.s3.study import infrastructure_failure
except ImportError:infrastructure_failure=None

class S3FailureRecordTests(unittest.TestCase):
    def test_infrastructure_failure_can_be_saved_with_three_unknown_steps(self):
        self.assertIsNotNone(infrastructure_failure,'S3 failed-trial persistence factory missing')
        s=S3Spec();r=infrastructure_failure(s,development_plan()[0],RuntimeError('injected fixture failure'))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'invalid';save_trial(r,path,s);record=load_trial(path)
            self.assertEqual(record['manifest']['cohort'],'main')
            self.assertEqual(r.metrics['reference_unknown_steps'],3)
            self.assertEqual(len(r.steps),3)
            self.assertEqual(r.metrics['terminal_outcome'],'infrastructure_invalid')

if __name__=='__main__':unittest.main()
