from pathlib import Path
import unittest

try:
    from scripts.chapter2_process_figures_revision import load_plot_source, panel_records, visible_states
except ImportError:
    load_plot_source=None


ROOT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1')


class ProcessFigureRevisionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(load_plot_source,'read-only figure adapter missing')
        self.r=load_plot_source(ROOT/'development_smoke_r2/trials/end_to_end__normal__262000__F')

    def test_exact_same_trial_and_six_logged_ticks(self):
        panels=panel_records(self.r)
        self.assertEqual([p['time_s'] for p in panels],[.5,.81,1.06,1.46,1.92,1.96])
        self.assertEqual({p['trial_id'] for p in panels},{'normal:262000:F:end_to_end:full'})

    def test_applied_tick_cannot_paint_old_mask_or_next_world_activation(self):
        s=self.r.snapshot(1.96)
        self.assertIsNone(s['overlay_mask'])
        self.assertEqual(s['truth']['world_active'],191)
        self.assertEqual(s['truth']['target'],192)

    def test_no_stationary_or_deviation_fabricated(self):
        self.assertEqual(visible_states(self.r),['Unknown','Moving','Partial','Arrived'])

    def test_reference_confirmation_and_application_are_distinct(self):
        self.assertAlmostEqual(self.r.references[0]['upper_s'],1.46)
        self.assertAlmostEqual(next(e['time_s'] for e in self.r.events if e['event']=='Update'),1.92)
        self.assertAlmostEqual(next(e['time_s'] for e in self.r.events if e['event']=='Applied' and e.get('action')=='Update'),1.96)

    def test_no_unoccurred_retry_or_recovery(self):
        self.assertFalse(any(e['event'] in ('Retry','Recovery') for e in self.r.events))

    def test_plotter_does_not_call_simulation(self):
        import ast
        import scripts.chapter2_process_figures_revision as module
        tree=ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
        names={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertFalse(names & {'run_trial_v2','run_formal_trial','DropletWorld','SyntheticCamera'})


if __name__=='__main__':unittest.main()
