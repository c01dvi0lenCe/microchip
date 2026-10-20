import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from ctypes import c_int

import numpy as np

from dmf.experiment.mvs_camera import MvsCamera, convert_mvs_buffer


class PixelTypes:
    PixelType_Gvsp_Mono8 = 1
    PixelType_Gvsp_BayerRG8 = 2
    PixelType_Gvsp_BayerGR8 = 3
    PixelType_Gvsp_BayerGB8 = 4
    PixelType_Gvsp_BayerBG8 = 5


class MvsCameraFrameTests(unittest.TestCase):
    def test_mono8_is_returned_as_three_channel_bgr(self):
        raw = np.arange(16, dtype=np.uint8).tobytes()
        frame = convert_mvs_buffer(4, 4, PixelTypes.PixelType_Gvsp_Mono8, raw, PixelTypes)
        self.assertEqual(frame.shape, (4, 4, 3))
        self.assertEqual(frame.dtype, np.uint8)
        np.testing.assert_array_equal(frame[:, :, 0], np.arange(16, dtype=np.uint8).reshape(4, 4))

    def test_bayer8_is_demosaiced_to_bgr(self):
        raw = np.full((6, 6), 127, dtype=np.uint8).tobytes()
        frame = convert_mvs_buffer(6, 6, PixelTypes.PixelType_Gvsp_BayerRG8, raw, PixelTypes)
        self.assertEqual(frame.shape, (6, 6, 3))
        self.assertEqual(frame.dtype, np.uint8)

    def test_all_pfnc_bayer_patterns_preserve_bgr_channels(self):
        patterns = (
            (PixelTypes.PixelType_Gvsp_BayerRG8, "RGGB"),
            (PixelTypes.PixelType_Gvsp_BayerGR8, "GRBG"),
            (PixelTypes.PixelType_Gvsp_BayerGB8, "GBRG"),
            (PixelTypes.PixelType_Gvsp_BayerBG8, "BGGR"),
        )
        for pixel_type, pattern in patterns:
            for channels in ({"R": 227, "G": 101, "B": 19},
                             {"R": 255, "G": 0, "B": 0},
                             {"R": 0, "G": 0, "B": 255}):
                with self.subTest(pattern=pattern, channels=channels):
                    mosaic = np.empty((8, 8), dtype=np.uint8)
                    for index, color in enumerate(pattern):
                        mosaic[index // 2::2, index % 2::2] = channels[color]
                    actual = convert_mvs_buffer(8, 8, pixel_type, mosaic.tobytes(), PixelTypes)
                    expected = np.empty((6, 6, 3), dtype=np.uint8)
                    expected[:] = [channels["B"], channels["G"], channels["R"]]
                    np.testing.assert_array_equal(actual[1:-1, 1:-1], expected)

    def test_unknown_packed_format_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "Unsupported MVS pixel format"):
            convert_mvs_buffer(2, 2, 99, bytes(4), PixelTypes)

    def test_malformed_buffer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Expected 4 image bytes"):
            convert_mvs_buffer(2, 2, PixelTypes.PixelType_Gvsp_Mono8, bytes(3), PixelTypes)

    def test_vendor_avi_recording_starts_and_stops_with_sdk(self):
        class Value:
            nCurValue = 0
            fCurValue = 0.0
        class Camera:
            def __init__(self):
                self.started_with = None
                self.stopped = 0
            def MV_CC_GetIntValue(self, name, value):
                value.nCurValue = {'Width': 640, 'Height': 480}[name]
                return 0
            def MV_CC_GetEnumValue(self, name, value):
                value.nCurValue = 22
                return 0
            def MV_CC_GetFloatValue(self, name, value):
                value.fCurValue = 19.25
                return 0
            def MV_CC_StartRecord(self, value):
                self.started_with = value
                return 0
            def MV_CC_StopRecord(self):
                self.stopped += 1
                return 0

        camera = MvsCamera.__new__(MvsCamera)
        camera.camera = Camera()
        camera.headers = SimpleNamespace(
            MVCC_INTVALUE=Value,
            MVCC_ENUMVALUE=Value,
            MVCC_FLOATVALUE=Value,
            MV_CC_RECORD_PARAM=lambda: SimpleNamespace(),
            MvGvspPixelType=c_int,
            MV_FormatType_AVI=1,
        )
        camera.recording = False
        camera.recording_path = None
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'test.avi'
            target.write_bytes(b'preserve this prior attempt')
            actual = Path(camera.start_recording(target))
            self.assertEqual(actual, target.with_name('test_001.avi').resolve())
            self.assertEqual(camera.camera.started_with.nWidth, 640)
            self.assertEqual(camera.camera.started_with.nHeight, 480)
            self.assertEqual(camera.camera.started_with.fFrameRate, 19.25)
            self.assertEqual(camera.camera.started_with.enRecordFmtType, 1)
            # This SDK stub creates no AVI or frames: final validation must fail.
            with self.assertRaisesRegex(OSError, 'not created'):
                camera.stop_recording()
            self.assertEqual(target.read_bytes(), b'preserve this prior attempt')
        self.assertEqual(camera.camera.stopped, 1)
        self.assertFalse(camera.recording)

    def test_sidecar_collision_also_reserves_the_recording_name(self):
        # Reuse the SDK fixture above, but reserve an audit file without an AVI.
        from unittest.mock import patch
        from dmf.recording import sidecar_paths
        camera=MvsCamera.__new__(MvsCamera)
        camera.recording=False
        camera.headers=SimpleNamespace(MV_CC_RECORD_PARAM=SimpleNamespace,
            MvGvspPixelType=c_int,MV_FormatType_AVI=1)
        camera.camera=SimpleNamespace(MV_CC_StartRecord=lambda record:0,MV_CC_StopRecord=lambda:0)
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'test.avi'
            reserved=sidecar_paths(video)['timestamps'];reserved.write_text('preserve')
            with patch.object(camera,'_get_int',return_value=16), \
                    patch.object(camera,'_get_enum',return_value=1), \
                    patch.object(camera,'_get_float',return_value=20):
                self.assertEqual(Path(camera.start_recording(video)).name,'test_001.avi')
                with self.assertRaisesRegex(OSError,'not created'):
                    camera.stop_recording()
            self.assertEqual(reserved.read_text(),'preserve')


if __name__ == "__main__":
    unittest.main()
