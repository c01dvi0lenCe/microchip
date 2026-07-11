"""Reliable atomic electrode transactions for the STM32 serial protocol."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import threading
import time
from collections.abc import Callable, Mapping


@dataclass(frozen=True)
class TransactionResult:
    sequence: int
    attempts: int
    applied: bool
    error: str = ""


class ElectrodeTransactionClient:
    """Send one delta batch and wait until firmware reports frame application.

    ``ACK:<sequence>:APPLIED`` confirms only the electrical frame swap. Droplet
    arrival remains a separate vision-controller decision.
    """

    def __init__(
        self,
        send_line: Callable[[str], bool],
        *,
        electrode_count: int = 420,
        ack_timeout_s: float = 0.35,
        max_retries: int = 2,
        initial_sequence: int | None = None,
    ):
        self._send_line = send_line
        self.electrode_count = electrode_count
        self.ack_timeout_s = ack_timeout_s
        self.max_retries = max_retries
        self._next_sequence = initial_sequence or (secrets.randbelow(0x7FFFFFFE) + 1)
        self._condition = threading.Condition()
        self._messages: list[str] = []
        self._transaction_lock = threading.Lock()

    def feed_line(self, line: str) -> bool:
        """Route one serial line into the ACK waiter.

        Returns ``True`` when the line belongs to the transaction protocol so
        the caller can avoid presenting routine ACK traffic as device output.
        """

        line = line.strip()
        if not (line.startswith("ACK:") or line.startswith("ERR:")):
            return False
        with self._condition:
            self._messages.append(line)
            self._condition.notify_all()
        return True

    def apply_changes(self, changes: Mapping[int, int | bool]) -> TransactionResult:
        normalized = self._normalize_changes(changes)
        with self._transaction_lock:
            self._clear_messages()
            sequence = self._next_sequence
            self._next_sequence += 1
            return self._apply_sequence(sequence, normalized)

    def all_off(self) -> bool:
        with self._transaction_lock:
            self._clear_messages()
            for _ in range(self.max_retries + 1):
                cursor = self._message_cursor()
                if not self._send_line("ALL_OFF"):
                    continue
                response = self._wait_for(
                    cursor,
                    lambda line: line == "ACK:ALL_OFF" or line.startswith("ERR:"),
                )
                if response == "ACK:ALL_OFF":
                    self._next_sequence = 1
                    return True
            return False

    def _apply_sequence(self, sequence: int, changes: dict[int, int]) -> TransactionResult:
        last_error = "ACK timeout"
        for attempt in range(1, self.max_retries + 2):
            begin_cursor = self._message_cursor()
            if not self._send_line(f"BEGIN:{sequence}"):
                last_error = "serial send failed"
                continue

            begin_reply = self._wait_for(
                begin_cursor,
                lambda line: self._is_sequence_stage(line, sequence, {"BEGIN", "QUEUED", "APPLIED"})
                or line.startswith("ERR:"),
            )
            if begin_reply is None:
                last_error = "BEGIN acknowledgement timeout"
                continue
            if begin_reply == f"ACK:{sequence}:APPLIED":
                return TransactionResult(sequence, attempt, True)
            if begin_reply == f"ACK:{sequence}:QUEUED":
                queued_reply = self._wait_for(
                    begin_cursor,
                    lambda line: line == f"ACK:{sequence}:APPLIED" or line.startswith("ERR:"),
                )
                if queued_reply == f"ACK:{sequence}:APPLIED":
                    return TransactionResult(sequence, attempt, True)
                last_error = queued_reply or "queued APPLIED acknowledgement timeout"
                continue
            if begin_reply.startswith("ERR:"):
                last_error = begin_reply
                continue

            sent_all = True
            for electrode_id, state in sorted(changes.items()):
                if not self._send_line(f"SET:{electrode_id}:{state}"):
                    sent_all = False
                    last_error = f"SET:{electrode_id} send failed"
                    break
            if not sent_all:
                continue

            commit_cursor = self._message_cursor()
            if not self._send_line(f"COMMIT:{sequence}"):
                last_error = "COMMIT send failed"
                continue
            commit_reply = self._wait_for(
                commit_cursor,
                lambda line: line == f"ACK:{sequence}:APPLIED" or line.startswith("ERR:"),
            )
            if commit_reply == f"ACK:{sequence}:APPLIED":
                return TransactionResult(sequence, attempt, True)
            last_error = commit_reply or "APPLIED acknowledgement timeout"

        return TransactionResult(sequence, self.max_retries + 1, False, last_error)

    def _wait_for(self, cursor: int, predicate: Callable[[str], bool]) -> str | None:
        deadline = time.monotonic() + self.ack_timeout_s
        with self._condition:
            while True:
                for line in self._messages[cursor:]:
                    if predicate(line):
                        return line
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def _message_cursor(self) -> int:
        with self._condition:
            return len(self._messages)

    def _clear_messages(self) -> None:
        with self._condition:
            self._messages.clear()

    def reset_sequence(self, sequence: int = 1) -> None:
        if sequence < 1:
            raise ValueError("sequence must be positive")
        with self._transaction_lock:
            self._next_sequence = sequence
            self._clear_messages()

    @staticmethod
    def _is_sequence_stage(line: str, sequence: int, stages: set[str]) -> bool:
        parts = line.split(":")
        return (
            len(parts) >= 3
            and parts[0] == "ACK"
            and parts[1] == str(sequence)
            and parts[2] in stages
        )

    def _normalize_changes(self, changes: Mapping[int, int | bool]) -> dict[int, int]:
        normalized: dict[int, int] = {}
        for electrode_id, state in changes.items():
            if not 1 <= electrode_id <= self.electrode_count:
                raise ValueError(f"electrode id must be in 1..{self.electrode_count}")
            if state not in (0, 1, False, True):
                raise ValueError("electrode state must be 0 or 1")
            normalized[int(electrode_id)] = 1 if state else 0
        return normalized
