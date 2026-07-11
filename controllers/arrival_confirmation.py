"""Stable vision-arrival confirmation shared by closed-loop operations."""

from __future__ import annotations

from collections.abc import Iterable


class ArrivalConfirmationGate:
    def __init__(self, *, stable_frames: int = 5, minimum_duration_s: float = 0.25):
        if stable_frames < 1:
            raise ValueError("stable_frames must be positive")
        if minimum_duration_s < 0:
            raise ValueError("minimum_duration_s cannot be negative")
        self.stable_frames = stable_frames
        self.minimum_duration_s = minimum_duration_s
        self._targets: frozenset[tuple[int, int]] = frozenset()
        self._stable_count = 0
        self._first_stable_time: float | None = None

    @property
    def stable_count(self) -> int:
        return self._stable_count

    def reset(self) -> None:
        self._targets = frozenset()
        self._stable_count = 0
        self._first_stable_time = None

    def observe(
        self,
        targets: Iterable[tuple[int, int]],
        detections: Iterable[tuple[int, int]],
        now: float,
    ) -> bool:
        expected = frozenset(targets)
        detected = frozenset(detections)
        if expected != self._targets:
            self._targets = expected
            self._stable_count = 0
            self._first_stable_time = None

        if not expected or not expected.issubset(detected):
            self._stable_count = 0
            self._first_stable_time = None
            return False

        if self._stable_count == 0:
            self._first_stable_time = now
        self._stable_count += 1
        stable_duration = now - (self._first_stable_time if self._first_stable_time is not None else now)
        return (
            self._stable_count >= self.stable_frames
            and stable_duration + 1e-9 >= self.minimum_duration_s
        )
