import json
from pathlib import Path
import tempfile
import unittest

from dmf.chapter2_sim.config import SimConfig
from dmf.chapter2_sim.fixed_inputs import generate_fixed_input
from dmf.experiment.mask_cache import load_cache


class FixedInputTests(unittest.TestCase):
    def test_repeatable_gt_separate_and_all_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = SimConfig(route=(190, 191), max_time_s=5.)
            a = generate_fixed_input(cfg, 'normal', 23, root/'one')
            b = generate_fixed_input(cfg, 'normal', 23, root/'two')
            self.assertEqual(a['input_sha256'], b['input_sha256'])
            cache = load_cache(root/'one'/'inputs')
            self.assertEqual(len(cache['tasks']), 1)
            self.assertNotIn('truth_radius', json.dumps(json.loads((root/'one'/'inputs'/'manifest.json').read_text())))
            refs = json.loads((root/'one'/'evaluation'/'references.json').read_text())
            self.assertEqual(refs[0]['annotation_source'], 'simulation_physics')
            self.assertEqual(refs[0]['status'], 'arrived')
            self.assertLess(refs[0]['arrival_lower_s'], refs[0]['arrival_upper_s'])


if __name__ == '__main__': unittest.main()
