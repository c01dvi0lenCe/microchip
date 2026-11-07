import unittest
import numpy as np

try:
    from scripts import chapter2_paper_figure_closeout as p
except ImportError:
    p=None

class PaperFigureDataTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(p,'new read-only figure module missing')

    def test_zero_reference_is_na_not_zero(self):
        r=dict(reference_arrivals='0',supported_confirmations='0',premature_confirmations='0',unsupported_confirmations='17',planned_steps='20')
        self.assertTrue(np.isnan(p.s2_cell(r)[0]));self.assertEqual(p.s2_cell(r)[2],('NA','0/17'))

    def test_exact_denominators_and_error_counts(self):
        r=dict(reference_arrivals='20',supported_confirmations='5',premature_confirmations='2',unsupported_confirmations='3',planned_steps='20')
        self.assertEqual(p.s2_cell(r),(.25,.25,('5/20','2/3')))

    def test_observed_series_breaks_at_missing_id_epoch_and_missing_value(self):
        rows=[dict(frame_id=str(i),step='0',epoch='1',processing_s=str(i*.1),x=str(i)) for i in (0,1,3)]
        rows.append(dict(frame_id='4',step='0',epoch='2',processing_s='.4',x='4'))
        rows.append(dict(frame_id='5',step='0',epoch='2',processing_s='',x=''))
        x,y=p.observed_series(rows,'x')
        self.assertEqual(sum(np.isnan(y)),3);self.assertEqual(list(y[~np.isnan(y)]),[0.,1.,3.,4.])

    def test_frozen_interval_is_not_recalculated(self):
        self.assertEqual(p.interval_values(dict(mean='.6',ci_low='.3866',ci_high='.7812')),(.6,.3866,.7812))

    def test_reversed_interval_is_rejected(self):
        with self.assertRaises(ValueError):p.interval_values(dict(mean='.6',ci_low='.8',ci_high='.9'))

    def test_seven_scenarios_and_twenty_planned_each_required(self):
        rs=[dict(cohort='main',scenario=s,method=m,planned_trials='20') for s in p.SCENARIOS for m in p.METHODS]
        self.assertEqual(len(p.validate_summary(rs)),28)
        rs[0]['planned_trials']='19'
        with self.assertRaises(ValueError):p.validate_summary(rs)

    def test_trial_selection_rejects_mixed_seed_or_missing_strategy(self):
        rs=[dict(cohort='main',scenario='deviation',method=m,seed='265000') for m in p.METHODS]
        self.assertEqual([r['method'] for r in p.select_trials(rs)],list(p.METHODS))
        rs.pop()
        with self.assertRaises(ValueError):p.select_trials(rs)

    def test_font_and_width_contract(self):
        self.assertEqual(p.WIDTH_MM,160);self.assertGreaterEqual(p.MIN_PT,8.5)

if __name__=='__main__':unittest.main()
