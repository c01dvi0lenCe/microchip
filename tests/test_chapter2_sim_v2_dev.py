from pathlib import Path
import tempfile
import unittest
from dmf.chapter2_sim.v2.spec import StudySpecV2,load_spec
try:
    from dmf.chapter2_sim.v2.development import run_smoke,run_compatibility,failed_trial
except ImportError:
    run_smoke=None


class DevelopmentTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(run_smoke,'development entry missing')

    def test_config_is_independent_and_phase_specific(self):
        spec=load_spec(Path(__file__).parents[1]/'configs/chapter2_simulation_v2.yaml')
        self.assertEqual(spec.target.window,spec.source.window)
        self.assertIsNot(spec.target.window,spec.source.window)

    def test_failed_trial_keeps_planned_support_and_unknown_reference(self):
        from dmf.chapter2_sim.v2.evaluation import summarize_phases
        r=failed_trial(StudySpecV2(),'normal',262000,'F','end_to_end','injected infrastructure error')
        s=summarize_phases([r])
        self.assertEqual(s['planned_trials'],1);self.assertEqual(s['planned_steps'],3)
        self.assertEqual(s['terminal_counts'],{'infrastructure_error':1})
        self.assertEqual(r.metrics['reference_unknown_steps'],3)

    def test_development_output_refuses_overwrite_before_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):run_smoke(StudySpecV2(),Path(tmp))

    def test_historical_compatibility_small_sample(self):
        report=run_compatibility(StudySpecV2(),scenarios=('normal',))
        self.assertEqual(report['checked_trials'],1)
        self.assertTrue(report['all_equal'])


if __name__=='__main__':unittest.main()
