import csv
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import numpy as np
from dmf.vision.contracts import FramePacket,FrameTiming
from dmf.vision.task_regions import TaskRegion,TaskBinding

try:
    from dmf.vision.priority_vision import PriorityVisionDetector
except ImportError:
    PriorityVisionDetector=None


class Predictor:
    device='software_fixture';batch_size=1;manifest={}
    def predict_batch(self,images):
        return [np.where(image[:,:,0]<50,255,0).astype(np.uint8) for image in images]


class PriorityVisionTests(unittest.TestCase):
    def packet(self,frame=0,value=200):
        image=np.full((700,1000,3),value,np.uint8);image[100:140,500:550]=0
        return FramePacket('fixture',frame,frame*.1,'synthetic_fixture',image)

    def build(self,path,regions=(),predictor=None,**settings):
        self.assertIsNotNone(PriorityVisionDetector,'Cooperative priority detector missing')
        return PriorityVisionDetector(lambda:predictor or Predictor(),path,regions,
            clock_policy='replay',**settings)

    def wait(self,detector,region_id=None):
        until=time.monotonic()+4
        while time.monotonic()<until:
            value=detector.poll_result()
            if value is not None and (region_id is None or value.region_id==region_id):return value
            time.sleep(.002)
        self.fail('no matching region observation')

    def end(self,d):
        d.stop();d.worker.join(4);self.assertFalse(d.worker.is_alive())

    def test_task_preempts_scan_after_one_inflight_tile(self):
        entered=threading.Event();release=threading.Event()
        class Slow(Predictor):
            n=0
            def predict_batch(self,images):
                self.n+=1
                if self.n==1:entered.set();release.wait(3)
                return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',predictor=Slow(),max_task_age_s=2)
            try:
                d.submit(self.packet(0));self.assertTrue(entered.wait(1))
                d.update_regions([TaskRegion('watch',(480,80,100,100))]);d.submit(self.packet(1))
                release.set();r=self.wait(d,'watch');self.assertTrue(r.data_valid)
            finally:release.set();self.end(d)
            with (Path(t)/'run/events.csv').open(encoding='utf8') as handle:rows=list(csv.DictReader(handle))
            starts=[r for r in rows if r['event']=='tile_started']
            self.assertEqual([r['region_id'] for r in starts[:2]],['__inspection__','watch'])

    def test_task_mask_is_complete_native_offset_and_owns_one_source(self):
        entered=threading.Event();release=threading.Event()
        class Slow(Predictor):
            n=0
            def predict_batch(self,images):
                self.n+=1
                if self.n==1:entered.set();release.wait(3)
                return super().predict_batch(images)
        region=TaskRegion('large',(0,0,800,600))
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',[region],Slow(),max_task_age_s=3)
            try:
                p=self.packet(0);d.submit(p);self.assertTrue(entered.wait(1))
                p.image_bgr[:]=255;d.submit(self.packet(1,value=255));release.set()
                r=self.wait(d,'large')
                self.assertEqual(r.packet.capture_identity,0);self.assertEqual(r.mask.shape,(600,800))
                self.assertEqual(int((r.mask>0).sum()),2000)
                self.assertEqual(r.components[0]['centroid_px'],(524.5,119.5))
                self.assertEqual(r.tile_count,6);self.assertFalse(r.control_eligible)
            finally:release.set();self.end(d)

    def test_task_round_robin_and_latest_only_rejects_repeat_or_reverse(self):
        with tempfile.TemporaryDirectory() as t:
            regions=[TaskRegion('a',(0,0,800,600)),TaskRegion('b',(480,80,100,100))]
            d=self.build(Path(t)/'run',regions,max_task_age_s=3)
            try:
                self.assertTrue(d.submit(self.packet(0)))
                self.assertFalse(d.submit(self.packet(0)));self.assertFalse(d.submit(self.packet(0)))
                r=self.wait(d,'b');self.assertEqual(r.packet.capture_identity,0)
            finally:self.end(d)
            with (Path(t)/'run/events.csv').open(encoding='utf8') as handle:rows=list(csv.DictReader(handle))
            starts=[r['region_id'] for r in rows if r['event']=='tile_started']
            self.assertEqual(starts[:2],['a','b'])
            self.assertEqual(d.duplicate_frames,2)

    def test_epoch_change_discards_old_work_and_requires_new_frame(self):
        entered=threading.Event();release=threading.Event()
        class Slow(Predictor):
            def predict_batch(self,images):
                entered.set();release.wait(3);return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',[TaskRegion('a',(480,80,100,100))],Slow(),max_task_age_s=3)
            try:
                d.submit(self.packet(0));self.assertTrue(entered.wait(1))
                d.update_regions([TaskRegion('a',(480,80,100,100),epoch=1)])
                release.set();time.sleep(.03)
                values=[]
                while (r:=d.poll_result()) is not None:values.append(r)
                self.assertFalse(any(r.region_id=='a' for r in values))
                d.submit(self.packet(1));r=self.wait(d,'a')
                self.assertEqual(r.epoch,1);self.assertEqual(r.packet.capture_identity,1)
            finally:release.set();self.end(d)

    def test_stale_observation_is_retained_but_invalid_and_no_partial_failure(self):
        class Slow(Predictor):
            def predict_batch(self,images):time.sleep(.03);return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',[TaskRegion('a',(480,80,100,100))],Slow(),max_task_age_s=.005)
            try:
                d.submit(self.packet());r=self.wait(d,'a')
                self.assertFalse(r.data_valid);self.assertIn('stale',r.reason)
                self.assertTrue(r.needs_relocalization)
            finally:self.end(d)
            self.assertTrue(list((Path(t)/'run/masks').rglob('*.png')))

    def test_error_never_publishes_partial_task_mask(self):
        class Bad(Predictor):
            n=0
            def predict_batch(self,images):
                self.n+=1
                if self.n==2:raise RuntimeError('mid-region failure')
                return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',[TaskRegion('a',(0,0,800,600))],Bad())
            try:
                d.submit(self.packet());r=self.wait(d,'a')
                self.assertIsNone(r.mask);self.assertIn('mid-region',r.error);self.assertFalse(r.data_valid)
            finally:self.end(d)

    def test_rolling_scan_labels_per_region_source_and_does_not_fabricate_full_mask(self):
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run')
            try:
                d.submit(self.packet());r=self.wait(d,'__inspection__')
                self.assertEqual(r.kind,'rolling_inspection');self.assertLess(r.mask.size,700*1000)
                self.assertEqual(r.mask.shape,(r.roi[3],r.roi[2]))
                self.assertFalse(r.control_eligible)
            finally:self.end(d)
            m=json.loads((Path(t)/'run/manifest.json').read_text(encoding='utf8'))
            self.assertFalse(m['control_output']);self.assertTrue(m['rolling_regions_not_one_frame'])

    def test_stop_nonblocking_and_no_late_task_publish(self):
        entered=threading.Event();release=threading.Event()
        class Slow(Predictor):
            def predict_batch(self,images):entered.set();release.wait(3);return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',[TaskRegion('a',(480,80,100,100))],Slow())
            try:
                d.submit(self.packet());self.assertTrue(entered.wait(1))
                before=time.perf_counter();d.stop();self.assertLess(time.perf_counter()-before,.1)
                self.assertFalse(d.submit(self.packet(1)));release.set();d.worker.join(3)
                self.assertIsNone(d.poll_result())
            finally:release.set();self.end(d)

    def test_source_change_and_return_does_not_revive_inflight_old_capture(self):
        entered=threading.Event();release=threading.Event()
        class Slow(Predictor):
            def predict_batch(self,images):entered.set();release.wait(3);return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run',[TaskRegion('a',(480,80,100,100))],Slow(),max_task_age_s=3)
            try:
                d.submit(self.packet(0));self.assertTrue(entered.wait(1))
                b=self.packet(0);b=FramePacket('other',0,0.,'synthetic_fixture',b.image_bgr)
                d.submit(b);d.submit(self.packet(1));release.set()
                r=self.wait(d,'a');self.assertEqual(r.packet.capture_identity,1)
            finally:release.set();self.end(d)

    def test_live_receive_age_not_replaced_by_fresh_inference_submission(self):
        self.assertIsNotNone(PriorityVisionDetector,'Cooperative priority detector missing')
        class Counts(Predictor):
            n=0
            def predict_batch(self,images):self.n+=1;return super().predict_batch(images)
        predictor=Counts()
        with tempfile.TemporaryDirectory() as t:
            d=PriorityVisionDetector(lambda:predictor,Path(t)/'run',[TaskRegion('a',(480,80,100,100))],
                                    clock_policy='live',max_task_age_s=.1,inspection_enabled=False)
            try:
                p=self.packet();p=FramePacket(p.video_id,p.frame_id,p.timestamp_s,p.timestamp_source,p.image_bgr,
                    FrameTiming(capture_frame_id=0,receive_monotonic_ns=time.monotonic_ns()-500000000,
                                clock_domain='host_monotonic',timing_quality='host_receive_only'))
                d.submit(p);r=self.wait(d,'a')
                self.assertFalse(r.data_valid);self.assertGreaterEqual(r.source_age_ms,500)
                self.assertEqual(predictor.n,0,'Already stale task input must not occupy GPU')
            finally:self.end(d)

    def test_returning_source_cannot_resubmit_a_previously_accepted_capture(self):
        with tempfile.TemporaryDirectory() as t:
            d=self.build(Path(t)/'run')
            try:
                self.assertTrue(d.submit(self.packet(0)))
                p=self.packet(0)
                self.assertTrue(d.submit(FramePacket('other',0,0.,'synthetic_fixture',p.image_bgr)))
                self.assertFalse(d.submit(self.packet(0)))
            finally:self.end(d)

    def test_calibrated_task_rejected_after_capture_or_full_size_changes(self):
        from tests.test_task_regions import TaskRegionTests
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);design,manifest,reference,conditions,_=TaskRegionTests().fixture(root)
            binding=TaskBinding.load(design,manifest,reference,conditions)
            region=binding.region('bound',190,191,epoch=0,frame_shape=(100,100,3),
                                  acquisition_id='fixture_capture',margin_px=2)
            d=self.build(root/'run',[region],inspection_enabled=False,task_period_s=.001)
            try:
                image=np.full((100,100,3),200,np.uint8)
                d.submit(FramePacket('fixture_capture',0,0.,'fixture',image));self.wait(d,'bound')
                d.submit(FramePacket('other_capture',0,0.,'fixture',np.full((120,120,3),200,np.uint8)))
                time.sleep(.04)
                self.assertIsNone(d.poll_result(),'Changed acquisition must not reuse calibrated task')
                d.submit(FramePacket('fixture_capture',1,.1,'fixture',np.full((120,120,3),200,np.uint8)))
                time.sleep(.04)
                self.assertIsNone(d.poll_result(),'Changed full image size must not reuse calibrated task')
            finally:self.end(d)


if __name__=='__main__':unittest.main()
