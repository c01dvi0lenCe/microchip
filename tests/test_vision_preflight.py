import importlib.util
from pathlib import Path
import tempfile
import unittest
from scripts.vision_preflight import make_report


class PreflightTests(unittest.TestCase):
    def test_no_sdk_or_model_is_warning_not_application_start_block(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'configs').mkdir()
            report=make_report(p,query_cuda=False)
            self.assertFalse(report['camera_opened']);self.assertFalse(report['serial_opened'])
            self.assertFalse(report['sdk_bindings_present']);self.assertFalse(report['model_ready'])
            self.assertTrue(report['base_gui_ready'])


if __name__=='__main__':unittest.main()
