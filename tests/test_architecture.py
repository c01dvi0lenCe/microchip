import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def test_main_is_thin_entrypoint_and_reexports_controller(self):
        import app_controller
        import main

        self.assertIs(main.STM32MatrixController, app_controller.STM32MatrixController)
        self.assertLessEqual(len(Path("main.py").read_text(encoding="utf-8").splitlines()), 80)

    def test_simulation_profiles_and_metrics_have_dedicated_modules(self):
        from simulation.metrics import OperationMetrics, StepEvent
        from simulation.profiles import MotionProfile, VisionNoiseProfile

        self.assertEqual(MotionProfile().name, "ideal")
        self.assertEqual(VisionNoiseProfile().name, "off")

        metrics = OperationMetrics(operation="move")
        metrics.record_event(StepEvent(stage="DRIVE_TARGET", on_cells=((1, 2),)))
        self.assertEqual(metrics.total_steps, 1)
        self.assertEqual(metrics.electrode_switch_count, 1)

    def test_hardware_protocol_is_separated_from_gui_controller(self):
        from controllers.hardware_controller import HardwareProtocol

        self.assertEqual(HardwareProtocol.set_electrode(23, True), "SET:23:1")
        self.assertEqual(HardwareProtocol.set_electrode(23, False), "SET:23:0")
        self.assertEqual(HardwareProtocol.set_frequency(5000), "FREQ:5000")
        self.assertEqual(HardwareProtocol.query_frequency(), "FREQ?")


if __name__ == "__main__":
    unittest.main()
