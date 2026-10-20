import ast
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from matplotlib import rc_context
from PIL import Image

from scripts.chapter3_plot_style import METHOD_COLORS, METHOD_LABELS, METHOD_ZORDERS, LINES, MARKERS, font_settings, panels
from scripts.plot_chapter3_final import PlotAudit, generate, metric_line, one, plot_a, plot_b, plot_d, plot_tails, read_summary, sha


def write_summary(folder, name, rows):
    with (folder / (name + ".csv")).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()} for r in rows)
    (folder / (name + ".json")).write_text(json.dumps(rows), encoding="utf-8")


def row(group, method="coordinated", droplet_count=8, gate_width=None, fault_count=None, placement=None, successes=20):
    result = dict(group=group, method=method, droplet_count=droplet_count, gate_width=gate_width,
                  fault_count=fault_count, placement=placement, n=20, eligible_n=20, successes=successes,
                  success_rate=successes / 20, success_ci_low=max(0, successes / 20 - 0.2),
                  success_ci_high=min(1, successes / 20 + 0.15), status_counts={"success": successes})
    for metric in ("conflict_pair_steps", "makespan_steps", "planning_time_ms", "wait_steps", "max_release_delay_steps",
                   "wait_fraction", "spatial_length", "static_core_overlap_pair_cells", "detour_vs_zero_fault",
                   "replanning_time_ms", "delta_makespan_vs_zero_fault"):
        result.update({metric + "_mean": 3.0, metric + "_std": 0.5, metric + "_n": 20})
    return result


