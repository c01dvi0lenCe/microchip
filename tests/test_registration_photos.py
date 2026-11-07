"""Synthetic file fixtures test photo transport, not physical registration."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_registration_workspace as fixtures
from dmf.vision.design_registration import file_hash
from dmf.vision.registration_workspace import load_workspace, build_report


class PhotoRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('dmf.vision.registration_photos'),
                             'photo registration adapter is not implemented')
        from dmf.vision.registration_photos import prepare_photo_workspace
        self.prepare_photos=prepare_photo_workspace
        base=fixtures.WorkspaceTests('test_cli_help');base.setUp();self.addCleanup(base.doCleanups)
        self.root=base.root;self.design=base.design;self.image=base.pilot/'reference.png'
        self.inputs=self.root/'photo_inputs.json';self.output=self.root/'photo_output'
        self.data=dict(schema='dmf_photo_registration_inputs_v1',
            user_confirmed_industrial_camera_photos=True,use_scope='pre_experiment_only',
            references=[dict(resource_id='photo_fixture',image=str(self.image),
                sha256=file_hash(self.image),image_size=[300,300],
                initial_core_corners_px=[[50,50],[250,50],[250,250],[50,250]])])
        self.write_inputs()

    def write_inputs(self):self.inputs.write_text(json.dumps(self.data),encoding='utf-8')
    def prepare(self):return self.prepare_photos(self.design,self.inputs,self.output)

    def test_native_photo_no_fake_frame_or_video(self):
        path=self.prepare()[0];w=load_workspace(path)
        self.assertEqual(w['source']['kind'],'real_industrial_camera_photo')
        self.assertNotIn('source_video',w['source']);self.assertNotIn('source_frame_id',w['source'])
        self.assertEqual(w['use_scope'],'pre_experiment_only')
        self.assertFalse(w['final_experiment_calibration_approved'])
        self.assertFalse(w['transfer_to_old_videos_verified'])
        self.assertFalse(w['final_relative_height_fixed'])
        self.assertEqual(file_hash(path.parent/'original.png'),file_hash(self.image))
        self.assertEqual(len(w['points']),24)
        self.assertTrue(all(p['status']=='pending' and p['observed_px'] is None for p in w['points']))
        self.assertIsNone(w['fit_freeze'])
        self.assertTrue((self.output/'启动配准核对.cmd').is_file())

    def test_source_confirmation_required(self):
        self.data['user_confirmed_industrial_camera_photos']=False;self.write_inputs()
        with self.assertRaisesRegex(ValueError,'confirmed'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_final_purpose_rejected(self):
        self.data['use_scope']='final_calibration';self.write_inputs()
        with self.assertRaisesRegex(ValueError,'pre.experiment'):self.prepare()

    def test_wrong_photo_hash_rejected_before_output(self):
        self.data['references'][0]['sha256']='0'*64;self.write_inputs()
        with self.assertRaisesRegex(ValueError,'hash'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_invalid_navigation_quad_rejected(self):
        self.data['references'][0]['initial_core_corners_px']=[[5,5]]*4;self.write_inputs()
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.output.exists())

    def test_outside_navigation_quad_rejected(self):
        self.data['references'][0]['initial_core_corners_px'][0]=[-5,5];self.write_inputs()
        with self.assertRaisesRegex(ValueError,'image'):self.prepare()

    def test_duplicate_resource_rejected(self):
        self.data['references'].append(dict(self.data['references'][0]));self.write_inputs()
        with self.assertRaisesRegex(ValueError,'duplicate'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_existing_output_preserved(self):
        self.prepare()
        with self.assertRaises(FileExistsError):self.prepare()

    def test_native_size_mismatch_rejected(self):
        self.data['references'][0]['image_size']=[299,300];self.write_inputs()
        with self.assertRaisesRegex(ValueError,'size'):self.prepare()

    def test_cli_photo_route(self):
        result=subprocess.run([sys.executable,'run_design_registration.py','prepare-photos','--help'],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--inputs',result.stdout)

    def test_photo_figures_cannot_claim_video_or_final_calibration(self):
        path=self.prepare()[0];report=build_report(path)
        text=(report/'electrode_overlay.svg').read_text(encoding='utf-8')
        self.assertIn('PRE-EXPERIMENT',text)
        self.assertNotIn('video frame',text);self.assertNotIn('Legacy four-corner',text)
        integrity=json.loads((report/'figure_integrity.json').read_text(encoding='utf-8'))
        self.assertFalse(integrity['formal_thesis_accuracy_figure_ready'])
        result=json.loads((report/'registration_result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['use_scope'],'pre_experiment_only')
        self.assertFalse(result['final_experiment_calibration_approved'])
        self.assertIsNone(result['rmse_px'])

    def test_photo_review_ui_has_scope_banner(self):
        path=self.prepare()[0]
        code=('import tkinter as tk;from pathlib import Path;'
              'from dmf.vision.registration_gui import RegistrationReviewApp;'
              f'r=tk.Tk();r.withdraw();a=RegistrationReviewApp(r,Path({str(path)!r}));'
              'r.update();assert "预实验" in r.title();r.destroy()')
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
