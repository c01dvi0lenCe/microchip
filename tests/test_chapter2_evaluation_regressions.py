"""Software-only fixtures; no human annotation or hardware evidence is created."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from dmf.vision.dataset import read_csv_rows, write_csv_rows
from dmf.vision.evaluation import evaluate_results
from dmf.vision.image_io import write_image
from dmf.vision.metrics import state_classification_metrics


class StateDenominatorTests(unittest.TestCase):
    def test_p9_unknown_is_an_abstention_not_a_removed_reference(self):
        result = state_classification_metrics(["Arrived", "Unknown"], ["Arrived", "Arrived"])
        self.assertEqual(result["per_class"]["Arrived"]["recall"], .5)
        self.assertEqual(result["per_class"]["Arrived"]["support"], 2)
        self.assertEqual(result["confusion_matrix"]["Arrived"]["Unknown"], 1)
        self.assertEqual(result["abstention_rate"], .5)
        self.assertEqual(result["known_gt_count"], 2)
        self.assertEqual(result["conditional_five_class"]["denominator"], 1)
        self.assertEqual(result["conditional_five_class"]["per_class"]["Arrived"]["recall"], 1.)

    def test_unknown_truth_counted_separately_and_five_names_preserved(self):
        result = state_classification_metrics(["Moving", "Unknown"], ["Unknown", "Arrived"])
        self.assertEqual(len(result["labels"]), 5)
        self.assertEqual(result.get("prediction_labels"), result["labels"] + ["Unknown"])
        self.assertEqual(result["unknown_gt_count"], 1)
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["known_gt_count"], 1)
        self.assertEqual(result["abstention_rate"], 1.)


class EvaluationDenominatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mask = np.zeros((12, 12), np.uint8)
        self.mask[3:9, 3:9] = 255
        self.assertTrue(write_image(self.root / "truth.png", self.mask))
        self.truths = [dict(video_id="v", frame_id=i, mask_path="truth.png", state_gt="Arrived") for i in range(2)]
        self.predictions = [self.prediction(0)]

    def prediction(self, frame_id, **extra):
        return dict(video_id="v", frame_id=frame_id, mask_path="truth.png", detected=True,
                    centroid_u_px=5.5, centroid_v_px=5.5, state_pred="Arrived", **extra)

    def evaluate(self):
        write_csv_rows(self.root / "truth.csv", self.truths)
        write_csv_rows(self.root / "results.csv", self.predictions,
                       fieldnames=list(self.prediction(0)))
        return evaluate_results(self.root / "results.csv", self.root / "truth.csv", self.root / "out")

    def test_missing_prediction_is_zero_segmentation_and_unknown_state(self):
        result = self.evaluate()
        self.assertEqual(result["matched_frames"], 2)
        self.assertEqual(result.get("reference_frames"), 2)
        self.assertEqual(result["missing_prediction_rows"], 1)
        self.assertEqual(result["prediction_rows_matched"], 1)
        self.assertEqual(result["mean_iou"], .5)
        self.assertEqual(result["segmentation_denominator"], 2)
        self.assertEqual(result["miss_rate"], .5)
        self.assertEqual(result["state_metrics"]["per_class"]["Arrived"]["recall"], .5)
        rows = read_csv_rows(self.root / "out" / "per_frame_metrics.csv")
        self.assertEqual(rows[1]["iou"], "0.0")
        self.assertEqual(rows[1]["prediction_missing"], "True")

    def test_blank_mask_and_detected_false_are_empty_misses(self):
        for failure in ("blank", "not_detected", "empty"):
            with self.subTest(failure=failure):
                row = self.prediction(1)
                if failure == "blank":
                    row["mask_path"] = ""
                elif failure == "not_detected":
                    row["detected"] = False
                else:
                    write_image(self.root / "empty.png", np.zeros_like(self.mask))
                    row["mask_path"] = "empty.png"
                self.predictions = [self.prediction(0), row]
                result = self.evaluate()
                self.assertEqual(result["mean_iou"], .5)
                self.assertEqual(result["miss_rate"], .5)
                self.assertEqual(result["detection_misses"], 1)
                self.assertEqual(result["missing_prediction_rows"], 0)

    def test_no_predictions_preserves_complete_denominator(self):
        self.predictions = []
        result = self.evaluate()
        self.assertEqual(result.get("reference_frames"), 2)
        self.assertEqual(result["mean_iou"], 0.)
        self.assertEqual(result["missing_prediction_rows"], 2)
        self.assertEqual(result["unknown_prediction_count"], 2)
        self.assertEqual(result["state_metrics"]["abstention_rate"], 1.)

    def test_duplicate_prediction_and_reference_keys_rejected(self):
        for table in ("predictions", "truths"):
            with self.subTest(table=table):
                original = list(getattr(self, table))
                setattr(self, table, original + [original[0]])
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    self.evaluate()
                setattr(self, table, original)

    def test_nonempty_missing_mask_reference_rejected_even_when_not_detected(self):
        self.predictions[0]["mask_path"] = "missing.png"
        self.predictions[0]["detected"] = False
        with self.assertRaises(FileNotFoundError):
            self.evaluate()

    def test_missing_truth_mask_is_error(self):
        self.truths[1]["mask_path"] = "missing.png"
        with self.assertRaises(FileNotFoundError):
            self.evaluate()

    def test_unmatched_predictions_are_counted_not_added_to_reference_denominator(self):
        self.predictions.append(self.prediction(99))
        result = self.evaluate()
        self.assertEqual(result.get("reference_frames"), 2)
        self.assertEqual(result["unmatched_prediction_rows"], 1)

    def test_experiment_mm_schema_requires_explicit_adapter(self):
        write_csv_rows(self.root / "results.csv", [dict(experiment_id="e", frame_id=0,
                       centroid_x=1.2, centroid_y=2.3, recognized_state="Arrived")])
        write_csv_rows(self.root / "truth.csv", self.truths)
        try:
            with self.assertRaisesRegex(ValueError, "adapter"):
                evaluate_results(self.root / "results.csv", self.root / "truth.csv", self.root / "out")
        except KeyError:
            self.fail("experiment schema must be rejected with an explicit adapter explanation")

    def test_empty_experiment_schema_still_requires_adapter(self):
        write_csv_rows(self.root / "results.csv", [], fieldnames=["experiment_id", "frame_id", "centroid_x", "centroid_y"])
        write_csv_rows(self.root / "truth.csv", self.truths)
        with self.assertRaisesRegex(ValueError, "adapter"):
            evaluate_results(self.root / "results.csv", self.root / "truth.csv", self.root / "out")

    def test_unmatched_prediction_with_missing_artifact_is_error(self):
        row = self.prediction(99)
        row["mask_path"] = "missing.png"
        self.predictions.append(row)
        with self.assertRaises(FileNotFoundError):
            self.evaluate()
