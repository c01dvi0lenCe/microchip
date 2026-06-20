from __future__ import annotations


class HardwareProtocol:
    """Serial command strings shared by simulation and hardware modes."""

    @staticmethod
    def set_electrode(electrode_id: int, state: bool | int) -> str:
        return f"SET:{electrode_id}:{1 if state else 0}"

    @staticmethod
    def camera_start() -> str:
        return "CAMERA:START"

    @staticmethod
    def camera_stop() -> str:
        return "CAMERA:STOP"

    @staticmethod
    def camera_get() -> str:
        return "CAMERA:GET"
