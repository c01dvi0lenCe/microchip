"""Frozen command geometry and APPLIED-paced timing, never physical arrival.

Preflight checks commanded positions only. In particular it cannot prove that
stuck-on electrodes are isolated, or that any droplet followed its commands.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from dmf.layout import cell_from_electrode_id
from dmf.planning.geometry import pull_risk_neighbors
from controllers.timed_mixing import reminder_ids


def _core_id(eid):
    if isinstance(eid, bool) or not isinstance(eid, int) or not 1 <= eid <= 400:
        raise ValueError(f'核心电极须为1–400整数: {eid!r}')
    return eid


def _group_id(group):
    if not isinstance(group, str) or not group.strip():
        raise ValueError('组ID须为非空字符串')
    return group


def _hold_id(eid):
    if isinstance(eid, bool) or not isinstance(eid, int):
        raise ValueError(f'保持电极须为已有布局整数编号: {eid!r}')
    cell_from_electrode_id(eid)
    return eid


@dataclass(frozen=True)
class FourCellTask:
    group_id: str
    start: int | None
    ring: tuple[int | None, ...]
    target: int | None

    def __post_init__(self):
        # Freeze a caller-provided list too; validation belongs to compilation.
        try:
            object.__setattr__(self, 'ring', tuple(self.ring))
        except TypeError as exc:
            raise ValueError('四宫格须提供四个有序电极') from exc


def four_cell_missing_fields(tasks) -> dict[str, tuple[str, ...]]:
    """Report unset editing fields in task order, without validating geometry.

    Only ``None`` denotes an unset electrode. Present but invalid IDs, duplicate
    ring points and ring ordering remain the compiler's validation concerns.
    """
    missing = {}
    seen = set()
    for task in tasks:
        if not isinstance(task, FourCellTask):
            raise ValueError('四宫格任务类型不正确')
        group = _group_id(task.group_id)
        if group in seen:
            raise ValueError(f'重复组ID: {group}')
        seen.add(group)
        fields = []
        if task.start is None:
            fields.append('起点')
        if task.target is None:
            fields.append('终点')
        selected = sum(eid is not None for eid in task.ring)
        if selected < 4 or None in task.ring:
            fields.append(f'四点（已选{selected}/4）')
        if fields:
            missing[group] = tuple(fields)
    return missing


@dataclass(frozen=True)
class OpenLoopPlan:
    routes: Mapping[str, tuple[int, ...]]
    hold_ids: frozenset[int] = frozenset()
    length: int = field(init=False)

    def __post_init__(self):
        routes = {group: tuple(route) for group, route in self.routes.items()}
        if not routes or any(not route for route in routes.values()):
            raise ValueError('至少需要一组非空路径')
        object.__setattr__(self, 'routes', MappingProxyType(routes))
        object.__setattr__(self, 'hold_ids', frozenset(self.hold_ids))
        object.__setattr__(self, 'length', max(map(len, routes.values())))

    def positions_at(self, index):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < self.length:
            raise ValueError('全局步索引超出路径范围')
        return {group: route[min(index, len(route) - 1)] for group, route in self.routes.items()}

    def active_at(self, index):
        return frozenset(self.positions_at(index).values()) | self.hold_ids


def compile_four_cell_tasks(tasks, cycles, *, hold_ids=(), forbidden_ids=None):
    """Expand each clicked ring: full cycles followed by its forward prefix."""
    if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= 9999:
        raise ValueError('圈数须为1–9999整数')
    tasks = tuple(tasks)
    missing = four_cell_missing_fields(tasks)
    if missing:
        details = '；'.join(f'组{group}: 缺少{"、".join(fields)}'
                           for group, fields in missing.items())
        raise ValueError(f'四宫格任务未完成：{details}')
    routes = {}
    for task in tasks:
        if not isinstance(task, FourCellTask):
            raise ValueError('四宫格任务类型不正确')
        group = _group_id(task.group_id)
        if group in routes:
            raise ValueError(f'重复组ID: {group}')
        ring = tuple(_core_id(eid) for eid in task.ring)
        if len(ring) != 4 or len(set(ring)) != 4:
            raise ValueError(f'组{group}: 四宫格须有四个互异电极')
        cells = tuple(cell_from_electrode_id(eid) for eid in ring)
        rows = {cell[0] for cell in cells}
        cols = {cell[1] for cell in cells}
        if (len(rows) != 2 or len(cols) != 2 or max(rows) - min(rows) != 1
                or max(cols) - min(cols) != 1):
            raise ValueError(f'组{group}: 四点须构成实际2×2四宫格')
        for a, b in zip(cells, cells[1:] + cells[:1]):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                raise ValueError(f'组{group}: 点击顺序须沿四宫格逐点四邻接')
        start, target = _core_id(task.start), _core_id(task.target)
        if start not in ring or target not in ring:
            raise ValueError(f'组{group}: 起点和终点须在所选四宫格内')
        offset = ring.index(start)
        rotated = ring[offset:] + ring[:offset]
        lap = rotated[1:] + rotated[:1]
        routes[group] = (start,) + lap * cycles + rotated[1:rotated.index(target) + 1]
    return compile_routes(routes, hold_ids=hold_ids, forbidden_ids=forbidden_ids)


def compile_routes(routes: Mapping[str, Sequence[int]], *, hold_ids=(), forbidden_ids=None):
    """Validate one frozen, synchronized command sequence including holds.

    All distinct previous/current global transitions are checked once, keeping
    repeated 9999-cycle ring runs practical without weakening the preflight.
    """
    if not isinstance(routes, Mapping) or not routes:
        raise ValueError('至少需要一组路径')
    forbidden = frozenset(_core_id(eid) for eid in (reminder_ids() if forbidden_ids is None else forbidden_ids))
    holds = frozenset(_hold_id(eid) for eid in hold_ids)
    frozen = {}
    for group, route in routes.items():
        _group_id(group)
        try:
            route = tuple(_core_id(eid) for eid in route)
        except TypeError as exc:
            raise ValueError(f'组{group}: 路径须为电极序列') from exc
        if not route:
            raise ValueError(f'组{group}: 路径不能为空')
        for index, (a, b) in enumerate(zip(route, route[1:]), 1):
            ac, bc = cell_from_electrode_id(a), cell_from_electrode_id(b)
            if abs(ac[0] - bc[0]) + abs(ac[1] - bc[1]) > 1:
                raise ValueError(f'组{group} 全局步{index}: {a}→{b}不是核心四邻接')
        frozen[group] = route
    used = holds | frozenset(eid for route in frozen.values() for eid in route)
    blocked = used & forbidden
    if blocked:
        raise ValueError(f'路径/保持点经过故障保护区: {sorted(blocked)}')
    plan = OpenLoopPlan(frozen, holds)
    cells = {eid: cell_from_electrode_id(eid) for eid in used}
    zones = {eid: pull_risk_neighbors(cell) for eid, cell in cells.items()}

    # Labels remain separate even for duplicate positions, so same-cell conflicts
    # cannot disappear through set union. Holds are individual stationary actors.
    groups = tuple(plan.routes)
    hold_order = tuple(sorted(holds))
    labels = groups + tuple(f'额外保持{eid}' for eid in hold_order)
    seen = set()
    previous = None
    for index in range(plan.length):
        current = tuple(route[min(index, len(route) - 1)] for route in plan.routes.values()) + hold_order
        old = current if previous is None else previous
        signature = (old, current)
        if signature not in seen:
            seen.add(signature)
            for left in range(len(labels)):
                for right in range(left + 1, len(labels)):
                    if old[left] == current[right] and old[right] == current[left]:
                        raise ValueError(f'全局步{index}: 组{labels[left]}/{labels[right]}对向交换/同格冲突')
                    for a in (old[left], current[left]):
                        for b in (old[right], current[right]):
                            if cells[b] in zones[a]:
                                raise ValueError(f'全局步{index}: 组{labels[left]}/{labels[right]} 电极{a}/{b}拉拽/保持冲突')
        previous = current
    return plan


class _ActiveRoute(Sequence):
    """Lazy complete frames, one per global phase, not 40,000 allocated sets."""
    def __init__(self, plan):
        self._plan = plan

    def __len__(self):
        return self._plan.length

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self[i] for i in range(*index.indices(len(self))))
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError('路径索引须为整数')
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self._plan.active_at(index)


class TimedPlanSequence:
    """At most one full frame pending; APPLIED is electrical, not vision."""
    def __init__(self, plan, dwell_s, *, manual=False):
        if (isinstance(dwell_s, bool) or not isinstance(dwell_s, (int, float))
                or not math.isfinite(dwell_s) or not .1 <= dwell_s <= 60):
            raise ValueError('单步停留须为0.1–60秒')
        if not isinstance(plan, OpenLoopPlan):
            raise ValueError('须提供已编译开环路径')
        self.plan = plan
        self.route = _ActiveRoute(plan)
        self.dwell_s = float(dwell_s)
        self.manual = bool(manual)
        self.paused = False
        self.index = 0
        self.pending = None
        self.active_id = None
        self.deadline = None
        self.running = True
        self.complete = False
        self._last_time = None
        self._stopped = False
        self._pending_requested_at = None
        self._pending_resume_anchor = None

    def _time(self, value, *, pending_history=False):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
                or (not pending_history and self._last_time is not None and value < self._last_time)):
            raise ValueError('invalid nonnegative monotonic time')
        return float(value)

    def next_request(self, now, manual_step=False):
        now = self._time(now)
        self._last_time = now
        if not self.running or self.pending is not None:
            return None
        if self.deadline is not None and now < self.deadline:
            return None
        # Completion needs no transaction, including when paused/manual.
        if self.index == len(self.route):
            self.running = False
            self.complete = True
            return None
        if self.index and (self.manual or self.paused) and not manual_step:
            return None
        self.pending = self.route[self.index]
        self._pending_requested_at = now
        self._pending_resume_anchor = None
        return self.pending

    def applied(self, target, at):
        # A worker's actual ACK receive stamp may precede a later UI poll or
        # resume while its result is queued. Its causal floor is this request,
        # not the latest UI observation; never rewrite the recorded ACK stamp.
        at = self._time(at, pending_history=True)
        if self.pending is None or target != self.pending:
            raise ValueError('unmatched APPLIED')
        if at < self._pending_requested_at:
            raise ValueError('APPLIED predates its pending request')
        self._last_time = max(self._last_time, at)
        self.active_id = self.pending
        self.pending = None
        self.index += 1
        anchor = at if self._pending_resume_anchor is None else max(at, self._pending_resume_anchor)
        self.deadline = anchor + self.dwell_s
        self._pending_requested_at = None
        self._pending_resume_anchor = None

    def pause(self):
        self.paused = True

    def resume(self, now):
        now = self._time(now)
        self._last_time = now
        if self._stopped or self.complete:
            return
        self.paused = False
        if self.pending is not None:
            self._pending_resume_anchor = now
        if self.active_id is not None:
            self.deadline = now + self.dwell_s

    def stop(self):
        self.running = False
        self._stopped = True
