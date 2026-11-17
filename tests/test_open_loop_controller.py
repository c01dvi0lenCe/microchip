import csv
import gc
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

    def test_multigroup_preflight_partitions_full_rings_without_output(self):
        self.groups()
        active={190,211,210,252,272,350}
        for eid in active:self.app.update_ui_only(eid,1)
        plan=self.app.precheck_open_loop()
        self.assertIsNotNone(plan,self.app.open_loop_status_var.get())
        self.assertEqual(plan.hold_ids,{350})
        self.assertEqual(plan.startup_clear_ids,active-{350})
        self.assertEqual(self.app._active_electrode_ids(),active)
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

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


class RouteStartupTests(unittest.TestCase):
    """Use the actual BEGIN/SET/COMMIT client; only the transport is in memory."""
    def setUp(self):
        gc.collect()  # finalize old Tk objects on their owning (test) thread
        for guard in (patch('serial.tools.list_ports.comports',return_value=[]),
                      patch('serial.Serial',side_effect=AssertionError('No hardware'))):
            guard.start(); self.addCleanup(guard.stop)
        self.root=tk.Tk(); self.root.withdraw()
        self.app=STM32MatrixController(self.root,operator_only=True)
        self.temp=tempfile.TemporaryDirectory()
        self.app.open_loop_output_root=Path(self.temp.name)
        app=self.app
        app.path=[cell_from_electrode_id(i) for i in (190,191,192)]
        app.start_cell,app.goal_cell=app.path[0],app.path[-1]
        app.open_loop_dwell_var.set(60)
        self.lines=[]
        self.commit=threading.Event()
        self.sequence=None
        def write(payload):
            line=payload.decode().strip(); self.lines.append(line)
            client=app.electrode_transactions
            if line.startswith('BEGIN:'):
                self.sequence=int(line.split(':')[1])
                client.feed_line(f'ACK:{self.sequence}:BEGIN')
            elif line.startswith('SET:'):
                client.feed_line(f'ACK:{self.sequence}:SET:{line.split(":")[1]}')
            elif line.startswith('COMMIT:'):
                self.commit.set()  # tests supply/withhold the APPLIED notification
            elif line=='ALL_OFF':
                client.feed_line('ACK:ALL_OFF')
            return len(payload)
        app.ser=SimpleNamespace(write=write,close=lambda:None,is_open=True,in_waiting=0)
        app.is_connected=True
        app.electrode_transactions.ack_timeout_s=2
        app.electrode_transactions.max_retries=0
        app.electrode_transactions.reset_sequence(21)
        app.electrode_event_stream.emit(dict(event='all_off_confirmed'))

    def tearDown(self):
        app=self.app
        if app._timed_mix_owned:
            app.stop_timed_mixing()
            if app._timed_mix_worker:
                self.commit.wait(2); self.ack()
        app.is_connected=False; app.ser=None; app._open_loop_release_required=False
        for token in self.root.tk.call('after','info'):self.root.after_cancel(token)
        app.on_close(); app.recv_thread.join(2); self.temp.cleanup()
        del self.app,self.root,app
        gc.collect()

    def acknowledge_initial(self,ids):
        self.app.electrode_event_stream.emit(dict(event='applied',changes={i:1 for i in ids}))

    def ack(self, *, error=False):
        self.commit.clear()
        self.app.electrode_transactions.feed_line('ERR:test' if error else f'ACK:{self.sequence}:APPLIED')
        self.app._timed_mix_worker.join(3)
        self.assertFalse(self.app._timed_mix_worker.is_alive())
        self.app._timed_mix_tick()

    def begin_cleanup(self,initial=(191,350)):
        self.acknowledge_initial(initial)
        self.assertTrue(self.app.start_open_loop(),self.app.open_loop_status_var.get())
        self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines,['BEGIN:21']+[f'SET:{i}:0' for i in sorted(set(initial)&{190,191,192})]+['COMMIT:21'])
        self.assertIsNone(self.app._timed_mix.deadline)
        self.assertEqual(self.app._timed_mix.index,0)

    def test_cleanup_is_separate_acknowledged_delta_then_original_first_step(self):
        app=self.app
        self.acknowledge_initial([350])
        app.update_ui_only(171,1)  # stale display conflict, not a confirmed hold
        preview=app.precheck_open_loop()
        self.assertIsNotNone(preview,app.open_loop_status_var.get())
        self.assertEqual(preview.hold_ids,{350})
        self.assertEqual(self.lines,[])
        self.begin_cleanup((190,191,192,350))  # start must re-read acknowledged state
        app.electrode_transactions.feed_line('ACK:999:APPLIED')
        app._timed_mix_tick()
        self.assertFalse(app.step_open_loop())
        self.assertEqual(self.lines[-1],'COMMIT:21')
        self.ack()
        self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines[-3:],['BEGIN:22','SET:190:1','COMMIT:22'])
        self.assertEqual(app.electrode_event_stream.active,{350})
        self.assertEqual(app._timed_mix.index,0)
        self.assertIsNone(app._timed_mix.deadline)
        self.ack()
        self.assertEqual(app._timed_mix.index,1)
        self.assertIsNotNone(app._timed_mix.deadline)
        self.assertEqual(app._active_electrode_ids(),{190,350})
        app.stop_timed_mixing()
        with (app._open_loop_output_dir/'steps.csv').open(encoding='utf-8-sig',newline='') as f:
            self.assertEqual([(r['event'],r['phase']) for r in csv.DictReader(f)],
                             [('request','0'),('applied_confirmed','0')])
        self.assertNotIn('ALL_OFF',self.lines)

    def test_stop_during_cleanup_never_activates_first_step(self):
        self.begin_cleanup()
        self.app.stop_timed_mixing()
        self.ack()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertEqual(self.app.electrode_event_stream.active,{350})
        self.assertEqual(self.lines[-1],'COMMIT:21')
        self.assertEqual(self.app._timed_mix.index,0)

    def test_close_drains_cleanup_before_release_without_start(self):
        self.begin_cleanup()
        self.app.on_close()
        self.assertTrue(self.app._timed_mix_owned)
        self.assertNotIn('ALL_OFF',self.lines)
        self.ack()
        self.assertEqual(self.lines,['BEGIN:21','SET:191:0','COMMIT:21','ALL_OFF'])
        self.assertFalse(self.app._timed_mix_owned)

    def test_failed_cleanup_leaves_unknown_and_no_first_step(self):
        self.begin_cleanup()
        self.ack(error=True)
        self.assertFalse(self.app._timed_mix_owned)
        self.assertTrue(self.app.hardware_state_uncertain)
        self.assertFalse(self.app.electrode_event_stream.known)
        self.assertEqual(self.lines[-1],'COMMIT:21')
        self.assertEqual(self.app._timed_mix.index,0)

    def test_unknown_during_cleanup_blocks_first_step_even_after_matching_ack(self):
        self.begin_cleanup()
        self.app.electrode_event_stream.emit(dict(event='state_unknown'))
        self.ack()
        self.assertFalse(self.app._timed_mix_owned)
        self.assertEqual(self.lines[-1],'COMMIT:21')

    def test_pause_during_cleanup_defers_first_step_until_resume(self):
        self.begin_cleanup()
        self.app.pause_resume_open_loop()
        self.ack()
        self.assertTrue(self.app._timed_mix_owned)
        self.assertEqual(self.lines[-1],'COMMIT:21')
        self.assertIsNone(self.app._timed_mix.deadline)
        self.app.pause_resume_open_loop(); self.app._timed_mix_tick()
        self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines[-3:],['BEGIN:22','SET:190:1','COMMIT:22'])

    def test_real_conflict_outside_route_is_not_silently_cleared(self):
        self.acknowledge_initial((191,171))
        self.assertFalse(self.app.start_open_loop())
        self.assertIn('171',self.app.open_loop_status_var.get())
        self.assertEqual(self.app.electrode_event_stream.active,{191,171})
        self.assertEqual(self.lines,[])

    def test_multigroup_routes_clean_once_then_one_joint_source_activation(self):
        app=self.app
        app.open_loop_kind_var.set('多组四宫格'); app.on_open_loop_kind_changed()
        for ring,target in (([190,191,211,210],211),([251,252,272,271],251)):
            app.open_loop_add_group()
            app.open_loop_groups[-1].update(start=ring[0],ring=ring,target=target)
        self.acknowledge_initial([190,211,252,271,350])
        self.assertTrue(app.start_open_loop(),app.open_loop_status_var.get())
        self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines,['BEGIN:21','SET:190:0','SET:211:0','SET:252:0','SET:271:0','COMMIT:21'])
        self.ack()
        self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines[-4:],['BEGIN:22','SET:190:1','SET:251:1','COMMIT:22'])
        self.ack()
        self.assertEqual(app.electrode_event_stream.active,{190,251,350})

    def test_manual_intent_during_cleanup_is_serialized_and_does_not_advance(self):
        self.begin_cleanup()
        app=self.app
        self.assertFalse(app._apply_manual_electrode_changes({191:1}))
        self.assertTrue(app._apply_manual_electrode_changes({350:0}))
        self.assertEqual(self.lines[-1],'COMMIT:21')
        self.ack(); self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines[-3:],['BEGIN:22','SET:190:1','COMMIT:22'])
        self.ack(); self.assertTrue(self.commit.wait(2))
        self.assertEqual(self.lines[-3:],['BEGIN:23','SET:350:0','COMMIT:23'])
        self.ack()
        self.assertEqual(app._timed_mix.index,1)
        self.assertEqual(app.electrode_event_stream.active,{190})

    def test_new_inflight_during_preflight_rejects_start(self):
        precheck=self.app.precheck_open_loop
        def changed():
            plan=precheck()
            self.app.electrode_event_stream.emit(dict(event='transaction_requested',request_id='other'))
            return plan
        with patch.object(self.app,'precheck_open_loop',side_effect=changed):
            self.assertFalse(self.app.start_open_loop())
        self.assertEqual(self.lines,[])

if __name__=='__main__':unittest.main()
