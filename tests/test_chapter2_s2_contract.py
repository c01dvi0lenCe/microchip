import inspect
import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import asdict
from pathlib import Path

try:
    from dmf.chapter2_sim.s2.spec import METHODS, DIAGNOSTICS, StudySpecS2, flags_for
    from dmf.chapter2_sim.s2.benchmark import predict_arrivals
    READY = True
except ModuleNotFoundError:
    READY = False


class S2ContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(READY, 'S2 isolated spec/benchmark is not implemented')

    def test_five_primary_methods_and_separate_bq(self):
        self.assertEqual(METHODS, ('B_single_frame','BTQ','BTQ+S','BTQ+K','F_arrival'))
        self.assertEqual(DIAGNOSTICS, ('BQ_single_frame',))
        self.assertEqual(asdict(flags_for('BQ_single_frame', diagnostic=True)),
                         dict(S=False,W=False,K=False,Q=True))
        with self.assertRaises(ValueError): flags_for('BQ_single_frame')

    def test_strong_methods_change_only_s_k(self):
        expected = {'BTQ':(False,False),'BTQ+S':(True,False),
                    'BTQ+K':(False,True),'F_arrival':(True,True)}
        spec = StudySpecS2()
        for method,(s,k) in expected.items():
            flags=flags_for(method)
            self.assertEqual((flags.S,flags.K,flags.W,flags.Q),(s,k,True,True))
            self.assertEqual(spec.shared_contract(method),spec.shared_contract('BTQ'))

    def test_confirmatory_seed_is_rejected(self):
        StudySpecS2().validate_seed(262000)
        with self.assertRaises(ValueError): StudySpecS2().validate_seed(263000)

    def test_prediction_api_has_no_scoring_or_scenario_argument(self):
        self.assertEqual(tuple(inspect.signature(predict_arrivals).parameters),
                         ('cache_root','method','output_root','spec','diagnostic'))

    def test_old_methods_are_not_renamed(self):
        for name in ('S1','S2','S3','S4','F','C_formal'):
            with self.assertRaises(ValueError): flags_for(name)

    def test_five_methods_share_cache_and_raw_features(self):
        from dmf.chapter2_sim.s2.inputs import generate_base,freeze_input
        spec=StudySpecS2();base=generate_base(spec,262000,'normal')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=freeze_input(base,base['observations']['normal'],root/'inputs',spec)
            raw=[];reports=[]
            for method in METHODS:
                out=root/method
                reports.append(predict_arrivals(root/'inputs',method,out,spec))
                with (out/'gate_trace.csv').open(encoding='utf-8') as handle:
                    rows=list(csv.DictReader(handle))
                raw.append([(r['frame_id'],r.get('raw','')) for r in rows])
            self.assertTrue(all(r['input_sha256']==cache['input_sha256'] for r in reports))
            self.assertTrue(all(r==raw[0] for r in raw))
            self.assertEqual(reports[1]['events'],reports[4]['events'])
            self.assertLessEqual(len(reports[4]['events']),1)

    def test_reference_replacement_does_not_change_prediction(self):
        from dmf.chapter2_sim.s2.inputs import generate_base,freeze_input
        spec=StudySpecS2();base=generate_base(spec,262000,'normal')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);freeze_input(base,base['observations']['normal'],root/'inputs',spec)
            ref=root/'reference.json';ref.write_text('[]')
            a=predict_arrivals(root/'inputs','F_arrival',root/'a',spec)
            ref.write_text('[{"changed_reference":true}]')
            b=predict_arrivals(root/'inputs','F_arrival',root/'b',spec)
            self.assertEqual(a,b)

    def test_study_cli_has_no_formal_entry(self):
        try:
            from dmf.chapter2_sim.s2.study import run_development
        except ImportError:
            run_development=None
        self.assertIsNotNone(run_development,'development study is not implemented')

    def test_one_cache_smoke_retains_five_planned_steps(self):
        from dmf.chapter2_sim.s2.study import run_development
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'study'
            report=run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,))
            self.assertEqual(report['planned_method_steps'],5)
            self.assertEqual(report['input_caches'],1)
            self.assertEqual(report['primary_prediction_runs'],5)
            self.assertEqual(report['formal_seed_runs'],0)
            self.assertTrue(report['raw_features_invariant'])
            with (out/'step_scores.csv').open(encoding='utf-8') as handle:
                scores=list(csv.DictReader(handle))
            self.assertEqual(len(scores),5)
            self.assertTrue(all(int(r['planned_steps'])==1 for r in scores))

    def test_prediction_failure_keeps_independent_reference_denominator(self):
        from dmf.chapter2_sim.s2.study import run_development
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'study'
            with patch('dmf.chapter2_sim.s2.study.predict_arrivals',side_effect=RuntimeError('injected prediction failure')):
                report=run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,))
            with (out/'step_scores.csv').open(encoding='utf-8') as handle:
                scores=list(csv.DictReader(handle))
            self.assertEqual(len(scores),5)
            self.assertTrue(all(r.get('reference_arrivals')=='1' for r in scores))
            self.assertTrue(all(r['infrastructure_unknown']=='1' for r in scores))
            self.assertTrue(all(r.get('reference_status')=='arrived' for r in scores))

    def test_base_failure_still_writes_all_planned_rows_as_unknown(self):
        from dmf.chapter2_sim.s2.study import run_development
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'study'
            with patch('dmf.chapter2_sim.s2.study.generate_base',side_effect=RuntimeError('injected world failure')):
                run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,))
            with (out/'step_scores.csv').open(encoding='utf-8') as handle:
                scores=list(csv.DictReader(handle))
            self.assertEqual(len(scores),5)
            self.assertTrue(all(r['reference_right_censored']=='1' for r in scores))
            self.assertTrue(all(r['infrastructure_unknown']=='1' for r in scores))

    def test_audit_rejects_incomplete_cache_identity_ledger(self):
        from dmf.chapter2_sim.s2.study import run_development,audit_development
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'study'
            run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,))
            (out/'input_identity_audit.json').write_text('[]')
            with self.assertRaises(ValueError):audit_development(out)

    def test_audit_rejects_duplicate_score_identity_with_same_method_set(self):
        from dmf.chapter2_sim.s2.study import run_development,audit_development
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'study'
            run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,262001))
            p=out/'step_scores.csv'
            with p.open(encoding='utf-8',newline='') as handle:
                reader=csv.DictReader(handle);fields=reader.fieldnames;rows=list(reader)
            rows[-1]=dict(rows[4])
            with p.open('w',encoding='utf-8',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            with self.assertRaises(ValueError):audit_development(out)

    def test_audit_rejects_missing_summary_groups(self):
        from dmf.chapter2_sim.s2.study import run_development,audit_development
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'study'
            run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,))
            p=out/'development_summary.csv'
            p.write_text(p.read_text(encoding='utf-8').splitlines()[0]+'\n',encoding='utf-8')
            with self.assertRaises(ValueError):audit_development(out)


if __name__ == '__main__': unittest.main()
