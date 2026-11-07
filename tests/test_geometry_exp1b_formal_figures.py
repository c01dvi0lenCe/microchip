"""Plot input contracts with in-memory identities only, not research results."""
import importlib.util
from pathlib import Path
import unittest


class FormalFigureContractTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'scripts/plot_geometry_exp1b_formal.py'
        self.assertTrue(path.exists(),'formal figure source is required')
        spec=importlib.util.spec_from_file_location('formal_figure_source',path)
        self.p=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.p)

    def test_all_twenty_condition_strata_are_preserved(self):
        groups=self.p.display_groups()
        self.assertEqual(len(groups),20)
        self.assertEqual(len({(r['condition'],r['stratum']) for r in groups}),20)
        self.assertEqual(sum(r['n']==20 for r in groups),4)
        self.assertEqual(sum(r['n']==10 for r in groups),16)

    def test_primary_missing_duplicate_and_wrong_stratum_rejected(self):
        rows=[]
        for seed in range(266000,266020):
            for cid in self.p.CONDITIONS:
                for method in self.p.ALL_METHODS:
                    rows.append(dict(seed=str(seed),condition=cid,method=method,reference_id='R0',
                        stratum='base' if cid in ('N','V','P','T') else 'low' if seed<266010 else 'high'))
        self.p.validate_primary(rows)
        for bad in [rows[:-1],rows[:-1]+[rows[0]], [dict(rows[0],stratum='high')]+rows[1:]]:
            with self.assertRaises(ValueError):self.p.validate_primary(bad)

    def test_unknown_interval_uses_identification_not_fake_ci(self):
        row=dict(ci_lower='',ci_upper='',ident_lower='.2',ident_upper='.7',estimate='.2')
        self.assertEqual(self.p.interval(row),(.2,.7,True))
        self.assertEqual(self.p.interval(dict(row,ci_lower='.1',ci_upper='.8')),(.1,.8,False))

    def test_joint_times_do_not_substitute_unpaired_samples(self):
        self.assertTrue(hasattr(self.p,'joint_times'),'joint-supported timing reader is required')
        self.assertEqual(self.p.joint_times(dict(n_joint='2',raw_differences_json='[0.1,0.2]')),[.1,.2])
        self.assertEqual(self.p.joint_times(dict(n_joint='0',raw_differences_json='[]')),[])
        with self.assertRaises(ValueError):
            self.p.joint_times(dict(n_joint='1',raw_differences_json='[0.1,0.2]'))


if __name__=='__main__':unittest.main()
