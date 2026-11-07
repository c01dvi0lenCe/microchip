"""Software fixtures for the approved one-step demonstration, not formal trials."""
import csv
import dataclasses
import json
import math
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
MAP=BASE/'电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1/electrode_design_map.json'
MASK=BASE/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot/masks/sample_0002.png'


class SingleStepMechanismTests(unittest.TestCase):
    def inputs(self,**kwargs):
        from dmf.chapter2_geometry_sim.model import DesignGeometry
        from dmf.chapter2_geometry_sim.footprint import AreaFootprint
        from dmf.chapter2_geometry_sim.single_step import SingleStepConfig
        return DesignGeometry(MAP),AreaFootprint.from_mask(MASK,4.),SingleStepConfig(**kwargs)

    def test_template_retains_hash_and_exact_equivalent_area(self):
        _,shape,_=self.inputs()
        self.assertEqual(len(shape.source_sha256),64)
        self.assertAlmostEqual(shape.polygon((0,0),1).area,4*math.pi,places=9)
        self.assertAlmostEqual(shape.polygon((3,2),1.55).area,4*math.pi,places=9)

    def test_template_rejects_extra_components_and_holes(self):
        from dmf.chapter2_geometry_sim.footprint import AreaFootprint
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'mask.png'
            for hole in (False,True):
                a=np.zeros((40,40),np.uint8);a[5:30,5:30]=255
                if hole:a[15:20,15:20]=0
                else:a[35:37,35:37]=255
                p.write_bytes(cv2.imencode('.png',a)[1].tobytes())
                with self.assertRaises(ValueError): AreaFootprint.from_mask(p,4.)

    def test_applied_at_exact_boundary_and_no_early_motion(self):
        from dmf.chapter2_geometry_sim.single_world import DeformingWorld
        g,s,c=self.inputs();w=DeformingWorld(g,s,c)
        w.advance(.5);w.request(191);w.advance(.54)
        self.assertEqual(w.active,191)
        self.assertAlmostEqual(w.response_at_s,.72)
        w.advance(.72)
        np.testing.assert_allclose(w.position,g.center(190),atol=1e-10)
        w.advance(.73)
        self.assertGreater(w.position[0],g.center(190)[0])

    def test_shape_smoothly_stretches_and_relaxes_without_area_change(self):
        from dmf.chapter2_geometry_sim.single_world import DeformingWorld
        g,s,c=self.inputs();w=DeformingWorld(g,s,c)
        w.advance(.5);w.request(191)
        stretch=[]
        for t in np.arange(.51,2.81,.01):
            w.advance(float(t));stretch.append(w.stretch)
            self.assertAlmostEqual(w.polygon.area,4*math.pi,places=8)
        self.assertGreater(max(stretch),1.3)
        self.assertLess(abs(w.stretch-1),1e-4)
        self.assertLess(max(abs(np.diff(stretch))),.06)

    def test_default_is_noiseless_smooth_minimum_jerk_motion(self):
        from dmf.chapter2_geometry_sim.single_world import DeformingWorld
        g,s,c=self.inputs()
        self.assertEqual(c.position_noise_mm,0.)
        w=DeformingWorld(g,s,c);w.advance(.5);w.request(191)
        samples=[]
        for t in np.arange(.51,2.51,.01):
            w.advance(float(t));samples.append(w.speed_mm_s)
        positive=[v for v in samples if v>1e-8]
        self.assertLess(positive[0],.1)
        self.assertLess(positive[-1],.1)
        self.assertLessEqual(max(samples),4.8+1e-8)
        self.assertGreater(max(samples),4.7)

    def test_static_five_positions_are_adjacent_and_endpoint_gate_is_feasible(self):
        from dmf.chapter2_geometry_sim.preflight import static_geometry
        g,s,_=self.inputs();r=static_geometry(g,s)
        self.assertTrue(r['logical_adjacency_verified'])
        self.assertEqual([x['fraction'] for x in r['rows']],[0,.25,.5,.75,1])
        self.assertTrue(r['endpoint_gate_feasible'])
        self.assertAlmostEqual(r['center_distance_mm'],3.2,places=6)
        self.assertGreater(r['rows'][-1]['rho_target'],.98)

    def test_three_gates_share_inputs_and_space_can_add_rejection(self):
        from dmf.chapter2_geometry_sim.shadow import ShadowArrival
        from dmf.chapter2_geometry_sim.observation import CameraFrame
        from dmf.experiment.evidence import StepContext
        ctx=StepContext('fixture',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54)
        gate=ShadowArrival(ctx)
        f=dict(valid=True,rho_target=.98,eta_source=.04,x_mm=0.,y_mm=0.,distance_mm=1.,area_mm2=4*math.pi,components=1)
        for i in range(6):
            t=.6+i*.05;r=gate.observe(CameraFrame(i,t,t+.008,t+.048,np.ones((2,2),np.uint8),ctx),f)
        self.assertTrue(r['window_event'])
        self.assertFalse(r['spatiotemporal_event'])
        self.assertFalse(r['raw_S'])

    def test_no_overlap_no_motion_or_artificial_extension(self):
        from dmf.chapter2_geometry_sim.single_world import DeformingWorld
        g,s,c=self.inputs();w=DeformingWorld(g,s,c)
        w.advance(.5);w.request(200);w.advance(2.)
        np.testing.assert_allclose(w.position,g.center(190))
        self.assertEqual(w.status,'blocked_no_overlap')
        self.assertEqual(w.stretch,1.)

    def test_pending_rejected_same_target_does_not_reset_response(self):
        from dmf.chapter2_geometry_sim.single_world import DeformingWorld
        g,s,c=self.inputs();w=DeformingWorld(g,s,c);w.advance(.5);w.request(191)
        with self.assertRaises(ValueError):w.request(192)
        w.advance(.6);r=w.response_at_s
        w.request(191);w.advance(.7)
        self.assertEqual(w.response_at_s,r)
        self.assertEqual(w.activation_segment,1)

    def test_camera_features_come_from_actual_mask(self):
        from dmf.chapter2_geometry_sim.observation import SyntheticCamera, extract_features
        g,s,c=self.inputs(position_noise_mm=0)
        camera=SyntheticCamera(g,c)
        frame=camera.expose(0,.8,s.polygon(g.center(191),1),None)
        f=extract_features(frame,camera.raster,190,191)
        self.assertAlmostEqual(f['x_mm'],g.center(191)[0],delta=.03)
        self.assertLess(abs(f['area_mm2']/(4*math.pi)-1),.02)
        self.assertGreater(f['rho_target'],.95)
        self.assertAlmostEqual(frame.available_s,.848)
        frame.mask[:]=0
        self.assertFalse(extract_features(frame,camera.raster,190,191)['valid'])

    def test_reference_continuity_and_speed_not_mask_gate(self):
        from dmf.chapter2_geometry_sim.reference import evaluate_reference
        rows=[dict(time_s=i*.01,x_mm=0.,y_mm=0.,speed_mm_s=0.,active=191) for i in range(31)]
        r=evaluate_reference(rows,(0.,0.),191,0.)
        self.assertAlmostEqual(r['confirmed_s'],.15)
        for row in rows[:20]: row['speed_mm_s']=1.
        r=evaluate_reference(rows,(0.,0.),191,0.)
        self.assertIsNone(r['confirmed_s'])
        rows[20]['time_s']=.19
        with self.assertRaises(ValueError):evaluate_reference(rows,(0.,0.),191,0.)

    def test_causal_shadow_duplicates_gaps_and_once_only(self):
        from dmf.chapter2_geometry_sim.shadow import ShadowArrival
        from dmf.chapter2_geometry_sim.observation import CameraFrame
        from dmf.experiment.evidence import StepContext
        ctx=StepContext('fixture',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54)
        f=dict(valid=True,rho_target=.98,eta_source=.04,x_mm=0.,y_mm=0.)
        def frame(i,t,context=ctx):return CameraFrame(i,t,t+.008,t+.048,np.ones((2,2),np.uint8),context)
        gate=ShadowArrival(ctx)
        self.assertFalse(gate.observe(frame(0,.5),f)['eligible'])
        for i,t in enumerate((.55,.60,.65),1):gate.observe(frame(i,t),f)
        self.assertFalse(gate.observe(frame(3,.65),f)['window_event'])
        self.assertFalse(gate.observe(frame(4,.70,dataclasses.replace(ctx,epoch=0)),f)['eligible'])
        for i in range(5,11):r=gate.observe(frame(i,.75+(i-5)*.05),f)
        self.assertTrue(r['window_event'])
        self.assertFalse(gate.observe(frame(11,1.05),f)['window_event'])
        gap=ShadowArrival(ctx)
        for i,t in enumerate((.55,.60,.65,.90,.95,1.0)):r=gap.observe(frame(i,t),f)
        self.assertFalse(r['window_event'])

    def test_fixed_run_is_one_request_masks_and_separate_truth(self):
        from dmf.chapter2_geometry_sim.single_step import run_single_step
        g,s,c=self.inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'trial';m=run_single_step(g,s,c,out)
            self.assertEqual(m['research_trials'],1)
            self.assertEqual(m['source_preparation'],'controlled_initial_condition_not_P0')
            with (out/'events.csv').open(encoding='utf-8-sig') as stream:
                events=list(csv.DictReader(stream))
            requests=[r for r in events if r['event']=='request']
            applied=[r for r in events if r['event']=='simulated_applied']
            self.assertEqual(len(requests),1);self.assertEqual(requests[0]['target'],'191')
            self.assertEqual(len(applied),1)
            self.assertTrue((out/'world.csv').exists())
            self.assertEqual(len(list((out/'masks').glob('*.png'))),60)
            self.assertIsNotNone(m['summary']['window_confirmation_s'])
            self.assertLess(m['summary']['max_mask_area_relative_error'],.02)
            with self.assertRaises(FileExistsError):run_single_step(g,s,c,out)

    def test_config_rejects_scope_expansion_and_bad_values(self):
        from dmf.chapter2_geometry_sim.single_step import SingleStepConfig
        for kwargs in ({'seed':265000},{'source':191},{'target':192},{'duration_s':0},{'diameter_mm':3.8},{'position_noise_mm':float('nan')}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):SingleStepConfig(**kwargs)

    def test_independent_audit_detects_rehashed_wrong_feature(self):
        import hashlib
        from dmf.chapter2_geometry_sim.audit import audit_trial
        from dmf.chapter2_geometry_sim.single_step import run_single_step,write_csv
        g,s,c=self.inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'trial';run_single_step(g,s,c,out)
            self.assertTrue(audit_trial(out)['passed'])
            with (out/'observations.csv').open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
            rows[-1]['rho_target']='0.123'
            write_csv(out/'observations.csv',rows)
            manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
            manifest['artifacts']['observations.csv']=hashlib.sha256((out/'observations.csv').read_bytes()).hexdigest()
            (out/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            report=audit_trial(out)
            self.assertFalse(report['passed'])
            self.assertTrue(any('feature' in s for s in report['failures']))

    def test_visualization_selects_distinct_actual_frames_without_world_imports(self):
        from dmf.chapter2_geometry_sim.single_step import run_single_step
        from dmf.chapter2_geometry_sim.render import load_trial,select_keyframes,write_player
        g,s,c=self.inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'trial';run_single_step(g,s,c,out)
            data=load_trial(out);keys=select_keyframes(data)
            self.assertLessEqual(len(keys),6)
            self.assertEqual(len({k['tick_index'] for k in keys}),len(keys))
            for k in keys:self.assertEqual(k['time_s'],data['world'][k['tick_index']]['time_s'])
            player=out/'player.html';write_player(data,player)
            html=player.read_text(encoding='utf-8')
            self.assertIn('SIMULATION',html);self.assertIn('type="range"',html)
            self.assertNotIn('GeometryWorld',html)

    def test_frame_decision_uses_processing_time_not_exposure_or_ready_time(self):
        from dmf.chapter2_geometry_sim.shadow import ShadowArrival
        from dmf.chapter2_geometry_sim.observation import CameraFrame
        from dmf.experiment.evidence import StepContext
        ctx=StepContext('fixture',1,0,1,190,191,clock_domain='simulation',applied_timestamp_s=.54)
        gate=ShadowArrival(ctx);f=dict(valid=True,rho_target=.99,eta_source=.01)
        frame=CameraFrame(1,.6,.608,.648,np.ones((2,2),np.uint8),ctx,processed_at_s=.65)
        self.assertTrue(gate.observe(frame,f)['single_event'])
        self.assertEqual(gate.single_s,.65)


if __name__=='__main__':unittest.main()
