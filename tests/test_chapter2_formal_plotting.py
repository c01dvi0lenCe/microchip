from pathlib import Path
import tempfile
import unittest

from dmf.chapter2_sim.formal_plotting import render_figures


class FormalPlotTests(unittest.TestCase):
    def test_partial_sensitivity_cannot_claim_full_scan(self):
        from dmf.chapter2_sim.formal_plotting import load_sensitivity_rows
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): load_sensitivity_rows(Path(tmp), list(range(261000,261020)))

    def test_rejects_missing_data_and_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError): render_figures(root/'study', root/'figures')
            (root/'figures').mkdir()
            with self.assertRaises(FileExistsError): render_figures(root/'study', root/'figures')


if __name__ == '__main__': unittest.main()
