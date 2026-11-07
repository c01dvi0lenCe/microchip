"""Queued manual intents for the real operator's timed open-loop session."""
from collections import deque
from dataclasses import dataclass

from .open_loop_manual import OpenLoopManualOverlay


@dataclass(frozen=True)
class ManualTransaction:
    intent_id: int
    changes: tuple[tuple[int, int], ...]


class OpenLoopManualControllerMixin:
    def _shared_open_loop_manual(self):
        return (self._operator_only and self._timed_mix_owned
                and self._timed_mix_kind == 'open_loop')

    def _init_open_loop_manual(self, plan):
        self._open_loop_manual_overlay = OpenLoopManualOverlay(plan)
        self._open_loop_manual_queue = deque()
        self._open_loop_manual_inflight = None
        self._open_loop_manual_next_id = 1
        self._timed_mix_inflight_changes = {}

    def _open_loop_manual_phase(self):
        return max(0, self._timed_mix.index - 1)

    def _open_loop_composed_targets(self, phase):
        if self._shared_open_loop_manual():
            return self._open_loop_manual_overlay.targets_at(phase)
        return self._open_loop_plan.active_at(phase)

    def _open_loop_manual_record(self, event, intent, *, sequence='', reason='', at=''):
        journal = self._open_loop_journal
        if journal is not None:
            journal.manual(event, intent.intent_id, dict(intent.changes),
                           self._open_loop_manual_phase(), sequence=sequence,
                           reason=reason, at=at)

    def _open_loop_manual_ready(self):
        with self.electrode_event_stream.lock:
            known = self.electrode_event_stream.known
        return (self._shared_open_loop_manual() and self._timed_mix.running
                and self.is_connected and known and not self.hardware_state_uncertain
                and not self._timed_mix_release_requested
                and not self._timed_mix_disconnect_requested
                and self._open_loop_journal is not None
                and not self._open_loop_journal.error)

    def _queue_open_loop_manual(self, changes):
        if not self._open_loop_manual_ready():
            self.log('手动操作未排队：任务已停止、状态未知或日志不可用')
            return False
        try:
            reasons = self._open_loop_manual_overlay.conflict_reasons(
                changes, self._open_loop_manual_phase())
        except (ValueError, TypeError) as exc:
            self.log(f'手动操作拒绝：{exc}')
            return False
        if reasons:
            self.log('手动操作拒绝：' + '；'.join(reasons))
            return False
        pending = {eid for intent in self._open_loop_manual_queue for eid, _ in intent.changes}
        if self._open_loop_manual_inflight is not None:
            pending.update(eid for eid, _ in self._open_loop_manual_inflight.changes)
        if pending.intersection(changes):
            self.log('手动操作拒绝：该电极已有待确认操作，请等待APPLIED')
            return False
        if len(self._open_loop_manual_queue) >= 64:
            self.log('手动操作拒绝：待执行队列已满')
            return False
        intent = ManualTransaction(self._open_loop_manual_next_id, tuple(sorted(changes.items())))
        self._open_loop_manual_next_id += 1
        self._open_loop_manual_record('queued', intent)
        if self._open_loop_journal.error:
            self._timed_mix.stop()
            self._timed_mix_tick()
            return False
        self._open_loop_manual_queue.append(intent)
        self._timed_mix_tick()
        self._draw_matrix_canvas()
        return True

    def _dispatch_open_loop_manual(self):
        """Run on Tk thread, only when the single worker is idle."""
        while self._open_loop_manual_queue:
            intent = self._open_loop_manual_queue.popleft()
            if not self._open_loop_manual_ready():
                self._open_loop_manual_record('cancelled', intent, reason='session_not_ready')
                self._cancel_open_loop_manual('session_not_ready')
                self._timed_mix.stop()
                return False
            # Re-evaluate after earlier manual ACKs; queued holds may conflict together.
            reasons = self._open_loop_manual_overlay.conflict_reasons(
                dict(intent.changes), self._open_loop_manual_phase())
            if reasons:
                self._open_loop_manual_record('rejected', intent, reason='；'.join(reasons))
                self.log('排队手动操作拒绝：' + '；'.join(reasons))
                continue
            changes = {eid:state for eid,state in intent.changes if self.buttons[eid]['state'] != state}
            if not changes:
                self._open_loop_manual_record('no_change', intent)
                continue
            self._open_loop_manual_record('submitted', intent)
            if self._open_loop_journal.error:
                self._timed_mix.stop()
                self._cancel_open_loop_manual('log_error')
                return False
            self._open_loop_manual_inflight = intent
            self._timed_mix_start_transaction(intent, changes)
            return True
        return False

    def _accept_open_loop_manual(self, intent, changes, at, sequence=''):
        for eid, state in changes.items():
            self.update_ui_only(eid, state)
        self._open_loop_manual_overlay.reconcile(self._active_electrode_ids(), self._open_loop_manual_phase())
        self._open_loop_manual_record('applied_confirmed', intent, sequence=sequence, at=at)
        self._open_loop_manual_inflight = None
        self.timed_mix_status_var.set('手动电极APPLIED已确认 · 开环任务未额外步进')
        self._draw_matrix_canvas()

    def _cancel_open_loop_manual(self, reason):
        for intent in tuple(getattr(self, '_open_loop_manual_queue', ())):
            self._open_loop_manual_record('cancelled', intent, reason=reason)
        if hasattr(self, '_open_loop_manual_queue'):
            self._open_loop_manual_queue.clear()

    def _open_loop_pending_ids(self):
        if not self._shared_open_loop_manual():
            return set()
        ids = set(getattr(self, '_timed_mix_inflight_changes', {}))
        ids.update(eid for intent in self._open_loop_manual_queue for eid,_ in intent.changes)
        return ids

    def _draw_open_loop_pending(self):
        from dmf.layout import cell_from_electrode_id
        for eid in self._open_loop_pending_ids():
            x0,y0,x1,y1 = self._cell_rect(cell_from_electrode_id(eid))
            self.matrix_canvas.create_rectangle(x0+3,y0+3,x1-3,y1-3,
                fill='', outline='#B9770E', width=2, dash=(3,2))
