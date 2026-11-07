import ast
from pathlib import Path
import unittest

try:
    from scripts import chapter2_s1_core_figures as core
except ImportError:
    core = None


TRIAL = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1/development_smoke_r2/trials/end_to_end__normal__262000__F')


class S1CoreFigureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(core, 'independent read-only S1 figure module missing')
        self.r = core.load_plot_source(TRIAL)

    def test_six_times_and_original_states(self):
        rows = core.s1_panels(self.r)
        self.assertEqual([x['time_s'] for x in rows], [.50, .81, 1.06, 1.46, 1.92, 1.96])
        self.assertEqual([x['state'] for x in rows], ['Moving', 'Moving', 'Partial', 'Unknown', 'Arrived', 'Unknown'])
        self.assertEqual(rows[0]['action'], 'Start')

    def test_phase_boundaries_use_actual_applied_not_request(self):
        phases = core.phase_intervals(self.r)
        self.assertEqual([(x['source'], x['target']) for x in phases], [(190,191),(191,192),(192,172)])
        self.assertEqual([round(x['start_s'], 2) for x in phases], [.54,1.96,3.05])
        self.assertEqual([round(x['end_s'], 2) for x in phases], [1.96,3.05,4.11])

    def test_route_polygons_are_frozen_and_neighbouring(self):
        route, polygons = core.route_geometry(self.r)
        self.assertEqual(route, [190,191,192,172])
        self.assertEqual(set(polygons), set(route))
        self.assertEqual(polygons[172], self.r.geometry['polygons']['172'])

    def test_applied_tick_does_not_use_previous_task_mask(self):
        last = core.s1_panels(self.r)[-1]
        self.assertEqual(last['frame_id'],38)
        s = self.r.snapshot(last['time_s'])
        self.assertIsNone(s['overlay_mask'])
        self.assertEqual(s['frame']['reason'],'TASK_EPOCH_MISMATCH')
        self.assertEqual(s['truth']['world_active'],191)
        self.assertEqual(s['truth']['target'],192)

    def test_spatial_values_are_recorded_transport_only(self):
        rows = core.spatial_segments(self.r.frames, 'distance_pitch')
        actual = {f['frame_id']:f for f in self.r.frames}
        points = [p for segment in rows for p in segment]
        self.assertEqual(len(points),65)
        for p in points:
            f = actual[p['frame_id']]
            self.assertEqual(p['value'],f['distance_pitch'])
            self.assertEqual(p['time_s'],f['processing_s'])
            self.assertEqual(f['phase'],'transport')

    def test_gap_missing_and_epoch_do_not_connect(self):
        base=dict(phase='transport',step=0,epoch=1,processing_s=.1,distance_pitch=.9,frame_id=1)
        rows=[base,dict(base,frame_id=2,processing_s=.2,distance_pitch=None),
              dict(base,frame_id=3,processing_s=.3,distance_pitch=.8),
              dict(base,frame_id=5,processing_s=.4,distance_pitch=.7),
              dict(base,frame_id=6,processing_s=.5,epoch=2,step=1,distance_pitch=.6)]
        self.assertEqual([len(x) for x in core.spatial_segments(rows,'distance_pitch')],[1,1,1,1])

    def test_missing_optional_field_is_not_synthesized(self):
        row=dict(phase='transport',step=0,epoch=1,processing_s=.1,frame_id=1)
        self.assertEqual(core.spatial_segments([row],'distance_pitch'),[])

    def test_no_model_or_recognizer_execution_calls(self):
        tree=ast.parse(Path(core.__file__).read_text(encoding='utf-8'))
        forbidden={'run_trial_v2','run_formal_trial','DropletWorld','SyntheticCamera','StateRecognizer','run_arrival_variant'}
        names={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertFalse(names & forbidden)


if __name__=='__main__':unittest.main()
