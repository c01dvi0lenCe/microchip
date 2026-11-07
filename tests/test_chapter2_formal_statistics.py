from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import csv
import json
import random

from unittest.mock import patch

from dmf.vision.event_evaluation import evaluate_events, evaluate_simulation_events
from dmf.chapter2_sim.formal_batch import summarize_trials, summarize_offline, run_formal_batch
from dmf.chapter2_sim.config import SimConfig


class FormalStatisticsTests(unittest.TestCase):
    def fixture(self):
        manifest = [dict(trial_id='one', task_id='route', clock_domain='simulation', eligible=True, step_ids=[0, 1, 2])]
        refs = [dict(trial_id='one', task_id='route', clock_domain='simulation', step_id=0,
                     simulation=True, annotation_source='simulation_physics', provenance='independent physics fixture',
                     status='arrived', observation_start_s=0., observation_end_s=4., arrival_lower_s=1., arrival_upper_s=1.01)]
        return manifest, refs

    def test_reference_origins_never_interchangeable(self):
        manifest, refs = self.fixture()
        with self.assertRaises(ValueError): evaluate_events([], refs, manifest)
        result = evaluate_simulation_events([], refs, manifest)
        self.assertEqual(result['denominators']['eligible_steps'], 3)
        self.assertEqual(result['counts']['missing_reference_steps'], 2)
        self.assertEqual(result['counts']['missing_arrival_events'], 1)
        refs[0].update(annotation_source='human', reviewed=True)
        with self.assertRaises(ValueError): evaluate_simulation_events([], refs, manifest)

    def rows(self):
        return [dict(simulation=True, scenario='normal', seed=i, method='C', method_version='C_formal_b1b4_v1',
                     transport_steps=3, path_complete=i==0, early_updates=0, confirmed_steps=3 if i==0 else 0,
                     reference_arrived_steps=3 if i==0 else 1, correct_confirmed_steps=3 if i==0 else 0,
                     confirmation_delay_s=.2 if i==0 else None, completion_time_s=4. if i==0 else None,
                     total_time_s=4. if i==0 else 8., retries=i, recoveries=i, recovery_resends=0,
                     preparation_time_s=.4, transport_execution_time_s=3.6 if i==0 else 7.6,
                     delay_missing_steps=0 if i==0 else 3, delay_censored_steps=i,
                     delay_no_arrival_steps=0 if i==0 else 2, delay_unattempted_steps=0) for i in range(2)]

    def test_failed_and_missing_samples_retain_support(self):
        result = summarize_trials(self.rows(), bootstrap_repeats=40)[0]
        self.assertEqual(result['n_trials'], 2)
        self.assertEqual(result['transport_steps'], 6)
        self.assertEqual(result['path_complete_rate'], .5)
        self.assertEqual(result['arrival_confirmation_recall'], .75)
        self.assertEqual(result['completion_time_s_n'], 1)
        self.assertEqual(result['confirmation_delay_s_n'], 1)
        self.assertEqual(result['total_time_s_mean'], 6.)
        self.assertEqual(result['delay_missing_steps'], 3)
        self.assertEqual(result, summarize_trials(self.rows(), bootstrap_repeats=40)[0])

    def test_version_collision_and_duplicates_rejected(self):
        rows = self.rows()
        with self.assertRaises(ValueError): summarize_trials(rows+[rows[0]])
        rows[1]['method_version'] = 'C_legacy'
        with self.assertRaises(ValueError): summarize_trials(rows)

    def test_offline_unknown_failure_not_removed(self):
        rows = self.rows(); rows[0]['method']='S4'; rows[1]['method']='S4'
        for row in rows: row['method_version']='S4_mask_cache_v1'; row['unknown_frames']=20
        result = summarize_offline(rows, bootstrap_repeats=40)[0]
        self.assertEqual(result['n_trials'], 2)
        self.assertEqual(result['unknown_frames'], 40)

    def test_batch_preserves_versions_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'batch'
            rows = run_formal_batch(SimConfig(route=(190,191), max_time_s=5.), ['normal'], [23], output,
                                    methods=('A','B','C','C_no_temporal'), bootstrap_repeats=20)
            self.assertEqual(len(rows), 4)
            self.assertEqual({r['method'] for r in rows}, {'A','B','C','C_no_temporal'})
            self.assertTrue((output/'manifest.json').is_file())
            with self.assertRaises(FileExistsError):
                run_formal_batch(SimConfig(), ['normal'], [23], output)

    def test_ratio_support_missing_counts_and_rng_are_explicit(self):
        rows = self.rows()
        rows[1]['unknown_frames'] = 4
        rows[0]['early_updates'] = 1
        rows[0]['correct_confirmed_steps'] = 2
        state = random.getstate()
        result = summarize_trials(rows, bootstrap_repeats=40)[0]
        self.assertEqual(random.getstate(), state)
        self.assertEqual(result['early_update_rate'], 1 / 6)
        self.assertEqual(result['early_update_rate_per_issued_update'], 1 / 3)
        self.assertEqual(result['reference_arrived_steps'], 4)
        self.assertEqual(result['correct_confirmed_steps'], 2)
        self.assertIsNone(result['unknown_frames'])
        self.assertEqual(result['unknown_frames_missing_trials'], 1)

    def test_invalid_input_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'batch'
            for scenes, seeds, methods in (([], [1], ('A',)), (['normal'], [1,1], ('A',)),
                                           (['normal'], [1], ()), (['normal'], [1], ('C','C'))):
                with self.assertRaises(ValueError):
                    run_formal_batch(SimConfig(), scenes, seeds, output, methods=methods)
                self.assertFalse(output.exists())

    def test_incomplete_ratio_support_has_no_conditional_interval(self):
        rows = self.rows()
        rows[1].pop('reference_arrived_steps')
        result = summarize_trials(rows, bootstrap_repeats=100)[0]
        self.assertIsNone(result['arrival_confirmation_recall'])
        self.assertIsNone(result['arrival_confirmation_recall_ci_low'])
        self.assertIsNone(result['arrival_confirmation_recall_ci_high'])
        self.assertEqual(result['reference_arrived_steps_missing_trials'], 1)

    def test_invalid_public_metrics_are_rejected(self):
        invalid = (
            ('early_updates', -1), ('transport_steps', True), ('confirmed_steps', .5),
            ('unknown_frames', -1), ('delay_missing_steps', False), ('retries', 1.5),
            ('total_time_s', float('nan')), ('confirmation_delay_s', float('inf')),
            ('preparation_time_s', -1.), ('recoveries', True), ('total_time_s', True),
            ('path_complete', 1), ('path_complete', 'yes'),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                rows = self.rows(); rows[0][field] = value
                with self.assertRaises(ValueError):
                    summarize_trials(rows, bootstrap_repeats=10)

    def test_impossible_count_relationships_are_rejected(self):
        invalid = (
            dict(early_updates=4), dict(confirmed_steps=4), dict(reference_arrived_steps=4),
            dict(correct_confirmed_steps=4), dict(confirmed_steps=2),
            dict(reference_arrived_steps=2), dict(early_updates=1),
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                rows = self.rows(); rows[0].update(changes)
                with self.assertRaises(ValueError):
                    summarize_trials(rows, bootstrap_repeats=10)

    def test_optional_missing_metrics_remain_unknown(self):
        rows = self.rows()
        rows[1].update(reference_arrived_steps=None, total_time_s=None, path_complete=None,
                       retries=None, unknown_frames=None)
        result = summarize_trials(rows, bootstrap_repeats=10)[0]
        self.assertIsNone(result['reference_arrived_steps'])
        self.assertEqual(result['total_time_s_n'], 1)
        self.assertEqual(result['retries_n'], 1)
        self.assertEqual(result['path_complete_missing_trials'], 1)

    def test_evaluator_counters_are_preserved_without_semantic_imputation(self):
        row = dict(self.rows()[0], path_complete=False, confirmed_steps=1,
                   reference_arrived_steps=2, correct_confirmed_steps=1,
                   missing_arrival_events=1, delay_censored_steps=1,
                   right_censored_reference_steps=2, occluded_reference_steps=0,
                   uncertain_reference_steps=0, unassessable_events=1,
                   duplicate_events=3, ambiguous_timing_events=1, early_events=0, false_events=2)
        result = summarize_trials([row], bootstrap_repeats=10)[0]
        for field in ('missing_arrival_events', 'right_censored_reference_steps',
                      'occluded_reference_steps', 'uncertain_reference_steps',
                      'unassessable_events', 'duplicate_events', 'ambiguous_timing_events',
                      'early_events', 'false_events', 'delay_censored_steps'):
            self.assertEqual(result[field], row[field])
        self.assertEqual(result['confirmation_delay_s_censored_steps'], 1)
        partial = summarize_trials([row, self.rows()[1]], bootstrap_repeats=10)[0]
        self.assertIsNone(partial['false_events'])
        self.assertEqual(partial['false_events_missing_trials'], 1)

    def test_batch_derives_unknown_and_missing_masks_from_raw_frames(self):
        from dmf.chapter2_sim.runner import TrialResult
        def execute(cfg, scenario, seed, method='C', ablation='full'):
            metric = dict(self.rows()[seed], method=method,
                          captured_frames=5, pending_frames_at_termination=1)
            frames = [dict(state='Unknown', reason='CAMERA_DROPPED'),
                      dict(state='Unknown', reason='NO_MASK'),
                      dict(state='Unknown', reason='AMBIGUOUS_MASK'),
                      dict(state='Unknown', reason='PROCESSING_PENDING_AT_TERMINATION', censored=True),
                      dict(state='Arrived', reason='')]
            return TrialResult(metric, frames, [], [])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'batch'
            with patch('dmf.chapter2_sim.formal_runner.run_formal_trial', side_effect=execute):
                rows = run_formal_batch(SimConfig(), ['normal'], [0,1], output,
                                        methods=('C',), bootstrap_repeats=10)
            self.assertEqual([r['unknown_frames'] for r in rows], [4,4])
            self.assertEqual([r['missing_mask_frames'] for r in rows], [2,2])
            summary = summarize_trials(rows, bootstrap_repeats=10)[0]
            self.assertEqual(summary['unknown_frames'], 8)
            self.assertEqual(summary['missing_mask_frames'], 4)
            self.assertEqual(summary['pending_frames_at_termination'], 2)
            self.assertEqual(summary['captured_frames'], 10)

    def test_streamed_raw_union_headers_manifest_and_paired_ablation(self):
        from dmf.chapter2_sim.runner import TrialResult
        def execute(cfg, scenario, seed, method='C', ablation='full'):
            metric = dict(self.rows()[seed], method=method,
                          method_version='C_formal_b1b4_v1', ablation=ablation)
            return TrialResult(metric, [dict(frame_id=1, **{ablation: seed})],
                               [dict(time_s=1.)], [dict(event='fixture')])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'batch'
            with patch('dmf.chapter2_sim.formal_runner.run_formal_trial', side_effect=execute):
                rows = run_formal_batch(SimConfig(), ['normal'], [0,1], output,
                                        methods=('C','C_no_spatial'), bootstrap_repeats=20)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len({r['method_version'] for r in rows}), 2)
            with (output/'frames.csv').open(encoding='utf-8', newline='') as handle:
                raw = list(csv.DictReader(handle))
            self.assertEqual(len(raw), 4)
            self.assertIn('full', raw[0]); self.assertIn('no_spatial', raw[0])
            manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
            self.assertIn('git_dirty', manifest)
            self.assertIn('dmf/experiment/perception.py', manifest['source_sha256'])
            self.assertIn('dmf/layout.py', manifest['source_sha256'])
            self.assertIn('truth.csv', manifest['output_sha256'])
            with (output/'paired_differences.csv').open(encoding='utf-8', newline='') as handle:
                paired = list(csv.DictReader(handle))
            self.assertTrue(any(r['comparison']=='C_no_spatial-C' and r['n_pairs']=='2' for r in paired))


if __name__ == '__main__': unittest.main()
