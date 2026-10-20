import unittest

from dmf import MultiDropletAssignment
from scripts.generate_chapter3_advantage_case import (
    audit_schedule, evaluate_case, serial_reference, uncoordinated_reference,
)
from scripts.generate_chapter3_results import _base_planner


def assignment(identity, path, schedule=None):
    return MultiDropletAssignment(identity, path[0], path[-1], path, path if schedule is None else schedule)


class Chapter3AdvantageCaseTests(unittest.TestCase):
    def test_auditor_detects_transition_risk_even_when_current_positions_are_separated(self):
        first = assignment(1, [(0, 2), (0, 3)])
        second = assignment(2, [(0, 0), (0, 1)])
        events = audit_schedule([first, second])
        self.assertEqual([(e["step"], e["type"]) for e in events], [(1, "transition_spacing")])
        second.scheduled_path = [(0, 0), (0, 0), (0, 1)]
        self.assertEqual(audit_schedule([first, second]), [])

    def test_auditor_classifies_vertex_and_swap_without_double_counting(self):
        events = audit_schedule([
            assignment(1, [(0, 0), (0, 1)]),
            assignment(2, [(0, 2), (0, 1)]),
        ])
        self.assertEqual([(e["step"], e["type"]) for e in events], [(1, "vertex")])
        events = audit_schedule([
            assignment(1, [(0, 0), (0, 1)]),
            assignment(2, [(0, 1), (0, 0)]),
        ])
        self.assertEqual([e["type"] for e in events if e["step"] == 1], ["edge_swap"])

    def test_reference_preserves_per_reservoir_dispensing_and_rejects_hiding_initial_drops(self):
        planner = _base_planner()
        source = (-3, 6)
        items = [assignment(i + 1, planner.plan(source, target)) for i, target in enumerate(((4, 6), (4, 10)))]
        reference = uncoordinated_reference(items, planner, set())
        self.assertEqual(reference[0].scheduled_path[0], source)
        self.assertEqual(reference[1].scheduled_path[:3], [None, None, None])
        self.assertEqual(reference[1].scheduled_path[3], source)
        with self.assertRaises(ValueError):
            serial_reference([assignment(1, [(1, 1), (1, 2)])], planner, set())

    def test_shared_channel_case_demonstrates_safe_parallel_coordination(self):
        _, sources, targets, obstacles, proposed, baseline, serial, rows, _ = evaluate_case()
        self.assertEqual((len(sources), len(targets), len(obstacles)), (4, 8, 39))
        self.assertEqual(len(proposed), 8)
        self.assertGreater(rows[0]["cross_source_conflict_pair_steps"], 0)
        self.assertFalse(rows[0]["safety_valid"])
        self.assertEqual(audit_schedule(proposed), [])
        self.assertEqual(audit_schedule(serial), [])
        self.assertEqual(rows[1]["peak_simultaneous_moves"], 1)
        self.assertGreater(rows[2]["peak_simultaneous_moves"], 1)
        self.assertLess(rows[2]["makespan_steps"], rows[1]["makespan_steps"])
        expected = {(a.droplet_id, a.source, a.target) for a in proposed}
        self.assertEqual(expected, {(a.droplet_id, a.source, a.target) for a in baseline})
        self.assertEqual(expected, {(a.droplet_id, a.source, a.target) for a in serial})


if __name__ == "__main__":
    unittest.main()
