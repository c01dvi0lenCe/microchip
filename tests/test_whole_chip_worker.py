import csv
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
from dmf.vision.contracts import FramePacket, FrameTiming

try:
    from dmf.vision.whole_chip import WholeChipDetector
except ImportError:
    WholeChipDetector=None


class FakePredictor:
    batch_size=4; device='software_fixture'; batch_parity_different_pixels=0
    def predict_batch(self,images):
        return [np.where(im[:,:,0]<50,255,0).astype(np.uint8) for im in images]


class WholeChipWorkerTests(unittest.TestCase):
    def packet(self,i=0):
        im=np.full((650,820,3),200,np.uint8); im[300:470,330:430]=0; im[2,2]=0
        return FramePacket('fixture',i,i*.1,'synthetic_fixture',im,
            FrameTiming(capture_frame_id=i,receive_monotonic_ns=100000000+i*100000000,
                        device_ticks_raw=999+i,clock_domain='fixture_not_host',timing_quality='synthetic_test'))

    def start(self,path,predictor=None):
        self.assertIsNotNone(WholeChipDetector,'Whole-chip worker missing')
        detector=WholeChipDetector(lambda:predictor or FakePredictor(),Path(path))
        self.addCleanup(lambda:(detector.stop(),detector.worker.join(4)))
        return detector

    def result(self,detector):
        until=time.monotonic()+5
        while time.monotonic()<until:
            value=detector.poll_result()
            if value is not None:return value
            time.sleep(.005)
        self.fail('no detection result')

    def test_native_complete_mask_snapshot_and_all_components(self):
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run'); packet=self.packet(); d.submit(packet)
            packet.image_bgr[:]=255
            r=self.result(d)
            self.assertEqual(r.packet.frame_id,0); self.assertEqual(r.mask.shape,(650,820))
            self.assertEqual(int((r.mask>0).sum()),17001)
            self.assertEqual(sorted(x['area_px'] for x in r.components),[1,17000])
            self.assertEqual(r.packet.timing.device_ticks_raw,999)
            d.stop(); d.worker.join(2)
            m=json.loads((Path(t)/'run/manifest.json').read_text(encoding='utf-8'))
            self.assertFalse(m['control_output']); self.assertFalse(m['physical_exposure_verified'])

    def test_failure_never_publishes_partial_mask(self):
        class Failing(FakePredictor):
            batch_size=1
            def __init__(self):self.n=0
            def predict_batch(self,images):
                self.n+=1
                if self.n==2:raise RuntimeError('injected midframe failure')
                return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run',Failing()); d.submit(self.packet()); r=self.result(d)
            self.assertIsNone(r.mask); self.assertIn('injected',r.error)
            d.stop(); d.worker.join(2)

    def test_latest_only_queue_and_stop_prevents_following_inference(self):
        entered=threading.Event(); release=threading.Event()
        class Slow(FakePredictor):
            def predict_batch(self,images):
                entered.set(); release.wait(3); return super().predict_batch(images)
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run',Slow()); d.submit(self.packet(0)); self.assertTrue(entered.wait(1))
            d.submit(self.packet(1)); d.submit(self.packet(2)); d.submit(self.packet(3))
            self.assertEqual(d.queue_overwrites,2)
            d.stop(); release.set(); d.worker.join(3)
            self.assertFalse(d.worker.is_alive()); self.assertIsNone(d.poll_result())
            self.assertFalse(d.submit(self.packet(4)))

    def test_initialization_error_is_visible_and_journal_sealed(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNotNone(WholeChipDetector)
            def fail():raise RuntimeError('missing model')
            d=WholeChipDetector(fail,Path(t)/'run'); d.worker.join(2)
            self.assertIn('missing model',d.error)
            self.assertTrue((Path(t)/'run/manifest.json').exists())

    def test_duplicates_do_not_count_as_fresh_detections(self):
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run'); packet=self.packet(1)
            self.assertTrue(d.submit(packet)); self.assertFalse(d.submit(packet)); self.result(d)
            self.assertEqual(d.duplicate_frames,1)
            d.stop(); d.worker.join(2)

    def test_stop_remains_nonblocking_while_journal_flushes(self):
        entered=threading.Event();release=threading.Event();returned=threading.Event()
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run')
            close=d.log.close
            def slow_close():entered.set();release.wait(2);close()
            with patch.object(d.log,'close',side_effect=slow_close):
                d.stop();self.assertTrue(entered.wait(1))
                caller=threading.Thread(target=lambda:(d.stop(),returned.set()))
                caller.start()
                try:self.assertTrue(returned.wait(.1),'stop waits on blocking log flush')
                finally:release.set();caller.join(2);d.worker.join(2)

    def test_delivered_sdk_gaps_not_claimed_as_independent_capture_loss(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run')
            one=self.packet(0);one=replace(one,timing=replace(one.timing,capture_frame_id=10,queue_overwrites=0))
            d.submit(one);self.result(d)
            two=self.packet(1);two=replace(two,timing=replace(two.timing,capture_frame_id=14,queue_overwrites=3))
            d.submit(two);self.result(d);d.stop();d.worker.join(2)
            m=json.loads((Path(t)/'run/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(m['delivered_sdk_number_gaps'],3)
            self.assertIsNone(m['sdk_capture_skips'])
            self.assertEqual(m['source_queue_overwrites'],3)

    def test_low_light_and_preview_replacements_are_persisted_diagnostics(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as t:
            d=self.start(Path(t)/'run');p=self.packet();p=replace(p,image_bgr=np.zeros_like(p.image_bgr))
            d.note_preview_overwrite();d.note_preview_overwrite();d.submit(p)
            r=self.result(d);self.assertIn('low_brightness',r.quality_diagnostic)
            d.stop();d.worker.join(2)
            m=json.loads((Path(t)/'run/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(m['preview_queue_overwrites'],2)


if __name__=='__main__':unittest.main()
