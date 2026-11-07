import importlib.util
from pathlib import Path
import unittest


class FormalFigureTests(unittest.TestCase):
    def test_stat_figure_retains_all_conditions_and_missing_reference(self):
        script=Path(__file__).resolve().parents[1]/'scripts/chapter2_s2_formal_figures.py'
        self.assertTrue(script.exists(),'formal S2-B read-only renderer missing')
        spec=importlib.util.spec_from_file_location('s2figure',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from dmf.chapter2_sim.s2.spec import CONDITIONS,METHODS
        rows=[dict(condition=c,method=m,planned_steps='20',reference_arrivals='0',
            supported_confirmations='0',missed_supported_confirmation='0',
            premature_confirmations='0',unsupported_confirmations='0') for c in CONDITIONS for m in METHODS]
        data=module.figure_matrices(rows)
        self.assertEqual(data['support'].shape,(13,5))
        self.assertTrue(module.np.isnan(data['support']).all())
        self.assertEqual(data['errors'].sum(),0)
        with self.assertRaises(ValueError):module.figure_matrices(rows[:-1])


if __name__=='__main__':unittest.main()
