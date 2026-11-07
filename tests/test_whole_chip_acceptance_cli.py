import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import csv
from contextlib import redirect_stdout
import io


ROOT = Path(__file__).resolve().parents[1]


class WholeChipAcceptanceCliTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('scripts.verify_whole_chip_replay')
        except ImportError:
            self.fail('Whole-chip acceptance CLI is missing')

    def test_help_does_not_import_optional_runtime_or_hardware(self):
        for name in ('export_g4_model', 'verify_whole_chip_replay'):
            code = (
                "import builtins,runpy,sys\n"
                "old=builtins.__import__\n"
                "def guarded(name,*a,**kw):\n"
                " if name.split('.')[0] in {'torch','cv2','numpy','serial','MvCameraControl_class'}: raise RuntimeError('eager dependency '+name)\n"
                " return old(name,*a,**kw)\n"
                "builtins.__import__=guarded\n"
                f"sys.argv=['{name}','--help']\n"
                f"runpy.run_path('scripts/{name}.py',run_name='__main__')\n"
            )
            run = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('--output', run.stdout)

    def test_selection_uses_real_video_ids_and_30_consecutive_native_frames(self):
        api = self.api()
        videos = [dict(source=f'v{i}.avi', video_id=f'v{i}', sha256=str(i) * 64, frames=200) for i in range(2)]
        rows = [dict(sample_id=f'N1106_{i:03}', parent_video_id='v0',
                     source_frame_id=str(i + 40), source_sha256='0' * 64)
                for i in (90, 91, 92)]
        selected = api.select_replay_frames(dict(videos=videos), rows)
        self.assertEqual(len(selected), 63)
        for vid in ('v0', 'v1'):
            self.assertEqual([r['frame_id'] for r in selected if r['video_id'] == vid and r['kind'] == 'consecutive'], list(range(30)))
        self.assertEqual(sum(r['save_example'] for r in selected), 7)
        self.assertEqual(selected[-3]['sample_id'], 'N1106_090')

    def test_selection_rejects_inconsistent_dark_source_hash(self):
        api = self.api()
        rows = [dict(sample_id=f'N1106_{i:03}', parent_video_id='v0',
                     source_frame_id=str(i), source_sha256='bad') for i in (90, 91, 92)]
        with self.assertRaisesRegex(ValueError, 'hash'):
            api.select_replay_frames(dict(last2=[dict(path='v0.avi', sha256='a'), dict(path='v1.avi', sha256='b')]), rows)

    def test_recorded_timing_is_not_replaced_with_replay_clock(self):
        api = self.api()
        row = dict(video_frame_index='12', sdk_frame_number='444', device_timestamp_raw='12345',
                   sdk_host_timestamp_raw='987', host_receive_monotonic_ns='6000',
                   host_receive_perf_counter_ns='7000', host_utc_ns='8000', receive_relative_s='1.25',
                   timestamp_source='host_receive_perf_counter')
        timing, stamp = api.recorded_timing(row)
        self.assertEqual(stamp, 1.25)
        self.assertEqual(timing.capture_frame_id, 444)
        self.assertEqual(timing.device_ticks_raw, 12345)
        self.assertEqual(timing.receive_perf_counter_ns, 7000)
        self.assertEqual(timing.sdk_host_timestamp_raw, 987)
        self.assertIsNone(timing.exposure_start_ns)
        self.assertIn('recorded', timing.clock_domain)

    def test_output_cannot_overwrite_or_nest_under_inputs(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source'; source.mkdir()
            with self.assertRaises(FileExistsError):
                api.validate_output(source, [source])
            with self.assertRaisesRegex(ValueError, 'separate'):
                api.validate_output(source/'new', [source])

    def test_single_pixel_parity_mismatch_is_failure(self):
        api = self.api()
        import numpy as np
        with self.assertRaisesRegex(ValueError, 'pixel'):
            api.assert_native_parity(np.zeros((2, 3), np.uint8),
                                     np.array([[0, 0, 0], [0, 0, 255]], np.uint8), (2, 3), 'x')

    def fixture(self, tmp):
        import cv2
        import numpy as np
        api = self.api()
        root = Path(tmp)
        package = root/'package'; package.mkdir()
        (package/'manifest.json').write_text('{}', encoding='utf-8')
        roi = root/'roi'; (roi/'frames').mkdir(parents=True)
        reference = root/'reference'; (reference/'masks/unet').mkdir(parents=True)
        image = np.full((32, 32, 3), 240, np.uint8); image[4:8, 8:12] = 0
        mask = np.where(image[:, :, 0] < 50, 255, 0).astype(np.uint8)
        videos = []; files = []
        for i in range(2):
            source = root/f'v{i}.avi'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
            self.assertTrue(writer.isOpened())
            for n in range(40):
                frame = np.full((48, 64, 3), 240, np.uint8); frame[10:20, n:n+4] = 0
                writer.write(frame)
            writer.release()
            timing = source.with_suffix('.timestamps.csv')
            timing_rows = [dict(video_frame_index=n, sdk_frame_number=100+n,
                device_timestamp_raw=1000+n, sdk_host_timestamp_raw=2000+n,
                host_receive_monotonic_ns=3000+n, host_receive_perf_counter_ns=4000+n,
                host_utc_ns=5000+n, receive_relative_s=n*.1,
                timestamp_source='host_receive_perf_counter', width=64, height=48) for n in range(40)]
            api.write_rows(timing, timing_rows)
            videos.append(dict(video_id=f'v{i}', source=str(source), frames=40,
                               width=64, height=48, sha256=api.sha256(source)))
            files.append(dict(path=str(timing), sha256=api.sha256(timing)))
        rows = []; hashes = {}
        for i in range(1, 121):
            sid = f'N1106_{i:03}'
            frame_path = roi/'frames'/f'{sid}.png'
            api._write_png(frame_path, image)
            cached = reference/'masks/unet'/f'{sid}.png'
            api._write_png(cached, mask)
            hashes[f'masks\\unet\\{sid}.png'] = api.sha256(cached)
            rows.append(dict(sample_id=sid, frame_path=f'frames/{sid}.png',
                frame_path_sha256=api.sha256(frame_path), roi_h=32, roi_w=32,
                parent_video_id='v0', source_frame_id=35+i-90 if i in (90, 91, 92) else 0,
                source_sha256=videos[0]['sha256']))
        api.write_rows(roi/'annotations.csv', rows)
        api.write_json(reference/'manifest.json', dict(output_sha256=hashes))
        inventory = root/'inventory.json'
        api.write_json(inventory, dict(videos=videos, source_files=files))

        class Predictor:
            device = 'software_fixture'; batch_size = 1; manifest = {}
            def _infer(self, images):
                return [np.where(im[:, :, 0] < 50, 255, 0).astype(np.uint8) for im in images]
            predict_batch = _infer
            def audit_batch_equivalence(self, images):
                return dict(samples=len(images), different_pixels=0, selected_batch_size=1)
        return package, roi, reference, inventory, Predictor

    def test_fixture_replay_exports_63_masks_and_preserves_provenance_and_input_hashes(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            package, roi, reference, inventory, predictor = self.fixture(tmp)
            output = Path(tmp)/'result'
            with redirect_stdout(io.StringIO()):
                report = api.run_verification(package, roi, reference, inventory, output,
                                              predictor_factory=predictor)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(report['roi_parity_samples'], 120)
            self.assertEqual(report['successful_predictions'], 63)
            self.assertEqual(len(list((output/'masks').glob('*.png'))), 63)
            self.assertEqual(len(list((output/'examples').glob('*_raw.png'))), 7)
            self.assertEqual(len(list((output/'examples').glob('*_overlay.png'))), 7)
            self.assertFalse(report['camera_acceptance'])
            self.assertFalse(report['control_output'])
            self.assertEqual(report['input_sha256_before'], report['input_sha256_after'])
            for relative in ('scripts/verify_whole_chip_replay.py', 'dmf/vision/g4_model.py',
                             'dmf/vision/whole_chip.py', 'dmf/vision/whole_chip_geometry.py'):
                self.assertIn(str((ROOT/relative).resolve()), report['input_sha256_before'])
            self.assertEqual(report['predictions'][0]['sdk_frame_number'], 100)
            self.assertEqual(report['predictions'][0]['device_ticks_raw'], 1000)
            self.assertEqual(report['predictions'][0]['source_frame_id'], 0)
            self.assertEqual(report['predictions'][-1]['source_frame_id'], 37)
            self.assertEqual(report['session']['completed'], 63)
            self.assertEqual(len(api.read_rows(output/'session/frames.csv')), 63)
            self.assertEqual(report['session']['inference_queue_overwrites'], 0)

    def test_frozen_reference_hash_failure_is_saved_without_fabricated_mask(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            package, roi, reference, inventory, predictor = self.fixture(tmp)
            (reference/'masks/unet/N1106_001.png').write_bytes(b'corrupt')
            output = Path(tmp)/'result'
            with self.assertRaisesRegex(ValueError, 'hash'):
                api.run_verification(package, roi, reference, inventory, output,
                                     predictor_factory=predictor)
            report = json.loads((output/'verification.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['successful_predictions'], 0)
            self.assertFalse((output/'masks').exists())
            self.assertIn('hash', report['error'])

    def test_deleted_protected_input_still_produces_failed_verification_journal(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            package, roi, reference, inventory, predictor = self.fixture(tmp)
            class DeletesProtectedInput(predictor):
                def _infer(self, images):
                    (package/'manifest.json').unlink(missing_ok=True)
                    raise RuntimeError('injected source deletion')
            output = Path(tmp)/'result'
            with self.assertRaises(RuntimeError):
                api.run_verification(package, roi, reference, inventory, output,
                                     predictor_factory=DeletesProtectedInput)
            report = json.loads((output/'verification.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'failed')
            self.assertFalse(report['read_only_inputs_verified'])
            self.assertIn(str((package/'manifest.json').resolve()), report['input_changes'])


if __name__ == '__main__':
    unittest.main()
