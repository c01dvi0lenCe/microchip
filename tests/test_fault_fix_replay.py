import copy
import json
from pathlib import Path
import tempfile
import unittest

from dmf.planning import scheduler
from scripts.generate_chapter3_advantage_case import assignment_data
from scripts.run_chapter3_statistics import (
    ROOT, congestion_task, fault_order, fault_snapshot, load_config, run_fault_trial, run_triplet,
)
from scripts.replay_chapter3_fault_fix import digest, load_v1_replanner, replay, restore_trial, time_tail_rows


class FaultFixReplayTests(unittest.TestCase):
    def fixture(self, root):
        baseline, archive = root / "baseline", root / "archive"
        baseline.mkdir()
        archive.mkdir()
        hashes = {}
        for relative in ("dmf/planning/scheduler.py", "dmf/planning/assignment.py", "dmf/planning/geometry.py",
                         "dmf/planning/astar.py", "dmf/layout.py", "dmf/models.py"):
            hashes[relative] = digest(ROOT / relative)
        for name in ("scheduler.py", "assignment.py"):
            (archive / name).write_bytes((ROOT / "dmf/planning" / name).read_bytes())
        manifest = {"source_sha256": hashes}
        (baseline / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        config = load_config(ROOT / "configs/chapter3_statistics.yaml")
        config.update(repeats=1, fault_counts=[0, 1], fault_droplets=2)
        (baseline / "config.json").write_text(json.dumps(config), encoding="utf-8")
        task = congestion_task(260600, 2, 3)
        _, _, original = run_triplet(task)
        step, positions, completed = fault_snapshot(original)
        rows, traces = [], []
        for placement in config["fault_placements"]:
            ordered, remaining = fault_order(task, original, step, positions, placement)
            for count in config["fault_counts"]:
                row, trace = run_fault_trial(task, original, step, positions, completed, ordered[:count])
                row.update(placement=placement, faults_on_remaining_path=sum(c in remaining for c in ordered[:count]))
                trace.update(group="fault", placement=placement, fault_count=count, task=task, fault_step=step,
                             original=[assignment_data(a) for a in original])
                rows.append(row)
                traces.append(trace)
        for filename, values in (("records.jsonl", rows), ("traces.jsonl", traces)):
            (baseline / filename).write_text("".join(json.dumps(v) + "\n" for v in values), encoding="utf-8")
        return baseline, archive, manifest, traces

    def test_snapshot_restore_rejects_changed_current_position(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, _, traces = self.fixture(Path(folder))
            changed = copy.deepcopy(traces[0])
            identity = next(iter(changed["current_positions"]))
            changed["current_positions"][identity] = (19, 19)
            with self.assertRaises(ValueError):
                restore_trial(changed)

    def test_old_loader_does_not_replace_live_modules_and_rejects_wrong_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            _, archive, manifest, _ = self.fixture(Path(folder))
            function = load_v1_replanner(archive, manifest)
            self.assertEqual(function.__module__, "dmf._chapter3_v1_replay.assignment")
            from dmf.planning import scheduler as still_live
            self.assertIs(still_live, scheduler)
            manifest["source_sha256"]["dmf/planning/scheduler.py"] = "wrong"
            with self.assertRaises(ValueError):
                load_v1_replanner(archive, manifest)

    def test_paired_replay_preserves_baseline_and_writes_both_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline, archive, _, _ = self.fixture(root)
            before = {p.name: digest(p) for p in baseline.iterdir()}
            report = replay(baseline, archive, root / "replay")
            self.assertEqual(report["trials"], 4)
            self.assertTrue(report["v1_outcomes_match_original"])
            self.assertNotIn("invalid_replay", report["v2_status_counts"])
            self.assertEqual(before, {p.name: digest(p) for p in baseline.iterdir()})
            self.assertTrue((root / "replay/图片/D_identity_fix_before_after.png").exists())
            self.assertTrue((root / "replay/v1_original_records.csv").exists())
            self.assertTrue((root / "replay/v2_records.csv").exists())
            with self.assertRaises(FileExistsError):
                replay(baseline, archive, root / "replay")

    def test_tail_statistics_include_failed_slow_tasks(self):
        records = [dict(group="scale", method="coordinated", droplet_count=30, seed=i,
                        planning_time_ms=v, success=i < 3, status="safe_completed" if i < 3 else "failed")
                   for i, v in enumerate((1, 2, 3, 100))]
        tails, slow = time_tail_rows(records)
        self.assertEqual(tails[0]["n"], 4)
        self.assertEqual(tails[0]["success_n"], 3)
        self.assertEqual(tails[0]["median_ms"], 2.5)
        self.assertEqual(tails[0]["max_ms"], 100)
        self.assertAlmostEqual(tails[0]["p95_ms"], 85.45)
        self.assertEqual(slow[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
