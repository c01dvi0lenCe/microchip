import subprocess
import sys
import unittest
from pathlib import Path
import tempfile
import json
import csv
from unittest.mock import patch
from dataclasses import asdict, replace


class FormalCliTests(unittest.TestCase):
    def test_frozen_study_rejects_reduced_seed_or_method_design(self):
        from dmf.chapter2_sim.study import validate_study_spec
        import yaml
        import copy
        spec = yaml.safe_load(Path('configs/chapter2_formal_simulation.yaml').read_text(encoding='utf-8'))['study']
        for field, value in (('formal_seed_count', 1), ('smoke_seeds', [260600]), ('methods', ['C']),
                             ('arrival_coverages', [.85])):
            changed = copy.deepcopy(spec); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_study_spec(changed)

    def test_help_and_materials_check_do_not_construct_hardware(self):
        for args in (['--help'], ['materials-check']):
            result = subprocess.run([sys.executable, 'run_chapter2_formal_simulation.py', *args],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            if args == ['materials-check']:
                self.assertIn('false', result.stdout.lower())
                self.assertIn('unet_model', result.stdout)

    def test_evaluation_rejects_reference_from_different_cache(self):
        from dmf.chapter2_sim.study import evaluate_prediction_file
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            values = dict(prediction=dict(clock_domain='simulation', variant='S4', input_sha256='one', events=[]),
                          references=[], manifest=[dict(trial_id='x', task_id='route', clock_domain='simulation',
                                                       eligible=True, step_ids=[0], input_sha256='other')])
            for name, value in values.items(): (root/f'{name}.json').write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                evaluate_prediction_file(root/'prediction.json', root/'references.json', root/'manifest.json', root/'out.json')

    def test_smoke_gate_rejects_old_frame_updates(self):
        from dmf.chapter2_sim.study import validate_closed_loop_bundle
        from dmf.chapter2_sim.config import SimConfig
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [dict(scenario='normal', seed=23, method='C', action='Update', valid=True,
                         clock_domain='simulation', causality='simulation_exposure_verified',
                         exposure_start_s=.1, applied_s=.5)]
            with (root/'frames.csv').open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            with self.assertRaises(ValueError): validate_closed_loop_bundle(root, SimConfig())

    def test_smoke_gate_binds_resolved_environment_parameters(self):
        from dmf.chapter2_sim.study import run_study, semantic_hashes
        from dmf.chapter2_sim.config import load_config
        import yaml
        path = 'configs/chapter2_formal_simulation.yaml'; cfg = load_config(path)
        study = yaml.safe_load(Path(path).read_text(encoding='utf-8'))['study']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); gate = root/'gate.json'
            gate.write_text(json.dumps(dict(stage='smoke', smoke_gate_passed=True, frozen_study=study,
                                           semantic_source_sha256=semantic_hashes(),
                                           resolved_simulation_config=asdict(cfg), map_input_sha256=None)))
            with patch('dmf.chapter2_sim.formal_batch.run_formal_batch', side_effect=RuntimeError('gate bypassed')):
                with self.assertRaises(ValueError):
                    run_study(replace(cfg, speed=2.), path, 'formal', root/'out', smoke_manifest=gate)

    def test_evaluation_requires_real_hash_and_never_rewrites_clock(self):
        from dmf.chapter2_sim.study import evaluate_prediction_file
        for digest, event_clock in ((None, 'simulation'), ('a'*64, 'host_monotonic')):
            with self.subTest(digest=digest, event_clock=event_clock), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                identity = dict(trial_id='one', task_id='route', clock_domain='simulation', input_sha256=digest)
                refs = [dict(identity, step_id=0, simulation=True, annotation_source='simulation_physics',
                             provenance='independent fixture', status='arrived', observation_start_s=0.,
                             observation_end_s=3., arrival_lower_s=1., arrival_upper_s=1.)]
                values = dict(prediction=dict(clock_domain='simulation', input_sha256=digest, variant='S4',
                                              events=[dict(step_id=0, timestamp_s=2., action='Update', clock_domain=event_clock)]),
                              references=refs, manifest=[dict(identity, eligible=True, step_ids=[0])])
                for name, value in values.items(): (root/f'{name}.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    evaluate_prediction_file(root/'prediction.json', root/'references.json', root/'manifest.json',
                                             root/'out.json', simulation=True)


if __name__ == '__main__': unittest.main()
