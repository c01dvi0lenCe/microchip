"""Operator shared queue regressions; memory-only, never opens serial ports."""
import csv
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app_controller import STM32MatrixController
from dmf.layout import cell_from_electrode_id


class SharedManualTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.app = STM32MatrixController(self.root, operator_only=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.app.open_loop_output_root = Path(self.tmp.name)
        # Integration assertions control deadlines explicitly, not wall-clock
        # rendering speed (multiple Tk regression processes can be slow).
        self.app.open_loop_dwell_var.set(60)
        self.app.start_cell = cell_from_electrode_id(190)
        self.app.goal_cell = cell_from_electrode_id(192)
        self.app.path = [cell_from_electrode_id(i) for i in (190,191,192)]
        self.app.is_connected = True
        self.app.ser = SimpleNamespace(write=lambda _:None, close=lambda:None, is_open=True, in_waiting=0)
        self.app.electrode_event_stream.emit(dict(event='all_off_confirmed'))
        self.calls = []
        def apply(changes):
            self.calls.append(dict(changes))
            return SimpleNamespace(applied=True, sequence=len(self.calls), error='')
        self.mock = patch.object(self.app.electrode_transactions, 'apply_changes', side_effect=apply)
        self.mock.start()

    def tearDown(self):
        self.app.stop_timed_mixing()
        worker = self.app._timed_mix_worker
        if worker: worker.join(3); self.app._timed_mix_tick()
        self.mock.stop()
        self.app.is_connected=False; self.app.ser=None
        self.app._open_loop_release_required=False
        self.app.on_close(); self.tmp.cleanup()

    def drain(self):
        worker = self.app._timed_mix_worker
        if worker: worker.join(2); self.assertFalse(worker.is_alive())
        self.app._timed_mix_tick()

    def start(self):
        self.assertTrue(self.app.start_open_loop()); self.drain()
        self.assertEqual(self.app._active_electrode_ids(), {190})

    def test_nonconflicting_manual_ack_does_not_advance_and_hold_survives(self):
        self.start(); index=self.app._timed_mix.index
        self.assertTrue(self.app._apply_manual_electrode_changes({350:1}))
        self.drain()
        self.assertEqual(self.app._timed_mix.index,index)
        self.assertEqual(self.app._active_electrode_ids(),{190,350})
        self.app._timed_mix.deadline=0; self.app._timed_mix_tick(); self.drain()
        self.assertEqual(self.app._active_electrode_ids(),{191,350})

    def test_colors_wait_applied_and_duplicate_pending_click_is_refused(self):
        self.start(); release=threading.Event()
        def delayed(changes):
            release.wait(2)
            return SimpleNamespace(applied=True,sequence=20,error='')
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=delayed):
            self.assertTrue(self.app._apply_manual_electrode_changes({350:1}))
            self.assertEqual(self.app.buttons[350]['state'],0)
            self.assertFalse(self.app._apply_manual_electrode_changes({350:1}))
            release.set(); self.drain()
        self.assertEqual(self.app.buttons[350]['state'],1)

    def test_task_electrodes_are_refused_without_pausing_or_prompting(self):
        self.start()
        before=len(self.calls)
        for eid,state in ((190,0),(191,1),(192,1)):
            self.assertFalse(self.app._apply_manual_electrode_changes({eid:state}))
        self.assertFalse(self.app._timed_mix.paused)
        self.assertEqual(self.app._active_electrode_ids(),{190})
        self.assertEqual(len(self.calls),before)

    def test_path_neighbor_conflict_is_refused_without_transaction(self):
        self.start(); before=len(self.calls)
        self.assertFalse(self.app._apply_manual_electrode_changes({171:1}))
        self.assertFalse(self.app._timed_mix.paused)
        self.assertEqual(len(self.calls),before)

    def test_manual_neighbor_click_is_blocked_and_does_not_turn_off_task(self):
        self.start()
        self.app.manual_toggle_electrode(cell_from_electrode_id(191))
        self.assertEqual(self.calls,[{190:1}])
        self.assertEqual(self.app._active_electrode_ids(),{190})

    def test_stop_cancels_queued_manual_while_inflight_drains(self):
        self.start(); release=threading.Event()
        def delayed(changes):
            self.calls.append(dict(changes)); release.wait(2)
            return SimpleNamespace(applied=True,sequence=20,error='')
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=delayed):
            self.assertTrue(self.app._apply_manual_electrode_changes({350:1}))
            self.assertTrue(self.app._apply_manual_electrode_changes({370:1}))
            self.app.stop_timed_mixing(); release.set(); self.drain()
        self.assertEqual(self.app.buttons[350]['state'],1)
        self.assertEqual(self.app.buttons[370]['state'],0)
        self.assertFalse(self.app._timed_mix_owned)

    def test_manual_failure_stops_queue_and_keeps_last_confirmed_color(self):
        self.start()
        with patch.object(self.app.electrode_transactions,'apply_changes',return_value=SimpleNamespace(applied=False,sequence=2,error='timeout')):
            self.assertTrue(self.app._apply_manual_electrode_changes({350:1})); self.drain()
        self.assertEqual(self.app.buttons[350]['state'],0)
        self.assertTrue(self.app.hardware_state_uncertain)
        self.assertFalse(self.app._timed_mix_owned)

    def test_external_hold_can_be_turned_off_without_neighbor_side_effects(self):
        self.start()
        self.app.manual_toggle_electrode(cell_from_electrode_id(350)); self.drain()
        self.app.manual_toggle_electrode(cell_from_electrode_id(350)); self.drain()
        self.assertEqual(self.app._active_electrode_ids(),{190})
        self.app._timed_mix.deadline=0; self.app._timed_mix_tick(); self.drain()
        self.assertEqual(self.app._active_electrode_ids(),{191})

    def test_manual_events_are_separate_from_path_steps(self):
        self.start(); self.app._apply_manual_electrode_changes({350:1}); self.drain()
        folder=self.app._open_loop_output_dir; self.app.stop_timed_mixing()
        with (folder/'manual_commands.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        self.assertIn('applied_confirmed',{r['event'] for r in rows})
        self.assertTrue(any(r['sequence']=='2' for r in rows))
        with (folder/'steps.csv').open(encoding='utf-8-sig',newline='') as f:
            self.assertEqual(len(list(csv.DictReader(f))),2)

    def test_pending_outline_does_not_change_confirmed_fill(self):
        self.start(); release=threading.Event()
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=lambda _: (release.wait(2) or True) and SimpleNamespace(applied=True,sequence=3,error='')):
            self.app._apply_manual_electrode_changes({350:1})
            self.assertIn(350,self.app._open_loop_pending_ids())
            self.assertEqual(self.app.buttons[350]['state'],0)
            release.set(); self.drain()
        self.assertNotIn(350,self.app._open_loop_pending_ids())

    def test_rejected_batch_does_not_partially_send_safe_changes(self):
        self.start(); before=len(self.calls)
        self.assertFalse(self.app._apply_manual_electrode_changes({350:1,191:1}))
        self.assertEqual(len(self.calls),before)
        self.assertEqual(self.app.buttons[350]['state'],0)

    def test_external_original_hold_can_be_removed_permanently(self):
        self.app.update_ui_only(350,1); self.assertTrue(self.app.start_open_loop()); self.drain()
        self.assertEqual(self.app._open_loop_plan.hold_ids,{350})
        self.assertTrue(self.app._apply_manual_electrode_changes({350:0})); self.drain()
        self.app._timed_mix.deadline=0; self.app._timed_mix_tick(); self.drain()
        self.assertEqual(self.app._active_electrode_ids(),{191})
        self.assertEqual(self.app._open_loop_plan.hold_ids,{350})
        self.assertNotIn('350',self.app.timed_mix_status_var.get())

    def test_manual_log_failure_prevents_send(self):
        self.start(); before=len(self.calls)
        def failed(*args,**kwargs): self.app._open_loop_journal.log.error='disk full'
        with patch.object(self.app._open_loop_journal,'manual',side_effect=failed):
            self.assertFalse(self.app._apply_manual_electrode_changes({350:1}))
        self.assertEqual(len(self.calls),before)
        self.assertFalse(self.app._timed_mix_owned)

    def test_toggle_button_uses_same_task_guard(self):
        self.start(); self.assertFalse(self.app.toggle_electrode(190))
        self.assertEqual(self.app.buttons[190]['state'],1)
        self.assertTrue(self.app.toggle_electrode(350)); self.drain()
        self.assertEqual(self.app.buttons[350]['state'],1)

    def test_queued_manual_intents_rechecked_against_prior_ack(self):
        self.start(); release=threading.Event(); entered=threading.Event()
        def delayed(changes):
            self.calls.append(dict(changes)); entered.set(); release.wait(2)
            return SimpleNamespace(applied=True,sequence=20,error='')
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=delayed):
            self.assertTrue(self.app._apply_manual_electrode_changes({350:1}))
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.app._apply_manual_electrode_changes({370:1}))
            release.set(); self.drain()
        self.assertEqual(self.app.buttons[350]['state'],1)
        self.assertEqual(self.app.buttons[370]['state'],0)

    def test_manual_operations_available_while_task_is_paused(self):
        self.start(); self.app.pause_resume_open_loop()
        self.assertTrue(self.app._apply_manual_electrode_changes({350:1})); self.drain()
        self.assertTrue(self.app._timed_mix.paused)
        self.assertEqual(self.app._timed_mix.index,1)

    def test_empty_manual_request_is_noop_without_starving_queue(self):
        self.start(); before=len(self.calls)
        self.assertTrue(self.app._apply_manual_electrode_changes({}))
        self.assertEqual(len(self.calls),before)

    def test_unsolicited_sync_does_not_repaint_shared_session_as_applied(self):
        self.start()
        def read():
            self.app.stop_event.set()
            return b'SYNC:350:1\r\n'
        self.app.ser=SimpleNamespace(in_waiting=1,readline=read,close=lambda:None,is_open=True)
        with patch.object(self.root,'after',side_effect=lambda _delay,fn,*args:fn(*args)), \
                patch('controllers.hardware_runtime.time.sleep'):
            self.app.receive_data()
        self.assertEqual(self.app.buttons[350]['state'],0)
        self.assertFalse(self.app.electrode_event_stream.known)
        self.app._timed_mix_tick()
        self.assertFalse(self.app._timed_mix_owned)

    def test_sync_invalidation_cannot_race_finish_and_reenable_repaint(self):
        self.start()
        emit=self.app.electrode_event_stream.emit
        def invalidate(event):
            emit(event)
            if event['event']=='state_unknown': self.app.stop_timed_mixing()
        def read():
            self.app.stop_event.set(); return b'SYNC:350:1\r\n'
        self.app.ser=SimpleNamespace(in_waiting=1,readline=read,close=lambda:None,is_open=True)
        with patch.object(self.app.electrode_event_stream,'emit',side_effect=invalidate), \
                patch.object(self.root,'after',side_effect=lambda _delay,fn,*args:fn(*args)), \
                patch('controllers.hardware_runtime.time.sleep'):
            self.app.receive_data()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertEqual(self.app.buttons[350]['state'],0)


if __name__=='__main__': unittest.main()
