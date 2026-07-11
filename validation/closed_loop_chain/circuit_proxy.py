"""Acceptance proxy for the single-select weak-pullback pixel circuit."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .scan_model import ScanModel

@dataclass(frozen=True)
class CircuitPhaseResult:
    phase_deg: float
    selected_rms_v: float
    inactive_rms_v: float
    vstore_after_write_v: float
    vstore_before_revisit_v: float
    passed: bool


class CircuitProxy:
    def __init__(
        self,
        *,
        pulse_hz: float = 300.0,
        selected_high_v: float = 199.999,
        selected_low_v: float = -190.592,
        inactive_edge_peak_v: float = 23.529,
        inactive_time_constant_s: float = 85e-6,
        vstore_after_write_v: float = 4.99867,
        vstore_before_revisit_v: float = 3.80167,
    ):
        self.pulse_hz = pulse_hz
        self.selected_high_v = selected_high_v
        self.selected_low_v = selected_low_v
        self.inactive_edge_peak_v = inactive_edge_peak_v
        self.inactive_time_constant_s = inactive_time_constant_s
        self.vstore_after_write_v = vstore_after_write_v
        self.vstore_before_revisit_v = vstore_before_revisit_v

    def sweep_independent_phase(self, phase_count: int = 24) -> list[CircuitPhaseResult]:
        if phase_count < 1:
            raise ValueError("phase_count must be positive")
        pulse_period_s = 1.0 / self.pulse_hz
        window_s = ScanModel().frame_period_us / 1_000_000.0
        sample_count = 2400
        results = []
        for index in range(phase_count):
            phase_deg = 360.0 * index / phase_count
            phase_s = pulse_period_s * index / phase_count
            selected_sq = 0.0
            inactive_sq = 0.0
            for sample in range(sample_count):
                time_s = window_s * (sample + 0.5) / sample_count
                cycle_s = (time_s + phase_s) % pulse_period_s
                high_phase = cycle_s < pulse_period_s / 2.0
                selected_v = self.selected_high_v if high_phase else self.selected_low_v
                edge_age_s = cycle_s if high_phase else cycle_s - pulse_period_s / 2.0
                inactive_v = self.inactive_edge_peak_v * math.exp(
                    -edge_age_s / self.inactive_time_constant_s
                )
                selected_sq += selected_v * selected_v
                inactive_sq += inactive_v * inactive_v
            selected_rms_v = math.sqrt(selected_sq / sample_count)
            inactive_rms_v = math.sqrt(inactive_sq / sample_count)
            passed = (
                selected_rms_v >= 150.0
                and inactive_rms_v < 50.0
                and self.vstore_after_write_v >= 4.0
                and self.vstore_before_revisit_v >= 3.0
            )
            results.append(
                CircuitPhaseResult(
                    phase_deg=phase_deg,
                    selected_rms_v=selected_rms_v,
                    inactive_rms_v=inactive_rms_v,
                    vstore_after_write_v=self.vstore_after_write_v,
                    vstore_before_revisit_v=self.vstore_before_revisit_v,
                    passed=passed,
                )
            )
        return results
