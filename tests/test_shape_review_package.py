import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from dmf.vision.pilot_annotation import PilotWorkspace,prepare_pilot
from dmf.vision.image_io import read_image,write_image
from tests import test_pilot_annotation as pilot_fixtures


class ShapeReviewPackageTests(unittest.TestCase):
    def test_cached_source_index_accepts_windows_path_separators(self):
        from scripts.prepare_chapter2_shape_review import artifact_hash
        self.assertEqual(artifact_hash({'frames\\0665.png':'abc'},'frames/0665.png'),'abc')
        self.assertEqual(artifact_hash({'frames/0665.png':'abc'},'frames\\0665.png'),'abc')
        with self.assertRaises(KeyError):artifact_hash({'frames/0665.png':'abc'},'frames/0999.png')

    def setup_workspace(self,root):
        dataset=pilot_fixtures.PilotAnnotationTests().make_input(root)
        prepare_pilot(dataset,root/'review')
        workspace=PilotWorkspace(root/'review');workspace.add_frame('clip1',2)
        snapshot=root/'snapshot';snapshot.mkdir()
        (snapshot/'images').mkdir();(snapshot/'masks').mkdir()
        for i,row in enumerate(workspace.rows):
            image,_=workspace.images(i)
            write_image(snapshot/f'images/{i}.png',image)
            mask=np.zeros(image.shape[:2],np.uint8);mask[10:20,12:24]=255
            write_image(snapshot/f'masks/{i}.png',mask)
        rows=[dict(parent_video_id='video1',source_frame_id=row['source_frame_id'],
              frame_path=f'images/{i}.png',mask_path=f'masks/{i}.png',
              frame_path_sha256=hashlib.sha256((snapshot/f'images/{i}.png').read_bytes()).hexdigest(),
              mask_path_sha256=hashlib.sha256((snapshot/f'masks/{i}.png').read_bytes()).hexdigest(),
              mask_reviewed='True' if i==0 else 'False') for i,row in enumerate(workspace.rows)]
        with (snapshot/'samples.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        return workspace,snapshot

    def test_inheritance_is_byte_exact_and_never_promotes_draft_or_state(self):
        from scripts.prepare_chapter2_shape_review import inherit_reviewed_masks
        with tempfile.TemporaryDirectory() as tmp:
            workspace,snapshot=self.setup_workspace(Path(tmp))
            result=inherit_reviewed_masks(workspace,snapshot)
            self.assertEqual(result['inherited_reviewed'],1)
            self.assertEqual(result['pending_review'],1)
            a,b=workspace.rows
            self.assertTrue(a['mask_reviewed']);self.assertFalse(b['mask_reviewed'])
            self.assertEqual((workspace.root/a['mask_path']).read_bytes(),(snapshot/'masks/0.png').read_bytes())
            self.assertEqual(b['mask_path'],'')
            for r in workspace.rows:
                self.assertEqual(r['state_gt'],'Unknown');self.assertFalse(r['state_reviewed'])
                self.assertEqual(r['source_electrode'],'');self.assertEqual(r['target_electrode'],'')
            self.assertEqual(workspace.report()['confirmed_maps'],0)

    def test_wrong_image_domain_rejects_reviewed_mask_inheritance(self):
        from scripts.prepare_chapter2_shape_review import inherit_reviewed_masks
        with tempfile.TemporaryDirectory() as tmp:
            workspace,snapshot=self.setup_workspace(Path(tmp))
            p=workspace.root/workspace.rows[0]['frame_path']
            image=read_image(p,cv2.IMREAD_COLOR);image[0,0]=[0,0,0];write_image(p,image)
            with self.assertRaisesRegex(ValueError,'pixels'):
                inherit_reviewed_masks(workspace,snapshot)

    def test_changed_original_mask_rejected(self):
        from scripts.prepare_chapter2_shape_review import inherit_reviewed_masks
        with tempfile.TemporaryDirectory() as tmp:
            workspace,snapshot=self.setup_workspace(Path(tmp))
            p=snapshot/'masks/0.png';image=read_image(p,0);image[0,0]=255;write_image(p,image)
            with self.assertRaisesRegex(ValueError,'hash'):
                inherit_reviewed_masks(workspace,snapshot)


if __name__=='__main__':unittest.main()
