import unittest

from controllers.arrival_confirmation import ArrivalConfirmationGate


class ArrivalConfirmationGateTests(unittest.TestCase):
    def test_requires_five_frames_and_quarter_second(self):
        gate = ArrivalConfirmationGate(stable_frames=5, minimum_duration_s=0.25)
        target = {(3, 4)}

        for frame, now in enumerate((0.00, 0.05, 0.10, 0.15), start=1):
            self.assertFalse(gate.observe(target, {(3, 4)}, now), frame)
        self.assertFalse(gate.observe(target, {(3, 4)}, 0.20))
        self.assertTrue(gate.observe(target, {(3, 4)}, 0.25))

    def test_wrong_or_missing_detection_resets_stability(self):
        gate = ArrivalConfirmationGate(stable_frames=2, minimum_duration_s=0.10)
        target = {(1, 1)}

        self.assertFalse(gate.observe(target, {(1, 1)}, 0.0))
        self.assertFalse(gate.observe(target, set(), 0.1))
        self.assertFalse(gate.observe(target, {(1, 1)}, 0.2))
        self.assertTrue(gate.observe(target, {(1, 1)}, 0.3))

    def test_multi_target_confirmation_requires_every_target(self):
        gate = ArrivalConfirmationGate(stable_frames=2, minimum_duration_s=0.05)
        targets = {(2, 2), (5, 5)}

        self.assertFalse(gate.observe(targets, {(2, 2)}, 0.0))
        self.assertFalse(gate.observe(targets, {(2, 2), (5, 5)}, 0.1))
        self.assertTrue(gate.observe(targets, {(2, 2), (5, 5)}, 0.16))

    def test_changing_targets_starts_a_new_confirmation_window(self):
        gate = ArrivalConfirmationGate(stable_frames=2, minimum_duration_s=0.05)

        self.assertFalse(gate.observe({(0, 1)}, {(0, 1)}, 0.0))
        self.assertFalse(gate.observe({(0, 2)}, {(0, 2)}, 0.1))
        self.assertTrue(gate.observe({(0, 2)}, {(0, 2)}, 0.16))


if __name__ == "__main__":
    unittest.main()
