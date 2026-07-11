import unittest
from pathlib import Path

from validation.closed_loop_chain.circuit_proxy import CircuitProxy
from validation.closed_loop_chain.protocol_model import AtomicFrameModel
from validation.closed_loop_chain.run_validation import validate_schedule
from validation.closed_loop_chain.scan_model import ScanModel
from validation.closed_loop_chain.scenarios import ScenarioSchedule, representative_scenarios


class ClosedLoopChainValidationTests(unittest.TestCase):
    def test_atomic_model_hides_partial_batch_until_frame_boundary(self):
        model = AtomicFrameModel(electrode_count=420)
        model.begin(1)
        model.set_electrode(23, 1)
        model.set_electrode(24, 1)
        self.assertEqual(model.active_ids, set())
        model.commit(1)
        self.assertEqual(model.active_ids, set())

        model.apply_frame_boundary()

        self.assertEqual(model.active_ids, {23, 24})

    def test_scan_model_uses_blank_load_drive_for_active_rows_only(self):
        scan = ScanModel()

        events = scan.frame_events({1, 420})

        self.assertEqual(len(events), 6)
        self.assertEqual([event.phase for event in events[:3]], ["blank", "load", "drive"])
        self.assertEqual({event.row for event in events if event.phase == "drive"}, {0, 19})
        self.assertAlmostEqual(scan.effective_frame_hz_for({1, 420}), 300.0, delta=0.1)

        full_rows = {row * 20 + 1 for row in range(20)}
        self.assertAlmostEqual(scan.effective_frame_hz_for(full_rows), 299.4, places=1)

    def test_independent_external_pulse_phase_sweep_meets_proxy_limits(self):
        results = CircuitProxy().sweep_independent_phase(phase_count=24)

        self.assertEqual(len(results), 24)
        self.assertTrue(all(result.passed for result in results))
        self.assertTrue(all(result.selected_rms_v >= 150.0 for result in results))
        self.assertTrue(all(result.inactive_rms_v < 50.0 for result in results))
        self.assertTrue(all(result.vstore_before_revisit_v >= 3.0 for result in results))
        self.assertGreater(
            max(result.selected_rms_v for result in results)
            - min(result.selected_rms_v for result in results),
            0.0,
        )

    def test_simple_schedule_reports_delta_batch_cost(self):
        schedule = ScenarioSchedule("move", [{1}, {2}, {3}], droplet_count=1)

        result = validate_schedule(schedule)

        self.assertTrue(result.passed)
        self.assertEqual(result.steps, 3)
        self.assertEqual(result.max_changed_electrodes, 2)
        self.assertGreater(result.transaction_bytes, 0)
        self.assertLess(result.max_serial_time_ms, 1000.0)

    def test_representative_tasks_include_letters_and_all_validate(self):
        preset_dir = Path(__file__).resolve().parents[1] / "presets"

        schedules = representative_scenarios(preset_dir)
        results = [validate_schedule(schedule) for schedule in schedules]

        self.assertEqual(
            {schedule.name for schedule in schedules},
            {"move", "mix", "split", "loop", "CSE", "ZJU", "CSC"},
        )
        self.assertTrue(all(result.passed for result in results))
        self.assertTrue(all(result.steps > 0 for result in results))

    def test_conflicting_droplet_tracks_fail_validation(self):
        schedule = ScenarioSchedule(
            "conflict",
            frames=[{1, 3}, {2}],
            droplet_count=2,
            tracks=(
                ((0, 0), (0, 1)),
                ((0, 2), (0, 1)),
            ),
        )

        result = validate_schedule(schedule)

        self.assertFalse(result.passed)
        self.assertIn("same-cell conflict", result.safety_violations)


if __name__ == "__main__":
    unittest.main()
