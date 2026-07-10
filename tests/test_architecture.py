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
        self.assertFalse(hasattr(HardwareProtocol, "set_frequency"))
        self.assertFalse(hasattr(HardwareProtocol, "query_frequency"))

    def test_dmf_core_has_deep_modules_behind_compatibility_facade(self):
        import dmf_simulation
        from dmf.layout import electrode_id
        from dmf.motion import SimulatedDroplet
        from dmf.planning import AStarPlanner
        from dmf.vision import DropletDetector

        self.assertIs(dmf_simulation.electrode_id, electrode_id)
        self.assertIs(dmf_simulation.SimulatedDroplet, SimulatedDroplet)
        self.assertIs(dmf_simulation.AStarPlanner, AStarPlanner)
        self.assertIs(dmf_simulation.DropletDetector, DropletDetector)
        self.assertLessEqual(len(Path("dmf_simulation.py").read_text(encoding="utf-8").splitlines()), 120)

    def test_planning_module_exposes_focused_deep_modules(self):
        from dmf.planning import AStarPlanner, build_multi_droplet_assignments, schedule_multi_paths
        from dmf.planning.assignment import build_multi_droplet_assignments as assignment_entrypoint
        from dmf.planning.astar import AStarPlanner as astar_entrypoint
        from dmf.planning.scheduler import schedule_multi_paths as scheduler_entrypoint

        self.assertIs(AStarPlanner, astar_entrypoint)
        self.assertIs(build_multi_droplet_assignments, assignment_entrypoint)
        self.assertIs(schedule_multi_paths, scheduler_entrypoint)
        self.assertLessEqual(len(Path("dmf/planning/scheduler.py").read_text(encoding="utf-8").splitlines()), 700)


if __name__ == "__main__":
    unittest.main()
