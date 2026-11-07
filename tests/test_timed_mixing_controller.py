import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import STM32MatrixController


class TimedMixingControllerTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw()
        self.app=STM32MatrixController(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        if hasattr(self.app,'stop_timed_mixing'):self.app.stop_timed_mixing()
        self.app.is_connected=False;self.app.ser=None
        self.app.on_close()

    def feature(self):
        self.assertTrue(hasattr(self.app,'start_timed_mixing'),'Missing timed-mixing UI/controller')

    def test_red_reminders_do_not_become_routing_faults(self):
        self.feature()
        self.assertEqual(len(self.app.hardware_reminder_ids),16)
        self.assertEqual(self.app.faulty_electrodes,set())
        self.assertEqual(self.app.obstacle_cells,set())

    def test_marked_electrode_remains_manually_switchable(self):
        self.feature()
        self.app.toggle_electrode(90)
        self.assertEqual(self.app.buttons[90]['state'],1)
        self.app.toggle_electrode(90)
        self.assertEqual(self.app.buttons[90]['state'],0)

    def test_hover_distinguishes_fault_polarity_and_neighbor_only(self):
        from dmf.layout import cell_from_electrode_id
        for eid,word in ((90,'持续导通'),(399,'无法导通'),(70,'邻接提醒')):
            self.app._update_cell_status(cell_from_electrode_id(eid))
            self.assertIn(word,self.app.cell_status_labels[0].cget('text'))
        self.app._update_cell_status(cell_from_electrode_id(380))
        self.assertNotIn('故障',self.app.cell_status_labels[0].cget('text'))

    def test_user_facing_four_cell_control_is_movement_not_merge(self):
        frame=self.app.manual_matrix_card.master.winfo_children()[0]
        self.assertIn('移动',frame.cget('text'))
        self.assertNotIn('混合',frame.cget('text'))

    def test_red_overlay_survives_active_state_on_both_canvases(self):
        self.feature();self.app.update_ui_only(90,1)
        for canvas in (self.app.manual_canvas,self.app.path_canvas):
            self.app.matrix_canvas=canvas
            found=[];old=self.app._draw_cell
            self.app._draw_cell=lambda cell,*a,**kw:(found.append((cell,kw)),old(cell,*a,**kw))[1]
            try:self.app._draw_matrix_canvas_one()
            finally:self.app._draw_cell=old
            marked=[kw for cell,kw in found if cell==(4,9) and kw.get('outline')=='#B52E32']
            self.assertTrue(marked)

    def test_simulation_preview_start_stop_keeps_last_electrode(self):
        self.feature();self.assertTrue(self.app.start_timed_mixing())
        self.assertTrue(self.app._timed_mix_owned)
        self.assertEqual(self.app.buttons[190]['state'],1)
        self.app.stop_timed_mixing()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertEqual(self.app.buttons[190]['state'],1)

    def test_busy_or_unconnected_start_rejected(self):
        self.feature();self.app.auto_running=True
        self.assertFalse(self.app.start_timed_mixing())
        self.app.auto_running=False;self.app.mode_var.set('实物')
        self.assertFalse(self.app.start_timed_mixing())

    def test_mode_switch_denied_while_owned(self):
        self.feature();self.app.start_timed_mixing()
        self.app.mode_var.set('实物');self.app.on_mode_changed()
        self.assertEqual(self.app.mode_var.get(),'仿真')

    def test_ack_failure_does_not_update_display(self):
        self.feature();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        with patch.object(self.app.electrode_transactions,'apply_changes',return_value=SimpleNamespace(applied=False,sequence=7,error='timeout')):
            self.assertTrue(self.app.start_timed_mixing())
            self.app._timed_mix_worker.join(1)
            self.app._timed_mix_tick()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertTrue(self.app.hardware_state_uncertain)
        self.assertEqual(self.app.buttons[190]['state'],0)

    def test_pending_stop_reconciles_ack_without_next_step(self):
        self.feature();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        entered=threading.Event();release=threading.Event()
        def apply(changes):
            entered.set();release.wait(2)
            return SimpleNamespace(applied=True,sequence=8,error='')
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=apply) as submit:
            self.app.start_timed_mixing();self.assertTrue(entered.wait(1))
            self.app.stop_timed_mixing()
            self.assertTrue(self.app._timed_mix_owned)
            self.assertTrue(self.app._hardware_manual_control_blocked())
            release.set();self.app._timed_mix_worker.join(1);self.app._timed_mix_tick()
            self.assertEqual(submit.call_count,1)
        self.assertFalse(self.app._timed_mix_owned)
        self.assertEqual(self.app.buttons[190]['state'],1)

    def test_pending_other_transaction_rejects_start(self):
        self.feature()
        self.app.electrode_event_stream.pending.add('other')
        self.assertFalse(self.app.start_timed_mixing())
        self.app.electrode_event_stream.pending.clear()

    def test_all_off_waits_until_pending_ack_then_clears(self):
        self.feature();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        release=threading.Event();events=[]
        def apply(changes):
            release.wait(2);events.append('APPLIED')
            return SimpleNamespace(applied=True,sequence=1,error='')
        def off():events.append('ALL_OFF');return True
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=apply), patch.object(self.app.electrode_transactions,'all_off',side_effect=off):
            self.app.start_timed_mixing();self.app.reset_all()
            self.assertEqual(events,[])
            release.set();self.app._timed_mix_worker.join(1);self.app._timed_mix_tick()
        self.assertEqual(events,['APPLIED','ALL_OFF'])
        self.assertEqual(self.app._active_electrode_ids(),set())

    def test_disconnection_ends_timed_owner_without_later_request(self):
        self.feature();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        with patch.object(self.app.electrode_transactions,'apply_changes',return_value=SimpleNamespace(applied=True,sequence=1,error='')):
            self.app.start_timed_mixing();self.app._timed_mix_worker.join(1);self.app._timed_mix_tick()
            self.app.is_connected=False;self.app._timed_mix_tick()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertTrue(self.app.hardware_state_uncertain)

    def test_legacy_switch_cannot_take_timed_ownership(self):
        self.feature();self.app.start_timed_mixing()
        self.assertFalse(self.app._set_auto_active_cells({(0,0)}))
        self.assertEqual(self.app._active_electrode_ids(),{190})

    def test_simulation_reset_cancels_next_timed_activation(self):
        self.feature();self.app.start_timed_mixing();self.app.reset_simulation()
        self.assertFalse(self.app._timed_mix_owned)
        self.app._timed_mix_tick()
        self.assertEqual(self.app._active_electrode_ids(),set())

    def test_already_active_real_start_still_obtains_fresh_ack(self):
        self.feature();self.app.update_ui_only(190,1)
        self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        with patch.object(self.app.electrode_transactions,'apply_changes',return_value=SimpleNamespace(applied=True,sequence=1,error='')) as submit:
            self.app.start_timed_mixing()
            if self.app._timed_mix_worker:self.app._timed_mix_worker.join(1)
            self.app._timed_mix_tick()
            submit.assert_called_once_with({190:1})

    def test_setup_marker_does_not_hide_last_red_reminder_outline(self):
        self.feature();self.app.start_cell=(4,9);self.app.matrix_canvas=self.app.path_canvas
        found=[];old=self.app._draw_cell
        self.app._draw_cell=lambda cell,*a,**kw:(found.append((cell,kw)),old(cell,*a,**kw))[1]
        try:self.app._draw_matrix_canvas_one()
        finally:self.app._draw_cell=old
        self.assertEqual([kw for cell,kw in found if cell==(4,9)][-1]['outline'],'#B52E32')


if __name__=='__main__':unittest.main()
