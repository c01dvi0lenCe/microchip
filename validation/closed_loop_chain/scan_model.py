"""Deterministic 20-row by 21-column scan timing model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanEvent:
    phase: str
    row: int
    start_us: float
    duration_us: float
    active_columns: tuple[int, ...] = ()


class ScanModel:
    def __init__(
        self,
        *,
        rows: int = 20,
        cols: int = 21,
        nominal_frame_hz: float = 300.0,
        row_on_us: float = 160.0,
        blank_us: float = 5.0,
        settle_us: float = 2.0,
    ):
        self.rows = rows
        self.cols = cols
        self.nominal_frame_hz = nominal_frame_hz
        self.row_on_us = row_on_us
        self.blank_us = blank_us
        self.settle_us = settle_us

    @property
    def row_period_us(self) -> float:
        return self._timing_for_row_count(self.rows)[0]

    @property
    def frame_period_us(self) -> float:
        return self.rows * self.row_period_us

    @property
    def effective_frame_hz(self) -> float:
        return 1_000_000.0 / self.frame_period_us

    def effective_frame_hz_for(self, active_ids: set[int]) -> float:
        active_rows = self._active_rows(active_ids)
        row_count = max(1, len(active_rows))
        slot_us, _blank_us, _row_on_us = self._timing_for_row_count(row_count)
        return 1_000_000.0 / (slot_us * row_count)

    def frame_events(self, active_ids: set[int]) -> list[ScanEvent]:
        row_columns = {row: [] for row in range(self.rows)}
        for electrode_id in sorted(active_ids):
            row, col = self._row_col(electrode_id)
            row_columns[row].append(col)

        active_rows = sorted(row for row, columns in row_columns.items() if columns)
        scan_rows = active_rows or [-1]
        slot_us, blank_us, row_on_us = self._timing_for_row_count(len(scan_rows))
        events: list[ScanEvent] = []
        cursor = 0.0
        for row in scan_rows:
            columns = tuple(row_columns[row]) if row >= 0 else ()
            events.append(ScanEvent("blank", row, cursor, blank_us))
            cursor += blank_us
            events.append(ScanEvent("load", row, cursor, self.settle_us, columns))
            cursor += self.settle_us
            events.append(ScanEvent("drive", row, cursor, row_on_us, columns))
            cursor += row_on_us
        if abs(cursor - slot_us * len(scan_rows)) > 1e-9:
            raise AssertionError("scan event timing does not fill the frame")
        return events

    def _active_rows(self, active_ids: set[int]) -> set[int]:
        return {self._row_col(electrode_id)[0] for electrode_id in active_ids}

    def _timing_for_row_count(self, row_count: int) -> tuple[float, float, float]:
        rows = max(1, min(self.rows, row_count))
        slot_us = float(int(1_000_000.0 / (self.nominal_frame_hz * rows) + 0.5))
        row_on_us = min(self.row_on_us, slot_us - self.blank_us - self.settle_us)
        blank_us = slot_us - self.settle_us - row_on_us
        return slot_us, blank_us, row_on_us

    def _row_col(self, electrode_id: int) -> tuple[int, int]:
        if not 1 <= electrode_id <= self.rows * self.cols:
            raise ValueError("electrode id outside 20x21 matrix")
        if electrode_id <= 400:
            index = electrode_id - 1
            return index // 20, index % 20
        return electrode_id - 401, 20
