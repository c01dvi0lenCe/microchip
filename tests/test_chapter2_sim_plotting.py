"""Minimal render smoke; figures must remain labelled synthetic simulation."""
import importlib
import hashlib
import json
import tempfile
from pathlib import Path
import unittest


class SimulationPlotTests(unittest.TestCase):
    def test_cli_and_plotting_export_real_files(self):
        try:
            plotting = importlib.import_module('dmf.chapter2_sim.plotting')
        except ModuleNotFoundError:
            self.fail('simulation figure exporter not implemented')
        from dmf.chapter2_sim.config import SimConfig
        from dmf.chapter2_sim.runner import run_trial
        from dmf.chapter2_sim.batch import summarize_trials
        config = SimConfig()
        results = [run_trial(config, 'normal', 1, m) for m in 'ABC']
        summary = summarize_trials([r.metrics for r in results], bootstrap_repeats=20)
        with tempfile.TemporaryDirectory() as temp:
            paths = plotting.plot_results(config, results, summary, [], Path(temp))
            self.assertTrue(paths)
            self.assertTrue(all(p.exists() for p in paths))
            self.assertTrue(any(p.suffix == '.pdf' for p in paths))
            self.assertIn('simulation', (Path(temp)/'figure_notes.md').read_text().lower())
            manifest = json.loads((Path(temp)/'figure_manifest.json').read_text())
            self.assertTrue(manifest['simulation'])
            self.assertEqual(manifest['plotting_source_sha256'],
                             hashlib.sha256(Path(plotting.__file__).read_bytes()).hexdigest())
            for name, digest in manifest['output_sha256'].items():
                self.assertEqual(hashlib.sha256((Path(temp)/name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
