"""Independent fixed-dwell 2x2 single-drop motion; no merging or vision claim."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk

from .timed_mixing import TimedMixing, reminder_ids, STUCK_ON_IDS, STUCK_OFF_IDS
from .open_loop_manual_controller import ManualTransaction


class TimedMixingControllerMixin:
    def _init_timed_mixing(self):
        self.hardware_reminder_ids = reminder_ids()
        self.hardware_fault_types = {eid: '持续导通故障' for eid in STUCK_ON_IDS}
        self.hardware_fault_types.update({eid: '无法导通故障' for eid in STUCK_OFF_IDS})
        self.timed_mix_first_var = tk.IntVar(value=190)
        self.timed_mix_dwell_var = tk.DoubleVar(value=1.)
        self.timed_mix_cycles_var = tk.IntVar(value=2)
        self.timed_mix_status_var = tk.StringVar(value='固定时间开环 · 未启动')
        self._timed_mix_owned = False
        self._timed_mix_kind = 'single_square'
        self._timed_mix_step_requested = False
        self._timed_mix = None
        self._timed_mix_worker = None
        self._timed_mix_after_id = None
        self._timed_mix_results = queue.Queue()
        self._timed_mix_release_requested = False
        self._timed_mix_disconnect_requested = False

    def _build_timed_mixing_controls(self, parent):
        frame = tk.LabelFrame(parent, text='定时四宫格单滴移动（不依赖视觉到达）',
                              bg=self.colors['panel'], fg=self.colors['text'])
        frame.pack(fill='x', pady=(0, 5))
        row = tk.Frame(frame, bg=self.colors['panel'])
        row.pack(fill='x')
        for label, var, low, high, increment in (
                ('左上电极', self.timed_mix_first_var, 1, 379, 1),
                ('单步停留/s', self.timed_mix_dwell_var, .1, 60, .1),
                ('圈数', self.timed_mix_cycles_var, 1, 9999, 1)):
            tk.Label(row, text=label, bg=self.colors['panel']).pack(side='left', padx=(6, 3))
            tk.Spinbox(row, textvariable=var, from_=low, to=high, increment=increment,
                       width=6).pack(side='left')
        tk.Button(row, text='开始', command=self.start_timed_mixing).pack(side='left', padx=5)
        tk.Button(row, text='停止', command=self.stop_timed_mixing).pack(side='left')
        tk.Label(frame, textvariable=self.timed_mix_status_var, bg=self.colors['panel'],
                 fg=self.colors['muted']).pack(anchor='w', padx=7)

    def start_timed_mixing(self):
        if self._operator_only:
            self.log('请在手动电极页明确设置开环任务，旧默认四宫格入口不用于实物')
            return False
        if (self._timed_mix_owned or self._experiment_active or self.auto_running
                or self.planning_jobs.is_active or self.hardware_auto_owned
                or self.hardware_state_uncertain):
            self.log('四宫格移动未启动：任务占用或硬件状态未明确')
            return False
        if not self.is_simulation_mode() and not self.is_connected:
            self.log('四宫格移动未启动：请先连接串口并确认电极状态')
            return False
        with self.electrode_event_stream.lock:
            if self.electrode_event_stream.pending:
                self.log('四宫格移动未启动：已有未完成电极事务')
                return False
        try:
            seq = TimedMixing(self.timed_mix_first_var.get(), self.timed_mix_cycles_var.get(),
                              self.timed_mix_dwell_var.get())
        except (ValueError, TypeError, tk.TclError) as exc:
            self.log(f'四宫格移动参数错误：{exc}')
            return False
        active = self._active_electrode_ids()
        if active - {seq.route[0]}:
            self.log('四宫格移动未启动：请先关闭四宫格起点以外的活动电极')
            return False
        self._timed_mix = seq
        self._timed_mix_kind = 'single_square'
        self._timed_mix_mode = self.mode_var.get()
        self._timed_mix_owned = True
        self._timed_mix_release_requested = False
        self._timed_mix_disconnect_requested = False
        if set(seq.route) & self.hardware_reminder_ids:
            self.log('提醒：四宫格含故障／邻接提醒电极；持续导通故障不能由软件关闭命令证明已隔离')
        self.log(f'定时四宫格移动开始：{seq.route[:5]}，单步{seq.dwell_s:g}s；仅时间推进，不表示视觉到达')
        self._timed_mix_tick()
        return True

    def _timed_mix_send_line(self, command):
        # This worker path must never call Tk, connection toggles or GUI logs.
        ser = self.ser
        if not self.is_connected or ser is None:
            return False
        ser.write((command + '\r\n').encode('utf-8'))
        return True

    def _timed_mix_submit(self, eid):
        old = self._active_electrode_ids()
        targets = {eid} if isinstance(eid, int) else set(eid)
        if self._timed_mix_kind == 'open_loop':
            targets = set(self._open_loop_composed_targets(self._timed_mix.index))
        changes = {i: 0 for i in old - targets}
        changes.update({i: 1 for i in targets - old})
        if not changes:
            # Reassert the starting hold through a fresh acknowledged transaction.
            changes.update({i: 1 for i in targets})
        if self.is_simulation_mode():
            self._timed_mix_accept(eid, changes, time.monotonic())
            return
        self._timed_mix_start_transaction(eid, changes)

    def _timed_mix_start_transaction(self, eid, changes):
        if self._timed_mix_worker is not None:
            raise RuntimeError('An electrode transaction is already in flight')
        if self._timed_mix_kind == 'open_loop':
            self._open_loop_release_required = True
        self._timed_mix_inflight_changes = dict(changes)
        def work():
            try:
                result = self.electrode_transactions.apply_changes(changes)
                self._timed_mix_results.put((eid, changes, result, '', time.monotonic()))
            except Exception as exc:
                self._timed_mix_results.put((eid, changes, None, str(exc), time.monotonic()))
        self._timed_mix_worker = threading.Thread(target=work, name='timed-mix-transaction', daemon=True)
        self._timed_mix_worker.start()
        label = eid
        if self._timed_mix_kind == 'open_loop':
            projected = self._active_electrode_ids() - {i for i,state in changes.items() if not state}
            projected.update(i for i,state in changes.items() if state)
            label = sorted(projected)
        self.timed_mix_status_var.set(f'请求 {label} · 等待APPLIED')
        self._draw_matrix_canvas()

    def _timed_mix_accept(self, eid, changes, at, sequence=''):
        if isinstance(eid, ManualTransaction):
            self._accept_open_loop_manual(eid, changes, at, sequence)
            return
        for changed, state in changes.items():
            self.update_ui_only(changed, state)
        self._timed_mix.applied(eid, at)
        prefix = '模拟生效' if self._timed_mix_mode == '仿真' else 'APPLIED已接收'
        label = sorted(self._active_electrode_ids()) if self._timed_mix_kind == 'open_loop' else eid
        self.timed_mix_status_var.set(f'{prefix} {label} · {self._timed_mix.index-1}/{len(self._timed_mix.route)-1}步')
        self.log(f'定时电极 {prefix}：电极{label}；从此计时{self._timed_mix.dwell_s:g}s')
        if self._timed_mix_kind == 'open_loop':
            self._open_loop_on_applied(eid, at)

    def _timed_mix_tick(self):
        if self._timed_mix_after_id is not None:
            self.root.after_cancel(self._timed_mix_after_id)
            self._timed_mix_after_id = None
        if not self._timed_mix_owned:
            return
        if (self._timed_mix_kind == 'open_loop' and self._open_loop_journal.error):
            self._timed_mix.stop()
            self.log(f'开环日志异常，停止后续步进：{self._open_loop_journal.error}')
        if self._timed_mix_kind == 'open_loop' and self._timed_mix_mode != '仿真':
            with self.electrode_event_stream.lock:
                known = self.electrode_event_stream.known
            if not known:
                self.hardware_state_uncertain = True
                self._timed_mix.stop()
                self.timed_mix_status_var.set('电极状态失去确认，停止后续步进')
        if self._timed_mix_mode != '仿真' and not self.is_connected:
            self.hardware_state_uncertain = True
            self._timed_mix.stop()
            self.timed_mix_status_var.set('连接中断 · 已取消后续步进')
        try:
            eid, changes, result, error, at = self._timed_mix_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._timed_mix_worker = None
            self._timed_mix_inflight_changes = {}
            if result is not None and result.applied:
                self._timed_mix_accept(eid, changes, at, getattr(result,'sequence',''))
            else:
                if isinstance(eid, ManualTransaction):
                    self._open_loop_manual_record('failed',eid,
                        sequence=getattr(result,'sequence',''),reason=error or getattr(result,'error','unknown'))
                    self._open_loop_manual_inflight = None
                self.hardware_state_uncertain = True
                self._timed_mix.stop()
                self.log(f'电极通信失败，状态未知：{error or getattr(result,"error","unknown")}')
                self.timed_mix_status_var.set('通信失败 · 状态未知')
        if not self._timed_mix.running and self._timed_mix_kind == 'open_loop':
            self._cancel_open_loop_manual('stopped_or_unknown')
        if not self._timed_mix.running and self._timed_mix_worker is None:
            self._finish_timed_mixing()
            return
        if self._timed_mix_worker is None:
            if self._shared_open_loop_manual() and self._dispatch_open_loop_manual():
                self._timed_mix_after_id = self.root.after(20, self._timed_mix_tick)
                return
            if not self._timed_mix.running:
                self._finish_timed_mixing()
                return
            if self._timed_mix_kind == 'open_loop':
                eid = self._timed_mix.next_request(time.monotonic(), manual_step=self._timed_mix_step_requested)
            else:
                eid = self._timed_mix.next_request(time.monotonic())
            if eid is not None:
                if self._timed_mix_kind == 'open_loop':
                    self._timed_mix_step_requested = False
                    self._open_loop_on_request(eid)
                    if self._open_loop_journal.error:
                        self._timed_mix.stop()
                        self._finish_timed_mixing()
                        return
                self._timed_mix_submit(eid)
            elif self._timed_mix.complete:
                self._finish_timed_mixing()
                return
        self._timed_mix_after_id = self.root.after(20, self._timed_mix_tick)

    def stop_timed_mixing(self):
        if not self._timed_mix_owned:
            return
        self._timed_mix.stop()
        if self._timed_mix_kind == 'open_loop':
            self._cancel_open_loop_manual('operator_stop')
        if self._timed_mix_worker is not None:
            self.timed_mix_status_var.set('已停止后续步进 · 等待在途事务结果')
        else:
            self._finish_timed_mixing()

    def _finish_timed_mixing(self):
        self._timed_mix_owned = False
        if self._timed_mix_after_id is not None:
            self.root.after_cancel(self._timed_mix_after_id)
            self._timed_mix_after_id = None
        if not self.hardware_state_uncertain:
            self.timed_mix_status_var.set('定时循环完成 · 保持末电极' if self._timed_mix.complete else '已停止 · 保持最后生效电极')
        if self._timed_mix_release_requested:
            self._timed_mix_release_requested = False
            self.reset_all()
        if self._timed_mix_disconnect_requested:
            self._timed_mix_disconnect_requested = False
            self.toggle_connection()
        if self._timed_mix_kind == 'open_loop':
            self._open_loop_on_finish()

    def _draw_hardware_reminders(self, outline_only=False):
        from dmf.layout import cell_from_electrode_id
        for eid in self.hardware_reminder_ids:
            cell = cell_from_electrode_id(eid)
            self._draw_cell(cell, fill='' if outline_only else '#F6D5D5', outline='#B52E32', width=2)
            if not outline_only and self.buttons.get(eid, {}).get('state'):
                # Separate activation indicator: red reminder must remain visible.
                x0,y0,x1,y1=self._cell_rect(cell)
                self.matrix_canvas.create_oval(x1-6,y0+2,x1-2,y0+6,
                    fill=self.colors['btn_on'],outline=self.colors['btn_on'])
