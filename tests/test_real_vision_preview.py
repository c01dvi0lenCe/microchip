import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

try:
    from scripts.preview_real_vision_1106 import load_candidates, component_rows, run_preview
except ImportError:
    load_candidates = component_rows = run_preview = None


class RealVisionPreviewTests(unittest.TestCase):
    def fixture(self, folder):
        root=Path(folder)/'input'; (root/'frames').mkdir(parents=True)
        image=np.full((64,96,3),180,np.uint8)
        image[20:40,20:40]=20
        p=root/'frames/a.png'; p.write_bytes(cv2.imencode('.png',image)[1].tobytes())
        row=dict(sample_id='a',frame_path='frames/a.png',frame_path_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            parent_video_id='v',source_frame_id='3',source_sha256='video_hash',roi_x='12',roi_y='20',
            roi_w='96',roi_h='64',category='motion_candidate',timestamp_s='0.3',timestamp_source='host_receive',
            mask_reviewed='False',state_reviewed='False',map_status='no_1106_calibration_bound')
        with (root/'annotations.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(row)); w.writeheader(); w.writerow(row)
        return root,row,image

    def require_api(self):
        self.assertIsNotNone(run_preview,'Independent read-only preview orchestration is missing')

    def test_hash_mismatch_rejected(self):
        self.require_api()
        with tempfile.TemporaryDirectory() as t:
            root,row,image=self.fixture(t); (root/'frames/a.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash'): load_candidates(root)

    def test_components_keep_small_droplet_and_restore_global_coordinates(self):
        self.require_api()
        mask=np.zeros((64,96),np.uint8); mask[10:12,5:7]=255; mask[30,40]=255
        rows=component_rows(mask,dict(sample_id='a',roi_x='12',roi_y='20'),'unet')
        self.assertEqual(len(rows),2)
        self.assertEqual(sorted(r['area_px'] for r in rows),[1,4])
        self.assertEqual(rows[0]['centroid_full_u_px'],17.5)
        self.assertEqual(rows[0]['centroid_full_v_px'],30.5)

    def test_native_masks_saved_without_gt_or_input_modification_and_no_overwrite(self):
        self.require_api()
        with tempfile.TemporaryDirectory() as t:
            root,row,image=self.fixture(t); before=(root/'annotations.csv').read_bytes()
            output=Path(t)/'out'
            manifest=run_preview(root,output,{'unet':lambda img:np.where(img[:,:,0]<100,255,0).astype(np.uint8)})
            self.assertEqual(manifest['successful_predictions'],1)
            self.assertFalse(manifest['accuracy_evaluated']); self.assertFalse(manifest['calibration_bound'])
            mask=cv2.imdecode(np.frombuffer((output/'masks/unet/a.png').read_bytes(),np.uint8),0)
            self.assertEqual(mask.shape,(64,96)); self.assertEqual(int((mask>0).sum()),400)
            self.assertEqual((root/'annotations.csv').read_bytes(),before)
            self.assertEqual(set(manifest['output_sha256']),
                {str(p.relative_to(output)) for p in output.rglob('*') if p.is_file() and p.name!='manifest.json'})
            with self.assertRaises(FileExistsError): run_preview(root,output,{})

    def test_predictor_error_is_recorded_not_replaced_with_empty_mask(self):
        self.require_api()
        with tempfile.TemporaryDirectory() as t:
            root,row,image=self.fixture(t); output=Path(t)/'out'
            def fail(_): raise RuntimeError('injected failure')
            manifest=run_preview(root,output,{'unet':fail})
            self.assertEqual(manifest['failed_predictions'],1)
            self.assertFalse((output/'masks/unet/a.png').exists())

    def test_roi_path_cannot_escape_source_root(self):
        self.require_api()
        with tempfile.TemporaryDirectory() as t:
            root,row,image=self.fixture(t)
            content=(root/'annotations.csv').read_text(encoding='utf-8-sig').replace('frames/a.png','../outside.png')
            (root/'annotations.csv').write_text(content,encoding='utf-8-sig')
            with self.assertRaisesRegex(ValueError,'path'): load_candidates(root)


if __name__=='__main__': unittest.main()
