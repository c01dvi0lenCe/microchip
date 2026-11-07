"""Deterministic geometry scaffolding tests; no measured droplet results."""
import json
import math
from pathlib import Path
import tempfile
import unittest

MAP = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1/electrode_design_map.json')


class GeometrySimulationTests(unittest.TestCase):
    def geometry(self):
        from dmf.chapter2_geometry_sim.model import DesignGeometry
        return DesignGeometry(MAP)

    def test_load_preserves_all_vertices_and_ids(self):
        g = self.geometry()
        raw = json.loads(MAP.read_text(encoding='utf-8'))
        self.assertEqual(set(g.polygons), set(range(1,421)))
        self.assertEqual(g.pitch_mm,3.2)
        for e in raw['electrodes']:
            self.assertEqual(list(g.polygons[e['control_id']].exterior.coords)[:-1],
                             [tuple(p) for p in e['polygon_map_mm']])

    def test_diameter_is_not_area(self):
        from dmf.chapter2_geometry_sim.model import DemoConfig, footprint
        c=DemoConfig()
        self.assertEqual(c.diameter_mm,3.8)
        self.assertEqual(c.spacer_height_mm,.8)
        self.assertAlmostEqual(footprint((0,0),3.8).area,math.pi*1.9**2,places=3)

    def test_map_pitch_is_not_silently_rescaled_from_memory(self):
        g=self.geometry()
        self.assertAlmostEqual(math.dist(g.center(190),g.center(191)),3.2,places=5)
        self.assertAlmostEqual(g.polygons[190].bounds[2]-g.polygons[190].bounds[0],3.47985,places=5)

    def test_large_drop_overlaps_neighbor_but_small_one_does_not(self):
        from dmf.chapter2_geometry_sim.model import footprint
        g=self.geometry()
        self.assertGreater(footprint(g.center(190),3.8).intersection(g.polygons[191]).area,.3)
        self.assertEqual(footprint(g.center(190),1).intersection(g.polygons[191]).area,0)

    def test_coverage_uses_droplet_denominator_not_electrode(self):
        from dmf.chapter2_geometry_sim.model import coverage_at
        g=self.geometry()
        row=coverage_at(g,3.8,190,191)
        self.assertAlmostEqual(row['eta_target'],.82963,places=4)
        self.assertAlmostEqual(row['rho_target'],.94736,places=4)
        self.assertFalse(row['old_G_eligible'])

    def test_configuration_rejects_nonfinite_or_negative(self):
        from dmf.chapter2_geometry_sim.model import DemoConfig
        for kw in ({'diameter_mm':0},{'spacer_height_mm':float('nan')},{'speed_mm_s':-1},{'camera_fps':0}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                DemoConfig(**kw)

    def test_no_motion_before_applied_and_response(self):
        from dmf.chapter2_geometry_sim.model import DemoConfig, GeometryWorld
        g=self.geometry(); c=DemoConfig(); w=GeometryWorld(g,c)
        start=w.position.copy(); w.request(191,0)
        w.advance(.2)
        self.assertEqual(w.position.tolist(),start.tolist())
        w.advance(.5)
        self.assertGreater(w.position[0],start[0])
        self.assertLessEqual(math.dist(w.position,start),c.speed_mm_s*.5)

    def test_zero_overlap_blocks_translation(self):
        from dmf.chapter2_geometry_sim.model import DemoConfig, GeometryWorld
        g=self.geometry(); w=GeometryWorld(g,DemoConfig(diameter_mm=1))
        start=w.position.copy(); w.request(191,0); w.advance(1)
        self.assertEqual(w.position.tolist(),start.tolist())
        self.assertEqual(w.status,'blocked_no_overlap')

    def test_pending_transaction_rejects_second_request(self):
        from dmf.chapter2_geometry_sim.model import DemoConfig, GeometryWorld
        w=GeometryWorld(self.geometry(),DemoConfig()); w.request(191,0)
        with self.assertRaisesRegex(ValueError,'pending'):
            w.request(192,0)

    def test_same_target_retry_does_not_reset_response(self):
        from dmf.chapter2_geometry_sim.model import DemoConfig, GeometryWorld
        w=GeometryWorld(self.geometry(),DemoConfig()); w.request(191,0); w.advance(.1)
        response=w.response_at_s; segment=w.activation_segment
        w.request(191,.1); w.advance(.15)
        self.assertEqual(w.response_at_s,response)
        self.assertEqual(w.activation_segment,segment)

if __name__=='__main__':
    unittest.main()
