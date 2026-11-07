"""Pure geometry and APPLIED-paced open-loop command tests; no hardware."""
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from controllers.open_loop_sequence import (
    FourCellTask, TimedPlanSequence, compile_four_cell_tasks, compile_routes,
)
from controllers.timed_mixing import reminder_ids


class CompilePlanTests(unittest.TestCase):
    def task(self, group='a', start=1, ring=(1, 2, 22, 21), target=1):
        return FourCellTask(group, start, ring, target)

    def test_ring_rotates_and_finishes_forward_after_complete_cycles(self):
        task = self.task(start=22, target=2)
        plan = compile_four_cell_tasks([task], 2, forbidden_ids=())
        self.assertEqual(plan.routes['a'], (22, 21, 1, 2, 22, 21, 1, 2, 22, 21, 1, 2))
        self.assertEqual(plan.length, 12)
        with self.assertRaises(FrozenInstanceError):
            task.start = 1

    def test_reverse_click_direction_is_preserved(self):
        plan = compile_four_cell_tasks([self.task(ring=(1, 21, 22, 2), target=2)], 1)
        self.assertEqual(plan.routes['a'], (1, 21, 22, 2, 1, 21, 22, 2))

    def test_completed_groups_hold_and_extra_holds_remain(self):
        plan = compile_routes({'a': [1, 2], 'b': [61, 62, 63]}, hold_ids=[100])
        self.assertEqual(plan.positions_at(2), {'a': 2, 'b': 63})
        self.assertEqual(plan.active_at(2), frozenset({2, 63, 100}))
        for index in (-1, 3, 1.0, True):
            with self.subTest(index=index), self.assertRaises((ValueError, IndexError)):
                plan.positions_at(index)

    def test_extra_holds_accept_existing_peripheral_layout_and_preserve_them(self):
        plan = compile_routes({'a': [190, 191]}, hold_ids=[402])
        self.assertEqual(plan.hold_ids, frozenset({402}))
        self.assertEqual(plan.active_at(0), frozenset({190, 402}))
        self.assertEqual(plan.active_at(1), frozenset({191, 402}))
        with self.assertRaises(ValueError):
            compile_routes({'a': [7]}, hold_ids=[401])
        for eid in (0, 421, True, 402.0, '402'):
            with self.subTest(eid=eid), self.assertRaises(ValueError):
                compile_routes({'a': [190]}, hold_ids=[eid])

    def test_plan_is_frozen_from_input_and_cannot_be_mutated(self):
        routes = {'a': [1, 2]}
        holds = [100]
        plan = compile_routes(routes, hold_ids=holds)
        routes['a'].append(3)
        holds.append(101)
        self.assertEqual(plan.routes['a'], (1, 2))
        self.assertEqual(plan.hold_ids, frozenset({100}))
        with self.assertRaises(TypeError):
            plan.routes['a'] = (3,)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            plan.length = 99

    def test_rejects_invalid_square_or_order_or_membership(self):
        cases = [self.task(ring=(1, 2, 21, 22)), self.task(ring=(1, 2, 3, 4)),
                 self.task(ring=(20, 21, 41, 40)), self.task(ring=(1, 2, 22, 1)),
                 self.task(ring=(1, 2, 22)), self.task(start=3), self.task(target=3),
                 self.task(ring=(381, 382, 402, 401))]
        for task in cases:
            with self.subTest(task=task), self.assertRaises(ValueError):
                compile_four_cell_tasks([task], 1)

    def test_rejects_empty_or_duplicate_groups_and_bad_cycles(self):
        for tasks in ([], [self.task(), self.task()], [self.task(group='')], [self.task(group=3)]):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                compile_four_cell_tasks(tasks, 1)
        for cycles in (0, -1, 10000, 1.2, True, '1'):
            with self.subTest(cycles=cycles), self.assertRaises(ValueError):
                compile_four_cell_tasks([self.task()], cycles)

    def test_core_ids_and_orthogonal_routes_only(self):
        for route in ([], [0], [401], [True], [1.0], ['1'], [1, 3], [20, 21], [1, 22]):
            with self.subTest(route=route), self.assertRaises(ValueError):
                compile_routes({'a': route}, forbidden_ids=())
        self.assertEqual(compile_routes({'a': [1, 1, 2]}).length, 3)
        with self.assertRaises(ValueError):
            compile_routes({})

    def test_default_forbidden_covers_exact_current_reminders(self):
        self.assertEqual(len(reminder_ids()), 16)
        for eid in reminder_ids():
            with self.subTest(eid=eid), self.assertRaises(ValueError):
                compile_routes({'a': [eid]})
        self.assertEqual(compile_routes({'a': [90]}, forbidden_ids=()).routes['a'], (90,))
        with self.assertRaises(ValueError):
            compile_routes({'a': [1]}, hold_ids=[90])

    def test_initial_same_adjacent_and_diagonal_targets_rejected(self):
        for b in (1, 2, 21, 22):
            with self.subTest(b=b), self.assertRaises(ValueError):
                compile_routes({'a': [1], 'b': [b]}, forbidden_ids=())

    def test_cross_step_pull_risk_even_when_each_snapshot_separated(self):
        # 2/4 -> 1/3: each snapshot gap2; previous a2 is adjacent to b target3.
        with self.assertRaisesRegex(ValueError, 'a|b'):
            compile_routes({'a': [2, 1], 'b': [4, 3]}, forbidden_ids=())

    def test_reverse_swap_is_rejected(self):
        with self.assertRaises(ValueError):
            compile_routes({'a': [1, 2], 'b': [2, 1]}, forbidden_ids=())

    def test_holds_checked_against_initial_and_all_later_and_each_other(self):
        for routes, holds in (({'a': [1]}, [1]), ({'a': [1]}, [22]),
                              ({'a': [1, 2]}, [3]), ({'a': [1]}, [99, 100])):
            with self.subTest(routes=routes, holds=holds), self.assertRaises(ValueError):
                compile_routes(routes, hold_ids=holds, forbidden_ids=())

    def test_completed_group_hold_blocks_other_later_route(self):
        with self.assertRaises(ValueError):
            compile_routes({'a': [1], 'b': [5, 4, 3, 2]}, forbidden_ids=())

    def test_max_cycles_are_practical_and_route_view_is_lazy(self):
        # Repeated global transitions require geometry checks only once each.
        import controllers.open_loop_sequence as module
        with patch.object(module, 'pull_risk_neighbors', wraps=module.pull_risk_neighbors) as risk:
            plan = compile_four_cell_tasks([self.task(), self.task('b', 65, (65, 66, 86, 85), 85)], 9999)
        self.assertEqual(plan.length, 40000)
        self.assertLess(risk.call_count, 100)
        seq = TimedPlanSequence(plan, .1)
        self.assertNotIsInstance(seq.route, (tuple, list))
        self.assertEqual(seq.route[-1], frozenset({1, 85}))