class Chapter3FinalPlottingTests(unittest.TestCase):
    def test_csv_json_comparison_is_exact_and_missing_statistic_stays_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            item = row("scale")
            item.update(makespan_steps_mean=None, makespan_steps_std=None, makespan_steps_n=0)
            write_summary(folder, "summary", [item])
            loaded = read_summary(folder / "summary.csv", folder / "summary.json")
            self.assertIsNone(loaded[0]["makespan_steps_mean"])
            self.assertEqual(loaded[0]["makespan_steps_n"], 0)
            item["planning_time_ms_mean"] = 99
            (folder / "summary.json").write_text(json.dumps([item]), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_summary(folder / "summary.csv", folder / "summary.json")

    def test_missing_completion_result_breaks_line_without_zero_or_bridging(self):
        rows = [row("scale", droplet_count=n) for n in (2, 4, 8)]
        rows[1].update(makespan_steps_mean=None, makespan_steps_std=None, makespan_steps_n=0)
        with rc_context(font_settings()[0]):
            fig, axes, _ = panels(1, 1, 3)
            audit = PlotAudit()
            metric_line(axes[0][0], rows, "droplet_count", "makespan_steps", "B", 1,
                        "coordinated", "fixture", audit, METHOD_COLORS["coordinated"], "Coordinated")
            values = axes[0][0].lines[0].get_ydata()
            self.assertTrue(np.isnan(values[1]))
            self.assertEqual((values[0], values[2]), (3, 3))
            self.assertEqual(audit.rows[1]["metric_n"], 0)

    def test_renderer_never_imports_simulation_or_planning_modules(self):
        from scripts import plot_chapter3_final, chapter3_plot_style
        for module in (plot_chapter3_final, chapter3_plot_style):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any(name and (name.startswith("dmf") or "statistics" in name or "replay_chapter3" in name) for name in imported))

    def test_duplicate_statistical_row_is_rejected(self):
        with self.assertRaises(ValueError):
            one([row("scale"), row("scale")], group="scale")

    def test_method_names_and_fault_panel_titles_remain_single_line(self):
        with rc_context(font_settings()[0]):
            methods = [row("scale", method=m) for m in ("static_astar", "safe_serial", "coordinated")]
            fig = plot_a(methods, {"baseline_plot_droplets": 8}, "fixture", PlotAudit())
            for ax in fig.axes:
                labels = [text.get_text().splitlines() for text in ax.get_xticklabels()]
                self.assertEqual([parts[0] for parts in labels], ["Uncoordinated A*", "Safe serial", "Coordinated"])
                self.assertTrue(all(len(parts) == 2 and parts[1].startswith("$n=") for parts in labels))
            config = {"fault_counts": [0, 1], "fault_placements": ["random", "path_critical"]}
            faults = [row("fault", fault_count=n, placement=p) for n in (0, 1) for p in config["fault_placements"]]
            fig = plot_d(faults, config, "fixture", PlotAudit())
            for ax in fig.axes[:4]:
                self.assertNotIn("\n", ax.get_title(loc="left"))

    def test_zero_display_limit_preserves_raw_sd_and_signed_change(self):
        methods = [row("scale", method=m) for m in ("static_astar", "safe_serial", "coordinated")]
        for item in methods:
            item.update(planning_time_ms_mean=3, planning_time_ms_std=5)
        before = copy.deepcopy(methods)
        with rc_context(font_settings()[0]):
            fig = plot_a(methods, {"baseline_plot_droplets": 8}, "fixture", PlotAudit())
            self.assertTrue(all(ax.get_ylim()[0] == 0 for ax in fig.axes))
            errors = [c for c in fig.axes[2].containers if hasattr(c, "lines")]
            self.assertEqual(errors[0].lines[2][0].get_segments()[0][0][1], -2)
            self.assertTrue(errors[0].lines[2][0].get_clip_on())
            self.assertEqual(methods, before)
            faults = [row("fault", fault_count=n, placement=p) for n in (0, 1) for p in ("random", "path_critical")]
            for item in faults:
                item.update(delta_makespan_vs_zero_fault_mean=-1, delta_makespan_vs_zero_fault_std=2)
            fig = plot_d(faults, {"fault_counts": [0, 1], "fault_placements": ["random", "path_critical"]}, "fixture", PlotAudit())
            self.assertTrue(all(ax.get_ylim()[0] == 0 for ax in fig.axes[:3]))
            self.assertLess(fig.axes[3].get_ylim()[0], 0)

    def test_scalability_encoding_has_no_coordinate_offsets(self):
        sizes = [2, 4, 8]
        methods = ("static_astar", "safe_serial", "coordinated")
        rows = [row("scale", method=m, droplet_count=n) for n in sizes for m in methods]
        with rc_context(font_settings()[0]):
            fig = plot_b(rows, {"droplet_counts": sizes}, "fixture", PlotAudit())
            for ax in fig.axes[:6]:
                for method in methods:
                    container = next(c for c in ax.containers if c.get_label() == METHOD_LABELS[method])
                    line = container.lines[0]
                    self.assertEqual(list(line.get_xdata()), sizes)
                    self.assertEqual(line.get_marker(), MARKERS[method])
                    self.assertEqual(line.get_linestyle(), LINES[method])
                    self.assertEqual(line.get_color(), METHOD_COLORS[method])
                    self.assertEqual(line.get_zorder(), METHOD_ZORDERS[method] + 0.1)
            tails = [dict(droplet_count=n, n=20, median_ms=10, p95_ms=40, max_ms=50) for n in (20, 24, 30)]
            fig = plot_tails(tails, "fixture", PlotAudit())
            self.assertEqual(fig.axes[0].get_title(loc="left"), "High-load planning-time statistics")

    def test_six_png_pdf_exports_preserve_every_source_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline, replay = root / "baseline", root / "replay"
            baseline.mkdir()
            replay.mkdir()
            config = dict(baseline_plot_droplets=8, droplet_counts=[2, 4, 8],
                          congestion_gate_widths=[20, 7, 3], fault_counts=[0, 1],
                          fault_placements=["random", "path_critical"])
            (baseline / "config.json").write_text(json.dumps(config), encoding="utf-8")
            baseline_rows = [row("scale", method=m, droplet_count=n)
                             for n in config["droplet_counts"] for m in ("static_astar", "safe_serial", "coordinated")]
            baseline_rows += [row("congestion", gate_width=w) for w in config["congestion_gate_widths"]]
            for r in baseline_rows:
                if r["method"] == "static_astar" and r["droplet_count"] == 8:
                    r["makespan_steps_n"] = 2
            write_summary(baseline, "summary", baseline_rows)
            fault_rows = [row("fault", fault_count=n, placement=p) for n in (0, 1) for p in config["fault_placements"]]
            write_summary(replay, "summary_v2", fault_rows)
            counts = {"v1": {"success": 60, "invalid_replay": 4, "protective_pause": 8, "unreachable": 8},
                      "v2": {"success": 60, "protective_pause": 12, "unreachable": 8}}
            for version, name in (("v1", "v1_replay_records"), ("v2", "v2_records")):
                with (replay / (name + ".csv")).open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["status"])
                    writer.writeheader()
                    for key, count in counts[version].items():
                        writer.writerows({"status": key} for _ in range(count))
            comparison = dict(v1_status_counts=counts["v1"], v2_status_counts=counts["v2"],
                              common_success_trials=60, common_makespan_changed=0)
            (replay / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
            with (replay / "planning_time_tails_v1.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["droplet_count", "n", "median_ms", "p95_ms", "max_ms"])
                writer.writeheader()
                writer.writerows(dict(droplet_count=n, n=20, median_ms=10, p95_ms=40, max_ms=50) for n in (20, 24, 30))
            protected = [p for folder in (baseline, replay) for p in folder.iterdir()]
            hashes = {str(p): sha(p) for p in protected}
            report = generate(baseline, replay, root / "final")
            self.assertEqual(hashes, {str(p): sha(p) for p in protected})
            self.assertTrue(report["original_data_unchanged"])
            self.assertFalse(report["simulation_rerun"])
            self.assertEqual(len(report["files"]), 12)
            captions = (root / "final/figure_captions.md").read_text(encoding="utf-8")
            self.assertIn("Before identity check", captions)
            self.assertIn("Identity-preserving", captions)
            self.assertIn("channel width in electrode cells", captions)
            self.assertEqual(len(list((root / "final/PDF").glob("*.pdf"))), 6)
            for p in (root / "final/PNG").glob("*.png"):
                with Image.open(p) as image:
                    self.assertAlmostEqual(image.info["dpi"][0], 300, delta=1)
            for p in (root / "final/PDF").glob("*.pdf"):
                self.assertTrue(p.read_bytes().startswith(b"%PDF-"))
            with (root / "final/plot_values.csv").open(encoding="utf-8-sig", newline="") as stream:
                audit = list(csv.DictReader(stream))
            a = [r for r in audit if r["figure"] == "A" and r["metric"] == "makespan_steps" and r["series"] == "static_astar"][0]
            self.assertEqual(float(a["metric_n"]), 2)
            self.assertEqual(float(a["total_n"]), 20)
            with self.assertRaises(FileExistsError):
                generate(baseline, replay, root / "final")


if __name__ == "__main__":
    unittest.main()
