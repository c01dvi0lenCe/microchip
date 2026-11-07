"""Hand-computable outcome separation, independent of a running controller."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def api():
    path = ROOT / 'scripts/analyze_geometry_exp2_outcomes.py'
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location('exp2_outcomes_test_api', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def event(kind, time, action, target, step, request_id=''):
    return dict(event=kind, time_s=time, action=action, target=target,
                origin_step=step, request_id=request_id)


class OutcomeSeparationTests(unittest.TestCase):
    def module(self):
        module = api(); self.assertIsNotNone(module, 'outcome separation module is not implemented')
        return module

    def test_complete_before_reference_is_not_retroactively_supported(self):
        m = self.module()
        spans = [dict(target=172, start_s=1.2, end_s=2., horizon_inclusive=True, left_limit_end=False)]
        outcome, align = m.separate_outcomes([event('Complete', 1., 'Complete', 172, 2)], spans, (190,191,192,172), 2.)
        self.assertFalse(outcome['final_reference_supported_at_complete'])
        self.assertTrue(outcome['final_reference_supported_at_horizon'])
        self.assertEqual(outcome['final_target_reference_first_s'], 1.2)
        self.assertEqual(outcome['update_request_count'], 0)
        self.assertIsNone(align[-1]['commanded_active_electrode'])
        self.assertIsNone(align[-1]['applied_active_electrode'])

    def test_update_distinguishes_completed_target_and_commanded_electrode(self):
        m = self.module()
        events = [event('request', 1., 'Update', 192, 0, '3'),
                  event('simulated_applied', 1.04, 'Update', 192, 0, '3')]
        spans = [dict(target=191, start_s=1.01, end_s=1.04, horizon_inclusive=False, left_limit_end=True)]
        outcome, align = m.separate_outcomes(events, spans, (190,191,192,172), 2.)
        self.assertEqual(align[0]['completed_task_target'], 191)
        self.assertEqual(align[0]['commanded_active_electrode'], 192)
        self.assertEqual(align[0]['applied_active_electrode'], 192)
        self.assertFalse(align[0]['decision_reference_supported'])
        self.assertTrue(align[0]['applied_reference_supported'])
        self.assertEqual(outcome['unsupported_update_requests'], 1)
        self.assertEqual(outcome['unsupported_update_applied'], 0)

    def test_ever_reference_does_not_mask_departure_before_horizon(self):
        m = self.module()
        spans = [dict(target=172, start_s=.5, end_s=1.5, horizon_inclusive=False, left_limit_end=False)]
        outcome, _ = m.separate_outcomes([event('Complete', 1., 'Complete', 172, 2)], spans, (190,191,192,172), 2.)
        self.assertTrue(outcome['final_reference_supported_at_complete'])
        self.assertFalse(outcome['final_reference_supported_at_horizon'])
        self.assertTrue(outcome['final_reference_ever_completed'])

    def test_unattempted_steps_keep_three_planned_rows_and_na(self):
        m = self.module()
        outcome, align = m.separate_outcomes([], [], (190,191,192,172), 2.)
        self.assertEqual(outcome['planned_steps'], 3)
        self.assertEqual(outcome.get('attempted_steps'), 0)
        self.assertEqual(len(align), 3)
        self.assertIsNone(outcome['final_reference_supported_at_complete'])
        self.assertFalse(outcome['final_reference_supported_at_horizon'])
        self.assertEqual(outcome['decision_count'], 0)

    def test_attempted_steps_derive_from_actual_applied_not_complete(self):
        m = self.module()
        events = [event('simulated_applied', .4, 'Start', 191, 0, '2'),
                  event('simulated_applied', .8, 'Retry', 191, 0, '3'),
                  event('Complete', 1., 'Complete', 172, 2)]
        outcome, _ = m.separate_outcomes(events, [], (190,191,192,172), 2.)
        self.assertEqual(outcome.get('attempted_steps'), 1)

    def test_unmatched_applied_cannot_be_counted_as_success(self):
        m = self.module()
        with self.assertRaises(ValueError):
            m.separate_outcomes([event('simulated_applied', 1., 'Update', 192, 0, '4')], [], (190,191,192,172), 2.)

    def test_control_complete_is_one_decision_not_electrode_request(self):
        m = self.module()
        outcome, _ = m.separate_outcomes([event('Complete', 1., 'Complete', 172, 2)], [], (190,191,192,172), 2.)
        self.assertEqual(outcome['decision_count'], 1)
        self.assertEqual(outcome['unsupported_decisions'], 1)
        self.assertEqual(outcome['update_request_count'], 0)
        self.assertEqual(outcome['update_applied_count'], 0)


if __name__ == '__main__':
    unittest.main()
