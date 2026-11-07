import importlib.util
import ast
from pathlib import Path
import unittest


class CloseoutTests(unittest.TestCase):
    def module(self):
        path=Path(__file__).resolve().parents[1]/'scripts/chapter2_s2_closeout.py'
        self.assertTrue(path.exists(),'read-only closeout renderer missing')
        spec=importlib.util.spec_from_file_location('closeout',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_fixed_representatives_and_all_thirteen_conditions(self):
        m=self.module()
        self.assertEqual(m.MAIN,('A_normal','C_jump_short','D_tail_false','C_jump_persistent','F_jitter','F_dropout'))
        from dmf.chapter2_sim.s2.spec import CONDITIONS,METHODS
        rows=[dict(condition=c,method=k,planned_steps='20',reference_arrivals='0',
            supported_confirmations='0',missed_supported_confirmation='0',late_supported_confirmations='0',
            premature_confirmations='0',unsupported_confirmations='0') for c in CONDITIONS for k in METHODS]
        matrices=m.matrices(rows)
        self.assertEqual(len(matrices['support']),6)
        self.assertEqual(len(matrices['all_rows']),65)
        self.assertTrue(m.np.isnan(matrices['support']).all())
        with self.assertRaises(ValueError):m.matrices(rows[:-1])

    def test_late_is_not_subtracted_from_main_misses(self):
        m=self.module()
        self.assertEqual(m.failure_counts(dict(reference_arrivals='20',missed_supported_confirmation='15',late_supported_confirmations='10')),(15,10,20))

    def test_no_model_prediction_or_scoring_imports(self):
        m=self.module();tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                self.assertNotRegex(node.module or '',r'(world|runner|benchmark|evaluation|confirmatory|statistics)$')


if __name__=='__main__':unittest.main()
