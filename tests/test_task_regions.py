import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from dmf.vision.image_io import write_image
from dmf.vision.registration_audit import CONDITION_FIELDS

try:
    from dmf.vision.task_regions import TaskRegion, TaskBinding
except ImportError:
    TaskRegion = TaskBinding = None


class TaskRegionTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(TaskRegion, 'Observation region contract missing')
        self.assertIsNotNone(TaskBinding, 'Strict task geometry binding missing')

    def fixture(self, root):
        root=Path(root);reference=root/'reference.png';design=root/'design.json';manifest=root/'binding.json'
        write_image(reference,np.full((100,100,3),200,np.uint8))
        electrodes=[]
        for eid in range(1,421):
            row,col=divmod(eid-1,20);x=10+col*3;y=10+row*3
            electrodes.append(dict(control_id=eid,polygon_map_mm=[[x,y],[x+2.5,y],[x+2.5,y+2.5],[x,y+2.5]]))
        design.write_text(json.dumps(dict(schema='dmf_electrode_design_map_v1',coordinate_system=dict(unit='mm'),
            electrode_count=420,binding=dict(confirmed=True),electrodes=electrodes)),encoding='utf8')
        conditions={key:'synthetic_test_fixture' for key in CONDITION_FIELDS}
        conditions['resolution']=[100,100];conditions['acquisition_id']='fixture_capture'
        data=dict(schema='dmf_final_calibration_manifest_v1',status='accepted_final_calibration',
            source_scope='final_apparatus',final_height_fixed=True,independently_checked=True,
            reviewer='software_fixture_not_real_review',conditions=conditions,
            reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
            design_map_sha256=hashlib.sha256(design.read_bytes()).hexdigest(),
            image_to_design_mm=np.eye(3).tolist(),acceptance=dict(declared_before_check_review=True,
                thresholds_px=dict(rmse_px=2,p95_px=3,max_px=4),measured_px=dict(rmse_px=0,p95_px=0,max_px=0)))
        manifest.write_text(json.dumps(data),encoding='utf8')
        return design,manifest,reference,conditions,data

    def test_pixel_region_has_no_electrode_identity_or_control_validity(self):
        self.api();r=TaskRegion('watch1',(2,3,50,40))
        r.validate_shape((100,100,3))
        self.assertEqual(r.kind,'pixel_observation')
        self.assertIsNone(r.source_electrode);self.assertIsNone(r.target_electrode)
        self.assertFalse(r.control_eligible)

    def test_bad_region_and_frame_domains_rejected(self):
        self.api()
        for name,roi in [('',(0,0,1,1)),('a/b',(0,0,1,1)),('x',(-1,0,5,5)),('x',(0,0,True,1))]:
            with self.subTest(roi=roi),self.assertRaises(ValueError):TaskRegion(name,roi)
        with self.assertRaises(ValueError):TaskRegion('x',(90,90,20,20)).validate_shape((100,100,3))
        with self.assertRaises(ValueError):TaskRegion('x',(0,0,10,10),source_electrode=190)

    def test_hand_calculated_task_bounds_include_both_four_neighborhoods(self):
        self.api()
        with tempfile.TemporaryDirectory() as t:
            design,manifest,reference,conditions,_=self.fixture(t)
            binding=TaskBinding.load(design,manifest,reference,conditions)
            r=binding.region('transport',190,191,epoch=2,frame_shape=(100,100,3),
                             acquisition_id='fixture_capture',margin_px=2)
            self.assertEqual(r.roi,(32,32,17,14))
            self.assertEqual(r.kind,'calibrated_task');self.assertEqual(r.epoch,2)
            self.assertEqual((r.source_electrode,r.target_electrode),(190,191))
            self.assertEqual(len(r.binding_sha256),64)
            self.assertFalse(r.control_eligible,'Geometry alone must not arm control')

    def test_preexperiment_changed_geometry_hash_and_reference_rejected(self):
        self.api()
        with tempfile.TemporaryDirectory() as t:
            design,manifest,reference,conditions,data=self.fixture(t)
            for key,value in [('status','pre_experiment_only'),('image_to_design_mm',[[0]*3]*3)]:
                changed=dict(data);changed[key]=value;manifest.write_text(json.dumps(changed),encoding='utf8')
                with self.assertRaises(ValueError):TaskBinding.load(design,manifest,reference,conditions)
            manifest.write_text(json.dumps(data),encoding='utf8')
            changed=dict(conditions,chip_height_mm='changed')
            with self.assertRaises(ValueError):TaskBinding.load(design,manifest,reference,changed)
            design.write_text(design.read_text(encoding='utf8')+' ',encoding='utf8')
            with self.assertRaises(ValueError):TaskBinding.load(design,manifest,reference,conditions)

    def test_binding_cannot_be_reused_for_other_capture_size_or_unseen_electrode(self):
        self.api()
        with tempfile.TemporaryDirectory() as t:
            design,manifest,reference,conditions,data=self.fixture(t)
            binding=TaskBinding.load(design,manifest,reference,conditions)
            for shape,capture in [((100,101,3),'fixture_capture'),((100,100,3),'other_capture')]:
                with self.assertRaises(ValueError):binding.region('x',190,191,epoch=0,
                    frame_shape=shape,acquisition_id=capture,margin_px=2)
            data['image_to_design_mm']=[[1,0,200],[0,1,0],[0,0,1]]
            manifest.write_text(json.dumps(data),encoding='utf8')
            binding=TaskBinding.load(design,manifest,reference,conditions)
            with self.assertRaises(ValueError):binding.region('x',190,191,epoch=0,
                frame_shape=(100,100,3),acquisition_id='fixture_capture',margin_px=2)


if __name__=='__main__':unittest.main()
