"""Single background planning job with main-thread result delivery."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dmf.layout import Cell


@dataclass(frozen=True)
class MultiPlanRequest:
    sources: tuple[Cell, ...]
    targets: tuple[Cell, ...]
    obstacles: frozenset[Cell]
    source_capacity: tuple[tuple[Cell, int], ...]


class PlanningJobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._outcomes: queue.Queue[tuple[bool, Any, Callable, Callable]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._active = False

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def submit(self, *, work: Callable[[], Any], on_success: Callable[[Any], None], on_error: Callable[[Exception], None]) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True
            self._thread = threading.Thread(
                target=self._run,
                args=(work, on_success, on_error),
                daemon=True,
                name="dmf-planning",
            )
            self._thread.start()
        return True

    def _run(self, work: Callable[[], Any], on_success: Callable[[Any], None], on_error: Callable[[Exception], None]) -> None:
        try:
            result = work()
        except Exception as exc:
            self._outcomes.put((False, exc, on_success, on_error))
        else:
            self._outcomes.put((True, result, on_success, on_error))

    def drain(self) -> int:
        delivered = 0
        while True:
            try:
                succeeded, payload, on_success, on_error = self._outcomes.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self._active = False
                self._thread = None
            if succeeded:
                on_success(payload)
            else:
                on_error(payload)
            delivered += 1
        return delivered

    def join_for_test(self, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
