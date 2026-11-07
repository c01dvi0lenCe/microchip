import importlib.util
from pathlib import Path
import unittest


class FaultFigureDataTests(unittest.TestCase):
    def api(self):
        path=Path(__file__).resolve().parents[1]/'scripts/plot_geometry_exp2_faults.py'
        self.assertTrue(path.is_file(),'fault plotting data contract missing')
        spec=importlib.util.spec_from_file_location('fault_plot_test',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def test_missing_event_time_stays_na_not_zero(self):
        self.assertIsNone(self.api().event_time(''))
        self.assertEqual(self.api().event_time('0.0'),0.)
    def test_reversed_or_negative_event_time_rejected(self):
        with self.assertRaises(ValueError):self.api().event_time('-1')
    def test_completion_cannot_enter_electrode_transaction_markers(self):
        m=self.api();events=[dict(event='Complete',time_s='1',target='172',action='Complete')]
        self.assertEqual(m.real_markers(events),[])


if __name__=='__main__':unittest.main()
