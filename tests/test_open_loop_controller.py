import json
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import STM32MatrixController
from dmf.layout import cell_from_electrode_id


class OpenLoopControllerTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.app=STM32MatrixController(self.root)
        self.temp=tempfile.TemporaryDirectory()
        self.app.open_loop_output_root=Path(self.temp.name)
        self.root.update_idletasks()

    def tearDown(self):
        self.app.stop_timed_mixing()
        self.app.is_connected=False;self.app.ser=None;self.app.camera_running=False
        self.app.on_close();self.temp.cleanup()

    def feature(self):
        self.assertTrue(hasattr(self.app,'start_open_loop'),'Multi-group/open-loop control is missing')

    def group(self,ring=(190,191,211,210),target=211):
        gid=self.app.open_loop_add_group()
        for role,ids in [('起点',[ring[0]]),('四点',ring),('终点',[target])]:
            self.app.open_loop_pick_var.set(role)
            for eid in ids:self.app.open_loop_handle_cell(cell_from_electrode_id(eid))
        return gid

    def groups(self):
        self.feature();self.app.open_loop_kind_var.set('多组四宫格');self.app.on_open_loop_kind_changed()
        self.group();self.group((251,252,272,271),251)

    def test_canvas_adds_multiple_independent_single_drop_groups(self):
        self.groups()
        self.assertEqual(len(self.app.open_loop_groups),2)
        self.assertEqual(self.app.open_loop_groups[0]['ring'],[190,191,211,210])
        self.assertEqual(self.app.open_loop_groups[0]['target'],211)
        self.assertEqual(self.app.open_loop_groups[1]['start'],251)

    def test_joint_source_activation_preserves_extra_holds(self):
        self.groups();self.app.update_ui_only(350,1)
        self.assertTrue(self.app.start_open_loop())
        self.assertEqual(self.app._active_electrode_ids(),{190,251,350})
        self.assertEqual(self.app._open_loop_plan.hold_ids,{350})

    def test_conflict_refuses_all_groups_without_partial_commands(self):
        self.groups();self.app.open_loop_groups[1].update(start=190,ring=[190,191,211,210],target=190)
        self.assertFalse(self.app.start_open_loop())
        self.assertFalse(self.app._timed_mix_owned)
        self.assertEqual(self.app._active_electrode_ids(),set())

    def test_forbidden_region_and_hold_refuse_start(self):
        self.groups();self.app.update_ui_only(90,1)
        self.assertFalse(self.app.start_open_loop())
        self.assertEqual(self.app._active_electrode_ids(),{90})

    def test_existing_planned_single_move_uses_no_visual_gate(self):
        self.feature();self.app.start_cell=(9,9);self.app.goal_cell=(9,11)
        self.app.path=[(9,9),(9,10),(9,11)]
        with patch.object(self.app.sim_camera,'render') as render,patch.object(self.app.sim_droplet,'update_towards') as move:
            self.assertTrue(self.app.start_open_loop())
            render.assert_not_called();move.assert_not_called()
        self.assertEqual(self.app._open_loop_plan.routes['移动'],(190,191,192))

    def test_camera_preview_remains_independent(self):
        self.groups();self.app.camera_running=True
        with patch.object(self.app,'stop_camera') as stop,patch.object(self.app.sim_camera,'render') as render:
            self.app.start_open_loop();self.app.stop_timed_mixing()
            stop.assert_not_called();render.assert_not_called()
        self.assertTrue(self.app.camera_running)

    def test_edit_while_running_cannot_mutate_frozen_plan(self):
        self.groups();self.app.start_open_loop()
        before=self.app._open_loop_plan.routes['G1']
        self.app.open_loop_pick_var.set('起点')
        self.app.open_loop_handle_cell(cell_from_electrode_id(300))
        self.assertEqual(self.app.open_loop_groups[1]['start'],251)
        self.assertEqual(self.app._open_loop_plan.routes['G1'],before)

    def test_manual_step_and_pause_do_not_duplicate_pending_request(self):
        self.groups();self.app.open_loop_advance_var.set('人工单步')
        self.app.start_open_loop()
        self.assertTrue(self.app._timed_mix.manual)
        self.assertEqual(self.app._timed_mix.index,1)
        self.app.pause_resume_open_loop()
        self.assertTrue(self.app._timed_mix.paused)
        self.app.step_open_loop()
        self.assertTrue(self.app._timed_mix_step_requested)
        self.assertEqual(self.app._timed_mix.index,1)

    def test_real_joint_transaction_waits_ack_then_updates_whole_frame(self):
        self.groups();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.electrode_event_stream.emit(dict(event='all_off_confirmed'))
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        entered=threading.Event();release=threading.Event();calls=[]
        def apply(changes):
            calls.append(changes);entered.set();release.wait(2)
            return SimpleNamespace(applied=True,sequence=11,error='')
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=apply):
            self.assertTrue(self.app.start_open_loop());self.assertTrue(entered.wait(1))
            self.assertEqual(self.app._active_electrode_ids(),set())
            self.assertEqual(self.app._timed_mix.index,0)
            self.app.stop_timed_mixing()
            release.set();self.app._timed_mix_worker.join(1);self.app._timed_mix_tick()
        self.assertEqual(calls,[{190:1,251:1}])
        self.assertEqual(self.app._active_electrode_ids(),{190,251})
        self.assertFalse(self.app._timed_mix_owned)

    def test_session_log_does_not_claim_physical_arrival(self):
        self.groups();self.app.start_open_loop();self.app.stop_timed_mixing()
        folder=self.app._open_loop_output_dir
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['control_mode'],'timed_open_loop')
        self.assertFalse(manifest['vision_used_for_advancement'])
        self.assertFalse(manifest['physical_transport_verified'])
        self.assertTrue((folder/'steps.csv').exists())
        self.assertTrue((folder/'electrode_events.csv').exists())

    def test_journal_request_failure_prevents_any_electrode_submission(self):
        self.groups()
        from controllers.open_loop_journal import OpenLoopJournal
        def failed(journal,*args,**kwargs):journal.log.error='injected full queue'
        with patch.object(OpenLoopJournal,'step',failed),patch.object(self.app,'_timed_mix_submit') as submit:
            self.app.start_open_loop()
            submit.assert_not_called()
        self.assertFalse(self.app._timed_mix_owned)

    def test_finish_manifest_error_does_not_leave_owned_or_raise(self):
        self.groups();self.app.start_open_loop()
        with patch.object(self.app._open_loop_journal,'_write_manifest',side_effect=OSError('disk full')):
            self.app.stop_timed_mixing()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertIsNone(self.app._open_loop_journal)
        self.assertIn('日志',self.app.open_loop_status_var.get())

    def test_closed_cycle_and_terminal_are_visible_in_preview(self):
        self.groups();self.app.precheck_open_loop()
        with patch.object(self.app,'_draw_path_arrow') as arrows,patch.object(self.app,'_draw_cell_text') as labels:
            self.app._draw_open_loop_overlay()
        self.assertIn([cell_from_electrode_id(i) for i in (190,191,211,210,190)],
                      [call.args[0] for call in arrows.call_args_list])
        self.assertTrue(any(call.args[:2]==(cell_from_electrode_id(211),'G1终') for call in labels.call_args_list))

    def test_multi_editor_preserves_usable_canvas_height(self):
        self.root.deiconify();self.app.main_notebook.select(1);self.groups();self.root.update()
        self.assertGreaterEqual(self.app.path_canvas.winfo_height(),330)

    def test_close_after_normal_stop_still_releases_hardware(self):
        self.groups();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.electrode_event_stream.emit(dict(event='all_off_confirmed'))
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        with patch.object(self.app.electrode_transactions,'apply_changes',return_value=SimpleNamespace(applied=True,error='')):
            self.app.start_open_loop();self.app._timed_mix_worker.join(1);self.app._timed_mix_tick()
        self.app.stop_timed_mixing()
        with patch.object(self.app.electrode_transactions,'all_off',return_value=True) as off,patch.object(self.root,'destroy'):
            self.app.on_close();off.assert_called_once()

    def test_mode_switch_releases_in_real_mode_before_entering_simulation(self):
        self.app.mode_var.set('仿真');self.app.is_connected=True
        self.app._open_loop_release_required=True
        self.app.ser=SimpleNamespace(close=lambda:None,is_open=True,in_waiting=0)
        modes=[]
        def off():modes.append(self.app.mode_var.get());return True
        with patch.object(self.app.electrode_transactions,'all_off',side_effect=off):
            self.app.on_mode_changed()
        self.assertEqual(modes,['实物'])
        self.assertEqual(self.app.mode_var.get(),'仿真')

    def test_compact_editor_survives_real_simulation_mode_roundtrip(self):
        self.groups()
        self.app.mode_var.set('实物');self.app.on_mode_changed()
        self.app.mode_var.set('仿真');self.app.on_mode_changed()
        self.assertEqual(self.app.open_loop_kind_var.get(),'多组四宫格')
        self.assertFalse(self.app.metrics_row.winfo_manager())

    def test_real_unknown_full_state_refuses_delta_sequence(self):
        self.groups();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.electrode_event_stream.emit(dict(event='state_unknown'))
        with patch.object(self.app,'_timed_mix_submit') as submit:
            self.assertFalse(self.app.start_open_loop());submit.assert_not_called()

    def test_external_unknown_state_stops_future_requests_after_pending_ack(self):
        self.groups();self.app.mode_var.set('实物');self.app.is_connected=True
        self.app.electrode_event_stream.emit(dict(event='all_off_confirmed'))
        self.app.ser=SimpleNamespace(write=lambda _:None,close=lambda:None,is_open=True,in_waiting=0)
        release=threading.Event()
        def apply(_):
            release.wait(1);return SimpleNamespace(applied=True,error='')
        with patch.object(self.app.electrode_transactions,'apply_changes',side_effect=apply):
            self.assertTrue(self.app.start_open_loop())
            self.app.electrode_event_stream.emit(dict(event='state_unknown'))
            release.set();self.app._timed_mix_worker.join(1)
            self.app._timed_mix_tick()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertTrue(self.app.hardware_state_uncertain)
        self.assertEqual(self.app._timed_mix.index,1)


if __name__=='__main__':unittest.main()
