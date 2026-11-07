import importlib
import unittest


def api():
    try:return importlib.import_module('scripts.plot_geometry_exp2_mechanisms')
    except ModuleNotFoundError:raise AssertionError('exp2 saved-data plotting contract is missing') from None


class Exp2PlotContractTests(unittest.TestCase):
    def test_complete_does_not_become_fake_applied_marker(self):
        rows=[dict(event='request',action='Start',time_s='0.5',target='191',request_id='1'),
              dict(event='simulated_applied',action='Start',time_s='0.54',target='191',request_id='1'),
              dict(event='Complete',action='Complete',time_s='8.0',target='172',request_id='')]
        values=api().transaction_markers(rows)
        self.assertEqual([(v['kind'],v['time_s']) for v in values],[('request',.5),('applied',.54)])

    def test_applied_without_matching_request_is_rejected(self):
        with self.assertRaises(ValueError):
            api().transaction_markers([dict(event='simulated_applied',action='Update',time_s='1',target='192',request_id='x')])

    def test_three_plan_steps_remain_even_if_unattempted(self):
        rows=[dict(step=str(i),attempted='False') for i in range(3)]
        self.assertEqual(len(api().validate_steps(rows)),3)
        with self.assertRaises(ValueError):api().validate_steps(rows[:2])
