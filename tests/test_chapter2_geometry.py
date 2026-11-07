"""B3 hand-computable fixtures. These are not measured droplet research data."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
import yaml

from dmf.vision import features
from dmf.vision.calibration import ArrayGridCalibration, Roi
from dmf.vision.config import load_electrode_map
from dmf.vision.contracts import FramePacket, VisionResult, DropletState as S
from dmf.vision.electrode_map import ElectrodeMap
from dmf.experiment.perception import PriorFeatures, Observation, StateRecognizer
from dmf.experiment.config import StateConfig, ControlConfig
from dmf.experiment.policy import EventController, Decision


class GeometryTests(unittest.TestCase):
    def map(self, overrides=None):
        return ElectrodeMap.from_calibration(ArrayGridCalibration(
            ((0,0),(400,0),(400,400),(0,400)), pitch_mm=1.), overrides)

    def test_same_intersection_has_distinct_droplet_and_electrode_denominators(self):
        self.assertTrue(hasattr(features, 'region_overlap'), 'dual-denominator overlap is missing')
        mask = np.zeros((40,40), np.uint8); region = mask.copy()
        region[10:30,10:30] = 255  # 400 electrode pixels
        mask[5:25,10:15] = 255   # 100 droplet pixels, 75 in electrode
        overlap = features.region_overlap(mask, region)
        self.assertTrue(overlap.valid)
        self.assertEqual((overlap.intersection_px,overlap.droplet_area_px,overlap.electrode_area_px), (75,100,400))
        self.assertAlmostEqual(overlap.eta_droplet, .75)
        self.assertAlmostEqual(overlap.rho_electrode, .1875)

    def test_small_and_large_droplet_are_not_conflated(self):
        self.assertTrue(hasattr(features, 'region_overlap'))
        electrode = np.zeros((40,40), np.uint8); electrode[10:30,10:30]=255
        small = np.zeros_like(electrode); small[15:25,15:25]=255
        a=features.region_overlap(small,electrode)
        b=features.region_overlap(np.full_like(electrode,255),electrode)
        self.assertEqual((a.eta_droplet,a.rho_electrode),(1.,.25))
        self.assertEqual((b.eta_droplet,b.rho_electrode),(.25,1.))

    def test_unknown_or_empty_overlap_denominator_is_not_zero_filled(self):
        self.assertTrue(hasattr(features, 'region_overlap'))
        full=np.ones((4,4),np.uint8); empty=np.zeros_like(full)
        for a,b in ((empty,full),(full,empty)):
            overlap=features.region_overlap(a,b)
            self.assertFalse(overlap.valid)
            self.assertIsNone(overlap.rho_electrode)
        clipped=features.region_overlap(full,full,region_complete=False)
        self.assertFalse(clipped.valid); self.assertIsNone(clipped.rho_electrode)

    def test_signed_projection_and_lateral_error_are_hand_calculable(self):
        self.assertTrue(hasattr(features, 'transport_projection'), 'directional features are absent')
        horizontal=features.transport_projection((3.,2.),(1.,1.),(5.,1.))
        self.assertEqual((horizontal.progress_mm,horizontal.progress_fraction,horizontal.lateral_error_mm),(2.,.5,1.))
        reverse=features.transport_projection((0.,1.),(1.,1.),(5.,1.))
        self.assertEqual(reverse.progress_mm,-1.)
        diagonal=features.transport_projection((1.,2.),(0.,0.),(3.,4.))
        self.assertAlmostEqual(diagonal.progress_mm,2.2)
        self.assertAlmostEqual(diagonal.lateral_error_mm,.4)
        with self.assertRaises(ValueError):features.transport_projection((1,1),(0,0),(0,0))

    def test_override_center_and_distance_use_the_same_actual_geometry(self):
        mapped=self.map({191:((230,180),(250,180),(250,200),(230,200))})
        self.assertAlmostEqual(mapped[191].center_mm[0],12.)
        self.assertAlmostEqual(mapped[191].polygon_mm[0][0],11.5)
        packet=FramePacket('fixture',0,0.,'video_pts',np.zeros((400,400,3),np.uint8))
        result=VisionResult(None,(240.,190.),10,1,0,True)
        common=features.DropletFeatureExtractor(mapped).extract(packet,result,190,191)
        self.assertAlmostEqual(common.distance_to_target_mm,0.)

    def test_direction_velocity_uses_elapsed_time_not_frame_count(self):
        extractor=features.DropletFeatureExtractor(self.map())
        def at(i,t,p):
            packet=FramePacket('fixture',i,t,'video_pts',np.zeros((400,400,3),np.uint8))
            return extractor.extract(packet,VisionResult(None,p,10,1,0,True),190,191)
        a=at(0,1.,(190.,190.)); b=at(9,1.5,(200.,194.))
        self.assertTrue(hasattr(b,'velocity_parallel_mm_s'))
        self.assertIsNone(a.velocity_parallel_mm_s)
        self.assertAlmostEqual(b.velocity_parallel_mm_s,1.,places=5)
        self.assertAlmostEqual(b.lateral_error_mm,.2,places=5)
        self.assertIsNone(at(10,1.5,(210.,190.)).velocity_parallel_mm_s)
        self.assertAlmostEqual(at(11,2.,(190.,190.)).velocity_parallel_mm_s,-1.,places=5)

    def test_velocity_does_not_subtract_different_timestamp_domains(self):
        from dmf.vision.contracts import FrameTiming
        extractor=features.DropletFeatureExtractor(self.map())
        image=np.zeros((400,400,3),np.uint8)
        a=FramePacket('v',0,1.,'video_pts',image,FrameTiming(clock_domain='video_relative'))
        b=FramePacket('v',1,1.5,'host_receive_monotonic',image,FrameTiming(clock_domain='host_monotonic'))
        extractor.extract(a,VisionResult(None,(190.,190.),10,1,0,True),190,191)
        f=extractor.extract(b,VisionResult(None,(200.,190.),10,1,0,True),190,191)
        self.assertIsNone(f.velocity_mm_s)
        self.assertIsNone(f.velocity_parallel_mm_s)

    def test_prior_does_not_share_a_time_origin_between_videos(self):
        prior=PriorFeatures(self.map(),StateConfig(min_area_px=1))
        def at(video,t,x):
            image=np.zeros((400,400,3),np.uint8); mask=np.zeros((400,400),np.uint8)
            cv2.circle(mask,(x,190),5,255,-1)
            return prior.extract(FramePacket(video,0,t,'video_pts',image),
                VisionResult(mask,(x,190),81,1,0,True),190,191,[])
        at('a',1.,190)
        self.assertIsNone(at('b',1.1,192).velocity)

    def test_detached_source_residual_is_not_reported_as_zero(self):
        mapped=self.map(); mask=np.zeros((400,400),np.uint8)
        mask[185:190,185:190]=255; mask[185:190,205:220]=255
        packet=FramePacket('v',0,0.,'video_pts',np.zeros((400,400,3),np.uint8))
        result=VisionResult(mask,(210.,187.),100,1,0,True)
        f=features.DropletFeatureExtractor(mapped).extract(packet,result,190,191)
        self.assertEqual((f.source_coverage,f.target_coverage),(.25,.75))
        obs=PriorFeatures(mapped,StateConfig(min_area_px=1)).extract(packet,result,190,191,[])
        self.assertFalse(obs.valid);self.assertEqual(obs.error,'AMBIGUOUS_MASK')

    def test_prior_outputs_source_residual_rho_and_only_caches_needed_regions(self):
        prior=PriorFeatures(self.map(),StateConfig(min_area_px=1))
        image=np.zeros((400,400,3),np.uint8); mask=np.zeros((400,400),np.uint8)
        mask[185:195,195:205]=255
        result=VisionResult(mask,(199.5,189.5),100,1,0,True)
        obs=prior.extract(FramePacket('v',0,0.,'video_pts',image),result,190,191,[])
        self.assertTrue(hasattr(obs,'rho_target'))
        # Inclusive rasterization shares boundary column 200, but definitions stay explicit.
        self.assertAlmostEqual(obs.eta_source, .6)
        self.assertAlmostEqual(obs.eta_target, .5)
        self.assertEqual(obs.source_intersection_px,60)
        self.assertAlmostEqual(obs.rho_target,50/441)
        self.assertEqual(len(prior.extractor.region_mask_cache),2)

    def test_clipped_electrode_rho_is_unknown(self):
        mapped=self.map({191:((390,180),(420,180),(420,200),(390,200))})
        extractor=features.DropletFeatureExtractor(mapped)
        mask=np.zeros((400,400),np.uint8); mask[185:195,390:398]=255
        obs=extractor.extract(FramePacket('v',0,0.,'video_pts',np.zeros((400,400,3),np.uint8)),
            VisionResult(mask,(394.,190.),80,1,0,True),190,191)
        self.assertTrue(hasattr(obs,'target_electrode_coverage'))
        self.assertIsNone(obs.target_electrode_coverage)
        self.assertIn('REGION_CLIPPED',obs.geometry_quality)

    def test_coverage_alone_cannot_arrive_outside_target_position(self):
        cfg=StateConfig(consistency_frames=1,arrival_frames=1,arrival_duration_s=0)
        self.assertIn('target_position_ok',Observation.__dataclass_fields__)
        obs=Observation(True,(1,1),100,0.,.99,10.,0.,None,True,True,
                        target_position_ok=False)
        self.assertNotEqual(StateRecognizer(cfg).recognize(obs,0.),S.ARRIVED)
        self.assertEqual(StateRecognizer(cfg).recognize(replace(obs,target_position_ok=True),0.),S.ARRIVED)

    def test_progress_watchdog_uses_directed_progress_not_lateral_distance_gain(self):
        self.assertIn('progress_mm',Observation.__dataclass_fields__)
        controller=EventController([190,191],ControlConfig(wait_s=1,attempt_timeout_s=10))
        controller.accept(Decision('Start',191),0.)
        def obs(distance):return Observation(True,(1,1),100,.4,.4,distance,1.,None,True,True,progress_mm=.2)
        controller.decide(S.MOVING,0.,observation=obs(10.))
        self.assertEqual(controller.decide(S.MOVING,1.01,observation=obs(1.)).action,'Retry')

    def test_degenerate_crossed_reversed_or_nonfinite_corners_are_rejected(self):
        invalid=[((0,0),)*4,((0,0),(2,2),(0,2),(2,0)),
                 ((0,0),(0,2),(2,2),(2,0)),((0,0),(1,0),(2,0),(3,0)),
                 ((0,0),(2,0),(2,float('nan')),(0,2))]
        for corners in invalid:
            with self.subTest(corners=corners), self.assertRaises(ValueError):ArrayGridCalibration(corners)

    def test_invalid_pitch_and_singular_homography_are_rejected(self):
        for pitch in (0.,-1.,float('inf'),True):
            with self.subTest(pitch=pitch),self.assertRaises(ValueError):
                ArrayGridCalibration(((0,0),(20,0),(20,20),(0,20)),pitch_mm=pitch)
        calibration=self.map().calibration
        with self.assertRaises(ValueError):calibration._transform([(1,1)],np.zeros((3,3)))

    def test_map_loader_rejects_fractional_dimensions_and_boolean_pitch(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'map.yaml'
            for invalid in (dict(rows=20.5),dict(pitch_mm=True)):
                path.write_text(yaml.safe_dump(dict(core_corners_px=[[0,0],[400,0],[400,400],[0,400]],**invalid)),encoding='utf8')
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):load_electrode_map(path)

    def test_invalid_override_polygon_is_rejected(self):
        for polygon in (((1,1),)*3,((0,0),(2,2),(0,2),(2,0)),((0,0),(1,0),(float('nan'),1))):
            with self.subTest(polygon=polygon),self.assertRaises(ValueError):self.map({191:polygon})

    def test_roi_requires_valid_bounds_and_translation_keeps_mm_coordinates(self):
        roi=Roi(100,120,200,180)
        self.assertTrue(hasattr(roi,'validate_for_frame'), 'ROI silently clamps incorrect coordinates')
        roi.validate_for_frame((400,400,3))
        for invalid in (Roi(-1,0,10,10),Roi(0,0,0,10),Roi(390,0,20,10)):
            with self.assertRaises(ValueError):invalid.validate_for_frame((400,400,3))
        self.assertTrue(hasattr(self.map().calibration,'for_roi'))
        original=self.map().calibration; local=original.for_roi(roi,(400,400,3))
        for a,b in zip(local.pixel_to_mm((40.,30.)),original.pixel_to_mm((140.,150.))):
            self.assertAlmostEqual(a,b,places=12)

    def test_roi_map_loader_translates_reference_coordinates_and_check_points_together(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'map.yaml'
            path.write_text(yaml.safe_dump(dict(core_corners_px=[[0,0],[400,0],[400,400],[0,400]],pitch_mm=1.,
                coordinate_frame='full_frame',roi=[100,120,200,180],reference_image_size_px=[400,400],
                validation_points=[dict(pixel_px=[140,150],reference_mm=[7.,7.5],independent=True,location='center')],
                validation_tolerance_mm=.01)),encoding='utf8')
            mapped=load_electrode_map(path)
            self.assertAlmostEqual(mapped.quality_manifest()['independent_validation']['center']['max_error_mm'],0.,places=10)
            self.assertAlmostEqual(mapped.calibration.pixel_to_mm((40,30))[0],7.)

    def test_saving_map_retains_independent_validation_references(self):
        from dmf.vision.config import save_electrode_map
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'map.yaml'; output=Path(td)/'saved.yaml'
            path.write_text(yaml.safe_dump(dict(core_corners_px=[[0,0],[400,0],[400,400],[0,400]],pitch_mm=1.,
                validation_points=[dict(pixel_px=[140,150],reference_mm=[7.,7.5],independent=True,location='edge')],
                validation_tolerance_mm=.01)),encoding='utf8')
            save_electrode_map(output,load_electrode_map(path))
            manifest=load_electrode_map(output).quality_manifest()
            self.assertEqual(manifest['independent_validation']['edge']['count'],1)

    def test_loader_tracks_map_hash_template_status_and_rejects_image_scale_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'map.yaml'
            path.write_text(yaml.safe_dump(dict(core_corners_px=[[0,0],[400,0],[400,400],[0,400]],
                pitch_mm=1.,image_size_px=[400,400],map_version='manual-fixture')),encoding='utf8')
            mapped=load_electrode_map(path)
            self.assertTrue(hasattr(mapped,'quality_manifest'), 'map quality is not auditable')
            quality=mapped.quality_manifest()
            self.assertEqual(quality['template_region_count'],420)
            self.assertFalse(quality['physical_calibration_verified'])
            self.assertEqual(len(quality['map_sha256']),64)
            with self.assertRaises(ValueError):mapped.validate_frame_shape((200,200,3))


if __name__=='__main__':unittest.main()
