import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from dmf.vision.image_io import write_image, read_image
from dmf.vision.dataset import write_csv_rows, read_csv_rows
from dmf.vision.pilot_annotation import prepare_pilot, PilotWorkspace, translated_map, draft_mask


class PilotAnnotationTests(unittest.TestCase):
    def make_input(self, root):
        dataset=root/'input';dataset.mkdir()
        source=root/'camera.avi'
        writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'FFV1'),10,(80,80))
        self.assertTrue(writer.isOpened())
        image=np.full((80,80,3),230,np.uint8);cv2.circle(image,(28,26),5,(20,20,20),-1)
        for _ in range(3):writer.write(image)
        writer.release()
        cropped=image[10:50,12:52]
        clip_path=root/'clip.avi'
        writer=cv2.VideoWriter(str(clip_path),cv2.VideoWriter_fourcc(*'FFV1'),10,(40,40))
        self.assertTrue(writer.isOpened())
        for _ in range(3):writer.write(cropped)
        writer.release()
        write_image(dataset/'frame.png',cropped)
        write_csv_rows(dataset/'annotations_to_label.csv',[dict(video_id='clip1',batch_id='day1',
            frame_id=0,timestamp_s=0,image_path=str(dataset/'frame.png'),parent_video_id='video1',
            source_frame_id=0,roi_x=12,roi_y=10)])
        (dataset/'clips_manifest.json').write_text(json.dumps([dict(clip_id='clip1',video_id='video1',
            source=str(source),path=str(clip_path),start_frame=0,end_frame_exclusive=3,
            fps=10,roi_xywh=[12,10,40,40],batch_id='day1')]))
        return dataset

    def test_prepare_never_promotes_drafts_or_overwrites_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dataset=self.make_input(root)
            old=(dataset/'annotations_to_label.csv').read_bytes()
            prepare_pilot(dataset,root/'review')
            workspace=PilotWorkspace(root/'review')
            row=workspace.rows[0]
            self.assertEqual(row['state_gt'],'Unknown')
            self.assertEqual(row['mask_path'],'')
            self.assertEqual(row['source_electrode'],'')
            self.assertEqual(row['timestamp_source'],'container_fps_unverified')
            self.assertTrue((workspace.root/row['draft_mask_path']).is_file())
            np.testing.assert_array_equal(read_image(workspace.root/row['frame_path'],cv2.IMREAD_COLOR),
                read_image(dataset/'frame.png',cv2.IMREAD_COLOR))
            self.assertEqual((dataset/'annotations_to_label.csv').read_bytes(),old)
            with self.assertRaises(FileExistsError):prepare_pilot(dataset,root/'review')
            with self.assertRaises(ValueError):prepare_pilot(dataset,dataset/'review')

    def test_map_translation_preserves_ids_and_millimetres(self):
        config=dict(core_corners_px=[[0,0],[80,0],[80,80],[0,80]],pitch_mm=1,
            pixel_overrides={'401':[[20,-8],[24,-8],[24,-4],[20,-4]]})
        electrode_map=translated_map(config,12,10)
        self.assertEqual(len(electrode_map),420)
        self.assertEqual(electrode_map[1].center_px,(-10.,-8.))
        self.assertEqual(electrode_map[1].center_mm,(.5,.5))
        self.assertEqual(electrode_map[401].geometry_source,'calibrated')
        self.assertEqual(electrode_map[401].polygon_px[0],(8.,-18.))

    def test_state_approval_requires_confirmed_map_pair_and_mask(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepare_pilot(self.make_input(root),root/'review');w=PilotWorkspace(root/'review')
            image,mask=w.images(0)
            with self.assertRaises(ValueError):w.review(0,mask,mask_reviewed=True,state_reviewed=True,
                source=1,target=2,state='Moving')
            w.save_calibration('video1',[[0,0],[80,0],[80,80],[0,80]],1,confirmed=True)
            with self.assertRaises(ValueError):w.review(0,mask,mask_reviewed=False,state_reviewed=True,
                source=1,target=2,state='Moving')
            w.review(0,mask,mask_reviewed=True,state_reviewed=True,source=1,target=2,state='Moving')
            self.assertEqual(w.rows[0]['state_gt'],'Moving')
            self.assertEqual(w.report()['state_reviewed_frames'],1)
            w.save_calibration('video1',[[1,0],[80,0],[80,80],[1,80]],1,confirmed=True)
            self.assertEqual(w.report()['state_reviewed_frames'],0)
            self.assertEqual(read_csv_rows(w.root/'annotations.csv')[0]['state_gt'],'Unknown')

    def test_mask_only_review_does_not_require_map_or_fabricate_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepare_pilot(self.make_input(root),root/'review');w=PilotWorkspace(root/'review')
            _,mask=w.images(0)
            w.review(0,mask,mask_reviewed=True)
            self.assertEqual(w.report()['mask_reviewed_frames'],1)
            self.assertEqual(w.rows[0]['state_gt'],'Unknown')
            self.assertEqual(len(read_csv_rows(w.root/'segmentation_reviewed.csv')),1)
            with self.assertRaises(ValueError):w.review(0,np.full(mask.shape,127,np.uint8),mask_reviewed=True)

    def test_rejects_degenerate_corners_and_invalid_pairs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepare_pilot(self.make_input(root),root/'review');w=PilotWorkspace(root/'review')
            with self.assertRaises(ValueError):w.save_calibration('video1',[[0,0]]*4,1,confirmed=True)
            with self.assertRaises(ValueError):w.save_calibration('video1',[[0,0],[80,0],[80,80],[0,80]],0,confirmed=True)
            _,mask=w.images(0)
            with self.assertRaises(ValueError):w.review(0,mask,source=421,target=2)

    def test_dark_orange_and_border_objects_are_not_selected_as_droplet(self):
        image=np.full((80,80,3),[5,20,100],np.uint8)
        image[:,0:15]=0;cv2.circle(image,(48,40),8,(20,20,20),-1)
        mask=draft_mask(image)
        self.assertEqual(mask[40,48],255)
        self.assertFalse(mask[:,0:15].any())
        self.assertFalse(mask[0].any())
        self.assertFalse(mask[70,70])

    def test_physical_metadata_does_not_confirm_image_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepare_pilot(self.make_input(root),root/'review');w=PilotWorkspace(root/'review')
            w.confirm_layout(3.2)
            self.assertEqual(w.report()['physical_layout']['pitch_mm'],3.2)
            self.assertEqual(w.report()['confirmed_maps'],0)

    def test_added_frames_keep_provenance_and_unreviewed_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepare_pilot(self.make_input(root),root/'review');w=PilotWorkspace(root/'review')
            index=w.add_frame('clip1',2)
            self.assertEqual(w.rows[index]['source_frame_id'],2)
            self.assertEqual(w.rows[index]['roi_x'],12)
            self.assertEqual(w.rows[index]['state_gt'],'Unknown')
            self.assertEqual(w.rows[index]['mask_path'],'')
            with self.assertRaises(ValueError):w.add_frame('clip1',2)
            with self.assertRaises(ValueError):w.add_frame('clip1',3)

    def test_launcher_handles_unicode_and_trailing_directory_separator(self):
        from scripts.annotate_camera_pilot import main
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dataset=self.make_input(root);output=root/'\u6807\u6ce8'
            main(['prepare','--dataset',str(dataset),'--output',str(output)])
            launcher=(output/'\u542f\u52a8\u6807\u6ce8.cmd').read_bytes()
            self.assertFalse(launcher.startswith(b'\xef\xbb\xbf'))
            self.assertNotIn(b'\r\r\n',launcher)
            self.assertIn(b'chcp 65001',launcher)
            self.assertIn(b'%~dp0.',launcher)

    def test_stale_window_cannot_overwrite_saved_annotations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepare_pilot(self.make_input(root),root/'review')
            first=PilotWorkspace(root/'review');second=PilotWorkspace(root/'review')
            _,mask=first.images(0);first.review(0,mask,mask_reviewed=True)
            with self.assertRaisesRegex(OSError,'another window'):second.review(0,mask,mask_reviewed=False)
            self.assertTrue(PilotWorkspace(root/'review').rows[0]['mask_reviewed'])


if __name__=='__main__':unittest.main()
