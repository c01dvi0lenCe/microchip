import json
import tempfile
import unittest
import threading
import time
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import Future

from controllers.recording_vision import RecordingVisionMixin


class Value:
    def __init__(self,value=True):self.value=value
    def get(self):return self.value


class Detector:
    def __init__(self,output):
        self.output=output;self.ready=False;self.error='';self.alive=True;self.finished=False
        self.worker=SimpleNamespace(is_alive=lambda:self.alive)
        self.log=SimpleNamespace(error='')
    def finish(self):self.finished=True
    def stop(self):self.alive=False


class App(RecordingVisionMixin):
    def __init__(self,folder):
        self.camera_running=True;self.camera_recording=False;self._vision_accepting=False
        self._vision_detector=None;self.callbacks=[];self.commands=[];self.logs=[];self.states=[]
        self.root=SimpleNamespace(after=lambda ms,callback:self.callbacks.append(callback))
        self.btn_camera_record=SimpleNamespace(config=lambda **kw:self.states.append(kw))
        self.vision_status_var=SimpleNamespace(set=lambda text:None,get=lambda:'model missing')
        self.recording_vision_var=Value();self._recording_vision=None;self.folder=folder
    def log(self,text):self.logs.append(text)
    def start_realtime_detection(self,**kwargs):
        self._vision_detector=Detector(self.folder/'detection');self._vision_accepting=True;return True
    def _submit_camera_recording_command(self,*args):self.commands.append(args)


class RecordingVisionTests(unittest.TestCase):
    def test_camera_button_uses_linked_lifecycle_and_ack_hook(self):
        from controllers.camera_controller import CameraControllerMixin
        with tempfile.TemporaryDirectory() as tmp:
            app=App(Path(tmp));app.is_simulation_mode=lambda:False
            app._camera_recording_output_path=lambda:Path(tmp)/'capture.avi'
            CameraControllerMixin.toggle_camera_recording(app)
            self.assertIsNotNone(app._recording_vision)
            app._vision_detector.ready=True;app.callbacks.pop(0)()
            app.camera_recording_timer_label=SimpleNamespace(config=lambda **kw:None)
            app._update_camera_recording_timer=lambda:None
            future=Future();future.set_result(str(Path(tmp)/'capture.avi'))
            CameraControllerMixin._poll_camera_recording_command(app,future,'start_recording')
            self.assertEqual(app._recording_vision['data']['status'],'recording')

    def test_missing_model_keeps_video_and_marks_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=App(Path(tmp));app.start_realtime_detection=lambda **kw:False
            video=Path(tmp)/'capture.avi';app._begin_linked_recording(video)
            self.assertEqual(app.commands,[('start_recording',video)])
            app._recording_vision_finished(video)
            data=json.loads(video.with_suffix('.vision-session.json').read_text())
            self.assertEqual(data['status'],'incomplete');self.assertTrue(data['errors'])

    def test_disabled_link_preserves_independent_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=App(Path(tmp));app.recording_vision_var.value=False
            self.assertFalse(app._begin_linked_recording(Path(tmp)/'capture.avi'))
            self.assertIsNone(app._vision_detector)

    def test_cancel_preparation_does_not_later_start_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=App(Path(tmp));app._begin_linked_recording(Path(tmp)/'capture.avi')
            app.camera_running=False;app._abort_recording_vision('camera_closed')
            app._vision_detector.alive=False
            while app.callbacks:app.callbacks.pop(0)()
            self.assertEqual(app.commands,[])
            self.assertEqual(json.loads((Path(tmp)/'capture.vision-session.json').read_text())['status'],'incomplete')

    def test_start_failure_is_persisted_and_rapid_repeated_start_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=App(Path(tmp));video=Path(tmp)/'capture.avi'
            app._begin_linked_recording(video);first=app._vision_detector
            app._begin_linked_recording(Path(tmp)/'second.avi')
            self.assertIs(app._vision_detector,first)
            app._recording_vision_finished(None,error='start_recording_failed: fixture')
            first.alive=False
            while app.callbacks:app.callbacks.pop(0)()
            self.assertEqual(app.commands,[])
            self.assertIn('start_recording_failed: fixture',json.loads(video.with_suffix('.vision-session.json').read_text())['errors'])

    def test_waits_for_model_then_links_video_and_flushes_masks_before_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=App(Path(tmp));video=Path(tmp)/'capture.avi'
            self.assertTrue(app._begin_linked_recording(video))
            self.assertEqual(app.commands,[])
            detector=app._vision_detector;detector.ready=True
            app.callbacks.pop(0)()
            self.assertEqual(app.commands,[('start_recording',video)])
            app._recording_vision_started(video)
            app._recording_vision_stopping()
            self.assertFalse(app._vision_accepting);self.assertTrue(detector.finished)
            app._recording_vision_finished(video)
            sidecar=video.with_suffix('.vision-session.json')
            self.assertEqual(json.loads(sidecar.read_text())['status'],'saving_detection')
            detector.alive=False
            detector.output.mkdir();(detector.output/'manifest.json').write_text('{}')
            while app.callbacks:app.callbacks.pop(0)()
            data=json.loads(sidecar.read_text())
            self.assertEqual(data['status'],'saved');self.assertFalse(data['control_output'])
            self.assertIn('electrodes',data['recording_sidecars'])
            self.assertIn('recording_start_ack_monotonic_ns',data)
            self.assertIsNone(app._recording_vision)

    def test_graceful_finish_rejects_new_frames_and_saves_current_complete_mask(self):
        from dmf.vision.whole_chip import WholeChipDetector
        from dmf.vision.priority_vision import PriorityVisionDetector
        from dmf.vision.task_regions import TaskRegion
        from dmf.vision.contracts import FramePacket
        for kind in ('whole','priority'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                entered=threading.Event();release=threading.Event()
                class Predictor:
                    batch_size=1;device='fixture'
                    def predict_batch(self,images):
                        entered.set();release.wait(3)
                        return [np.full((512,512),255,np.uint8) for _ in images]
                output=Path(tmp)/'detector'
                if kind=='whole':detector=WholeChipDetector(Predictor,output,save_masks=True)
                else:detector=PriorityVisionDetector(Predictor,output,[TaskRegion('watch',(0,0,600,600))],
                    clock_policy='replay',max_task_age_s=10,inspection_enabled=False)
                try:
                    image=np.zeros((600,600,3),np.uint8)
                    detector.submit(FramePacket('fixture',0,0.,'fixture',image))
                    self.assertTrue(entered.wait(2))
                    detector.finish()
                    if kind=='priority':self.assertFalse(detector.update_regions([]))
                    self.assertFalse(detector.submit(FramePacket('fixture',1,1.,'fixture',image)))
                    release.set();detector.worker.join(4)
                    self.assertFalse(detector.worker.is_alive())
                    self.assertEqual(detector.completed,1)
                    self.assertEqual(len(list(output.rglob('*.png'))),1)
                    self.assertTrue((output/'manifest.json').exists())
                finally:release.set();detector.stop();detector.worker.join(3)


if __name__=='__main__':unittest.main()
