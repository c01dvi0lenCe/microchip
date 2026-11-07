import tempfile
from pathlib import Path
import unittest

from dmf.chapter2_sim.v2.spec import StudySpecV2
from dmf.chapter2_sim.v2.runner import run_trial_v2
from dmf.chapter2_sim.v2.persistence import save_trial
try:
    from dmf.chapter2_sim.v2.replay import PersistedReplay
except ImportError:
    PersistedReplay=None


class VisualizationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)/'trial'
        save_trial(run_trial_v2(StudySpecV2(),'normal',262000,'F'),cls.path,StudySpecV2())

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def replay(self):
        self.assertIsNotNone(PersistedReplay,'persistent v2 replay missing')
        return PersistedReplay(self.path)

    def test_no_future_processed_mask_displayed(self):
        r=self.replay()
        self.assertIsNone(r.snapshot(0.)['frame'])
        for t in r.times:
            s=r.snapshot(t)
            if s['frame']:self.assertLessEqual(s['frame']['processing_s'],t+1e-9)

    def test_mask_is_exact_persisted_camera_pixels(self):
        import cv2,numpy as np
        r=self.replay();s=next(r.snapshot(t) for t in r.times if r.snapshot(t)['mask'] is not None)
        q=s['capture'];data=np.fromfile(self.path/q['mask_path'],np.uint8)
        np.testing.assert_array_equal(s['mask'],cv2.imdecode(data,cv2.IMREAD_GRAYSCALE))

    def test_epoch_switch_cannot_reuse_old_mask_as_current(self):
        r=self.replay()
        for t in r.times:
            s=r.snapshot(t)
            if s['overlay_mask'] is not None:
                self.assertEqual(s['capture']['capture_epoch'],s['truth']['epoch'])
                self.assertTrue(s['trace']['C0_passed'])

    def test_every_keyframe_is_one_tick_of_one_trial(self):
        r=self.replay();keys=r.keyframes()
        self.assertGreaterEqual(len(keys),4)
        self.assertTrue(all(any(abs(k['time_s']-t)<1e-9 for t in r.times) for k in keys))
        self.assertEqual(r.trial_id,r.data['manifest']['trial_id'])

    def test_refuse_extrapolation(self):
        r=self.replay()
        with self.assertRaises(ValueError):r.snapshot(r.times[-1]+.01)


if __name__=='__main__':unittest.main()