class TimedPlanSequenceTests(unittest.TestCase):
    def make(self, manual=False, route=(1, 2)):
        return TimedPlanSequence(compile_routes({'a': route}, hold_ids=[100]), .5, manual=manual)

    def test_one_pending_and_only_matching_applied_advances(self):
        seq = self.make()
        self.assertEqual(seq.next_request(0), frozenset({1, 100}))
        self.assertIsNone(seq.next_request(.1))
        self.assertEqual(seq.index, 0)
        for wrong in (None, 1, frozenset({2, 100})):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                seq.applied(wrong, .2)
        self.assertEqual(seq.index, 0)
        seq.applied(frozenset({1, 100}), .2)
        self.assertEqual(seq.active_id, frozenset({1, 100}))
        self.assertEqual(seq.index, 1)
        self.assertEqual(seq.deadline, .7)
        self.assertIsNone(seq.next_request(.69))
        self.assertEqual(seq.next_request(.7), frozenset({2, 100}))

    def test_completion_waits_for_final_minimum_dwell(self):
        seq = self.make(route=(1,))
        seq.next_request(0)
        seq.applied(frozenset({1, 100}), 1)
        self.assertFalse(seq.complete)
        self.assertTrue(seq.running)
        self.assertIsNone(seq.next_request(1.49))
        self.assertFalse(seq.complete)
        self.assertIsNone(seq.next_request(1.5))
        self.assertTrue(seq.complete)
        self.assertFalse(seq.running)

    def test_manual_and_pause_allow_source_then_explicit_step_after_dwell(self):
        seq = self.make(manual=True)
        seq.pause()
        self.assertEqual(seq.next_request(0), frozenset({1, 100}))
        seq.applied(seq.pending, 0)
        self.assertIsNone(seq.next_request(.4, manual_step=True))
        self.assertIsNone(seq.next_request(.5))
        self.assertEqual(seq.next_request(.5, manual_step=True), frozenset({2, 100}))
        seq.applied(seq.pending, .5)
        seq.next_request(1)
        self.assertTrue(seq.complete)

    def test_pause_reconciles_ack_resume_restarts_dwell_without_dropping_pending(self):
        seq = self.make()
        seq.next_request(0)
        pending = seq.pending
        seq.pause()
        seq.resume(.1)
        self.assertEqual(seq.pending, pending)
        seq.applied(pending, .2)
        seq.pause()
        self.assertIsNone(seq.next_request(2))
        seq.resume(2)
        self.assertEqual(seq.deadline, 2.5)
        self.assertIsNone(seq.next_request(2.49))
        self.assertEqual(seq.next_request(2.5), frozenset({2, 100}))

    def test_stop_prohibits_requests_but_reconciles_late_pending_ack(self):
        seq = self.make()
        seq.next_request(0)
        target = seq.pending
        seq.stop()
        seq.applied(target, 1)
        self.assertEqual(seq.active_id, target)
        self.assertEqual(seq.index, 1)
        seq.resume(2)
        self.assertIsNone(seq.next_request(100, manual_step=True))
        self.assertFalse(seq.running)
        self.assertFalse(seq.complete)

    def test_unsolicited_duplicate_ack_rejected(self):
        seq = self.make()
        with self.assertRaises(ValueError):
            seq.applied(None, 0)
        seq.next_request(0)
        target = seq.pending
        seq.applied(target, 0)
        with self.assertRaises(ValueError):
            seq.applied(target, .1)
        self.assertEqual(seq.index, 1)

    def test_invalid_dwell_and_invalid_or_backwards_time_rejected(self):
        plan = compile_routes({'a': [1]})
        for dwell in (0, .099, 60.01, float('nan'), float('inf'), True, '1'):
            with self.subTest(dwell=dwell), self.assertRaises(ValueError):
                TimedPlanSequence(plan, dwell)
        for method in ('next_request', 'resume'):
            for now in (-1, float('nan'), float('inf'), True, '1'):
                with self.subTest(method=method, now=now), self.assertRaises(ValueError):
                    getattr(self.make(), method)(now)
        seq = self.make()
        seq.next_request(10)
        for at in (-1, float('nan'), float('inf'), True, '10'):
            with self.subTest(at=at), self.assertRaises(ValueError):
                seq.applied(seq.pending, at)
        with self.assertRaises(ValueError):
            seq.applied(seq.pending, 9)
        self.assertEqual(seq.index, 0)
        seq.applied(seq.pending, 10)
        for method in ('next_request', 'resume'):
            with self.subTest(method=method), self.assertRaises(ValueError):
                getattr(seq, method)(9)

    def test_automatic_pause_blocks_steps_and_late_final_ack_can_complete(self):
        seq = self.make()
        seq.next_request(0)
        seq.applied(seq.pending, 0)
        seq.pause()
        self.assertIsNone(seq.next_request(.5))
        seq.next_request(.5, manual_step=True)
        seq.pause()
        seq.applied(seq.pending, 1)
        self.assertIsNone(seq.next_request(1.49))
        self.assertFalse(seq.complete)
        seq.next_request(1.5)
        self.assertTrue(seq.complete)

    def test_stop_before_source_cannot_be_resumed_or_manually_stepped(self):
        seq = self.make()
        seq.stop()
        seq.resume(0)
        self.assertIsNone(seq.next_request(1, manual_step=True))
        self.assertFalse(seq.complete)

    def test_ack_before_ui_resume_reconciles_and_preserves_resume_dwell(self):
        seq = self.make()
        seq.next_request(0)
        pending = seq.pending
        seq.pause()
        seq.resume(2)
        seq.applied(pending, 1)
        self.assertEqual(seq.index, 1)
        self.assertEqual(seq.active_id, pending)
        self.assertEqual(seq.deadline, 2.5)
        self.assertIsNone(seq.next_request(2.49))
        self.assertEqual(seq.next_request(2.5), frozenset({2, 100}))

    def test_ack_before_later_pending_poll_or_pause_still_reconciles(self):
        seq = self.make()
        seq.next_request(0)
        pending = seq.pending
        seq.next_request(2)
        seq.pause()
        seq.applied(pending, 1)
        self.assertEqual(seq.index, 1)
        self.assertEqual(seq.deadline, 1.5)
        with self.assertRaises(ValueError):
            seq.next_request(1.9)
        self.assertIsNone(seq.next_request(2))
        self.assertEqual(seq.next_request(2, manual_step=True), frozenset({2, 100}))


if __name__ == '__main__':
    unittest.main()
