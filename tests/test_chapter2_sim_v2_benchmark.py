from dataclasses import replace
import inspect
import tempfile
from pathlib import Path
import unittest

from dmf.chapter2_sim.v2.spec import StudySpecV2,FactorFlags
from dmf.chapter2_sim.geometry import SimulationMap

try:
    from dmf.chapter2_sim.v2.benchmark import run_arrival_variant
    from dmf.chapter2_sim.v2.probes import build_probe_case,write_probe_cache,run_probe_matrix
except ImportError:
    run_arrival_variant=None


class BenchmarkV2Tests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(run_arrival_variant,'v2 benchmark missing')
        self.spec=StudySpecV2();self.geometry=SimulationMap(self.spec.environment)

    def test_interface_cannot_accept_gt(self):
        self.assertFalse(any('truth' in k or 'reference' in k for k in inspect.signature(run_arrival_variant).parameters))

    def test_clean_shared_cache_same_arrival(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_probe_cache(root/'inputs','stable',self.spec)
            b=run_arrival_variant(root/'inputs','BTQ',root/'btq',self.spec)
            f=run_arrival_variant(root/'inputs','F',root/'f',self.spec)
            self.assertEqual(b['input_sha256'],f['input_sha256'])
            self.assertEqual(b['events'],f['events'])
            self.assertEqual(len(f['events']),1)

    def test_q_w_k_s_each_have_isolated_positive_probe(self):
        records=run_probe_matrix(self.spec)
        for flag,case in [('S','spatial_tail'),('W','transient'),('K','motion_jump'),('Q','low_confidence')]:
            full=next(r for r in records if r['case']==case and r['flags']==dict(S=True,W=True,K=True,Q=True))
            removed=next(r for r in records if r['case']==case and r['flags']=={f:(f!=flag) for f in 'SWKQ'})
            self.assertEqual(full['arrival_events'],0,(flag,full))
            self.assertEqual(removed['arrival_events'],1,(flag,removed))
        self.assertTrue(all(r['raw_invariant'] for r in records))

    def test_target_tail_geometry_hand_counted(self):
        from dmf.chapter2_sim.v2.adapter import ResearchAdapter
        a=ResearchAdapter(self.spec,self.geometry,'F');a.begin_transport(.04)
        f=build_probe_case('spatial_tail',self.spec,self.geometry)[0];a.observe(f,f.available_s)
        raw=a.last_trace['raw']
        self.assertEqual(raw['area_px'],105)
        self.assertAlmostEqual(raw['eta_target'],90/105)
        self.assertEqual(raw['eta_source'],0.)
        self.assertTrue(raw['Q']);self.assertTrue(raw['K']);self.assertFalse(raw['S_position'])

    def test_reference_files_cannot_change_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_probe_cache(root/'inputs','stable',self.spec)
            (root/'evaluation').mkdir();(root/'evaluation'/'references.json').write_text('[]')
            a=run_arrival_variant(root/'inputs','F',root/'a',self.spec)
            (root/'evaluation'/'references.json').write_text('[{"not_read":true}]')
            b=run_arrival_variant(root/'inputs','F',root/'b',self.spec)
            self.assertEqual(a,b)


if __name__=='__main__':unittest.main()
