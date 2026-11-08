"""Bit-exact gates for the opt-in native 512 single-tile implementation."""
import importlib
import importlib.util
import unittest
from unittest.mock import patch

import numpy as np


def native_implementation():
    name = 'dmf.vision.native_inference'
    if importlib.util.find_spec(name) is None:
        raise AssertionError('native single-tile implementation is missing')
    return importlib.import_module(name)


class NativeInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest('optional Torch dependency unavailable')
        from dmf.segmentation_research.deep_training import image_tensor
        from dmf.vision.g4_model import G4UNetPredictor
        cls.torch = torch; cls.image_tensor = staticmethod(image_tensor)
        cls.original_class = G4UNetPredictor
        cls.previous_threads = torch.get_num_threads(); torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls):
        cls.torch.set_num_threads(cls.previous_threads)

    def fixture(self, device='cpu'):
        cls = native_implementation().NativeTileG4Predictor
        predictor = cls.__new__(cls)
        predictor.torch = self.torch; predictor.image_tensor = self.image_tensor
        predictor.device = device; predictor.batch_size = 1
        model = self.torch.nn.Conv2d(3, 1, 1)
        with self.torch.no_grad():
            model.weight.copy_(self.torch.tensor([[[[1.]], [[-.7]], [[.3]]]]))
            model.bias.zero_()
        predictor.model = model.to(device).eval()
        return predictor

    def test_native_tensor_is_exact_for_random_uint8_and_every_intensity(self):
        native_tensor = native_implementation().native_tensor
        from dmf.segmentation_research.semantic_baselines import prepare_image
        pattern = np.arange(512 * 512 * 3, dtype=np.int64).reshape(512, 512, 3).astype(np.uint8)
        random = np.random.default_rng(783).integers(0, 256, (512, 512, 3), dtype=np.uint8)
        for image in (pattern, random, random[::-1, ::-1]):
            with self.subTest(contiguous=image.flags.c_contiguous):
                before = image.copy()
                prepared, _ = prepare_image(image)
                expected = self.image_tensor(prepared[:, :, ::-1].astype(np.float32) / 255.)
                actual = native_tensor(image, self.torch)
                self.assertTrue(self.torch.equal(actual, expected))
                self.assertEqual(tuple(actual.shape), (3, 512, 512))
                self.assertEqual(actual.dtype, self.torch.float32)
                self.assertTrue(actual.is_contiguous())
                np.testing.assert_array_equal(image, before)

    def test_constructor_is_opt_in_single_batch_and_exposes_implementation(self):
        cls = native_implementation().NativeTileG4Predictor
        self.assertTrue(issubclass(cls, self.original_class))
        with patch.object(self.original_class, '__init__', autospec=True, return_value=None) as initialize:
            predictor = cls('unused-package', device='cpu')
            initialize.assert_called_once_with(predictor, 'unused-package', device='cpu', batch_size=1)
            self.assertEqual(predictor.runtime_implementation, 'g4_native_single_v1')
        for batch in (0, 2, 4, True, 1.0, None):
            with self.subTest(batch=batch), patch.object(self.original_class, '__init__') as initialize:
                with self.assertRaisesRegex(ValueError, 'batch_size.*1'):
                    cls('unused-package', batch_size=batch)
                initialize.assert_not_called()

    def test_cpu_masks_match_original_and_fastpath_skips_legacy_preparation(self):
        predictor = self.fixture()
        image = np.random.default_rng(12).integers(0, 256, (512, 512, 3), dtype=np.uint8)
        expected = self.original_class._infer(predictor, [image])[0]
        with patch.object(self.original_class, '_infer', side_effect=AssertionError('legacy path used')):
            with patch.object(predictor, 'image_tensor', side_effect=AssertionError('legacy tensor used')):
                actual = predictor._infer([image])[0]
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(actual.dtype, np.uint8)
        self.assertEqual(actual.shape, (512, 512))
        self.assertTrue(set(np.unique(actual)).issubset({0, 255}))

    def test_non_native_and_multi_image_inputs_fallback_to_original(self):
        predictor = self.fixture()
        rng = np.random.default_rng(87)
        for images in ([rng.integers(0, 256, (57, 83, 3), dtype=np.uint8)],
                       [rng.integers(0, 256, (512, 512, 3), dtype=np.uint8) for _ in range(2)]):
            expected = self.original_class._infer(predictor, images)
            original = self.original_class._infer
            with patch.object(self.original_class, '_infer', autospec=True, side_effect=original) as fallback:
                actual = predictor._infer(images)
                fallback.assert_called_once_with(predictor, images)
            for got, want in zip(actual, expected):
                np.testing.assert_array_equal(got, want)

    def test_invalid_inputs_preserve_legacy_errors(self):
        predictor = self.fixture()
        for images in ([], [None], [np.zeros((512, 512, 3), np.float32)],
                       [np.zeros((512, 512), np.uint8)], [np.zeros((0, 512, 3), np.uint8)]):
            with self.subTest(input_type=type(images[0]).__name__ if images else 'empty'):
                try:
                    self.original_class._infer(predictor, images)
                except Exception as original_error:
                    with self.assertRaises(type(original_error)) as observed:
                        predictor._infer(images)
                    self.assertEqual(str(observed.exception), str(original_error))
                else:
                    self.fail('invalid fixture unexpectedly accepted by original')

    def test_finite_check_and_half_threshold_match_original(self):
        predictor = self.fixture(); torch = self.torch
        image = np.zeros((512, 512, 3), np.uint8)
        with torch.no_grad():
            predictor.model.weight.zero_(); predictor.model.bias.zero_()
        np.testing.assert_array_equal(predictor._infer([image])[0], np.full((512, 512), 255, np.uint8))
        with torch.no_grad():
            predictor.model.bias.fill_(float('nan'))
        with self.assertRaisesRegex(ValueError, 'nonfinite U-Net logits'):
            predictor._infer([image])

    def test_cuda_masks_match_original_when_available(self):
        native_implementation()
        if not self.torch.cuda.is_available():
            self.skipTest('CUDA unavailable; CPU parity still exercised')
        predictor = self.fixture('cuda')
        image = np.random.default_rng(94).integers(0, 256, (512, 512, 3), dtype=np.uint8)
        expected = self.original_class._infer(predictor, [image])[0]
        actual = predictor._infer([image])[0]
        np.testing.assert_array_equal(actual, expected)


if __name__ == '__main__':
    unittest.main()
