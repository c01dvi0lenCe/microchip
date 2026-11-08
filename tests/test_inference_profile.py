"""Independent timing must preserve the frozen predictor's actual pixels."""
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def implementation():
    name = 'dmf.vision.inference_profile'
    if importlib.util.find_spec(name) is None:
        raise AssertionError('independent inference profiler is not implemented')
    return importlib.import_module(name)


class InferenceProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest('optional Torch dependency unavailable')
        from dmf.vision.g4_model import G4UNetPredictor
        from dmf.segmentation_research.deep_training import image_tensor
        cls.torch = torch
        torch.set_num_threads(2)
        cls.predictor = G4UNetPredictor.__new__(G4UNetPredictor)
        cls.predictor.torch = torch
        cls.predictor.image_tensor = image_tensor
        cls.predictor.device = 'cpu'
        cls.predictor.batch_size = 1
        cls.predictor.manifest = {'fixture': 'tiny_cpu_no_weights'}
        model = torch.nn.Conv2d(3, 1, 1)
        with torch.no_grad():
            model.weight.copy_(torch.tensor([[[[1.]], [[-.7]], [[.3]]]]))
            model.bias.zero_()
        cls.predictor.model = model.eval()

    def test_native_pixels_match_original_for_mixed_shapes(self):
        profile = implementation().profile_infer
        rng = np.random.default_rng(52)
        images = [rng.integers(0, 256, shape, dtype=np.uint8)
                  for shape in ((37, 81, 3), (513, 257, 3), (512, 512, 3))]
        before = [image.copy() for image in images]
        expected = self.predictor._infer(images)
        actual, stages = profile(self.predictor, images)
        for source, snapshot, got, want in zip(images, before, actual, expected):
            np.testing.assert_array_equal(got, want)
            np.testing.assert_array_equal(source, snapshot)
            self.assertEqual(got.shape, source.shape[:2])
            self.assertEqual(got.dtype, np.uint8)
        host_fields = ('preprocess_host_ms', 'h2d_host_ms', 'model_host_ms',
                       'postprocess_host_ms', 'd2h_host_ms', 'restore_host_ms')
        self.assertTrue(all(stages[key] >= 0 for key in host_fields))
        self.assertGreaterEqual(stages['total_host_ms'] + 1e-9, sum(stages[k] for k in host_fields))
        self.assertIsNone(stages['cuda_events_ms'])
        self.assertEqual(stages['backend'], 'cpu')

    def test_rgb_imagenet_and_half_threshold_are_frozen(self):
        profile = implementation().profile_infer
        torch = self.torch
        captured = []
        handle = self.predictor.model.register_forward_pre_hook(lambda model, inputs: captured.append(inputs[0].clone()))
        image = np.full((512, 512, 3), (7, 80, 230), np.uint8)
        try:
            profile(self.predictor, [image])
        finally:
            handle.remove()
        expected = (np.array([230, 80, 7], np.float32) / 255 - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
        np.testing.assert_array_equal(captured[0][0, :, 0, 0].numpy(), expected)
        model = self.predictor.model
        try:
            zero = torch.nn.Conv2d(3, 1, 1)
            with torch.no_grad():
                zero.weight.zero_(); zero.bias.zero_()
            self.predictor.model = zero.eval()
            masks, _ = profile(self.predictor, [image])
            self.assertTrue(np.all(masks[0] == 255))
        finally:
            self.predictor.model = model

    def test_nonfinite_and_invalid_inputs_match_original_rejection(self):
        profile = implementation().profile_infer
        image = np.zeros((20, 30, 3), np.uint8)
        original = self.predictor.model
        class Nonfinite(self.torch.nn.Module):
            def forward(self, x):
                return x[:, :1] * float('nan')
        try:
            self.predictor.model = Nonfinite()
            for operation in (self.predictor._infer, lambda images: profile(self.predictor, images)):
                with self.assertRaisesRegex(ValueError, 'nonfinite U-Net logits'):
                    operation([image])
        finally:
            self.predictor.model = original
        with self.assertRaisesRegex(ValueError, 'uint8 BGR'):
            profile(self.predictor, [image.astype(np.float32)])

    def test_cli_help_loads_no_torch_or_model(self):
        script = ROOT / 'scripts/profile_whole_chip_vision.py'
        self.assertTrue(script.is_file(), 'independent profiling CLI is not implemented')
        code = ('import builtins,runpy,sys\n'
                'original=builtins.__import__\n'
                'def guarded(name,*a,**kw):\n'
                ' if name.split(".")[0] in ("torch","segmentation_models_pytorch"): raise AssertionError("heavy import during help")\n'
                ' return original(name,*a,**kw)\n'
                'builtins.__import__=guarded\n'
                'sys.argv=[sys.argv[1],"--help"]\n'
                'runpy.run_path(sys.argv[0],run_name="__main__")')
        done = subprocess.run([sys.executable, '-c', code, str(script)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('--frame', done.stdout)
        self.assertIn('--skip-gui', done.stdout)

    def test_cli_synthetic_video_strict_parity_and_fresh_outputs(self):
        implementation()
        script = ROOT / 'scripts/profile_whole_chip_vision.py'
        self.assertTrue(script.is_file(), 'independent profiling CLI is not implemented')
        spec = importlib.util.spec_from_file_location('profile_cli', script)
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); package = root / 'package'; package.mkdir()
            (package / 'manifest.json').write_text('{}', encoding='utf-8')
            video = root / 'source.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 5, (520, 400))
            self.assertTrue(writer.isOpened())
            writer.write(np.random.default_rng(5).integers(0, 256, (400, 520, 3), dtype=np.uint8))
            writer.release()
            output = root / 'fresh'
            report = cli.run_profile(package, video, [0], output, skip_gui=True,
                                     predictor_factory=lambda: self.predictor)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(report['frames'][0]['different_pixels'], 0)
            self.assertEqual(report['frames'][0]['tile_count'], 4)
            self.assertGreater(report['frames'][0]['host_stage_totals_ms']['preprocess_host_ms'], 0)
            self.assertIsNone(report['frames'][0]['cuda_event_stage_totals_ms'])
            self.assertEqual(report['tile_timing_summary']['sample_count'], 4)
            self.assertTrue(report['read_only_inputs_verified'])
            self.assertFalse(report['accuracy_evaluated'])
            self.assertTrue((output / 'tiles.csv').is_file())
            self.assertTrue((output / 'masks/frame_000000_profile.png').is_file())
            self.assertTrue((output / 'masks/frame_000000_reference.png').is_file())
            saved = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['status'], 'passed')
            with self.assertRaises(FileExistsError):
                cli.run_profile(package, video, [0], output, skip_gui=True,
                                predictor_factory=lambda: self.predictor)
            with self.assertRaises(ValueError):
                cli.run_profile(package, video, [0], package / 'nested', skip_gui=True,
                                predictor_factory=lambda: self.predictor)

    def test_cuda_events_are_separate_and_pixels_match_when_available(self):
        profile = implementation().profile_infer
        torch = self.torch
        if not torch.cuda.is_available():
            self.skipTest('CUDA unavailable; CPU parity remains exercised')
        from dmf.vision.g4_model import G4UNetPredictor
        predictor = G4UNetPredictor.__new__(G4UNetPredictor)
        predictor.torch = torch; predictor.image_tensor = self.predictor.image_tensor
        predictor.device = 'cuda'
        predictor.model = torch.nn.Conv2d(3, 1, 1).cuda().eval()
        image = np.random.default_rng(42).integers(0, 256, (97, 143, 3), dtype=np.uint8)
        expected = predictor._infer([image])
        actual, stages = profile(predictor, [image])
        np.testing.assert_array_equal(actual[0], expected[0])
        events = stages['cuda_events_ms']
        self.assertTrue(all(value >= 0 for value in events.values()))
        self.assertAlmostEqual(events['stream_span'], sum(value for key, value in events.items() if key != 'stream_span'), places=3)

    def test_cli_png_write_failure_rejects_run_and_seals_failed_summary(self):
        implementation()
        from dmf.vision.image_io import write_image
        script = ROOT / 'scripts/profile_whole_chip_vision.py'
        spec = importlib.util.spec_from_file_location('profile_write_failure_cli', script)
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); package = root / 'package'; package.mkdir()
            (package / 'manifest.json').write_text('{}', encoding='utf-8')
            video = root / 'source.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 5, (64, 48))
            self.assertTrue(writer.isOpened())
            writer.write(np.zeros((48, 64, 3), np.uint8)); writer.release()
            for suffix in ('profile', 'reference'):
                with self.subTest(failed_png=suffix):
                    output = root / f'failed_{suffix}'
                    filename = f'frame_000000_{suffix}.png'
                    def fail_selected_png(path, image):
                        return False if path.name == filename else write_image(path, image)
                    with patch('dmf.vision.image_io.write_image', side_effect=fail_selected_png):
                        with self.assertRaisesRegex(OSError, 'PNG write failed'):
                            cli.run_profile(package, video, [0], output, skip_gui=True,
                                            predictor_factory=lambda: self.predictor)
                    saved = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['status'], 'failed')
                    self.assertIn('PNG write failed', saved['error'])
                    self.assertIn(filename, saved['error'])
                    self.assertFalse((output / 'masks' / filename).exists())
                    self.assertTrue((output / 'tiles.csv').is_file())
                    self.assertTrue(saved['read_only_inputs_verified'])

    def test_gui_measurement_calls_actual_preview_without_camera(self):
        implementation()
        script = ROOT / 'scripts/profile_whole_chip_vision.py'
        self.assertTrue(script.is_file())
        spec = importlib.util.spec_from_file_location('profile_gui_cli', script)
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        result = cli._measure_gui_display(np.zeros((80, 120, 3), np.uint8),
                                          np.zeros((80, 120), np.uint8))
        self.assertEqual(result['status'], 'measured')
        self.assertFalse(result['physical_display_latency_measured'])
        self.assertEqual(set(result['modes']), {'raw', 'overlay', 'mask'})
        for timings in result['modes'].values():
            self.assertGreater(timings['show_camera_frame_host_ms'], 0)


if __name__ == '__main__':
    unittest.main()
