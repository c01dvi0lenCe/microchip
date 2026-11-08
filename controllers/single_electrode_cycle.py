"""One manually started, APPLIED-paced pixel cycle using the shared worker."""
from pathlib import Path
import queue
import threading
import time
import tkinter as tk

from dmf.recording import clock_stamp
from .single_electrode_journal import SingleElectrodeJournal


class SingleElectrodeCycleMixin:
    def _init_single_electrode_cycle(self):
        self.single_cycle_electrode_var = tk.StringVar(value='')
        self.single_cycle_status_var = tk.StringVar(value='未启动')
        self.single_cycle_output_root = Path(__file__).resolve().parents[1] / 'results/single_electrode_cycle'
        self._single_cycle_journal = None
        self._single_cycle_stopping = False
        self._single_cycle_due_at = None
        self._single_cycle_state = 0
        self._single_cycle_error = ''

    def _build_single_electrode_cycle_controls(self, parent):
        row = tk.Frame(parent, bg=self.colors['panel'])
        row.pack(side='right')
        tk.Label(row, text='电极编号', bg=self.colors['panel']).pack(side='left', padx=(7, 4))
        self.single_cycle_entry = tk.Entry(row, textvariable=self.single_cycle_electrode_var, width=6)
        self.single_cycle_entry.pack(side='left')
        self.single_cycle_button = tk.Button(row, text='开始单电极循环', width=14,
                                            command=self.toggle_single_electrode_cycle)
        self.single_cycle_button.pack(side='left', padx=7)
        tk.Label(row, textvariable=self.single_cycle_status_var,
                 width=15, anchor='w',
                 bg=self.colors['panel'], fg=self.colors['muted']).pack(side='left', padx=4)

    def toggle_single_electrode_cycle(self):
        if self._timed_mix_owned and self._timed_mix_kind == 'single_cycle':
            self.stop_timed_mixing()
            return True
        return self.start_single_electrode_cycle()

    def start_single_electrode_cycle(self):
        if (self._timed_mix_owned or self._timed_mix_worker is not None
                or self._experiment_active or self.auto_running or self.planning_jobs.is_active
                or self.hardware_auto_owned or self.hardware_state_uncertain
                or self._open_loop_release_required):
            self.log('单电极循环未启动：任务占用或硬件状态未明确')
            return False
        if self.is_simulation_mode() or not self.is_connected:
            self.log('单电极循环未启动：请先连接实物串口')
            return False
        with self.electrode_event_stream.lock:
            known = self.electrode_event_stream.known
            pending = bool(self.electrode_event_stream.pending)
            active = set(self.electrode_event_stream.active)
        if not known or pending:
            self.log('单电极循环未启动：等待已确认的空闲电极状态')
            return False
        value = self.single_cycle_electrode_var.get().strip()
        if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= self.total_channels:
            self.log('单电极循环未启动：请选择一个1–420电极编号')
            return False
        target = int(value)
        if (active | self._active_electrode_ids()) - {target}:
            self.log('单电极循环未启动：请先关闭其他活动电极')
            return False
        if target in self.hardware_reminder_ids:
            self.log('单电极循环未启动：该电极属于已记录故障或邻接提醒区域')
            return False
        try:
            self._single_cycle_journal = SingleElectrodeJournal(
                self.single_cycle_output_root, target, self.electrode_event_stream)
        except Exception as exc:
            self.log(f'单电极循环未启动：日志创建失败，{exc}')
            return False
        self._single_cycle_output_dir = self._single_cycle_journal.output
        self._single_cycle_target = target
        self._single_cycle_stopping = False
        self._single_cycle_due_at = None
        self._single_cycle_state = 0
        self._single_cycle_error = ''
        self._timed_mix_kind = 'single_cycle'
        self._timed_mix_mode = self.mode_var.get()
        self._timed_mix_owned = True
        self._timed_mix_release_requested = False
        self._timed_mix_disconnect_requested = False
        self._timed_mix_inflight_changes = {}
        self.single_cycle_entry.config(state='disabled')
        self.single_cycle_button.config(text='停止单电极循环', state='normal')
        self.log(f'单电极循环开始：{target}，ON/OFF各250ms；日志 {self._single_cycle_output_dir}')
        self._single_cycle_submit(1)
        self._timed_mix_tick()
        return True

    def _single_cycle_submit(self, state):
        changes = {self._single_cycle_target: state}
        self._timed_mix_inflight_changes = changes

        def work():
            try:
                result = self.electrode_transactions.apply_changes(changes)
                error = '' if result.applied else result.error
            except Exception as exc:
                result, error = None, str(exc)
            self._timed_mix_results.put(('cycle', state, result, error, time.monotonic()))

        self.single_cycle_status_var.set(f'{self._single_cycle_target} {"ON" if state else "OFF"}待确认')
        self._timed_mix_worker = threading.Thread(target=work, name='single-pixel-transaction', daemon=True)
        self._timed_mix_worker.start()

    def _stop_single_electrode_cycle(self):
        self._single_cycle_stopping = True
        self.single_cycle_button.config(text='正在关闭电极', state='disabled')
        self.single_cycle_status_var.set('正在写入OFF')
        self._timed_mix_tick()

    def _single_cycle_release(self):
        target = self._single_cycle_target
        journal = self._single_cycle_journal

        def work():
            errors = [self._single_cycle_error] if self._single_cycle_error else []
            try:
                result = self.electrode_transactions.apply_changes({target: 0})
                if not result.applied:
                    errors.append('OFF: ' + result.error)
            except Exception as exc:
                errors.append('OFF: ' + str(exc))
            try:
                released = self.electrode_transactions.all_off()
                if not released:
                    errors.append('ALL_OFF未确认')
            except Exception as exc:
                released = False
                errors.append('ALL_OFF: ' + str(exc))
            error = '; '.join(errors)
            try:
                journal.finish(released, error)
            except Exception as exc:
                error += '; 日志保存失败: ' + str(exc)
            self._timed_mix_results.put(('release', released, None, error, time.monotonic()))

        self._timed_mix_inflight_changes = {target: 0}
        self._timed_mix_worker = threading.Thread(target=work, name='single-pixel-release', daemon=True)
        self._timed_mix_worker.start()

    def _single_cycle_tick(self):
        if self._timed_mix_after_id is not None:
            self.root.after_cancel(self._timed_mix_after_id)
            self._timed_mix_after_id = None
        if not self._timed_mix_owned:
            return
        with self.electrode_event_stream.lock:
            known = self.electrode_event_stream.known
        if not self.is_connected or not known or self._single_cycle_journal.error:
            self._single_cycle_stopping = True
            self._single_cycle_error = ('连接中断' if not self.is_connected
                                        else self._single_cycle_journal.error or '电极状态未知')
            self.hardware_state_uncertain = True
        try:
            kind, state, result, error, at = self._timed_mix_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._timed_mix_worker = None
            self._timed_mix_inflight_changes = {}
            if kind == 'release':
                self._finish_single_electrode_cycle(state, error)
                return
            if result is not None and result.applied:
                self.update_ui_only(self._single_cycle_target, state)
                self._single_cycle_state = state
                self._single_cycle_due_at = at + .25
                self.single_cycle_status_var.set(f'{self._single_cycle_target} · {"ON" if state else "OFF"}')
            else:
                self._single_cycle_error = error or '事务未确认'
                self._single_cycle_stopping = True
                self.hardware_state_uncertain = True
                self.log(f'单电极循环停止：{self._single_cycle_error}')
        if self._timed_mix_worker is None:
            if self._single_cycle_stopping:
                self._single_cycle_release()
            elif self._single_cycle_due_at is not None and time.monotonic() >= self._single_cycle_due_at:
                self._single_cycle_submit(1 - self._single_cycle_state)
        self._timed_mix_after_id = self.root.after(10, self._timed_mix_tick)

    def _finish_single_electrode_cycle(self, released, error):
        self._timed_mix_owned = False
        self._single_cycle_due_at = None
        self._timed_mix_release_requested = False
        self._open_loop_release_required = False
        self.hardware_state_uncertain = not released
        self.hardware_auto_owned = not released
        if released:
            self._clear_local_electrode_display()
        else:
            self.electrode_event_stream.emit(dict(event='state_unknown', **clock_stamp(), error=error))
        self.single_cycle_status_var.set('已停止 · 已确认' if released else '已停止 · 状态未知')
        self.single_cycle_entry.config(state='normal')
        self.single_cycle_button.config(text='开始单电极循环', state='normal')
        self.log('单电极循环结束' + (f'：{error}' if error else ''))
        if self._timed_mix_disconnect_requested:
            self._timed_mix_disconnect_requested = False
            if self.ser:
                self.ser.close()
            self._set_connection_state(False)
