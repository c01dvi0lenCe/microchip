"""Synthetic software fixtures, NOT formal human ground truth."""
import importlib.util
import unittest


class EventMetricsTests(unittest.TestCase):
    def setUp(self):
        self.manifest = [dict(trial_id="trial", task_id="task", clock_domain="video:fixture",
                              eligible=True, step_ids=[0, 1])]
        self.references = [self.reference(i) for i in (0, 1)]
        self.predictions = [self.prediction(i) for i in (0, 1)]

    def reference(self, step_id, **extra):
        row = dict(trial_id="trial", task_id="task", step_id=step_id, clock_domain="video:fixture",
                   status="arrived", arrival_lower_s=1., arrival_upper_s=1.1,
                   observation_start_s=0., observation_end_s=2., annotation_source="human",
                   reviewed=True, provenance="software fixture only; not scientific annotation")
        row.update(extra)
        return row

    def prediction(self, step_id, **extra):
        row = dict(trial_id="trial", task_id="task", step_id=step_id, clock_domain="video:fixture",
                   action="Update", timestamp_s=1.3)
        row.update(extra)
        return row

    def evaluate(self):
        spec = importlib.util.find_spec("dmf.vision.event_evaluation")
        self.assertIsNotNone(spec, "B4 independent event evaluator must exist")
        from dmf.vision.event_evaluation import evaluate_events
        return evaluate_events(self.predictions, self.references, self.manifest)

    def test_arrival_interval_preserves_delay_bounds(self):
        result = self.evaluate()
        self.assertEqual(result["counts"]["confirmed_arrivals"], 2)
        self.assertEqual(result["counts"]["completed_paths"], 1)
        self.assertAlmostEqual(result["per_step"][0]["delay_lower_s"], .2)
        self.assertAlmostEqual(result["per_step"][0]["delay_upper_s"], .3)
        self.assertEqual(result["rates"]["path_completion_rate"], 1.)

    def test_before_interval_is_early_and_inside_is_ambiguous(self):
        self.predictions = [self.prediction(0, timestamp_s=.9), self.prediction(1, timestamp_s=1.05)]
        result = self.evaluate()
        self.assertEqual(result["counts"]["early_events"], 1)
        self.assertEqual(result["counts"]["ambiguous_timing_events"], 1)
        self.assertEqual(result["counts"]["confirmed_arrivals"], 0)
        self.assertEqual(result["counts"]["completed_paths"], 0)
        self.assertEqual(result["rates"]["early_event_rate"], .5)

    def test_no_events_counts_all_manifest_steps_and_missing_arrivals(self):
        self.predictions = []
        result = self.evaluate()
        self.assertEqual(result["denominators"]["eligible_steps"], 2)
        self.assertEqual(result["counts"]["missing_arrival_events"], 2)
        self.assertEqual(result["counts"]["missing_prediction_steps"], 2)
        self.assertEqual(result["rates"]["arrival_confirmation_recall"], 0.)
        self.assertEqual(result["rates"]["path_completion_rate"], 0.)

    def test_complete_nonarrival_false_update_is_not_censoring(self):
        self.references[0] = self.reference(0, status="not_arrived", arrival_lower_s=None, arrival_upper_s=None)
        result = self.evaluate()
        self.assertEqual(result["counts"]["false_events"], 1)
        self.assertEqual(result["denominators"]["observed_nonarrival_steps"], 1)
        self.assertEqual(result["rates"]["false_event_rate"], 1.)
        self.assertEqual(result["counts"]["completed_paths"], 0)

    def test_censored_occluded_uncertain_and_missing_reference_not_negatives(self):
        for status in ("right_censored", "occluded", "uncertain", "missing"):
            with self.subTest(status=status):
                self.references = [self.reference(1)]
                if status != "missing":
                    self.references.insert(0, self.reference(0, status=status, arrival_lower_s=None, arrival_upper_s=None))
                result = self.evaluate()
                self.assertEqual(result["denominators"]["eligible_steps"], 2)
                self.assertEqual(result["counts"]["false_events"], 0)
                self.assertEqual(result["counts"]["uncertain_paths"], 1)
                self.assertEqual(result["counts"]["completed_paths"], 0)
                self.assertEqual(result["counts"][status + "_reference_steps"], 1)

    def test_duplicate_events_flagged_and_early_cannot_be_erased(self):
        self.predictions.insert(0, self.prediction(0, timestamp_s=.9))
        result = self.evaluate()
        self.assertEqual(result["counts"]["duplicate_events"], 1)
        self.assertEqual(result["counts"]["duplicate_event_steps"], 1)
        self.assertEqual(result["counts"]["early_events"], 1)
        self.assertEqual(result["counts"]["confirmed_arrivals"], 1)
        self.assertEqual(result["counts"]["completed_paths"], 0)

    def test_complete_action_is_arrival_event_and_hold_is_not(self):
        self.predictions = [self.prediction(0, action="Hold"), self.prediction(1, action="Complete")]
        result = self.evaluate()
        self.assertEqual(result["counts"]["confirmed_arrivals"], 1)
        self.assertEqual(result["counts"]["missing_arrival_events"], 1)

    def test_missing_or_incomplete_reference_never_shrinks_trial_denominator(self):
        self.manifest.append(dict(trial_id="failed", task_id="task", clock_domain="video:fixture", eligible=True, step_ids=[0]))
        result = self.evaluate()
        self.assertEqual(result["denominators"]["eligible_trials"], 2)
        self.assertEqual(result["denominators"]["eligible_steps"], 3)
        self.assertEqual(result["rates"]["path_completion_rate"], .5)
        self.assertEqual(result["counts"]["missing_reference_steps"], 1)
        self.assertEqual(result["counts"]["uncertain_paths"], 1)

    def test_clock_domain_task_identity_and_unplanned_steps_rejected(self):
        for change in (dict(clock_domain="qpc"), dict(clock_domain=""), dict(task_id="other"), dict(step_id=99)):
            with self.subTest(change=change):
                self.predictions = [self.prediction(0, **change)] if "step_id" not in change else [self.prediction(99)]
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_invalid_times_and_intervals_rejected(self):
        for value in (-1., float("nan"), float("inf"), None):
            with self.subTest(value=value):
                self.predictions = [self.prediction(0, timestamp_s=value)]
                with self.assertRaises(ValueError):
                    self.evaluate()
        self.predictions = []
        self.references[0]["arrival_upper_s"] = .9
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_explicit_human_review_and_provenance_required(self):
        for change in (dict(annotation_source="algorithm"), dict(reviewed=False), dict(provenance=""), dict(reviewed="false")):
            with self.subTest(change=change):
                self.references[0] = self.reference(0, **change)
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_duplicate_references_and_manifest_trials_rejected(self):
        self.references.append(self.references[0])
        with self.assertRaises(ValueError):
            self.evaluate()
        self.references.pop()
        self.manifest.append(self.manifest[0])
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_path_completion_respects_planned_step_order(self):
        self.predictions = [self.prediction(0, timestamp_s=1.5), self.prediction(1, timestamp_s=1.3)]
        result = self.evaluate()
        self.assertEqual(result["counts"]["completed_paths"], 0)
        self.assertEqual(result["counts"].get("out_of_order_paths"), 1)

    def test_duplicate_late_confirmations_never_inflate_path_success(self):
        self.predictions.append(self.prediction(0, timestamp_s=1.4))
        result = self.evaluate()
        self.assertEqual(result["counts"]["confirmed_arrivals"], 2)
        self.assertEqual(result["counts"]["duplicate_events"], 1)
        self.assertEqual(result["counts"]["completed_paths"], 0)

    def test_point_interval_allows_zero_delay_without_fabricated_precision(self):
        self.references = [self.reference(i, arrival_lower_s=1., arrival_upper_s=1.) for i in (0, 1)]
        self.predictions = [self.prediction(i, timestamp_s=1.) for i in (0, 1)]
        result = self.evaluate()
        self.assertEqual(result["counts"]["confirmed_arrivals"], 2)
        self.assertEqual(result["per_step"][0]["delay_lower_s"], 0.)
        self.assertEqual(result["per_step"][0]["delay_upper_s"], 0.)

    def test_outside_observed_window_nonarrival_is_unassessable(self):
        self.references[0] = self.reference(0, status="not_arrived", arrival_lower_s=None, arrival_upper_s=None)
        self.predictions[0] = self.prediction(0, timestamp_s=3.)
        result = self.evaluate()
        self.assertEqual(result["counts"]["false_events"], 0)
        self.assertEqual(result["counts"]["unassessable_events"], 1)
        self.assertEqual(result["denominators"]["eligible_steps"], 2)

    def test_excluded_trials_are_explicit_and_zero_rates_are_not_invented(self):
        self.manifest[0]["eligible"] = False
        result = self.evaluate()
        self.assertEqual(result["counts"]["excluded_trials"], 1)
        self.assertEqual(result["counts"]["excluded_steps"], 2)
        self.assertEqual(result["counts"]["excluded_reference_rows"], 2)
        self.assertEqual(result["counts"]["excluded_events"], 2)
        self.assertIsNone(result["rates"]["path_completion_rate"])

    def test_reference_clock_mismatch_is_rejected(self):
        self.references[0]["clock_domain"] = "host:qpc"
        with self.assertRaises(ValueError):
            self.evaluate()
