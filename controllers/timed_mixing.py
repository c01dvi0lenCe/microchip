"""Pure APPLIED-paced open-loop mixing and visual-only hardware reminders."""
from __future__ import annotations

import math

STUCK_ON_IDS = frozenset({90, 337, 393})
STUCK_OFF_IDS = frozenset({399, 400})
TESTED_FAULT_IDS = STUCK_ON_IDS | STUCK_OFF_IDS


def reminder_ids():
    result = set(TESTED_FAULT_IDS)
    for eid in STUCK_ON_IDS:
        row, col = divmod(eid - 1, 20)
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            r, c = row + dr, col + dc
            if 0 <= r < 20 and 0 <= c < 20:
                result.add(r * 20 + c + 1)
    return frozenset(result)


def build_square_route(first: int, cycles: int):
    if isinstance(first, bool) or not isinstance(first, int) or not 1 <= first <= 400:
        raise ValueError('左上电极须为核心区整数编号')
    row, col = divmod(first - 1, 20)
    if row >= 19 or col >= 19:
        raise ValueError('左上电极不能在最后一行或最后一列')
    if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 9999:
        raise ValueError('圈数须为1–9999整数')
    return (first,) + (first + 1, first + 21, first + 20, first) * cycles


class TimedMixing:
    """No vision/arrival claim. At most one requested electrode awaits APPLIED."""
    def __init__(self, first, cycles, dwell_s):
        if not math.isfinite(dwell_s) or not .1 <= dwell_s <= 60:
            raise ValueError('单步停留须为0.1–60秒')
        self.route = build_square_route(first, cycles)
        self.dwell_s = float(dwell_s)
        self.index = 0
        self.pending = None
        self.active_id = None
        self.deadline = None
        self.running = True
        self.complete = False

    def next_request(self, now):
        if not math.isfinite(now) or now < 0:
            raise ValueError('invalid monotonic time')
        if not self.running or self.pending is not None:
            return None
        if self.deadline is not None and now < self.deadline:
            return None
        if self.index == len(self.route):
            self.running = False
            self.complete = True
            return None
        self.pending = self.route[self.index]
        return self.pending

    def applied(self, eid, at):
        if eid != self.pending or not math.isfinite(at) or at < 0:
            raise ValueError('unmatched APPLIED/time')
        self.active_id = eid
        self.pending = None
        self.index += 1
        self.deadline = at + self.dwell_s

    def stop(self):
        self.running = False
