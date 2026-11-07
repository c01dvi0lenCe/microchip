"""Pure acknowledged-state overlay checks; no serial, GUI, or hardware."""
import unittest

from controllers.open_loop_manual import OpenLoopManualOverlay
from controllers.open_loop_sequence import OpenLoopPlan, compile_routes
from controllers.timed_mixing import reminder_ids


class OpenLoopManualOverlayTests(unittest.TestCase):
    def make(self, routes=None, holds=(100,)):
        plan = compile_routes(routes or {'a': (1, 2, 3)}, hold_ids=holds)
        return OpenLoopManualOverlay(plan)

    def test_initial_targets_and_completed_groups_include_plan_holds(self):
        overlay = self.make({'a': (1, 2), 'b': (101, 102, 103)}, holds=(200, 402))
        self.assertEqual(overlay.current_task_ids(2), frozenset({2, 103}))
        self.assertEqual(overlay.targets_at(2), frozenset({2, 103, 200, 402}))
        self.assertEqual(overlay.hold_ids, frozenset({200, 402}))

    def test_constructor_requires_plan(self):
        for value in (None, {}, {'a': (1,)}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OpenLoopManualOverlay(value)

    def test_phase_is_strict_and_in_range_for_every_operation(self):
        overlay = self.make()
        calls = (overlay.targets_at, overlay.current_task_ids,
                 lambda phase: overlay.conflict_reasons({200: 1}, phase),
                 lambda phase: overlay.reconcile({1, 100}, phase),
                 lambda phase: overlay.validate_resume({1, 100}, phase))
        for phase in (-1, 3, True, 1.0, '1', None):
            for call in calls:
                with self.subTest(phase=phase, call=call), self.assertRaises(ValueError):
                    call(phase)

    def test_safe_manual_hold_survives_later_targets_and_off_removes_it(self):
        overlay = self.make()
        self.assertEqual(overlay.conflict_reasons({200: 1}, 0), ())
        overlay.reconcile({1, 100, 200}, 0)
        self.assertEqual(overlay.targets_at(1), frozenset({2, 100, 200}))
        self.assertEqual(overlay.targets_at(2), frozenset({3, 100, 200}))
        overlay.reconcile({2, 100}, 1)
        self.assertEqual(overlay.targets_at(2), frozenset({3, 100}))

    def test_reconcile_uses_actual_active_state_not_original_holds(self):
        overlay = self.make()
        overlay.reconcile({200}, 0)
        self.assertEqual(overlay.hold_ids, frozenset({200}))
        self.assertNotIn(1, overlay.hold_ids)
        self.assertNotIn(100, overlay.hold_ids)
        with self.assertRaisesRegex(ValueError, '当前任务'):
            overlay.validate_resume({200}, 0)
        self.assertEqual(overlay.hold_ids, frozenset({200}))

    def test_safe_peripheral_manual_hold_uses_existing_420_layout(self):
        overlay = self.make()
        self.assertEqual(overlay.conflict_reasons({420: 1}, 0), ())
        overlay.reconcile({1, 100, 420}, 0)
        self.assertIn(420, overlay.targets_at(2))

    def test_touching_current_or_future_route_rejected_for_on_and_off(self):
        overlay = self.make()
        for eid in (1, 2, 3):
            for state in (0, 1):
                with self.subTest(eid=eid, state=state):
                    reasons = overlay.conflict_reasons({eid: state}, 0)
                    self.assertTrue(reasons)
                    self.assertIn('路径', ' '.join(reasons))

    def test_initial_and_dynamic_holds_can_be_switched_off(self):
        overlay = self.make(holds=(350,))
        self.assertEqual(overlay.conflict_reasons({350: 0}, 0), ())
        overlay.reconcile({1, 350, 200}, 0)
        self.assertEqual(overlay.conflict_reasons({200: 0}, 0), ())
        overlay.reconcile({1, 350}, 0)
        self.assertEqual(overlay.hold_ids, frozenset({350}))

    def test_all_red_reminders_rejected_for_on_and_off(self):
        overlay = self.make()
        for eid in reminder_ids():
            for state in (0, 1):
                with self.subTest(eid=eid, state=state):
                    self.assertIn('故障', ' '.join(overlay.conflict_reasons({eid: state}, 0)))

    def test_future_and_diagonal_pull_risk_cannot_be_accepted_as_safe(self):
        overlay = self.make()
        for eid in (4, 24):
            with self.subTest(eid=eid):
                self.assertIn('冲突', ' '.join(overlay.conflict_reasons({eid: 1}, 0)))

    def test_proposed_holds_checked_against_each_other(self):
        overlay = self.make()
        self.assertTrue(overlay.conflict_reasons({200: 1, 199: 1}, 0))

    def test_removing_a_hold_before_adding_replacement_checks_proposed_state(self):
        overlay = self.make()
        self.assertEqual(overlay.conflict_reasons({100: 0, 101: 1}, 0), ())

    def test_entire_task_list_protected_and_completed_groups_retained(self):
        overlay = self.make({'a': (1, 2), 'b': (101, 102, 103, 104)}, holds=())
        self.assertTrue(overlay.conflict_reasons({1: 0}, 3))
        self.assertTrue(overlay.conflict_reasons({2: 0}, 3))
        self.assertTrue(overlay.conflict_reasons({3: 1}, 3))
        overlay.reconcile({2, 104, 3}, 3)
        with self.assertRaises(ValueError):
            overlay.validate_resume({2, 104, 3}, 3)

    def test_past_only_geometry_does_not_block_resume(self):
        overlay = self.make({'a': (1, 2, 3, 4)}, holds=())
        self.assertTrue(overlay.conflict_reasons({1: 1}, 3))
        # Manual task-list denial is separate from remaining-geometry safety.
        self.assertIsNone(overlay.validate_resume({4, 1}, 3))
        self.assertEqual(overlay.hold_ids, frozenset({1}))

    def test_validate_resume_requires_every_current_task_held(self):
        overlay = self.make({'a': (1, 2), 'b': (101, 102, 103)}, holds=())
        for active in ({103}, {2}, set()):
            with self.subTest(active=active):
                with self.assertRaises(ValueError):
                    overlay.validate_resume(active, 2)
        self.assertIsNone(overlay.validate_resume({2, 103, 200}, 2))

    def test_validate_resume_rejects_future_hold_conflict_and_preserves_old_holds(self):
        overlay = self.make()
        with self.assertRaises(ValueError):
            overlay.validate_resume({1, 4}, 0)
        self.assertEqual(overlay.hold_ids, frozenset({100}))
        self.assertIsNone(overlay.validate_resume({1, 200}, 0))
        self.assertEqual(overlay.hold_ids, frozenset({200}))

    def test_validate_resume_rejects_red_hold_even_when_far_from_route(self):
        overlay = self.make()
        with self.assertRaises(ValueError):
            overlay.validate_resume({1, 393}, 0)
        self.assertEqual(overlay.hold_ids, frozenset({100}))

    def test_remaining_group_conflict_is_checked_by_existing_compiler(self):
        # Raw OpenLoopPlan can be constructed without compile_routes preflight.
        overlay = OpenLoopManualOverlay(OpenLoopPlan({'a': (1,), 'b': (4, 3, 2)}))
        with self.assertRaises(ValueError):
            overlay.validate_resume({1, 4}, 0)

    def test_invalid_changes_raise_before_any_state_mutation(self):
        overlay = self.make()
        for changes in (None, [(200, 1)], {0: 1}, {421: 1}, {True: 1},
                        {200.0: 1}, {'200': 1}, {200: True}, {200: False},
                        {200: 1.0}, {200: '1'}, {200: 2}, {200: -1}, {200: None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                overlay.conflict_reasons(changes, 0)
            self.assertEqual(overlay.hold_ids, frozenset({100}))

    def test_active_ids_validated_strictly_and_atomically(self):
        overlay = self.make()
        for active in (None, [1, 200, 421], [True], [1.0], ['1'], [0], [421]):
            for operation in (overlay.reconcile, overlay.validate_resume):
                with self.subTest(active=active, operation=operation), self.assertRaises(ValueError):
                    operation(active, 0)
                self.assertEqual(overlay.hold_ids, frozenset({100}))

    def test_queries_never_mutate_overlay_and_original_plan_is_immutable(self):
        overlay = self.make()
        plan = overlay.plan
        overlay.conflict_reasons({200: 1}, 0)
        self.assertEqual(overlay.hold_ids, frozenset({100}))
        overlay.reconcile({1, 200}, 0)
        self.assertEqual(dict(plan.routes), {'a': (1, 2, 3)})
        self.assertEqual(plan.hold_ids, frozenset({100}))
        with self.assertRaises((AttributeError, TypeError)):
            overlay.hold_ids = frozenset({300})


if __name__ == '__main__':
    unittest.main()
