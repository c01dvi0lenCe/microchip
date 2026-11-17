"""The Windows installer and operator handoff must describe the shipped environment."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CameraPcDeliveryTests(unittest.TestCase):
    def test_installer_checks_dependency_consistency_and_points_to_real_model_release(self):
        setup = (ROOT / 'setup_vision_env.cmd').read_text(encoding='utf-8')
        self.assertIn('-m pip check', setup)
        self.assertIn('https://github.com/c01dvi0lenCe/microchip/releases/tag/g4-unet-inference-v1', setup)
        self.assertIn('docs\\camera-pc-quickstart.md', setup)

    def test_runtime_pins_are_part_of_the_installation_not_just_a_report(self):
        requirements = (ROOT / 'requirements-vision.txt').read_text(encoding='utf-8')
        lock = 'requirements-vision-win-py314.constraints.txt'
        self.assertIn('-c ' + lock, requirements.splitlines())
        pins = (ROOT / lock).read_text(encoding='utf-8').lower().splitlines()
        for expected in ('torch==2.11.0+cu128', 'torchvision==0.26.0+cu128',
                         'segmentation-models-pytorch==0.5.0', 'pyserial==3.5'):
            self.assertIn(expected, pins)
        self.assertTrue(all('://' not in s and ' @ ' not in s for s in pins))
