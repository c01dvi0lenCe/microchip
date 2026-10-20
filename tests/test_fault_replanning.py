import unittest
import copy
from unittest.mock import patch

from dmf.layout import LAYOUT_CELLS
from dmf.models import MultiDropletAssignment
from dmf.planning import AStarPlanner, build_multi_droplet_assignments, replan_multi_assignments_after_fault, schedule_multi_paths
from dmf.planning.scheduler import _schedule_assignments_in_fill_batches


class FaultReplanningTests(unittest.TestCase):
    def setUp(self):
        self.planner = AStarPlanner(valid_cells=LAYOUT_CELLS)

    def test_case_1_independent_droplets_finish_without_conflict(self):
        assignments = build_multi_droplet_assignments(
            [(2, 2), (10, 10)], [(2, 4), (10, 12)], self.planner
        )
        self.assertEqual(len(assignments), 2)
        self.assertTrue(all(a.path[0] == a.source and a.path[-1] == a.target for a in assignments))

    def test_case_2_vertex_conflict_is_resolved_with_wait_or_release_delay(self):
        paths = [[(0, 2), (0, 3), (0, 4)], [(0, 0), (0, 1), (0, 2)]]
        schedules = schedule_multi_paths(paths)
        self.assertEqual(len(schedules), 2)
        self.assertTrue(any(any(a is not None and a == b for a, b in zip(schedule, schedule[1:])) for schedule in schedules))
        for step in range(max(map(len, schedules))):
            cells = [schedule[step] if step < len(schedule) else schedule[-1] for schedule in schedules]
            self.assertNotEqual(cells[0], cells[1])

    def test_case_3_edge_swap_is_not_scheduled(self):
        schedules = schedule_multi_paths([[(4, 4), (4, 5)], [(4, 5), (4, 4)]])
        self.assertEqual(schedules, [])

    def test_case_4_chebyshev_pull_risk_is_preserved(self):
        paths = [
            [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)],
            [(2, 2), (1, 2), (1, 3), (2, 3)],
        ]
        schedules = schedule_multi_paths(paths)
        self.assertEqual(len(schedules), 2)
        for step in range(1, max(map(len, schedules))):
            positions = [schedule[step] if step < len(schedule) else schedule[-1] for schedule in schedules]
            previous = [schedule[step - 1] if step - 1 < len(schedule) else schedule[-1] for schedule in schedules]
            both_at_goals = positions[0] == paths[0][-1] and positions[1] == paths[1][-1]
            if not both_at_goals:
                self.assertGreater(max(abs(positions[0][0] - positions[1][0]), abs(positions[0][1] - positions[1][1])), 1)
            self.assertFalse(previous[0] == positions[1] and previous[1] == positions[0])

    def test_case_5_preplanned_fault_is_included_in_astar_obstacles(self):
        fault = (5, 3)
        assignments = build_multi_droplet_assignments(
            [(5, 1)], [(5, 6)], self.planner, faulty_electrodes={fault}
        )
        self.assertEqual(len(assignments), 1)
        self.assertNotIn(fault, assignments[0].path)

    def test_case_6_runtime_fault_reroutes_all_pending_and_holds_completed(self):
        completed = MultiDropletAssignment(1, (1, 1), (5, 5), [(1, 1), (5, 5)], [(1, 1), (5, 5)])
        pending = MultiDropletAssignment(2, (5, 1), (5, 8), [(5, 1), (5, 8)], [(5, 1), (5, 8)])
        result = replan_multi_assignments_after_fault(
            [completed, pending],
            {1: (5, 5), 2: (5, 2)},
            {1},
            set(),
            {(5, 4)},
            self.planner,
        )
        self.assertEqual(result.status, "success", result.reason)
        self.assertEqual(result.assignments[0].target, (5, 5))
        self.assertEqual(set(result.assignments[0].scheduled_path), {(5, 5)})
        self.assertEqual(result.assignments[1].source, (5, 2))
        self.assertNotIn((5, 4), result.assignments[1].path)
        self.assertGreaterEqual(len(result.assignments[1].scheduled_path), len(result.assignments[1].path))

    def test_case_7_unreachable_fault_route_returns_status_instead_of_raising(self):
        assignment = MultiDropletAssignment(1, (0, 2), (0, 0), [(0, 2), (0, 1), (0, 0)], [(0, 2), (0, 1), (0, 0)])
        result = replan_multi_assignments_after_fault(
            [assignment], {1: (0, 2)}, set(), {(1, 0)}, {(0, 1)}, self.planner
        )
        self.assertEqual(result.status, "unreachable")
        self.assertIn("不可达", result.reason)

    def test_case_8_irrelevant_fault_has_deterministic_success(self):
        assignment = MultiDropletAssignment(1, (10, 1), (10, 6), [(10, 1), (10, 6)], [(10, 1), (10, 6)])
        result = replan_multi_assignments_after_fault(
            [assignment], {1: (10, 1)}, set(), set(), {(0, 0)}, self.planner
        )
        self.assertEqual(result.status, "success", result.reason)
        self.assertNotIn((0, 0), result.assignments[0].path)
        self.assertEqual(result.assignments[0].path[0], (10, 1))

    def test_initial_planning_reports_separate_wall_clock_stages(self):
        measurements = {}
        assignments = build_multi_droplet_assignments(
            [(3, 3)], [(3, 6)], self.planner, planning_metrics=measurements
        )
        self.assertEqual(len(assignments), 1)
        self.assertEqual(
            set(measurements),
            {"assignment_time_ms", "routing_time_ms", "scheduling_time_ms", "total_planning_time_ms"},
        )
        self.assertTrue(all(value >= 0 for value in measurements.values()))

    def test_runtime_fill_batch_preserves_fixed_source_target_pairs(self):
        pairs = [((2, 2), (10, 12)), ((10, 10), (2, 4))]
        raw = [(s, t, self.planner.plan(s, t)) for s, t in pairs]
        routed, schedules, _ = _schedule_assignments_in_fill_batches(
            raw, self.planner, set(), {}, 4, 80, hold_start_during_delay=True,
        )
        self.assertEqual({(s, t) for s, t, _ in routed}, set(pairs))
        self.assertEqual(len(schedules), 2)
        for (source, _target, path), schedule in zip(routed, schedules):
            self.assertEqual(path[0], source)
            self.assertEqual(schedule[0], source)
            self.assertNotIn(None, schedule)

    def test_identity_guard_rejects_bad_scheduler_output_without_mutation(self):
        original = [MultiDropletAssignment(1, (2, 2), (2, 6),
                    [(2, 2), (2, 3), (2, 4), (2, 5), (2, 6)],
                    [(2, 2), (2, 3), (2, 4), (2, 5), (2, 6)])]
        before = copy.deepcopy(original)
        wrong_path = [(3, 5), (3, 6), (2, 6)]
        with patch("dmf.planning.assignment.schedule_assignments_with_reroute", return_value=(
            [((3, 5), (2, 6), wrong_path)], [wrong_path], [1],
        )):
            result = replan_multi_assignments_after_fault(original, {1: (2, 3)}, set(), set(), set(), self.planner)
        self.assertEqual(result.status, "protective_pause")
        self.assertEqual(original, before)

    def test_identity_guard_rejects_hidden_existing_drop(self):
        original = [MultiDropletAssignment(1, (2, 2), (2, 6), [(2, 2), (2, 6)], [(2, 2), (2, 6)])]
        path = [(2, 3), (2, 4), (2, 5), (2, 6)]
        with patch("dmf.planning.assignment.schedule_assignments_with_reroute", return_value=(
            [((2, 3), (2, 6), path)], [[None] + path], [1],
        )):
            result = replan_multi_assignments_after_fault(original, {1: (2, 3)}, set(), set(), set(), self.planner)
        self.assertEqual(result.status, "protective_pause")


if __name__ == "__main__":
    unittest.main()
