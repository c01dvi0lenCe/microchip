import json
import tempfile
import unittest
from pathlib import Path

try:
    from dmf.chapter2_sim.s2.plotting import load_figure_data
except ModuleNotFoundError:
    load_figure_data=None


class S2PlotDataTests(unittest.TestCase):
    def test_figure_loads_only_persisted_method_events(self):
        self.assertIsNotNone(load_figure_data,'read-only S2 figure loader missing')
        from dmf.chapter2_sim.s2.spec import StudySpecS2,METHODS
        from dmf.chapter2_sim.s2.benchmark import predict_arrivals
        from dmf.chapter2_sim.v2.probes import write_probe_cache
        spec=StudySpecS2()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache_id='hand_fixture'
            cache=root/'inputs'/cache_id;write_probe_cache(cache,'stable',spec.common)
            expected={}
            for method in METHODS:
                out=root/'predictions'/cache_id/method
                expected[method]=predict_arrivals(cache,method,out,spec)['events']
            ref=root/'scoring_side'/cache_id;ref.mkdir(parents=True)
            (ref/'references.json').write_text(json.dumps([dict(status='arrived',lower_s=.2,upper_s=.21)]))
            data=load_figure_data(root,cache_id)
            self.assertEqual(data['events'],expected)
            self.assertEqual(data['reference']['upper_s'],.21)
            self.assertEqual(len(data['traces']),5)
            self.assertEqual(data['task']['target'],191)


if __name__=='__main__':unittest.main()
