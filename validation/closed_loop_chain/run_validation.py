"""Run and export software-in-the-loop closed-loop chain validation."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path

from .circuit_proxy import CircuitProxy
from .protocol_model import AtomicFrameModel
from .scan_model import ScanModel
from .scenarios import ScenarioSchedule, representative_scenarios
from dmf.layout import in_pull_risk_zone


@dataclass(frozen=True)
class ValidationResult:
    scenario: str
    droplets: int
    steps: int
    max_active_electrodes: int
    max_changed_electrodes: int
    transaction_bytes: int
    max_serial_time_ms: float
    effective_scan_hz: float
    phase_cases: int
    selected_rms_v: float
    inactive_rms_v: float
    vstore_before_revisit_v: float
    safety_violations: str
    passed: bool


def validate_schedule(schedule: ScenarioSchedule, *, baudrate: int = 115200) -> ValidationResult:
    model = AtomicFrameModel(electrode_count=420)
    scan = ScanModel()
    phase_results = CircuitProxy().sweep_independent_phase(phase_count=24)
    previous: set[int] = set()
    sequence = 1
    total_bytes = 0
    max_serial_ms = 0.0
    max_changed = 0
    max_active = 0
    violations: list[str] = []
    observed_scan_hz: list[float] = []

    violations.extend(_track_safety_violations(schedule))

    for frame in schedule.frames:
        if any(electrode_id < 1 or electrode_id > 420 for electrode_id in frame):
            violations.append("electrode id outside 1..420")
            continue
        events = scan.frame_events(frame)
        expected_event_count = 3 * max(1, len({scan._row_col(electrode_id)[0] for electrode_id in frame}))
        if len(events) != expected_event_count:
            violations.append("scan phase count mismatch")
        observed_scan_hz.append(scan.effective_frame_hz_for(frame))

        changes = {electrode_id: 0 for electrode_id in previous - frame}
        changes.update({electrode_id: 1 for electrode_id in frame - previous})
        max_active = max(max_active, len(frame))
        max_changed = max(max_changed, len(changes))
        if not changes:
            previous = set(frame)
            continue

        before_commit = set(model.active_ids)
        model.begin(sequence)
        for electrode_id, state in sorted(changes.items()):
            model.set_electrode(electrode_id, state)
        lines = [f"BEGIN:{sequence}"] + [
            f"SET:{electrode_id}:{state}" for electrode_id, state in sorted(changes.items())
        ] + [f"COMMIT:{sequence}"]
        model.commit(sequence)
        if model.active_ids != before_commit:
            violations.append(f"partial state visible before frame boundary at sequence {sequence}")
        model.apply_frame_boundary()
        if model.active_ids != frame:
            violations.append(f"applied frame mismatch at sequence {sequence}")

        transaction_bytes = sum(len(line.encode("ascii")) + 2 for line in lines)
        serial_ms = transaction_bytes * 10.0 * 1000.0 / baudrate
        total_bytes += transaction_bytes
        max_serial_ms = max(max_serial_ms, serial_ms)
        sequence += 1
        previous = set(frame)

    if not all(result.passed for result in phase_results):
        violations.append("circuit proxy phase sweep failed")
    if max_serial_ms >= 1000.0:
        violations.append("transaction exceeds firmware timeout budget")

    return ValidationResult(
        scenario=schedule.name,
        droplets=schedule.droplet_count,
        steps=len(schedule.frames),
        max_active_electrodes=max_active,
        max_changed_electrodes=max_changed,
        transaction_bytes=total_bytes,
        max_serial_time_ms=round(max_serial_ms, 3),
        effective_scan_hz=round(min(observed_scan_hz, default=scan.effective_frame_hz), 3),
        phase_cases=len(phase_results),
        selected_rms_v=round(phase_results[0].selected_rms_v, 3),
        inactive_rms_v=round(phase_results[0].inactive_rms_v, 3),
        vstore_before_revisit_v=round(phase_results[0].vstore_before_revisit_v, 5),
        safety_violations="; ".join(dict.fromkeys(violations)),
        passed=not violations,
    )


def _track_safety_violations(schedule: ScenarioSchedule) -> list[str]:
    if not schedule.tracks:
        return []
    violations: list[str] = []
    max_steps = max(len(track) for track in schedule.tracks)
    for step in range(max_steps):
        current = [_track_cell(track, step) for track in schedule.tracks]
        previous = [_track_cell(track, step - 1) if step > 0 else None for track in schedule.tracks]
        for left in range(len(current)):
            if current[left] is None:
                continue
            for right in range(left + 1, len(current)):
                if current[right] is None:
                    continue
                if current[left] == current[right]:
                    if current[left] not in schedule.merge_cells:
                        violations.append(f"step {step}: D{left + 1}/D{right + 1} same-cell conflict")
                    continue
                if (
                    previous[left] is not None
                    and previous[right] is not None
                    and current[left] == previous[right]
                    and current[right] == previous[left]
                ):
                    violations.append(f"step {step}: D{left + 1}/D{right + 1} swap conflict")
                moved = current[left] != previous[left] or current[right] != previous[right]
                if moved and in_pull_risk_zone(current[left], current[right]):
                    if not (
                        current[left] in schedule.merge_cells
                        and current[right] in schedule.merge_cells
                    ):
                        violations.append(f"step {step}: D{left + 1}/D{right + 1} pull-risk conflict")
    return violations


def _track_cell(track, step):
    if not track:
        return None
    if step < len(track):
        return track[step]
    return track[-1]


def run(output_dir: Path | None = None) -> list[ValidationResult]:
    root = Path(__file__).resolve().parents[2]
    output_dir = output_dir or Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    schedules = representative_scenarios(root / "presets")
    results = [validate_schedule(schedule) for schedule in schedules]

    csv_path = output_dir / "closed_loop_chain_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0])))
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)

    markdown = [
        "# Closed-Loop Chain Software Validation",
        "",
        "| Scenario | Droplets | Steps | Max active | Max changed | Max serial ms | Result |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        markdown.append(
            f"| {result.scenario} | {result.droplets} | {result.steps} | "
            f"{result.max_active_electrodes} | {result.max_changed_electrodes} | "
            f"{result.max_serial_time_ms:.3f} | {'PASS' if result.passed else 'FAIL'} |"
        )
    markdown.extend(
        [
            "",
            "Software PASS verifies atomic protocol, ID mapping, scan-event construction, serial budget, and the circuit proxy across independent 300 Hz phase offsets.",
            "Circuit proxy uses the existing single-select waveform levels, VSTORE before revisit 3.80167 V, and a 23.529 V inactive edge peak under the 0.5 pF coupling assumption; RMS values are recomputed for every independent phase offset.",
            "The existing 1.22 pF sensitivity case reaches 52.928 V, so PCB parasitic coupling remains a hardware risk rather than a software PASS claim.",
            "It does not replace Keil build/flash, oscilloscope, logic-analyzer, camera calibration, or real-droplet validation.",
        ]
    )
    (output_dir / "closed_loop_chain_summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    validation_results = run()
    for item in validation_results:
        print(
            f"{item.scenario}: {'PASS' if item.passed else 'FAIL'} "
            f"steps={item.steps} max_changed={item.max_changed_electrodes} "
            f"serial={item.max_serial_time_ms:.3f}ms"
        )
    raise SystemExit(0 if all(item.passed for item in validation_results) else 1)
