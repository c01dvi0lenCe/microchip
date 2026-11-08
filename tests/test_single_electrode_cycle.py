import csv
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import STM32MatrixController
from dmf.layout import cell_from_electrode_id
from dmf.recording import clock_stamp


class SingleElectrodeCycleTests(unittest.TestCase):
    def setUp(self):
        self.port_guard = patch('serial.tools.list_ports.comports', return_value=[])
        self.serial_guard = patch('serial.Serial', side_effect=AssertionError('No hardware'))
        self.port_guard.start()
        self.serial_guard.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = STM32MatrixController(self.root, operator_only=True)
        self.root.update_idletasks()
        self.temp = tempfile.TemporaryDirectory()
        self.app.single_cycle_output_root = Path(self.temp.name)
        self.lines = []
        self.sequence = None
        self.changes = {}
        self.commits = []
        self.gate = threading.Event()
        self.gate.set()
        self.entered = threading.Event()
        self.fail_on = False
        self.fail_off = False
        self.fail_release = False

    def tearDown(self):
        self.gate.set()
        if getattr(self.app, '_timed_mix_owned', False):
            self.app.stop_timed_mixing()
            self.drain()
        self.app.is_connected = False
        self.app.ser = None
        for after_id in self.root.tk.call('after', 'info'):
            self.root.after_cancel(after_id)
        self.app.on_close()
        self.app.recv_thread.join(2)
        self.temp.cleanup()
        self.port_guard.stop()
        self.serial_guard.stop()

    def feature(self):
        self.assertTrue(callable(getattr(self.app, 'start_single_electrode_cycle', None)),
                        'Missing approved single-electrode cycle control')

    def connect_memory(self):
        def send(payload):
            line = payload.decode().strip()
            self.lines.append(line)
            client = self.app.electrode_transactions
            if line.startswith('BEGIN:'):
                self.sequence = int(line.split(':')[1])
                self.changes = {}
                client.feed_line(f'ACK:{self.sequence}:BEGIN')
            elif line.startswith('SET:'):
                _, electrode, state = line.split(':')
                self.changes[int(electrode)] = int(state)
                client.feed_line(f'ACK:{self.sequence}:SET:{electrode}')
            elif line.startswith('COMMIT:'):
                self.commits.append(dict(self.changes))
                if self.changes == {190: 1}:
                    self.entered.set()
                    self.gate.wait(2)
                fail = self.fail_on if any(self.changes.values()) else self.fail_off
                if not fail:
                    client.feed_line(f'ACK:{self.sequence}:APPLIED')
            elif line == 'ALL_OFF' and not self.fail_release:
                client.feed_line('ACK:ALL_OFF')
            return len(payload)

        self.app.ser = SimpleNamespace(write=send, close=lambda: None, is_open=True, in_waiting=0)
        self.app.is_connected = True
        self.app.electrode_transactions.ack_timeout_s = .015
        self.app.electrode_transactions.max_retries = 0
        self.app.electrode_event_stream.emit({'event': 'all_off_confirmed'})

    def start(self, electrode='190'):
        self.feature()
        self.connect_memory()
        self.app.single_cycle_electrode_var.set(electrode)
        self.assertTrue(self.app.start_single_electrode_cycle())

    def collect(self):
        worker = self.app._timed_mix_worker
        if worker is not None:
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.app._timed_mix_tick()

    def drain(self):
        for _ in range(12):
            if not self.app._timed_mix_owned:
                return
            self.collect()
        self.fail('Cycle ownership did not drain')

    def test_default_idle_and_one_button_on_manual_page(self):
        self.feature()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertIsNone(self.app._timed_mix_worker)
        self.assertEqual(self.app.single_cycle_electrode_var.get(), '')
        self.assertEqual(self.app.single_cycle_button.cget('text'), '开始单电极循环')
        manual = self.app.main_notebook.tabs()[0]
        widget = self.app.single_cycle_button
        parents = []
        while widget is not None:
            parents.append(str(widget))
            widget = getattr(widget, 'master', None)
        self.assertIn(manual, parents)

    def test_cycle_controls_fit_default_and_minimum_window_without_new_row(self):
        self.feature()
        self.root.attributes('-alpha', 0)
        self.root.deiconify()
        for size in ('1360x820', '1180x760'):
            with self.subTest(size=size):
                self.root.geometry(size)
                self.root.update()
                self.root.update_idletasks()
                row = self.app.single_cycle_button.master
                band = row.master
                self.assertGreaterEqual(row.winfo_width(), row.winfo_reqwidth())
                self.assertLessEqual(row.winfo_x() + row.winfo_width(), band.winfo_width())
                self.assertGreaterEqual(self.app.manual_canvas.winfo_height(), 300)

    def test_selection_is_explicit_not_hover_active_or_task_target(self):
        self.feature()
        self.connect_memory()
        self.app.hover_cell = cell_from_electrode_id(191)
        self.app.start_cell = cell_from_electrode_id(192)
        self.app.goal_cell = cell_from_electrode_id(193)
        self.assertFalse(self.app.start_single_electrode_cycle())
        self.assertEqual(self.lines, [])
        for value in ('0', '421', '190,191', '1.5'):
            self.app.single_cycle_electrode_var.set(value)
            self.assertFalse(self.app.start_single_electrode_cycle())
        self.app.manual_toggle_electrode(cell_from_electrode_id(190))
        self.assertEqual(self.app.single_cycle_electrode_var.get(), '190')
        self.assertTrue(self.app.start_single_electrode_cycle())
        self.collect()
        self.assertEqual(self.commits[-1], {190: 1})

    def test_applied_paced_fixed_dwell_repeats_without_cycle_limit(self):
        self.start()
        self.collect()
        self.assertEqual(self.commits, [{190: 1}])
        self.assertEqual(self.app.buttons[190]['state'], 1)
        for state in (0, 1, 0, 1, 0, 1):
            due = self.app._single_cycle_due_at
            with patch('controllers.single_electrode_cycle.time.monotonic', return_value=due-.001):
                self.app._timed_mix_tick()
            self.assertIsNone(self.app._timed_mix_worker)
            with patch('controllers.single_electrode_cycle.time.monotonic', return_value=due):
                self.app._timed_mix_tick()
            self.collect()
            self.assertEqual(self.commits[-1], {190: state})
            self.assertGreaterEqual(self.app._single_cycle_due_at, time.monotonic()+.20)
        self.assertNotIn('ALL_OFF', self.lines)
        self.assertTrue(self.app._timed_mix_owned)

    def test_pending_applied_does_not_color_or_advance_and_stop_drains_then_off(self):
        self.gate.clear()
        self.start()
        self.assertTrue(self.entered.wait(1))
        self.assertEqual(self.app.buttons[190]['state'], 0)
        self.app.single_cycle_button.invoke()
        self.assertTrue(self.app._timed_mix_owned)
        self.assertEqual(self.commits, [{190: 1}])
        self.gate.set()
        self.drain()
        self.assertEqual(self.commits, [{190: 1}, {190: 0}])
        self.assertEqual(self.lines[-1], 'ALL_OFF')
        self.assertEqual(self.app._active_electrode_ids(), set())
        self.app._timed_mix_tick()
        self.assertEqual(len(self.commits), 2)

    def test_all_manual_changes_and_other_tasks_rejected_while_owned(self):
        self.start()
        self.collect()
        before = list(self.lines)
        self.assertFalse(self.app._apply_manual_electrode_changes({250: 1}))
        self.app.toggle_electrode(190)
        self.app.manual_toggle_electrode(cell_from_electrode_id(250))
        self.assertFalse(self.app.start_open_loop())
        self.assertFalse(self.app.start_single_electrode_cycle())
        self.app.start_auto_control()
        self.app.start_experiment()
        self.assertFalse(self.app.auto_running)
        self.assertFalse(self.app._experiment_active)
        self.assertEqual(self.lines, before)
        self.assertEqual(self.app.single_cycle_electrode_var.get(), '190')

    def test_busy_unknown_pending_disconnected_and_other_active_reject_start(self):
        self.feature()
        self.app.single_cycle_electrode_var.set('190')
        self.assertFalse(self.app.start_single_electrode_cycle())
        self.connect_memory()
        for attr in ('auto_running', '_experiment_active', 'hardware_auto_owned', 'hardware_state_uncertain'):
            setattr(self.app, attr, True)
            self.assertFalse(self.app.start_single_electrode_cycle())
            setattr(self.app, attr, False)
        self.app.electrode_event_stream.pending.add('other')
        self.assertFalse(self.app.start_single_electrode_cycle())
        self.app.electrode_event_stream.pending.clear()
        self.app.electrode_event_stream.known = False
        self.assertFalse(self.app.start_single_electrode_cycle())
        self.app.electrode_event_stream.known = True
        self.app.update_ui_only(250, 1)
        self.assertFalse(self.app.start_single_electrode_cycle())
        self.assertEqual(self.lines, [])

    def test_emergency_and_disconnect_release_on_worker_not_tk(self):
        for action in ('reset_all', 'toggle_connection'):
            with self.subTest(action=action):
                self.start()
                self.collect()
                with patch.object(self.app.electrode_transactions, 'all_off',
                        wraps=self.app.electrode_transactions.all_off) as off:
                    getattr(self.app, action)()
                    self.drain()
                    off.assert_called_once()
                self.assertEqual(self.commits[-1], {190: 0})
                self.assertEqual(self.lines[-1], 'ALL_OFF')
                self.assertFalse(self.app.hardware_state_uncertain)
                if action == 'toggle_connection':
                    self.assertFalse(self.app.is_connected)

    def test_close_is_nonblocking_and_waits_for_release_and_journal(self):
        self.gate.clear()
        self.start()
        self.assertTrue(self.entered.wait(1))
        with patch.object(self.root, 'destroy') as destroy:
            self.app.on_close()
            destroy.assert_not_called()
            self.assertTrue(self.app._timed_mix_owned)
            self.gate.set()
            self.drain()
            self.app.on_close()
            destroy.assert_called_once()
        self.assertEqual(self.commits[-1], {190: 0})
        self.assertTrue((self.app._single_cycle_output_dir/'manifest.json').exists())

    def test_on_failure_stops_future_on_marks_unknown_and_attempts_release(self):
        self.fail_on = True
        self.fail_off = True
        self.fail_release = True
        self.start()
        self.drain()
        self.assertEqual(self.commits, [{190: 1}, {190: 0}])
        self.assertIn('ALL_OFF', self.lines)
        self.assertTrue(self.app.hardware_state_uncertain)
        self.assertFalse(self.app.electrode_event_stream.known)
        self.assertIn('未知', self.app.single_cycle_status_var.get())

    def test_lost_connection_during_inflight_ack_still_attempts_off_and_release(self):
        self.gate.clear()
        self.start()
        self.assertTrue(self.entered.wait(1))
        self.app.is_connected = False
        self.app._timed_mix_tick()
        self.gate.set()
        with patch.object(self.app.electrode_transactions, 'apply_changes',
                wraps=self.app.electrode_transactions.apply_changes) as apply, \
                patch.object(self.app.electrode_transactions, 'all_off',
                wraps=self.app.electrode_transactions.all_off) as off:
            self.drain()
            apply.assert_called_once_with({190: 0})
            off.assert_called_once()
        self.assertTrue(self.app.hardware_state_uncertain)
        self.assertFalse(self.app._timed_mix_owned)

    def test_session_log_records_requests_sequence_applied_errors_and_pc_times(self):
        self.start()
        self.collect()
        self.app.stop_timed_mixing()
        self.drain()
        output = self.app._single_cycle_output_dir
        with (output/'electrode_events.csv').open(encoding='utf-8', newline='') as handle:
            events = list(csv.DictReader(handle))
        applied = [row for row in events if row['event'] == 'applied']
        requests = [row for row in events if row['event'] == 'transaction_requested']
        self.assertEqual([json.loads(row['changes']) for row in requests], [{'190': 1}, {'190': 0}])
        self.assertEqual(len(applied), 2)
        self.assertTrue(all(row['sequence'] and row['host_perf_counter_ns'] and row['host_utc_ns'] for row in applied))
        manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['electrode_id'], 190)
        self.assertEqual(manifest['dwell_s'], .25)
        self.assertFalse(manifest['physical_off_verified'])
        self.assertEqual(manifest['status'], 'released_buffer_only')

    def test_external_unknown_state_cancels_next_on_and_releases(self):
        self.start()
        self.collect()
        self.app.electrode_event_stream.emit(dict(event='state_unknown', **clock_stamp(), error='lost state'))
        self.app._timed_mix_tick()
        self.assertTrue(self.app._single_cycle_stopping)
        self.drain()
        self.assertEqual(self.commits, [{190: 1}, {190: 0}])

    def test_unknown_event_has_timestamp_for_concurrent_camera_recording(self):
        events = []
        self.app.electrode_event_stream.subscribe(events.append)
        self.fail_on = self.fail_off = self.fail_release = True
        self.start()
        self.drain()
        unknown = [event for event in events if event['event'] == 'state_unknown']
        self.assertTrue(unknown)
        self.assertTrue(all(event.get('host_perf_counter_ns') for event in unknown))


if __name__ == '__main__':
    unittest.main()
