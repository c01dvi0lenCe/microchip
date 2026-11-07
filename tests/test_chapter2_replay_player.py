import base64
import unittest
from pathlib import Path
import numpy as np
import cv2

try:
    from dmf.chapter2_replay.data import build_bundle,tick_index,audit_bundle
except ImportError:
    build_bundle=tick_index=audit_bundle=None

TRIAL=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1/development_smoke_r2/trials/end_to_end__normal__262000__F')
try:
    from dmf.chapter2_replay.export import render_snapshot,load_verified_bundle
except ImportError:
    render_snapshot=load_verified_bundle=None


class ReplayPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=build_bundle(TRIAL) if build_bundle else None

    def setUp(self):self.assertIsNotNone(self.bundle,'read-only player bundle missing')

    def test_all_original_ticks_no_interpolation(self):
        b=self.bundle;self.assertEqual(len(b['ticks']),412)
        self.assertEqual(b['ticks'][-1]['time_s'],4.11)
        self.assertEqual(tick_index(b,1.925),192)
        with self.assertRaises(ValueError):tick_index(b,4.12)
        with self.assertRaises(ValueError):tick_index(b,-.01)

    def test_exact_event_and_reference_times(self):
        b=self.bundle
        self.assertEqual(b['references'][0]['upper_s'],1.46)
        s=b['ticks'][tick_index(b,1.92)]
        self.assertEqual(s['action'],'Update')
        self.assertEqual([e['event'] for e in s['events_now']],['ArrivalEvent','Update'])
        self.assertEqual(b['ticks'][tick_index(b,1.93)]['action'],'Hold')

    def test_no_stale_mask_overlay_after_epoch_change(self):
        t=self.bundle['ticks'][tick_index(self.bundle,1.96)]
        self.assertFalse(t['overlay_valid']);self.assertEqual(t['truth']['world_active'],191)
        self.assertEqual(t['truth']['target'],192)

    def test_truth_point_remains_without_observation(self):
        t=self.bundle['ticks'][0]
        self.assertIsNone(t['frame']);self.assertIn('x',t['truth']);self.assertFalse(t['overlay_valid'])

    def test_mask_data_is_original_png_and_pixels(self):
        masks=self.bundle['masks'];self.assertGreater(len(masks),0)
        m=next(iter(masks.values()));raw=base64.b64decode(m['data_url'].split(',')[1])
        self.assertEqual(raw,(TRIAL/m['path']).read_bytes())
        np.testing.assert_array_equal(cv2.imdecode(np.frombuffer(raw,np.uint8),0),cv2.imdecode(np.fromfile(TRIAL/m['path'],np.uint8),0))

    def test_audit_detects_changed_event(self):
        from copy import deepcopy
        bad=deepcopy(self.bundle);bad['events'][0]['time_s']+=.01
        self.assertFalse(audit_bundle(bad,TRIAL)['passed'])

    def test_full_audit_and_no_fabricated_events(self):
        a=audit_bundle(self.bundle,TRIAL);self.assertTrue(a['passed'],a)
        self.assertEqual(a['event_mismatches'],[])
        self.assertFalse({'Retry','Recovery'} & {e['event'] for e in self.bundle['events']})
        self.assertEqual(set(t['state'] for t in self.bundle['ticks']),{'Unknown','Moving','Partial','Arrived'})

    def test_export_consumes_same_snapshot_without_running_model(self):
        self.assertIsNotNone(render_snapshot,'export renderer missing')
        im=render_snapshot(self.bundle,192)
        self.assertEqual(im.size,(1600,900))
        # No observations at t0 must still render a non-white blue world point.
        before=render_snapshot(self.bundle,0)
        a=np.asarray(before);self.assertGreater(np.sum(np.all(a[:,:,:3]==[23,110,170],axis=2)),100)

    def test_export_refuses_changed_persisted_bundle(self):
        self.assertIsNotNone(load_verified_bundle,'verified export loader missing')
        import tempfile,json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'replay_bundle.json').write_text('{}',encoding='utf-8')
            (p/'source_manifest.json').write_text(json.dumps({'bundle_sha256':'wrong'}),encoding='utf-8')
            with self.assertRaises(ValueError):load_verified_bundle(p)

    def test_h264_encoder_options_are_explicit(self):
        import dmf.chapter2_replay.export as module
        options=getattr(module,'encoder_args',None)
        self.assertIsNotNone(options,'encoder-specific settings missing')
        self.assertNotIn('-crf',options('h264_mf'))
        self.assertIn('-crf',options('libx264'))
        with self.assertRaises(ValueError):options('unverified_codec')

    def test_audit_rejects_changed_geometry(self):
        from copy import deepcopy
        bad=deepcopy(self.bundle);bad['geometry']['polygons']['190'][0][0]+=.1
        self.assertFalse(audit_bundle(bad,TRIAL)['passed'])

    def test_audit_rejects_wrong_mask_frame_association(self):
        from copy import deepcopy
        bad=deepcopy(self.bundle);keys=list(bad['masks'])[:2]
        bad['masks'][keys[0]],bad['masks'][keys[1]]=bad['masks'][keys[1]],bad['masks'][keys[0]]
        self.assertFalse(audit_bundle(bad,TRIAL)['passed'])

    def test_video_index_audit_preserves_unknown_active_electrode(self):
        import scripts.verify_chapter2_replay_player as module
        parse=getattr(module,'csv_value',None)
        self.assertIsNotNone(parse,'CSV null parser missing')
        self.assertIsNone(parse('',None))
        self.assertEqual(parse('0',0),0)
        self.assertEqual(parse('Hold','Hold'),'Hold')


if __name__=='__main__':unittest.main()
