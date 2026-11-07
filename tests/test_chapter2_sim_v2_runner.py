from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

from dmf.chapter2_sim.v2.spec import StudySpecV2
from dmf.chapter2_sim.formal_runner import run_formal_trial

try:
    from dmf.chapter2_sim.v2.runner import run_trial_v2
    from dmf.chapter2_sim.v2.evaluation import evaluate_trial, summarize_phases
    from dmf.chapter2_sim.v2.persistence import save_trial, load_trial
except ImportError:
    run_trial_v2=None


class RunnerV2Tests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(run_trial_v2,'v2 runner missing')
        self.spec=StudySpecV2()

    def test_compatibility_preserves_every_legacy_row(self):
        old=run_formal_trial(self.spec.environment,'normal',261000)
        new=run_trial_v2(self.spec,'normal',261000,'C_v1_compat')
        self.assertEqual(new.legacy.metrics,old.metrics)
        self.assertEqual(new.legacy.truth,old.truth)
        self.assertEqual(new.legacy.frames,old.frames)
        self.assertEqual(new.legacy.events,old.events)

    def test_runner_cannot_expose_truth_to_adapter(self):
        import ast
        from dmf.chapter2_sim.v2 import adapter,observation,arrival
        for module in (adapter,observation,arrival):
            text=Path(module.__file__).read_text(encoding='utf-8')
            imports=[n.module or '' for n in ast.walk(ast.parse(text)) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(s.endswith(('world','reference','evaluation','runner')) for s in imports))

    def test_source_only_does_not_issue_transport(self):
        r=run_trial_v2(self.spec,'normal',262000,'F',phase_mode='source_only')
        self.assertTrue(r.metrics['prepared'])
        self.assertEqual(r.metrics['terminal_outcome'],'source_prepared')
        self.assertFalse(any(e['event'] in ('Start','Update','Complete') for e in r.events))
        self.assertEqual(len(r.steps),3)
        self.assertTrue(all(s['execution_outcome']=='unattempted' for s in r.steps))

    def test_transport_only_is_explicit_controlled_initial_condition(self):
        r=run_trial_v2(self.spec,'normal',262000,'BTQ',phase_mode='transport_only')
        self.assertEqual(r.metrics['preparation_status'],'controlled_initial_condition')
        self.assertIsNone(r.metrics['preparation_time_s'])
        self.assertEqual(r.metrics['planned_steps'],3)
        self.assertTrue(any(e['event']=='Start' for e in r.events))

    def test_source_and_target_configs_do_not_alias(self):
        spec=replace(self.spec,target=replace(self.spec.target,coverage=.95))
        a=run_trial_v2(self.spec,'normal',262000,'F',phase_mode='source_only')
        b=run_trial_v2(spec,'normal',262000,'F',phase_mode='source_only')
        self.assertEqual(a.metrics['preparation_time_s'],b.metrics['preparation_time_s'])
        self.assertEqual(a.gates,b.gates)

    def test_no_formal_seed_or_arbitrary_method(self):
        with self.assertRaises(ValueError):run_trial_v2(self.spec,'normal',263000,'F')
        with self.assertRaises(ValueError):run_trial_v2(self.spec,'normal',262000,'A')

    def test_planned_trials_and_steps_conserved(self):
        runs=[run_trial_v2(self.spec,s,262000,'F') for s in ('normal','jitter','failure')]
        total=summarize_phases(runs)
        self.assertEqual(total['planned_trials'],3)
        self.assertEqual(sum(total['terminal_counts'].values()),3)
        self.assertEqual(total['planned_steps'],9)
        self.assertEqual(sum(total['step_execution_counts'].values()),9)
        self.assertEqual(total['planned_trials'],total['prepared']+total['not_prepared'])

    def test_mask_persistence_complete_and_refuses_overwrite(self):
        r=run_trial_v2(self.spec,'normal',262000,'F')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'trial';save_trial(r,p,self.spec)
            loaded=load_trial(p)
            self.assertEqual(len(loaded['captures']),r.metrics['captured_frames'])
            self.assertEqual(len(loaded['truth']),len(r.truth))
            self.assertEqual(len(list((p/'observations/masks').glob('*.png'))),sum(not q['dropped'] for q in r.captures))
            with self.assertRaises(FileExistsError):save_trial(r,p,self.spec)

    def test_missing_predictions_not_removed(self):
        r=run_trial_v2(self.spec,'normal',262000,'F')
        result=evaluate_trial(r,[])  # Explicitly empty prediction list.
        self.assertEqual(result['planned_steps'],3)
        self.assertEqual(result['confirmed_steps'],0)
        self.assertEqual(result['missed_reference_events'],result['reference_arrived_steps'])
        self.assertIsNone(result['confirmation_delay_mean_s'])

    def test_target_frame_logs_the_actual_shared_window(self):
        r=run_trial_v2(self.spec,'normal',262000,'F')
        frames={f['frame_id']:f for f in r.frames if f.get('phase')=='transport'}
        for g in r.gates:
            if g['stage']=='target':self.assertEqual(frames[g['frame_id']]['arrival_window_count'],g['window_count'])


if __name__=='__main__':unittest.main()
