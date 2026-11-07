"""Hand-calculated, scoring-only checks for the isolated S2 study."""
import importlib
import math
from types import SimpleNamespace
import unittest

from dmf.chapter2_sim.v2.spec import ReferenceSpec


class S2EvaluationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.evaluation = importlib.import_module('dmf.chapter2_sim.s2.evaluation')
        except ModuleNotFoundError:
            self.fail('isolated S2 evaluation module has not been implemented')
        self.plan = dict(step_id=0, source=1, target=2, start_s=0., end_s=4., applied_s=0.)
        self.reference = dict(step_id=0, target=2, status='arrived', lower_s=1., upper_s=1.01,
                              dwell_begin_s=.86, observation_start_s=0., observation_end_s=4., truth_complete=True)
        self.followup = dict(task_entered=True, input_generated=True, records_end_s=3., truth_end_s=4.)

    def score(self, times=(), **followup):
        return self.evaluation.score_step(self.plan, self.reference,
            [dict(step_id=0, target=2, timestamp_s=t) for t in times], dict(self.followup, **followup))

    def test_hand_calculated_confirmation_classes_and_latency(self):
        cases = ((.99, 'premature', 0, 1), (1., 'timing_uncertain', 0, 1),
                 (1.005, 'timing_uncertain', 0, 1), (1.01, 'supported', 1, 0),
                 (2.01, 'supported', 1, 0), (2.10, 'late_supported', 0, 1))
        for when, label, primary, missed in cases:
            with self.subTest(when=when):
                result = self.score([when])
                self.assertEqual(label, result['confirmation_label'])
                self.assertEqual(primary, result['supported_confirmations'])
                self.assertEqual(missed, result['missed_supported_confirmation'])
                self.assertEqual(1, result['planned_steps'])
                self.assertEqual(1, result['reference_arrivals'])
                self.assertEqual(primary, result['S_H_numerator'])
                self.assertEqual(1, result['S_H_denominator'])
                self.assertEqual(0, result['unsupported_confirmations'])
        result = self.score([1.01])
        self.assertAlmostEqual(0., result['latency_lower_s'])
        self.assertAlmostEqual(.01, result['latency_upper_s'])
        self.assertIsNone(self.score([.99])['latency_lower_s'])

    def test_no_event_with_full_and_truncated_followup(self):
        full = self.score()
        self.assertEqual(1, full['missed_supported_confirmation'])
        self.assertEqual(1, full['no_prediction_reference'])
        truncated = self.score(records_end_s=1.5)
        self.assertEqual(1, truncated['confirmation_right_censored'])
        self.assertEqual(0, truncated['missed_supported_confirmation'])
        self.assertEqual(1, truncated['no_prediction_reference'])

    def test_first_early_event_consumes_opportunity_no_salvage(self):
        result = self.score([.99, 1.3])
        self.assertEqual(1, result['duplicate_events'])
        self.assertEqual(1, result['premature_confirmations'])
        self.assertEqual(0, result['all_supported_confirmations'])
        self.assertEqual(1, result['missed_supported_confirmation'])

    def test_integrity_counts_are_independent_and_task_end_is_half_open(self):
        events = [dict(step_id=0, target=9, timestamp_s=.5),
                  dict(step_id=99, target=2, timestamp_s=.7),
                  dict(step_id=0, target=2, timestamp_s=4.)]
        result = self.evaluation.score_step(self.plan, self.reference, events, self.followup)
        self.assertEqual(1, result['wrong_target_events'])
        self.assertEqual(1, result['wrong_step_events'])
        self.assertEqual(1, result['outside_task_events'])
        self.assertEqual(0, result['supported_confirmations'])

    def test_complete_no_reference_vs_missing_truth(self):
        event = [dict(step_id=0, target=2, timestamp_s=1.3)]
        for status, label, unsupported in [('not_arrived', 'unsupported_no_reference', 1),
                                         ('reference_right_censored', 'unassessable', 0)]:
            ref = dict(self.reference, status=status, lower_s=None, upper_s=None,
                       truth_complete=status == 'not_arrived')
            result = self.evaluation.score_step(self.plan, ref, event, self.followup)
            self.assertEqual(label, result['confirmation_label'])
            self.assertEqual(unsupported, result['unsupported_confirmations'])
            self.assertEqual(int(not ref['truth_complete']), result['reference_right_censored'])
            self.assertEqual(int(not ref['truth_complete']), result['unassessable_confirmations'])
            self.assertEqual(0, result['S_H_denominator'])
            self.assertIsNone(result['S_H_yield'])

    def test_no_input_or_task_not_entered_is_not_algorithm_miss(self):
        for flags in [dict(task_entered=False), dict(input_generated=False)]:
            result = self.score(**flags)
            self.assertEqual(1, result['unattempted_steps'])
            self.assertEqual(1, result['infrastructure_unknown'])
            self.assertEqual(0, result['missed_supported_confirmation'])
            self.assertEqual(0, result['confirmation_right_censored'])

    def test_explicit_missing_capture_records_are_followup_not_censoring(self):
        result = self.score(records_end_s=3., missing_mask_records=60)
        self.assertEqual(0, result['confirmation_right_censored'])
        self.assertEqual(1, result['missed_supported_confirmation'])

    def test_horizon_clipped_at_half_open_task_end(self):
        plan = dict(self.plan, end_s=1.8)
        result = self.evaluation.score_step(plan, self.reference,
            [dict(step_id=0, target=2, timestamp_s=1.8)], self.followup)
        self.assertEqual(1, result['outside_task_events'])
        self.assertEqual(0, result['missed_supported_confirmation'])
        self.assertEqual(1, result['confirmation_right_censored'])

    def test_invalid_event_times_and_identity_fail_explicitly(self):
        for times in [[math.nan], [math.inf], [1.3, 1.2]]:
            with self.subTest(times=times), self.assertRaises(ValueError):
                self.score(times)
        with self.assertRaises(ValueError):
            self.evaluation.score_step(self.plan, dict(self.reference, target=3), [], self.followup)

    def truth(self, *, position=2.):
        return [dict(time_s=i * .01, x=position, y=0., true_speed=0.,
                     step_id=0, source=1, target=2, world_active=2) for i in range(401)]

    def build(self, rows, tasks=None):
        return self.evaluation.build_reference(rows, tasks or [self.plan],
            SimpleNamespace(centers={1: (1., 0.), 2: (2., 0.)}), ReferenceSpec())

    def test_reference_is_dwell_completion_not_first_entry_and_excludes_preapplied(self):
        rows = self.truth()
        task = dict(self.plan, applied_s=.2)
        result = self.build(rows, [task])[0]
        self.assertEqual('arrived', result['status'])
        self.assertAlmostEqual(.2, result['dwell_begin_s'])
        self.assertAlmostEqual(.34, result['lower_s'])
        self.assertAlmostEqual(.35, result['upper_s'])
        self.assertTrue(result['truth_complete'])
        self.assertTrue(result['simulation'])
        self.assertEqual('simulation_scoring_only', result['provenance'])

    def test_complete_not_arrived_and_incomplete_truth_stay_distinct(self):
        rows = self.truth(position=1.)
        self.assertEqual('not_arrived', self.build(rows)[0]['status'])
        for incomplete in [rows[1:], rows[:-1], rows[:20] + rows[21:]]:
            with self.subTest(count=len(incomplete)):
                result = self.build(incomplete)[0]
                self.assertEqual('reference_right_censored', result['status'])
                self.assertFalse(result['truth_complete'])

    def test_reference_missing_truth_does_not_become_arrived_from_partial_segment(self):
        self.assertEqual('reference_right_censored', self.build(self.truth()[30:])[0]['status'])

    def test_reference_rejects_nonfinite_duplicate_reversed_and_inconsistent_truth(self):
        for field, value in [('time_s', math.nan), ('x', math.inf), ('true_speed', -.1),
                             ('step_id', 3), ('source', 3), ('target', 1), ('world_active', 1)]:
            rows = self.truth()
            rows[10] = dict(rows[10], **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(rows)
        for rows in [self.truth()[:10] + self.truth()[9:], list(reversed(self.truth()))]:
            with self.assertRaises(ValueError):
                self.build(rows)

    def test_reference_endpoint_can_belong_to_next_task_and_attributes_are_supported(self):
        rows = self.truth()
        rows[-1] = dict(rows[-1], step_id=1, source=2, target=3, world_active=3)
        result = self.build(rows, [SimpleNamespace(**self.plan)])[0]
        self.assertEqual('arrived', result['status'])

    def test_scheduled_apply_boundary_may_precede_next_interval_world_application(self):
        task = dict(self.plan, applied_s=.04)
        rows = self.truth()
        for row in rows[:5]:
            row.update(world_active=None, phase='pending')
        for row in rows[5:]:
            row['phase'] = 'transport'
        result = self.build(rows, [task])[0]
        self.assertAlmostEqual(.05, result['dwell_begin_s'])
        self.assertAlmostEqual(.20, result['upper_s'])
        rows[5]['world_active'] = None
        with self.assertRaises(ValueError):
            self.build(rows, [task])

    def test_reference_does_not_accumulate_pending_phase_or_cross_epochs(self):
        rows = self.truth()
        for row in rows:
            row.update(phase='pending', epoch=0)
        for row in rows[10:]:
            row['phase'] = 'transport'
        result = self.build(rows)[0]
        self.assertAlmostEqual(.1, result['dwell_begin_s'])
        self.assertAlmostEqual(.25, result['upper_s'])
        for row in rows[10:]:
            row['epoch'] = 1 if row['time_s'] < .2 else 2
        result = self.build(rows)[0]
        self.assertAlmostEqual(.2, result['dwell_begin_s'])
        self.assertAlmostEqual(.35, result['upper_s'])

    def test_reference_rejects_mismatched_declared_apply_time(self):
        rows = self.truth()
        rows[10]['applied_s'] = .5
        with self.assertRaises(ValueError):
            self.build(rows)


if __name__ == '__main__':
    unittest.main()
