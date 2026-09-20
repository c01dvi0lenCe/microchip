"""Serial client and validated configuration for Chapter 1 scope tests."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from collections.abc import Callable


SCOPE_TEST_MODES = {
    "H5B selected→inactive": "H3A",
    "H5A inactive→selected": "H3B",
    "H5C selected母线跟随": "H3C",
    "H6 异步inactive残余包络": "H6",
    "H7B 相邻inactive像素": "H5B",
    "H7A 选中像素参考": "H5A",
    "RET_ARRAY20 20行阵列保持": "RET_ARRAY20",
}

SCAN_TEST_FREQUENCIES_HZ = (100, 200, 300, 500, 800, 1000)

H4_PHASES = (
    "HIGH_EARLY",
    "HIGH_LATE",
    "FALLING_EDGE",
    "LOW_EARLY",
    "RISING_EDGE",
)


def matrix_electrode_id(row: int, col: int) -> int:
    """Return the firmware's 1-based logical ID for a physical 20x21 cell."""

    if not 1 <= row <= 20 or not 1 <= col <= 21:
        raise ValueError("行必须为1-20，列必须为1-21")
    if col <= 20:
        return (row - 1) * 20 + col
    return 400 + row


@dataclass(frozen=True)
class ScopeTestConfig:
    mode: str
    row: int = 1
    col: int = 1
    row_b: int = 1
    col_b: int = 2
    phase: str = "HIGH_EARLY"
    scan_frequency_hz: int = 300

    @property
    def id_a(self) -> int:
        return matrix_electrode_id(self.row, self.col)

    @property
    def id_b(self) -> int:
        return matrix_electrode_id(self.row_b, self.col_b)

    def validate(self) -> None:
        if self.mode not in SCOPE_TEST_MODES.values():
            raise ValueError(f"不支持的测试模式：{self.mode}")
        matrix_electrode_id(self.row, self.col)
        matrix_electrode_id(self.row_b, self.col_b)
        if self.phase not in H4_PHASES:
            raise ValueError(f"不支持的H4相位：{self.phase}")
        if self.mode == "RET_ARRAY20" and self.scan_frequency_hz not in SCAN_TEST_FREQUENCIES_HZ:
            raise ValueError(
                "扫描频率必须为 "
                + "/".join(str(value) for value in SCAN_TEST_FREQUENCIES_HZ)
                + " Hz"
            )
        if self.mode in {"H5A", "H5B"}:
            if self.row != self.row_b or abs(self.col - self.col_b) != 1:
                raise ValueError("H5要求A、B位于同一行且列号相邻")

    def start_command(self) -> str:
        self.validate()
        command = (
            f"CH1:START:{self.mode}:{self.row}:{self.col}:"
            f"{self.row_b}:{self.col_b}:{self.phase}"
        )
        if self.mode == "RET_ARRAY20":
            command += f":{self.scan_frequency_hz}"
        return command


@dataclass(frozen=True)
class ScopeCommandResult:
    ok: bool
    response: str = ""
    error: str = ""


class ScopeTestClient:
    """Send CH1 commands without interfering with atomic electrode ACKs."""

    def __init__(
        self,
        send_line: Callable[[str], bool],
        *,
        timeout_s: float = 1.5,
    ):
        self._send_line = send_line
        self.timeout_s = timeout_s
        self._condition = threading.Condition()
        self._messages: list[str] = []
        self._command_lock = threading.Lock()

    def feed_line(self, line: str) -> bool:
        line = line.strip()
        if not (line.startswith("ACK:CH1:") or line.startswith("ERR:CH1:")):
            return False
        with self._condition:
            self._messages.append(line)
            self._condition.notify_all()
        return True

    def start(self, config: ScopeTestConfig) -> ScopeCommandResult:
        command = config.start_command()
        return self._exchange(command, f"ACK:CH1:START:{config.mode}")

    def stop(self) -> ScopeCommandResult:
        return self._exchange("CH1:STOP", "ACK:CH1:STOP")

    def _exchange(self, command: str, expected: str) -> ScopeCommandResult:
        with self._command_lock:
            with self._condition:
                self._messages.clear()
                cursor = 0
            if not self._send_line(command):
                return ScopeCommandResult(False, error="串口发送失败")

            deadline = time.monotonic() + self.timeout_s
            with self._condition:
                while True:
                    for line in self._messages[cursor:]:
                        if line == expected or line.startswith(expected + ":"):
                            return ScopeCommandResult(True, response=line)
                        if line.startswith("ERR:CH1:"):
                            return ScopeCommandResult(False, response=line, error=line)
                    cursor = len(self._messages)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return ScopeCommandResult(False, error="等待STM32测试模式确认超时")
                    self._condition.wait(remaining)
