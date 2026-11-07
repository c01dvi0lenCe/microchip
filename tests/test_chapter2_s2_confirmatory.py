import importlib
import csv
import json
import tempfile
import unittest
from pathlib import Path
from dmf.chapter2_sim.s2.spec import StudySpecS2


class ConfirmatoryTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('dmf.chapter2_sim.s2.confirmatory')
        except ModuleNotFoundError:
            self.fail('separate sealed confirmatory entry is missing')

    def test_formal_and_development_seeds_are_disjoint(self):
        api=self.api(); spec=api.ConfirmatorySpecS2()
        for seed in (263000,263019):spec.validate_seed(seed)
        for seed in (262000,263020,True):
            with self.assertRaises(ValueError):spec.validate_seed(seed)
        with self.assertRaises(ValueError):StudySpecS2().validate_seed(263000)
        self.assertEqual(spec.shared_contract('BTQ'),StudySpecS2().shared_contract('BTQ'))

    def test_config_seal_rejects_tampering(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); config=root/'config.yaml'
            config.write_text(api.CONFIG_TEXT,encoding='utf-8')
            seal=root/'freeze'; api.freeze(config,seal)
            self.assertEqual(api.verify_seal(config,seal)['study_phase'],'confirmatory')
            config.write_text(api.CONFIG_TEXT+'\n# changed',encoding='utf-8')
            with self.assertRaises(ValueError):api.verify_seal(config,seal)

    def test_stages_cannot_be_silently_relabelled(self):
        api=self.api()
        from dmf.chapter2_sim.s2.study import run_development
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):run_development(Path(temp)/'wrong',api.ConfirmatorySpecS2())
            with self.assertRaises(ValueError):api.run_confirmatory(Path(temp)/'wrong',StudySpecS2())

    def test_figure_phase_follows_persisted_run_not_caller_label(self):
        from dmf.chapter2_sim.s2 import plotting
        self.assertTrue(hasattr(plotting,'figure_phase'),'formal plotting contract missing')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'run_report.json'
            path.write_text('{"study_phase":"confirmatory"}',encoding='utf-8')
            self.assertEqual(plotting.figure_phase(temp),'confirmatory')

    def test_independent_audit_detects_raw_history_tampering(self):
        from dmf.chapter2_sim.s2.study import run_development,audit_development
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'study'
            run_development(out,StudySpecS2(),conditions=('A_normal',),seeds=(262000,))
            audit_development(out)
            path=out/'predictions/A_normal_262000/F_arrival/gate_trace.csv'
            with path.open(encoding='utf-8',newline='') as handle:
                reader=csv.DictReader(handle);fields=reader.fieldnames;rows=list(reader)
            row=next(r for r in rows if r.get('raw'));raw=json.loads(row['raw'])
            raw['K']=not raw['K'];row['raw']=json.dumps(raw)
            with path.open('w',encoding='utf-8',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            with self.assertRaises(ValueError):audit_development(out)


class StatisticsTests(unittest.TestCase):
    def api(self):
        try:return importlib.import_module('dmf.chapter2_sim.s2.statistics')
        except ModuleNotFoundError:self.fail('paired S2 statistics missing')

    def row(self,seed,method,reference=1,support=0,latency=None):
        return dict(condition='A_normal',seed=seed,method=method,planned_steps=1,
            reference_arrivals=reference,supported_confirmations=support,
            latency_lower_s=latency,latency_upper_s=latency)

    def test_zero_event_interval_and_no_reference_na(self):
        api=self.api();rows=[self.row(s,'BTQ',reference=0) for s in range(20)]
        result=api.summarize_group(rows)
        self.assertIsNone(result['S_H_yield'])
        self.assertEqual(result['planned_steps'],20)
        self.assertGreater(result['unsupported_rate_hi'],0.)

    def test_paired_complete_denominator_and_conditional_latency(self):
        api=self.api(); rows=[]
        for seed in range(3):
            rows.extend([self.row(seed,'BTQ',support=1,latency=.4),
                self.row(seed,'F_arrival',support=int(seed!=2),latency=.2 if seed!=2 else None)])
        result=api.paired_contrast(rows,'BTQ','F_arrival',repeats=100)
        self.assertEqual(result['paired_planned_n'],3)
        self.assertEqual(result['dual_supported_n'],2)
        self.assertAlmostEqual(result['support_difference'],-1/3)
        self.assertAlmostEqual(result['latency_difference_s'],-.2)
        with self.assertRaises(ValueError):api.paired_contrast(rows+[rows[0]],'BTQ','F_arrival')
        with self.assertRaises(ValueError):api.paired_contrast(rows[:-1],'BTQ','F_arrival')


if __name__=='__main__':unittest.main()
