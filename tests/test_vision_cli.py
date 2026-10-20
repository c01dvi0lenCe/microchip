import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from dmf.vision.cli import extract_frames, main
from dmf.vision.evaluation import evaluate_results
from dmf.vision.config import load_electrode_map, save_electrode_map
from dmf.vision.overlay import render_electrode_overlay
from dmf.vision.pipeline import run_baseline
from dmf.vision.timeseries import export_transport_timeseries

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@unittest.skipIf(cv2 is None, "OpenCV is required")
class VisionCliTests(unittest.TestCase):
    def _write_video(self, path: Path) -> None:
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (80, 60))
        if not writer.isOpened():
            self.skipTest("MJPG video writer is unavailable")
        for offset in range(5):
            frame = np.full((60, 80, 3), 240, dtype=np.uint8)
            cv2.circle(frame, (25 + offset * 2, 30), 7, (20, 20, 20), -1)
            writer.write(frame)
        writer.release()

    def test_extract_frames_writes_timestamp_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "pilot.avi"
            self._write_video(video)
            manifest = extract_frames(video, "pilot", root / "extracted", every_n=2)
            with manifest.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([int(row["frame_id"]) for row in rows], [0, 2, 4])
            self.assertTrue(all((manifest.parent / row["frame_path"]).is_file() for row in rows))

    def test_background_pipeline_writes_unified_csv_masks_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "pilot.avi"
            self._write_video(video)
            background = np.full((60, 80, 3), 240, dtype=np.uint8)
            background_path = root / "background.png"
            cv2.imwrite(str(background_path), background)
            map_config = root / "map.yaml"
            map_config.write_text(
                yaml.safe_dump(
                    {
                        "rows": 20,
                        "cols": 20,
                        "pitch_mm": 3.2,
                        "core_corners_px": [[10, 10], [70, 10], [70, 50], [10, 50]],
                        "pixel_overrides": {},
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "run_id": "test-run",
                "video": {"video_id": "pilot", "batch_id": "b1", "split": "test", "path": "pilot.avi"},
                "electrode_map": "map.yaml",
                "output_dir": "output",
                "source_electrode": 1,
                "target_electrode": 2,
                "algorithm": {
                    "name": "background",
                    "parameters": {
                        "background_images": ["background.png"],
                        "min_diff": 10,
                        "min_area_px": 20,
                    },
                },
                "constraints": {"spatial": {"enabled": False}, "temporal": {"enabled": False}},
            }
            config_path = root / "experiment.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            results_path, manifest_path = run_baseline(config_path)
            with results_path.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row["algorithm"] == "background" for row in rows))
            self.assertTrue(all(row["detected"] == "True" for row in rows))
            self.assertTrue(all((results_path.parent / row["mask_path"]).is_file() for row in rows))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], "test-run")
            self.assertEqual(manifest["frames_processed"], 5)
            self.assertEqual(manifest["algorithm_version"], 1)

    def test_cli_lists_all_four_phase_one_commands(self):
        with self.assertRaises(SystemExit) as context:
            main(["--help"])
        self.assertEqual(context.exception.code, 0)

    def test_evaluation_writes_segmentation_and_localization_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mask = np.zeros((30, 30), dtype=np.uint8)
            mask[10:20, 10:20] = 255
            cv2.imwrite(str(root / "mask.png"), mask)
            ground_truth = root / "ground_truth.csv"
            ground_truth.write_text(
                "video_id,batch_id,frame_id,timestamp_s,mask_path,source_electrode,target_electrode,state_gt\n"
                "v1,b1,0,0.0,mask.png,1,2,Arrived\n",
                encoding="utf-8",
            )
            results = root / "results.csv"
            results.write_text(
                "video_id,frame_id,mask_path,centroid_u_px,centroid_v_px,detected,processing_time_ms,pipeline_time_ms,state_pred\n"
                "v1,0,mask.png,14.5,14.5,True,2.0,4.0,Arrived\n",
                encoding="utf-8",
            )
            summary = evaluate_results(results, ground_truth, root / "evaluation")
            self.assertEqual(summary["mean_iou"], 1.0)
            self.assertEqual(summary["miss_rate"], 0.0)
            self.assertAlmostEqual(summary["processing_fps"], 500.0)
            self.assertAlmostEqual(summary["pipeline_fps"], 250.0)
            self.assertEqual(summary["state_metrics"]["macro_f1"], 0.2)
            self.assertTrue((root / "evaluation" / "per_frame_metrics.csv").is_file())
            self.assertTrue((root / "evaluation" / "evaluation_summary.json").is_file())

    def test_evaluation_rejects_a_nonempty_missing_prediction_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth_mask = np.zeros((10, 10), dtype=np.uint8)
            cv2.imwrite(str(root / "truth.png"), truth_mask)
            ground_truth = root / "ground_truth.csv"
            ground_truth.write_text(
                "video_id,batch_id,frame_id,timestamp_s,mask_path,source_electrode,target_electrode,state_gt\n"
                "v1,b1,0,0.0,truth.png,1,2,Unknown\n",
                encoding="utf-8",
            )
            results = root / "results.csv"
            results.write_text(
                "video_id,frame_id,mask_path,detected,processing_time_ms,state_pred\n"
                "v1,0,missing.png,False,1.0,Unknown\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FileNotFoundError, "predicted mask"):
                evaluate_results(results, ground_truth, root / "evaluation")

    def test_electrode_map_configuration_rejects_invalid_dimensions_and_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "map.yaml"
            base = {
                "rows": 19,
                "cols": 20,
                "core_corners_px": [[0, 0], [20, 0], [20, 20], [0, 20]],
            }
            config_path.write_text(yaml.safe_dump(base), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "20 x 20"):
                load_electrode_map(config_path)
            base["rows"] = 20
            base["pixel_overrides"] = {421: [[0, 0], [1, 0], [1, 1]]}
            config_path.write_text(yaml.safe_dump(base), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid electrode IDs"):
                load_electrode_map(config_path)

    def test_map_json_round_trip_and_overlay_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_yaml = root / "map.yaml"
            map_yaml.write_text(
                yaml.safe_dump(
                    {
                        "rows": 20,
                        "cols": 20,
                        "pitch_mm": 3.2,
                        "core_corners_px": [[20, 20], [220, 20], [220, 220], [20, 220]],
                        "pixel_overrides": {"401": [[80, 8], [90, 8], [90, 18], [80, 18]]},
                    }
                ),
                encoding="utf-8",
            )
            electrode_map = load_electrode_map(map_yaml)
            map_json = root / "map.json"
            save_electrode_map(map_json, electrode_map)
            loaded = load_electrode_map(map_json)
            self.assertEqual(loaded[401].geometry_source, "calibrated")
            image = np.full((240, 240, 3), 245, dtype=np.uint8)
            image_path = root / "chip.png"
            cv2.imwrite(str(image_path), image)
            outputs = render_electrode_overlay(
                image_path,
                loaded,
                root / "overlay.png",
                zoom_electrodes=[1, 210],
            )
            self.assertEqual(len(outputs), 3)
            self.assertTrue(all(path.is_file() for path in outputs))

    def test_dmf_evaluation_and_timeseries_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mask = np.zeros((100, 100), dtype=np.uint8)
            mask[2:5, 2:5] = 255
            cv2.imwrite(str(root / "mask.png"), mask)
            map_path = root / "map.yaml"
            map_path.write_text(
                yaml.safe_dump(
                    {
                        "rows": 20,
                        "cols": 20,
                        "pitch_mm": 3.2,
                        "core_corners_px": [[0, 0], [100, 0], [100, 100], [0, 100]],
                    }
                ),
                encoding="utf-8",
            )
            truth = root / "truth.csv"
            truth.write_text(
                "video_id,frame_id,mask_path,source_electrode,target_electrode,state_gt\n"
                "v1,0,mask.png,1,2,Partial\n",
                encoding="utf-8",
            )
            results = root / "results.csv"
            results.write_text(
                "video_id,experiment_id,frame_id,timestamp_s,mask_path,centroid_u_px,centroid_v_px,"
                "detected,processing_time_ms,pipeline_time_ms,state_pred,state_gt,source_electrode,"
                "target_electrode,source_coverage,target_coverage,distance_to_target_mm,velocity_mm_s\n"
                "v1,e1,0,0.0,mask.png,3,3,True,1,2,Unknown,Partial,1,2,1,0,3.2,0\n",
                encoding="utf-8",
            )
            summary = evaluate_results(results, truth, root / "evaluation", electrode_map_path=map_path)
            self.assertEqual(summary["dmf_metrics"]["overall"]["electrode_assignment_accuracy"], 1.0)
            self.assertEqual(summary["dmf_metrics"]["partial"]["frames"], 1)
            self.assertEqual(summary["dmf_metrics"]["overall"]["mean_source_coverage_error"], 0.0)
            output = export_transport_timeseries(results, root / "timeseries.csv", experiment_id="e1")
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["target_coverage"], "0")


if __name__ == "__main__":
    unittest.main()
