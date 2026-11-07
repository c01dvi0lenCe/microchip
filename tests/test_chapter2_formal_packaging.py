from pathlib import Path
import tempfile
import unittest
import json

from scripts.package_chapter2_formal_results import package_results


class PackagingTests(unittest.TestCase):
    def test_duplicate_figures_are_not_a_complete_figure_set(self):
        from scripts.package_chapter2_formal_results import validate_figure_set
        with self.assertRaises(ValueError):
            validate_figure_set([dict(figure='prespecified_trajectory', simulation=True)]*16)

    def test_source_snapshot_must_match_executed_sources(self):
        from scripts.package_chapter2_formal_results import validate_stage_provenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'code.py').write_text('changed source')
            stage = dict(semantic_source_sha256={'code.py':'0'*64}, configuration_sha256='0'*64,
                         resolved_simulation_config={'map_path': None}, map_input_sha256=None, frozen_study={})
            stages = {name:dict(stage, smoke_gate_passed=name=='smoke') for name in ('smoke','formal','sensitivity')}
            with self.assertRaisesRegex(ValueError, 'source changed'):
                validate_stage_provenance(stages, root)

    def test_failed_or_unauditable_figures_are_not_deliverable(self):
        from scripts.package_chapter2_formal_results import validate_qa_verdicts
        for alignment, collision in (('FIX BEFORE DELIVERY','PASS'), ('NOT AUDITABLE','PASS'),
                                     ('PASS','FIX BEFORE DELIVERY'), ('PASS','NOT AUDITABLE')):
            with self.subTest(alignment=alignment, collision=collision), self.assertRaises(ValueError):
                validate_qa_verdicts({'verdict':alignment}, {'verdict':collision})

    def test_raw_output_deletion_or_change_blocks_packaging(self):
        from scripts.package_chapter2_formal_results import verify_batch_outputs, sha256
        for delete in (False, True):
            with self.subTest(delete=delete), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                names = ('config_snapshot.json','electrode_map_snapshot.json','trials.csv','frames.csv',
                         'truth.csv','events.csv','summary.csv','summary.json','paired_differences.csv')
                for name in names: (root/name).write_text('fixture')
                manifest = dict(simulation=True, output_sha256={name:sha256(root/name) for name in names})
                (root/'manifest.json').write_text(json.dumps(manifest))
                if delete: (root/'truth.csv').unlink()
                else: (root/'truth.csv').write_text('altered fixture')
                with self.assertRaisesRegex(ValueError, 'raw output'):
                    verify_batch_outputs(root, 20)

    def test_child_batch_must_match_parent_seeds_and_config(self):
        from scripts.package_chapter2_formal_results import verify_batch_outputs, sha256
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ('config_snapshot.json','electrode_map_snapshot.json','trials.csv','frames.csv',
                     'truth.csv','events.csv','summary.csv','summary.json','paired_differences.csv')
            for name in names: (root/name).write_text('fixture')
            (root/'config_snapshot.json').write_text(json.dumps({'config': {'speed':1.}}))
            (root/'trials.csv').write_text('scenario,seed,method,simulation\nnormal,1,C,True\n')
            manifest = dict(simulation=True, scenarios=['normal'], seeds=[1], methods=['C'],
                            output_sha256={name:sha256(root/name) for name in names})
            (root/'manifest.json').write_text(json.dumps(manifest))
            for expected in ({'expected_seeds':[2]}, {'expected_config':{'speed':2.}}):
                with self.subTest(expected=expected), self.assertRaises(ValueError):
                    verify_batch_outputs(root, 1, **expected)

    def test_offline_completion_delay_and_quality_must_match_evaluation(self):
        from scripts.package_chapter2_formal_results import expected_offline_row, verify_offline_trial_row
        from dmf.vision.event_evaluation import evaluate_simulation_events
        identity = dict(trial_id='fixture', task_id='task', clock_domain='simulation')
        refs = [dict(identity, step_id=0, simulation=True, annotation_source='simulation_physics',
                     provenance='synthetic software fixture', status='arrived', observation_start_s=0.,
                     observation_end_s=4., arrival_lower_s=1., arrival_upper_s=1.)]
        score = evaluate_simulation_events([],refs,[dict(identity,eligible=True,step_ids=[0])])
        predicted = dict(variant='S4',method_version='S4_mask_cache_v1',input_sha256='a'*64,
                         frames=[dict(state='Unknown',mask_available=False,observation_quality='invalid')])
        expected = expected_offline_row('normal',1,predicted,score)
        row = {k:'' if v is None else str(v) for k,v in expected.items()}
        for key,value in (('path_complete','True'),('confirmation_delay_s','0.2'),('delay_censored_steps','0'),('missing_mask_frames','0')):
            changed = dict(row); changed[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_offline_trial_row(changed,'normal',1,predicted,score)

    def test_incomplete_study_is_not_packaged_as_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError): package_results(root)
            self.assertFalse((root/'result_manifest.json').exists())


if __name__ == '__main__': unittest.main()
