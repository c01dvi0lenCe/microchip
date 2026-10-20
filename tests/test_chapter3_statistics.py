import json
from pathlib import Path
import tempfile
import unittest

from dmf import MultiDropletAssignment
from scripts.run_chapter3_statistics import (
    ROOT, check_geometry, congestion_task, fault_order, fault_snapshot,
    load_config, run, run_fault_trial, run_triplet, scale_task, summarize,
)


class Chapter3StatisticsTests(unittest.TestCase):
    def test_scale_tasks_use_matched_obstacles_and_nested_nonadjacent_targets(self):
        small, large = scale_task(260600, 2), scale_task(260600, 30)
        self.assertEqual(small, scale_task(260600, 2))
        self.assertEqual(small["obstacles"], large["obstacles"])
        self.assertEqual(small["targets"], large["targets"][:2])
        self.assertEqual(len(large["sources"]), 8)
        for i, a in enumerate(large["targets"]):
            self.assertNotIn(a, large["obstacles"])
            for b in large["targets"][i + 1:]:
                self.assertGreater(max(abs(a[0] - b[0]), abs(a[1] - b[1])), 1)

    def test_congestion_is_a_matched_channel_width_intervention(self):
        tasks = [congestion_task(260600, 8, w) for w in (20, 7, 3)]
        self.assertEqual(tasks[0]["sources"], tasks[2]["sources"])
        self.assertEqual(tasks[0]["targets"], tasks[2]["targets"])
        others = [{c for c in t["obstacles"] if c[0] != 10} for t in tasks]
        self.assertEqual(others[0], others[2])
        self.assertEqual([sum(c[0] == 10 for c in t["obstacles"]) for t in tasks], [0, 13, 17])

    def test_triplet_shares_pairs_and_excludes_unsafe_completion_time(self):
        rows, trace, _ = run_triplet(scale_task(260600, 8))
        self.assertFalse(rows[0]["success"])
        self.assertIsNone(rows[0]["makespan_steps"])
        self.assertGreater(rows[0]["nominal_timeline_steps"], 0)
        for method in ("static_astar", "safe_serial", "coordinated"):
            pairs = sorted((a["source"], a["target"]) for a in trace[method])
            self.assertEqual(pairs, sorted(trace["reference_pairs"]))
        self.assertTrue(rows[1]["success"])
        self.assertTrue(rows[2]["success"])

    def test_geometric_audit_rejects_teleport_disappearance_and_obstacle(self):
        task = dict(seed=1, sources=[(0, 0)], targets=[(0, 2)], obstacles=[])
        item = MultiDropletAssignment(1, (0, 0), (0, 2), [(0, 0), (0, 2)], [(0, 0), (0, 2)])
        self.assertFalse(check_geometry([item], task))
        item.path = [(0, 0), (0, 1), (0, 2)]
        item.scheduled_path = [None] + item.path
        self.assertTrue(check_geometry([item], task))
        item.scheduled_path = [(0, 0), None, (0, 1), (0, 2)]
        self.assertFalse(check_geometry([item], task))
        item.scheduled_path = item.path
        task["obstacles"] = [(0, 1)]
        self.assertFalse(check_geometry([item], task))

    def test_fault_snapshots_and_nested_positions_are_reproducible(self):
        task = congestion_task(260600, 8, 3)
        _, _, assignments = run_triplet(task)
        step, positions, completed = fault_snapshot(assignments)
        self.assertTrue(all(c is not None for c in positions.values()))
        for placement in ("random", "path_critical"):
            ordered, remaining = fault_order(task, assignments, step, positions, placement)
            self.assertEqual((ordered, remaining), fault_order(task, assignments, step, positions, placement))
            self.assertTrue(set(ordered[:10]).isdisjoint(set(positions.values()) | set(task["targets"]) | set(task["obstacles"])))
            if placement == "path_critical":
                self.assertTrue(set(ordered[:min(10, len(remaining))]) <= remaining)
        before = json.dumps([a.scheduled_path for a in assignments])
        row, _ = run_fault_trial(task, assignments, step, positions, completed, [])
        self.assertTrue(row["success"])
        self.assertEqual(before, json.dumps([a.scheduled_path for a in assignments]))

    def test_fault_replan_keeps_completed_drop_and_reports_unreachable(self):
        held = MultiDropletAssignment(1, (5, 5), (5, 5), [(5, 5)], [(5, 5)] * 4)
        moving = MultiDropletAssignment(2, (0, 2), (0, 0), [(0, 2), (0, 1), (0, 0)], [(0, 2), (0, 1), (0, 0)])
        task = dict(seed=2, sources=[(5, 5), (0, 2)], targets=[(5, 5), (0, 0)], obstacles=[(1, 0)])
        positions = {1: (5, 5), 2: (0, 2)}
        row, trace = run_fault_trial(task, [held, moving], 0, positions, {1}, [])
        self.assertTrue(row["success"])
        self.assertTrue(row["completed_droplets_held"])
        self.assertTrue(all(c == (5, 5) for c in trace["assignments"][0]["scheduled_path"]))
        row, _ = run_fault_trial(task, [held, moving], 0, positions, {1}, [(0, 1)])
        self.assertFalse(row["success"])
        self.assertEqual(row["status"], "unreachable")
        self.assertNotIn("detour_ratio", row)

    def test_summary_preserves_denominator_and_does_not_zero_fill_failures(self):
        rows = [dict(group="scale", droplet_count=2, method="coordinated", success=True,
                     status="safe_completed", makespan_steps=10, planning_time_ms=2),
                dict(group="scale", droplet_count=2, method="coordinated", success=False,
                     status="unreachable", planning_time_ms=4)]
        summary = summarize(rows)[0]
        self.assertEqual(summary["n"], 2)
        self.assertEqual(summary["success_rate"], 0.5)
        self.assertEqual(summary["makespan_steps_n"], 1)
        self.assertEqual(summary["makespan_steps_mean"], 10)
        self.assertIsNone(summary["makespan_steps_std"])
        self.assertEqual(summary["planning_time_ms_mean"], 3)
        self.assertAlmostEqual(summary["planning_time_ms_std"], 2 ** 0.5)
        self.assertLess(summary["success_ci_low"], 0.5)
        self.assertGreater(summary["success_ci_high"], 0.5)

    def test_known_fault_case_never_returns_a_different_droplets_start(self):
        task = congestion_task(260607, 8, 3)
        _, _, original = run_triplet(task)
        step, positions, completed = fault_snapshot(original)
        ordered, _ = fault_order(task, original, step, positions, "path_critical")
        row, trace = run_fault_trial(task, original, step, positions, completed, ordered[:8])
        self.assertNotEqual(row["status"], "invalid_replay")
        if trace["returned_status"] == "success":
            self.assertTrue(row["success"])
            self.assertEqual(trace["identity_changes"], [])
            for a in trace["assignments"]:
                self.assertEqual(a["scheduled_path"][0], positions[a["droplet_id"]])
        else:
            self.assertEqual(trace["returned_status"], "protective_pause")

    def test_batch_end_to_end_saves_four_figures_and_reproducible_records(self):
        config = load_config(ROOT / "configs/chapter3_statistics.yaml")
        config.update(repeats=1, droplet_counts=[2], baseline_plot_droplets=2,
                      congestion_gate_widths=[3], fault_counts=[0, 1])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "batch"
            records, _ = run(config, output)
            self.assertEqual(len(records), 10)
            self.assertEqual(len(list((output / "图片").glob("*.png"))), 4)
            self.assertTrue((output / "records.csv").exists())
            self.assertTrue((output / "traces.jsonl").exists())
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["simulation_only"])
            self.assertEqual(manifest["records"], 10)
            self.assertEqual(manifest["config"], config)
            self.assertTrue(manifest["source_sha256"])
            with self.assertRaises(FileExistsError):
                run(config, output)


if __name__ == "__main__":
    unittest.main()
