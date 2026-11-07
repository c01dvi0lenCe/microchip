"""Pure manual intent geometry over an immutable timed open-loop plan.

No method sends commands or assumes physical droplet arrival. Only reconcile
acknowledged active electrodes here. A missing task electrode is an invalid
state; the runtime never authorizes manual edits to protected task electrodes.
"""
from __future__ import annotations

from collections.abc import Mapping

from controllers.open_loop_sequence import OpenLoopPlan, compile_routes
from controllers.timed_mixing import reminder_ids


def _electrode_id(eid):
    if isinstance(eid, bool) or not isinstance(eid, int) or not 1 <= eid <= 420:
        raise ValueError(f'电极须为1–420整数: {eid!r}')
    return eid


def _active_ids(values):
    try:
        return frozenset(_electrode_id(eid) for eid in values)
    except TypeError as exc:
        raise ValueError('活动电极须为编号集合') from exc


class OpenLoopManualOverlay:
    """Compose task positions with mutable, electrically confirmed extra holds.

    ``phase`` is the currently applied zero-based plan phase, not the next
    requested phase. Conflict queries are read-only. Task-list electrodes are
    protected for the entire plan, including already traversed electrodes.
    Only safe external manual switches are permitted by the shared runtime.
    """

    def __init__(self, plan):
        if not isinstance(plan, OpenLoopPlan):
            raise ValueError('须提供已编译开环路径')
        self._plan = plan
        self._hold_ids = plan.hold_ids

    @property
    def plan(self):
        return self._plan

    @property
    def hold_ids(self):
        return self._hold_ids

    def current_task_ids(self, phase):
        return frozenset(self.plan.positions_at(phase).values())

    def targets_at(self, phase):
        return self.current_task_ids(phase) | self.hold_ids

    def _remaining_routes(self, phase):
        # Validation also rejects bool/float/out-of-range phases. A shorter
        # group's terminal electrode remains an actor throughout later phases.
        self.current_task_ids(phase)
        return {group: route[min(phase, len(route) - 1):]
                for group, route in self.plan.routes.items()}

    def conflict_reasons(self, changes, phase):
        """Return reasons to reject a manual intent, never change state.

        IDs and explicit binary states are strict integers (not booleans).
        Task-list/fault protection applies even to no-op or OFF intents. Extra
        holds may be switched OFF; geometric checks use the proposed complete
        hold set and remaining route rather than prohibiting hold edits.
        """
        routes = self._remaining_routes(phase)
        if not isinstance(changes, Mapping):
            raise ValueError('手动变更须为电极到0/1状态的映射')
        checked = {}
        for eid, state in changes.items():
            _electrode_id(eid)
            if isinstance(state, bool) or not isinstance(state, int) or state not in (0, 1):
                raise ValueError(f'电极状态须为0或1整数: {state!r}')
            checked[eid] = state

        touched = frozenset(checked)
        task_list = frozenset(eid for route in self.plan.routes.values() for eid in route)
        reasons = []
        for protected, description in ((task_list, '任务路径'),
                                       (reminder_ids(), '故障保护区')):
            overlap = touched & protected
            if overlap:
                reasons.append(f'手动操作涉及{description}: {sorted(overlap)}')

        proposed = set(self.hold_ids)
        for eid, state in checked.items():
            if state:
                proposed.add(eid)
            else:
                proposed.discard(eid)
        proposed.difference_update(self.current_task_ids(phase))
        try:
            compile_routes(routes, hold_ids=proposed)
        except ValueError as exc:
            reasons.append(f'剩余路径/保持冲突: {exc}')
        return tuple(reasons)

    def reconcile(self, active_ids, phase):
        """Record actual acknowledged extra holds, including unsafe ones.

        In particular, do not silently add a missing task electrode back to
        the active set. The caller owns lifecycle and all actuation.
        """
        task_ids = self.current_task_ids(phase)
        active = _active_ids(active_ids)
        self._hold_ids = active - task_ids

    def validate_resume(self, active_ids, phase):
        """Raise if current tasks or remaining geometry are unsafe.

        Holds are refreshed from acknowledged state only after every check
        passes. Failure has no effect on this overlay or its original plan.
        """
        task_ids = self.current_task_ids(phase)
        active = _active_ids(active_ids)
        missing = task_ids - active
        if missing:
            raise ValueError(f'当前任务电极未保持，须停止并重新核查: {sorted(missing)}')
        holds = active - task_ids
        compile_routes(self._remaining_routes(phase), hold_ids=holds)
        self._hold_ids = holds
