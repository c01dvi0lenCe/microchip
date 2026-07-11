"""Reference model of the firmware's atomic 420-electrode frame."""

from __future__ import annotations


class AtomicFrameModel:
    def __init__(self, electrode_count: int = 420):
        self.electrode_count = electrode_count
        self._committed = [0] * electrode_count
        self._staged: list[int] | None = None
        self._queued: list[int] | None = None
        self._sequence: int | None = None
        self._queued_sequence: int | None = None
        self.last_applied_sequence: int | None = None

    @property
    def active_ids(self) -> set[int]:
        return {index + 1 for index, state in enumerate(self._committed) if state}

    def begin(self, sequence: int) -> None:
        if self._staged is not None or self._queued is not None:
            raise RuntimeError("transaction busy")
        self._staged = self._committed.copy()
        self._sequence = sequence

    def set_electrode(self, electrode_id: int, state: int | bool) -> None:
        if self._staged is None:
            raise RuntimeError("no open transaction")
        if not 1 <= electrode_id <= self.electrode_count:
            raise ValueError("invalid electrode id")
        if state not in (0, 1, False, True):
            raise ValueError("invalid electrode state")
        self._staged[electrode_id - 1] = 1 if state else 0

    def commit(self, sequence: int) -> None:
        if self._staged is None or sequence != self._sequence:
            raise RuntimeError("sequence mismatch")
        self._queued = self._staged
        self._queued_sequence = sequence
        self._staged = None
        self._sequence = None

    def apply_frame_boundary(self) -> int | None:
        if self._queued is None:
            return None
        self._committed = self._queued
        self.last_applied_sequence = self._queued_sequence
        applied = self._queued_sequence
        self._queued = None
        self._queued_sequence = None
        return applied

    def all_off(self) -> None:
        self._committed = [0] * self.electrode_count
        self._staged = None
        self._queued = None
        self._sequence = None
        self._queued_sequence = None
