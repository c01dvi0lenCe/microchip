"""Synthetic geometry/UI fixtures; no fake human registration evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import test_registration_workspace as fixtures
from dmf.vision.design_registration import digest,file_hash
from dmf.vision.registration_repeatability import new_review,record_click,summarize,validate,save_new


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        from dmf.vision import registration_guidance
        self.g=registration_guidance
        self.design=fixtures.design_fixture()
        from dmf.vision.registration_workspace import point_catalog
        self.inverse=np.array([[2.,0,50.],[0,2.,50.],[0,0,1.]])
        self.points=point_catalog(self.design,self.inverse)
        self.workspace=dict(points=self.points,image_size=[300,300],
            fit_freeze=dict(image_to_design_mm=np.linalg.inv(self.inverse).tolist()))

    def assisted(self):
        data=new_review([p for p in self.points if p['role']=='check'],[300,300])
        data.update(schema='dmf_assisted_registration_repeatability_v1',review_mode='coarse_region_assisted',
            blinding='not_blind: coarse region from prior H',guidance=dict(
            regions=self.g.build_regions(self.workspace,self.design),
            source_workspace_sha256='a'*64,quantization_px=32))
        data['guidance_sha256']=digest(data['guidance'])
        return data

    def test_ranges_do_not_depend_on_old_check_clicks(self):
        before=self.g.build_regions(self.workspace,self.design)
        for p in self.workspace['points']:p['observed_px']=[1.,299.]
        self.assertEqual(before,self.g.build_regions(self.workspace,self.design))

    def test_core_range_covers_target_and_three_by_three_neighborhood(self):
        regions=self.g.build_regions(self.workspace,self.design)
        self.assertEqual(len(regions),16)
        for p in self.points:
            if p['role']!='check':continue
            region=regions[p['point_id']];x0,y0,x1,y1=region['bounds_px']
            xy=np.array([*p['map_mm'],1.])@self.inverse.T;u,v=xy[:2]/xy[2]
            self.assertTrue(x0<=u<=x1 and y0<=v<=y1)
            if p['control_id']<=400:self.assertEqual(len(region['neighbor_electrodes']),9)
            self.assertNotIn('center_px',region)

    def test_assisted_click_stays_raw_and_summary_declares_not_blind(self):
        data=self.assisted();record_click(data,1,'C1',[63.125,58.875],'human')
        obs=data['rounds'][0]['observations']['C1']
        self.assertEqual(obs['pixel'],[63.125,58.875])
        self.assertIn('coarse_region',obs['method'])
        result=summarize(data)
        self.assertEqual(result['review_mode'],'coarse_region_assisted')
        self.assertFalse(result['strict_blind'])
        self.assertIsNone(result['rmse_between_rounds_px'])

    def test_changed_guidance_or_outside_image_is_rejected(self):
        data=self.assisted();data['guidance']['regions']['C1']['bounds_px'][0]=-1
        with self.assertRaises(ValueError):validate(data)
        data['guidance_sha256']=digest(data['guidance'])
        with self.assertRaises(ValueError):validate(data)

    def test_assistance_cannot_be_mislabeled_as_original_blind_schema(self):
        data=self.assisted();data['schema']='dmf_blinded_registration_repeatability_v1'
        with self.assertRaises(ValueError):validate(data)

    def test_assisted_gui_has_rectangle_without_predicted_cross_or_saved_click(self):
        from dmf.vision.image_io import write_image
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'map.json').write_text(json.dumps(self.design),encoding='utf-8')
            write_image(root/'photo.png',np.zeros((300,300,3),np.uint8))
            data=self.assisted();data.update(image_path='photo.png',image_sha256=file_hash(root/'photo.png'),
                design_map_path='map.json',design_map_sha256=file_hash(root/'map.json'))
            path=root/'assisted.json';save_new(path,data);before=file_hash(path)
            code='''import sys,tkinter as tk
from dmf.vision.registration_repeatability_gui import RepeatabilityApp
root=tk.Tk();root.withdraw();app=RepeatabilityApp(root,sys.argv[1]);root.update_idletasks()
assert app.assisted and '非盲法' in root.title()
assert len(app.canvas.canvas.find_withtag('coarse_region'))==1
assert not any(app.canvas.canvas.type(i)=='line' for i in app.canvas.canvas.find_all())
assert app.draft is None
app.clicked(55.125,61.875,False)
assert app.draft==[55.125,61.875]
root.destroy()
'''
            run=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(file_hash(path),before)
    def test_overlay_has_only_coarse_rectangle_until_human_click(self):
        class Canvas:
            def __init__(self):self.rectangles=[];self.text=[]
            def create_rectangle(self,*args,**kwargs):self.rectangles.append(args)
            def create_text(self,*args,**kwargs):self.text.append(kwargs['text'])
        from dmf.vision.registration_repeatability_gui import coarse_region_overlay
        canvas=Canvas();coarse_region_overlay(canvas,2.,[10,20,100,120],'C1 / 1')
        self.assertEqual(canvas.rectangles,[(20.,40.,200.,240.)])
        self.assertEqual(len(canvas.text),1)

    def test_cli_has_explicit_separate_preparation(self):
        result=subprocess.run([sys.executable,'run_registration_audit.py','prepare-assisted','--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--workspace',result.stdout)

    def test_new_package_preserves_source_and_starts_empty(self):
        from dmf.vision.design_registration import project,record_observation,freeze_fit,seal_evaluation
        from dmf.vision.registration_workspace import load_workspace,save_workspace
        base=fixtures.WorkspaceTests('test_cli_help');base.setUp();self.addCleanup(base.doCleanups)
        source=base.prepare()[0];w=load_workspace(source);inverse=np.linalg.inv(w['initial_image_to_design_mm'])
        for role in ('fit','check'):
            for p in w['points']:
                if p['role']==role:record_observation(w,p['point_id'],project([p['map_mm']],inverse)[0],'fixture')
            if role=='fit':freeze_fit(w)
        seal_evaluation(w);save_workspace(source,w);old_hash=file_hash(source)
        path=self.g.prepare_assisted(source,base.root/'assisted')
        data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(file_hash(source),old_hash)
        self.assertEqual(data['rounds'][0]['observations'],{})
        self.assertEqual(data['rounds'][1]['observations'],{})
        self.assertNotIn('observed_px',path.read_text(encoding='utf-8'))
        self.assertNotIn('image_to_design_mm',path.read_text(encoding='utf-8'))
        self.assertTrue((path.parent/'启动粗范围辅助点选.cmd').is_file())
        with self.assertRaises(FileExistsError):self.g.prepare_assisted(source,path.parent)


if __name__=='__main__':unittest.main()
