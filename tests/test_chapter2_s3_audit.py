"""Hand-calculated fixtures for the independent, read-only S3 audit."""
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit_chapter2_s3.py'


def auditor(test):
    test.assertTrue(SCRIPT.exists(), 'independent audit implementation is absent')
    spec = importlib.util.spec_from_file_location('independent_s3_audit', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ticks(active=191, count=7, dt=.05):
    return [dict(time_s=round(i*dt, 8), x=0., y=0., true_speed=0.,
                 world_active=active, epoch=i//2, step=0, phase='transport')
            for i in range(count)]


class IndependentSupportTests(unittest.TestCase):
    def scan(self, rows, dt=.05):
        return auditor(self).scan_support(rows, {191: (0., 0.), 192: (1., 0.)}, dt)

    def test_dwell_upper_bound_is_strict_support_boundary(self):
        a = auditor(self); intervals = self.scan(ticks())
        self.assertEqual(a.support_at(intervals, 191, .149)['supported'], False)
        self.assertTrue(a.support_at(intervals, 191, .15)['supported'])
        self.assertAlmostEqual(intervals[0]['lower_s'], .10)
        self.assertAlmostEqual(intervals[0]['upper_s'], .15)

    def test_software_epochs_do_not_reset_same_active_dwell(self):
        a = auditor(self); intervals = self.scan(ticks())
        self.assertEqual(len(intervals), 1)
        self.assertTrue(a.support_at(intervals, 191, .2)['supported'])

    def test_unactivated_location_has_no_support(self):
        a = auditor(self)
        self.assertFalse(a.support_at(self.scan(ticks(None)), 191, .3)['supported'])

    def test_wrong_active_has_no_support_even_when_at_target(self):
        self.assertEqual(self.scan(ticks(192)), [])

    def test_speed_breaks_contiguous_dwell(self):
        a = auditor(self); rows = ticks(); rows[2]['true_speed'] = .061
        intervals = self.scan(rows)
        self.assertFalse(a.support_at(intervals, 191, .25)['supported'])
        self.assertTrue(a.support_at(intervals, 191, .3)['supported'])

    def test_position_breaks_contiguous_dwell(self):
        a = auditor(self); rows = ticks(); rows[2]['x'] = .091
        self.assertFalse(a.support_at(self.scan(rows), 191, .25)['supported'])

    def test_active_change_interrupts_dwell(self):
        rows = ticks(); rows[2]['world_active'] = 192
        a = auditor(self); intervals = self.scan(rows)
        self.assertFalse(a.support_at(intervals, 191, .25)['supported'])
        self.assertTrue(a.support_at(intervals, 191, .3)['supported'])

    def test_switch_left_limit_only_exists_at_switch_time(self):
        rows = ticks(); rows[4]['world_active'] = 192
        rows[5]['world_active'] = rows[6]['world_active'] = 192
        a = auditor(self); intervals = self.scan(rows)
        self.assertTrue(a.support_at(intervals, 191, .2)['supported'])
        self.assertFalse(a.support_at(intervals, 191, .20001)['supported'])

    def test_switch_left_limit_requires_current_position_continuity(self):
        rows = ticks(); rows[4].update(world_active=192, x=1.)
        a = auditor(self)
        self.assertFalse(a.support_at(self.scan(rows), 191, .2)['supported'])

    def test_truth_gap_does_not_bridge_dwell(self):
        a = auditor(self); rows = ticks(); del rows[2]
        self.assertFalse(a.support_at(self.scan(rows), 191, .25)['supported'])

    def test_request_is_not_retroactively_supported_by_applied(self):
        a = auditor(self); intervals = self.scan(ticks())
        events = [dict(event='Update', request_id='u', time_s=.1, step=0, target=191),
                  dict(event='Applied', request_id='u', time_s=.2, step=1, action='Update')]
        rows = a.evaluate_events(events, intervals)
        self.assertFalse(rows[0]['supported_at_request'])
        self.assertTrue(rows[0]['supported_at_applied'])

    def test_complete_has_no_fabricated_applied(self):
        a = auditor(self)
        events = [dict(event='Complete', request_id='c', time_s=.2, step=0, target=191)]
        row = a.evaluate_events(events, self.scan(ticks()))[0]
        self.assertIsNone(row['supported_at_applied'])
        self.assertIsNone(row['applied_s'])

    def test_boundaries_are_inclusive(self):
        rows = ticks();
        for row in rows: row.update(x=.09, true_speed=.06)
        self.assertTrue(auditor(self).support_at(self.scan(rows), 191, .15)['supported'])


class IndependentContractTests(unittest.TestCase):
    def test_expected_plan_has_exact_120_identities(self):
        a = auditor(self); plan = a.expected_plan()
        self.assertEqual(len(plan), 120)
        self.assertEqual(len({a.identity(x) for x in plan}), 120)
        self.assertEqual(sum(x['cohort']=='main' for x in plan), 84)
        self.assertEqual(sum(x['cohort']=='bridge' for x in plan), 12)
        self.assertEqual(sum(x['cohort']=='diagnostic' for x in plan), 24)

    def test_overlapping_pending_request_is_an_explicit_error(self):
        a = auditor(self)
        events = [dict(event='Prepare', request_id='a', time_s=0., activated_target=190, applied_s=.04),
                  dict(event='Start', request_id='b', time_s=.01, activated_target=191, applied_s=.05),
                  dict(event='Applied', request_id='a', time_s=.04, activated_target=190, action='Prepare', applied_s=.04),
                  dict(event='Applied', request_id='b', time_s=.05, activated_target=191, action='Start', applied_s=.05)]
        errors = a.check_transactions(events, [], 'normal', 'B_single')
        self.assertTrue(any('overlapping_pending' in e for e in errors), errors)

    def test_fixed_timer_rejects_arrival_and_early_update(self):
        a = auditor(self)
        events = [dict(event='ArrivalEvent', time_s=.2),
                  dict(event='Complete', request_id='c', time_s=1., attempt_applied_s=0.)]
        errors = a.check_transactions(events, [], 'normal', 'A_fixed')
        self.assertTrue(any('fixed_timer_arrival' in e for e in errors))
        self.assertTrue(any('fixed_timer_early' in e for e in errors))

    def test_fixed_timer_uses_actual_applied_not_untrusted_recorded_attempt(self):
        a = auditor(self)
        events = [dict(event='Start', request_id='s', time_s=.76, activated_target=191, applied_s=.8),
                  dict(event='Applied', request_id='s', time_s=.8, activated_target=191, action='Start', applied_s=.8),
                  dict(event='Complete', request_id='c', time_s=1.2, step=0, target=191, attempt_applied_s=0.)]
        errors = a.check_transactions(events, [], 'normal', 'A_fixed')
        self.assertTrue(any('fixed_timer_actual_applied' in e for e in errors), errors)

    def test_request_scheduled_applied_must_equal_notification(self):
        a = auditor(self)
        events = [dict(event='Prepare', request_id='s', time_s=0., activated_target=190, applied_s=.1),
                  dict(event='Applied', request_id='s', time_s=.04, activated_target=190, action='Prepare', applied_s=.04)]
        errors = a.check_transactions(events, [], 'normal', 'BTQ')
        self.assertTrue(any('request_applied_time_mismatch' in e for e in errors), errors)

    def test_missing_csv_is_never_treated_as_zero_rows(self):
        a = auditor(self)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'missing'):
                a.read_csv(Path(folder)/'absent.csv')

    def test_mask_divergence_requires_same_frame_after_control_fork(self):
        a = auditor(self)
        first = dict(events=[dict(event='Applied', time_s=.1, activated_target=191)],
                     captures=[dict(frame_id=1, capture_sample_time_s=.2, raw_mask_sha256='a')])
        second = dict(events=[dict(event='Applied', time_s=.1, activated_target=192)],
                      captures=[dict(frame_id=2, capture_sample_time_s=.3, raw_mask_sha256='b')])
        self.assertIsNone(a.mask_fork_witness(first, second))
        second['captures'][0]['frame_id'] = 1
        self.assertEqual(a.mask_fork_witness(first, second)['frame_id'], 1)

    def test_aggregate_step_values_must_match_not_just_identities(self):
        a = auditor(self)
        original = [dict(trial_id='t', step=0, supported_confirmation=False)]
        audited = [dict(trial_id='t', step=0, supported_confirmation=True)]
        self.assertTrue(a.compare_ledger(original, audited, ('trial_id', 'step')))

    def test_aggregate_event_reference_bounds_must_match(self):
        a = auditor(self)
        original = [dict(trial_id='t', request_id='u', reference_upper_s=.15)]
        audited = [dict(trial_id='t', request_id='u', reference_upper_s=.20)]
        self.assertTrue(a.compare_ledger(original, audited, ('trial_id', 'request_id')))

    def test_aggregate_missing_and_duplicate_rows_are_errors(self):
        a = auditor(self)
        row = dict(trial_id='t', step=0, supported_confirmation=True)
        self.assertTrue(a.compare_ledger([row, row], [row], ('trial_id', 'step')))
        self.assertTrue(a.compare_ledger([], [row], ('trial_id', 'step')))

    def test_identical_aggregate_rows_pass(self):
        a = auditor(self)
        row = dict(trial_id='t', step=0, reference_upper_s=.15)
        self.assertEqual(a.compare_ledger([row], [row], ('trial_id', 'step')), [])


if __name__ == '__main__':
    unittest.main()
