"""Seed-level statistical and audit-output checks for simulation-only batches."""
import csv
from dataclasses import dataclass
import importlib
from importlib import metadata
import hashlib
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@dataclass(frozen=True)
class ExampleConfig:
    arrival_coverage: float = 0.85
    stable_duration_s: float = 0.25
    map_path: Path | None = None
    physics_speed: float = 2.0


def trial(seed=0, method="C", **changes):
    metrics = dict(simulation=True, scenario="nominal", seed=seed, method=method,
                   path_complete=True, early_updates=0, transport_steps=4,
                   confirmed_steps=4, confirmation_delay_s=0.4,
                   total_time_s=4.0, retries=0, recoveries=0, status="complete")
    metrics.update(changes)
    return metrics


class BatchTests(unittest.TestCase):
    def setUp(self):
        try:
            self.batch = importlib.import_module("dmf.chapter2_sim.batch")
        except ModuleNotFoundError:
            self.batch = None
        self.assertIsNotNone(self.batch, "simulation batch statistics module is missing")

    def test_summary_uses_all_transport_steps_and_seed_cluster_intervals(self):
        rows = [trial(0, early_updates=1, transport_steps=1, confirmed_steps=0,
                      confirmation_delay_s=None, path_complete=False),
                trial(1, early_updates=0, transport_steps=9, confirmed_steps=9)]
        summary = self.batch.summarize_trials(rows, bootstrap_repeats=100)[0]
        self.assertAlmostEqual(summary["early_update_rate"], 0.1)
        self.assertEqual(summary["early_update_rate_ci_method"], "seed_cluster_bootstrap_ratio")
        self.assertEqual(summary["path_complete_rate_ci_method"], "wilson_95")
        self.assertEqual(summary["path_complete_rate"], 0.5)
        self.assertAlmostEqual(summary["path_complete_rate_ci_low"], 0.0945312057)
        self.assertAlmostEqual(summary["confirmation_delay_s_mean"], 0.4)
        self.assertEqual(summary["confirmation_delay_s_n"], 1)
        self.assertEqual(summary["confirmation_delay_s_missing_trials"], 1)
        self.assertEqual(summary["confirmation_delay_s_unconfirmed_steps"], 1)
        self.assertEqual(summary["total_time_s_mean"], 4.0)
        self.assertTrue(summary["simulation"])

    def test_empty_delay_and_zero_step_rate_stay_missing(self):
        summary = self.batch.summarize_trials([
            trial(transport_steps=0, confirmed_steps=0, confirmation_delay_s=None)
        ], bootstrap_repeats=30)[0]
        self.assertIsNone(summary["confirmation_delay_s_mean"])
        self.assertIsNone(summary["confirmation_delay_s_ci_low"])
        self.assertIsNone(summary["early_update_rate"])
        self.assertEqual(summary["confirmation_delay_s_missing_trials"], 1)

    def test_paired_differences_match_seeds_and_preserve_missing_pairs(self):
        rows = [trial(1, "B", total_time_s=12), trial(0, "A", total_time_s=4),
                trial(1, "A", total_time_s=10), trial(0, "B", total_time_s=6),
                trial(0, "C", total_time_s=7, confirmation_delay_s=None),
                trial(1, "C", total_time_s=13)]
        pairs = self.batch.paired_differences(rows, bootstrap_repeats=50)
        selected = next(r for r in pairs if r["comparison"] == "B-A" and
                        r["metric"] == "total_time_s")
        self.assertEqual(selected["mean_difference"], 2)
        self.assertEqual(selected["n_pairs"], 2)
        self.assertEqual(selected["ci_low"], 2)
        missing = next(r for r in pairs if r["comparison"] == "C-A" and
                       r["metric"] == "confirmation_delay_s")
        self.assertEqual(missing["n_pairs"], 1)
        self.assertEqual(missing["missing_pairs"], 1)

    def test_bootstrap_is_deterministic_and_rejects_duplicate_trials(self):
        rows = [trial(0, total_time_s=2), trial(1, total_time_s=9)]
        self.assertEqual(self.batch.summarize_trials(rows, bootstrap_repeats=60),
                         self.batch.summarize_trials(list(reversed(rows)), bootstrap_repeats=60))
        with self.assertRaises(ValueError):
            self.batch.summarize_trials(rows + rows, bootstrap_repeats=60)

    def test_summary_retains_observed_missing_and_censored_step_counts(self):
        rows = [trial(0, confirmed_steps=2, delay_observed_steps=2,
                      delay_missing_steps=2, delay_censored_steps=1,
                      delay_no_arrival_steps=1, delay_unattempted_steps=1)]
        state = random.getstate()
        result = self.batch.summarize_trials(rows, bootstrap_repeats=30)[0]
        self.assertEqual(random.getstate(), state)
        self.assertEqual(result.get("confirmation_delay_s_observed_steps"), 2)
        self.assertEqual(result.get("confirmation_delay_s_missing_steps"), 2)
        self.assertEqual(result.get("confirmation_delay_s_censored_steps"), 1)
        self.assertEqual(result.get("confirmation_delay_s_no_arrival_steps"), 1)
        self.assertEqual(result.get("confirmation_delay_s_unattempted_steps"), 1)

    def test_issued_update_rate_keeps_a_separate_denominator(self):
        result = self.batch.summarize_trials([
            trial(0, early_updates=1, confirmed_steps=2, transport_steps=4)
        ], bootstrap_repeats=30)[0]
        self.assertEqual(result["early_update_rate"], 0.25)
        self.assertEqual(result.get("early_update_rate_per_issued_update"), 0.5)
        self.assertEqual(result.get("early_update_rate_per_issued_update_ci_low"), 0.5)
        self.assertEqual(result.get("issued_updates"), 2)

    def test_real_config_snapshot_contains_all_420_polygons(self):
        from dmf.chapter2_sim.config import SimConfig
        def runner(config, scenario, seed, method):
            return SimpleNamespace(metrics=trial(seed, method), frames=[], truth=[], events=[])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "batch"
            self.batch.run_batch(SimConfig(), ["normal"], [0], output,
                                 runner=runner, bootstrap_repeats=30)
            path = output / "electrode_map_snapshot.json"
            self.assertTrue(path.exists(), "batch must snapshot every actual electrode polygon")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["simulation"])
            self.assertEqual(len(data["polygons"]), 420)
            self.assertIn("420", data["polygons"])

    def test_invalid_bootstrap_configuration_runs_no_trials_and_creates_no_output(self):
        calls = []
        def runner(config, scenario, seed, method):
            calls.append(method)
            return SimpleNamespace(metrics=trial(seed, method), frames=[], truth=[], events=[])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "batch"
            with self.assertRaises(ValueError):
                self.batch.run_batch(ExampleConfig(), ["nominal"], [0], output,
                                     runner=runner, bootstrap_repeats=0)
            self.assertEqual(calls, [])
            self.assertFalse(output.exists())

    def test_batch_writes_union_csv_snapshots_and_source_manifest(self):
        calls = []

        def runner(config, scenario, seed, method):
            calls.append((config, scenario, seed, method))
            return SimpleNamespace(metrics=trial(seed, method),
                                   frames=[{"time_s": seed, "extra_" + method: method}],
                                   truth=[{"x": 1.0}], events=[{"kind": "Update"}])

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "batch"
            config = ExampleConfig(map_path=Path("map.json"))
            self.batch.run_batch(config, ["nominal"], [1, 2], output,
                                 runner=runner, bootstrap_repeats=30)
            self.assertEqual(len(calls), 6)
            self.assertEqual({(s, m) for _, _, s, m in calls},
                             {(s, m) for s in (1, 2) for m in "ABC"})
            expected = {"config_snapshot.json", "trials.csv", "frames.csv", "truth.csv",
                        "events.csv", "summary.csv", "summary.json",
                        "paired_differences.csv", "manifest.json"}
            self.assertTrue(expected.issubset({p.name for p in output.iterdir()}))
            snapshot = json.loads((output / "config_snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["config"]["map_path"], "map.json")
            self.assertTrue(snapshot["simulation"])
            with (output / "frames.csv").open(newline="", encoding="utf-8") as handle:
                records = list(csv.DictReader(handle))
            self.assertTrue({"extra_A", "extra_B", "extra_C"}.issubset(records[0]))
            self.assertEqual(records[0]["simulation"], "True")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["simulation"])
            self.assertIn("dmf/chapter2_sim/batch.py", manifest["source_sha256"])
            self.assertEqual(len(manifest["source_sha256"]["dmf/chapter2_sim/batch.py"]), 64)
            self.assertIn("git_head", manifest)
            self.assertIn("environment", manifest)
            before = len(calls)
            with self.assertRaises(FileExistsError):
                self.batch.run_batch(config, ["nominal"], [1, 2], output, runner=runner)
            self.assertEqual(len(calls), before)

    def test_manifest_records_installed_package_versions_and_shared_geometry_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = self.batch._manifest(ExampleConfig(), ["normal"], [0],
                                             Path(folder), 30, "comparison")
        versions = manifest["environment"].get("package_versions", {})
        self.assertEqual(versions.get("numpy"), metadata.version("numpy"))
        self.assertEqual(versions.get("matplotlib"), metadata.version("matplotlib"))
        self.assertEqual(versions.get("PyYAML"), metadata.version("PyYAML"))
        opencv_names = ("opencv-python", "opencv-python-headless", "opencv-contrib-python",
                        "opencv-contrib-python-headless")
        self.assertTrue(any(versions.get(name) for name in opencv_names))
        root = Path(self.batch.__file__).resolve().parents[2]
        for name in ("calibration.py", "config.py", "electrode_map.py"):
            relative = "dmf/vision/" + name
            self.assertEqual(manifest["source_sha256"].get(relative),
                             hashlib.sha256((root / relative).read_bytes()).hexdigest())

    def test_manifest_preserves_missing_package_versions_without_failure(self):
        with patch("importlib.metadata.version", side_effect=metadata.PackageNotFoundError), \
                tempfile.TemporaryDirectory() as folder:
            manifest = self.batch._manifest(ExampleConfig(), ["normal"], [0],
                                             Path(folder), 30, "comparison")
        versions = manifest["environment"].get("package_versions", {})
        self.assertIn("numpy", versions)
        self.assertTrue(all(value is None for value in versions.values()))

    def test_sensitivity_changes_only_observation_thresholds_and_labels_output(self):
        calls = []

        def runner(config, scenario, seed, method):
            calls.append((config, seed, method))
            return SimpleNamespace(metrics=trial(seed, method), frames=[], truth=[], events=[])

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "sensitivity"
            config = ExampleConfig()
            summaries = self.batch.run_sensitivity(config, "nominal", [0, 1],
                                                   [0.8, 0.9], [0.2, 0.3], output,
                                                   runner=runner, bootstrap_repeats=30)
            self.assertEqual(len(calls), 8)
            self.assertEqual(len(summaries), 4)
            self.assertTrue(all(c.physics_speed == config.physics_speed and m == "C"
                                for c, _, m in calls))
            self.assertEqual(config.arrival_coverage, 0.85)
            with (output / "sensitivity_trials.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 8)
            self.assertEqual({r["arrival_coverage"] for r in rows}, {"0.8", "0.9"})
            self.assertEqual({r["stable_duration_s"] for r in rows}, {"0.2", "0.3"})
            self.assertTrue((output / "sensitivity_summary.csv").exists())


if __name__ == "__main__":
    unittest.main()
