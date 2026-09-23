from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoTimestampResolver:
    """Prefer monotonic video PTS and fall back to the declared frame rate."""

    fps: float
    previous_video_pts_s: Optional[float] = None
    previous_timestamp_s: Optional[float] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("fps must be a positive finite value")

    def resolve(self, frame_id: int, pts_ms: object) -> tuple[float, str]:
        try:
            pts_s = float(pts_ms) / 1000.0
        except (TypeError, ValueError):
            pts_s = float("nan")
        video_pts_valid = (
            math.isfinite(pts_s)
            and pts_s >= 0
            and (self.previous_video_pts_s is None or pts_s > self.previous_video_pts_s)
            and (self.previous_timestamp_s is None or pts_s > self.previous_timestamp_s)
        )
        if video_pts_valid:
            self.previous_video_pts_s = pts_s
            self.previous_timestamp_s = pts_s
            return pts_s, "video_pts"

        timestamp_s = max(0, int(frame_id)) / self.fps
        if self.previous_timestamp_s is not None and timestamp_s <= self.previous_timestamp_s:
            timestamp_s = self.previous_timestamp_s + 1.0 / self.fps
        self.previous_timestamp_s = timestamp_s
        return timestamp_s, "fps_fallback"
