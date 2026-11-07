"""Hermetic synthetic file fixtures, not experimental evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from dmf.vision.image_io import write_image
from dmf.vision.design_registration import file_hash


def design_fixture():
    positions={402:(20.8,-8),404:(43.2,-8),406:(72,20.8),408:(72,43.2),
               410:(43.2,72),412:(20.8,72),414:(-8,43.2),416:(-8,20.8),
               417:(-5,-5),418:(69,-5),419:(69,69),420:(-5,69)}
    electrodes=[]
    for i in range(1,421):
        x,y=positions.get(i,(((i-1)%20)*3.2+1.6,((i-1)//20)*3.2+1.6))
        half=2 if i>400 else 1.5
        polygon=[[x-half,y-half],[x+half,y-half],[x+half,y+half],[x-half,y+half]]
        electrodes.append(dict(control_id=i,polygon_map_mm=polygon,
            center_map_mm=[x,y],label_point_map_mm=[x,y],bbox_map_mm=[x-half,y-half,x+half,y+half],
            geometry_class='core' if i<=400 else 'large'))
    return dict(schema='dmf_electrode_design_map_v1',version='synthetic_unit_fixture',
        electrode_count=420,source_kind='design_gerber',coordinate_system=dict(unit='mm'),
        binding=dict(confirmed=True),electrodes=electrodes)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('dmf.vision.registration_workspace'),
                             'registration workspace is not implemented')
        from dmf.vision import registration_workspace
        self.r=registration_workspace
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.design=self.root/'design';self.design.mkdir()
        p=self.design/'electrode_design_map.json'
        p.write_text(json.dumps(design_fixture()),encoding='utf-8')
        (self.design/'manifest.json').write_text(json.dumps(dict(outputs_sha256={p.name:file_hash(p)})),encoding='utf-8')
        self.pilot=self.root/'pilot';self.pilot.mkdir()
        write_image(self.pilot/'reference.png',np.zeros((300,300,3),dtype=np.uint8))
        self.video=self.root/'synthetic_fixture.avi';self.video.write_bytes(b'unit fixture not a real video')
        config=dict(core_corners_px=[[50,50],[250,50],[250,250],[50,250]],pitch_mm=3.2)
        (self.pilot/'legacy.json').write_text(json.dumps(config),encoding='utf-8')
        ref=dict(image='reference.png',source_video=str(self.video),source_frame_id=0,width=300,height=300,
                 image_sha256=file_hash(self.pilot/'reference.png'))
        (self.pilot/'workspace.json').write_text(json.dumps(dict(references={'fixture':ref})),encoding='utf-8')
        self.resources=self.root/'resource_manifest.json'
        self.resources.write_text(json.dumps(dict(videos=[dict(video_id='fixture',source=str(self.video),
            sha256=file_hash(self.video),source_kind='real_camera_recording_user_confirmed')])),encoding='utf-8')

    def prepare(self):
        return self.r.prepare_workspace(self.design,self.pilot/'workspace.json',
            self.resources,self.root/'out',legacy_maps={'fixture':self.pilot/'legacy.json'})

    def test_catalog_fixed_roles_and_no_observed_truth(self):
        points=self.r.point_catalog(design_fixture(),np.eye(3))
        self.assertEqual([p['role'] for p in points].count('fit'),8)
        self.assertEqual([p['role'] for p in points].count('check'),16)
        self.assertTrue(all(p['observed_px'] is None and p['status']=='pending' for p in points))
        for p in points:
            e=design_fixture()['electrodes'][p['control_id']-1]
            self.assertEqual(p['map_mm'],e['polygon_map_mm'][p['vertex_index']])

    def test_prepare_preserves_sources_and_verifies_native_image(self):
        before=file_hash(self.pilot/'reference.png')
        result=self.prepare()
        workspace=self.r.load_workspace(result[0])
        self.assertEqual(workspace['image_size'],[300,300])
        self.assertEqual(file_hash(result[0].parent/'original.png'),before)
        self.assertEqual(file_hash(self.pilot/'reference.png'),before)
        self.assertFalse(workspace['simulation'])
        self.assertIsNone(workspace['fit_freeze'])
        self.assertEqual(workspace['source']['source_frame_id'],0)

    def test_existing_output_not_overwritten(self):
        self.prepare()
        with self.assertRaises(FileExistsError): self.prepare()

    def test_bad_image_hash_rejected_before_creating_output(self):
        write_image(self.pilot/'reference.png',np.ones((300,300,3),dtype=np.uint8))
        with self.assertRaisesRegex(ValueError,'image hash'):self.prepare()
        self.assertFalse((self.root/'out').exists())

    def test_bad_video_hash_rejected(self):
        self.video.write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError,'video hash'):self.prepare()

    def test_wrong_native_size_rejected(self):
        p=self.pilot/'workspace.json';d=json.loads(p.read_text());d['references']['fixture']['width']=299
        p.write_text(json.dumps(d),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'size'): self.prepare()

    def test_load_rejects_changed_image(self):
        result=self.prepare()
        write_image(result[0].parent/'original.png',np.ones((300,300,3),dtype=np.uint8))
        with self.assertRaisesRegex(ValueError,'image hash'):self.r.load_workspace(result[0])

    def test_save_optimistic_conflict(self):
        path=self.prepare()[0];a=self.r.load_workspace(path);b=self.r.load_workspace(path)
        a['notes']='first';self.r.save_workspace(path,a)
        b['notes']='second'
        with self.assertRaisesRegex(ValueError,'changed'):self.r.save_workspace(path,b)

    def test_build_pending_metrics_and_new_revision(self):
        path=self.prepare()[0]
        one=self.r.build_report(path,figures=False);two=self.r.build_report(path,figures=False)
        self.assertNotEqual(one,two)
        result=json.loads((one/'registration_result.json').read_text(encoding='utf-8'))
        self.assertIsNone(result['rmse_px']);self.assertEqual(result['check_missing'],16)
        self.assertTrue((one/'points.csv').exists())

    def test_cli_help(self):
        result=subprocess.run([sys.executable,'run_design_registration.py','--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('prepare',result.stdout)

    @unittest.skipUnless(sys.platform=='win32','Windows cmd parser regression')
    def test_windows_launcher_from_unicode_directory(self):
        self.assertTrue(hasattr(self.r,'write_review_launcher'),
                        'CRLF-safe review launcher writer is missing')
        repo=self.root/'中文 仓库';repo.mkdir()
        # This diagnostic CLI only prints argv; it never opens a GUI or real data.
        (repo/'run_design_registration.py').write_text(
            'import json,sys;print(json.dumps(sys.argv[1:]))',encoding='utf-8')
        folder=self.root/'中文 启动目录';folder.mkdir()
        workspace=folder/'待核对 数据.json';workspace.write_text('{}',encoding='utf-8')
        launcher=folder/'启动配准核对.cmd'
        self.r.write_review_launcher(launcher,repo,Path(sys.executable),workspace)
        raw=launcher.read_bytes()
        self.assertEqual(raw.count(b'\n'),raw.count(b'\r\n'))
        result=subprocess.run(['cmd.exe','/d','/c','call',str(launcher)],cwd=folder,
            input='\n',capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stderr,'')
        self.assertEqual(json.loads(result.stdout.strip()),['review',str(workspace.resolve())])

    def test_prepare_generates_launch_entry(self):
        self.prepare()
        self.assertTrue((self.root/'out'/'启动配准核对.cmd').is_file(),
                        'prepared package has no double-click entry')

    def test_pending_figure_exports_and_declares_navigation_only(self):
        path=self.prepare()[0]
        report=self.r.build_report(path)
        for stem in ('electrode_overlay','point_navigation'):
            for extension in ('svg','pdf','png','alignment.json'):
                self.assertTrue((report/f'{stem}.{extension}').is_file())
        notes=json.loads((report/'figure_integrity.json').read_text(encoding='utf-8'))
        self.assertFalse(notes['physical_scale_bar'])
        self.assertEqual(notes['accuracy_status'],'pending_fit')
        self.assertIn('navigation',notes['points_shown'])

    def test_review_gui_smoke_in_isolated_process(self):
        path=self.prepare()[0]
        code=('import tkinter as tk; from pathlib import Path; '
              'from dmf.vision.registration_gui import RegistrationReviewApp; '
              f'r=tk.Tk();r.withdraw();a=RegistrationReviewApp(r,Path({str(path)!r}));'
              'r.update();a._clicked(60,60,False);'
              'assert a.workspace["points"][0]["observed_px"] is None;'
              'r.destroy()')
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
