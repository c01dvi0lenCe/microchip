import inspect
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from main import STM32MatrixController
from dmf.layout import LAYOUT_CELLS, CORNER_RESERVOIRS, RESERVOIR_CELLS, cell_from_electrode_id


class OperatorProfileTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('operator_only',inspect.signature(STM32MatrixController).parameters,
                      'Real-only operator profile is missing')
        self.root=tk.Tk();self.root.withdraw()
        with patch('app_controller.SimulatedCamera') as camera,patch('app_controller.SimulatedDroplet') as drop:
            self.app=STM32MatrixController(self.root,operator_only=True)
            camera.assert_not_called();drop.assert_not_called()
        self.root.update_idletasks()

    def tearDown(self):
        if hasattr(self,'app'):self.app.on_close()

    def test_main_explicitly_selects_operator_profile(self):
        with patch.object(main.tk,'Tk') as root,patch.object(main,'STM32MatrixController') as build:
            main.main();build.assert_called_once_with(root.return_value,operator_only=True)

    def test_no_simulated_objects_callbacks_or_mode_switch(self):
        self.assertIsNone(self.app.sim_camera)
        self.assertIsNone(self.app.sim_droplet)
        self.assertEqual(self.app.sim_droplets,[])
        self.assertIsNone(self.app.manual_after_id)
        self.assertEqual(self.app.mode_var.get(),'实物')
        self.assertEqual(tuple(self.app.mode_combobox['values']),('实物',))
        self.assertFalse(self.app.is_connected)
        self.assertIsNone(self.app.latest_camera_frame_bgr)

    def test_open_loop_controls_are_only_on_manual_page(self):
        manual,auto=self.app.main_notebook.tabs()
        widget=self.app.open_loop_controls_frame
        parents=[]
        while widget is not None:
            parents.append(str(widget));widget=getattr(widget,'master',None)
        self.assertIn(manual,parents);self.assertNotIn(auto,parents)
        self.assertEqual(str(self.app.visual_start_button['state']),'disabled')
        self.assertIn('未就绪',self.app.visual_status_var.get())
        self.assertFalse(hasattr(self.app,'experiment_page'))

    def test_operator_headings_omit_explanatory_parentheses_but_keep_readiness(self):
        self.assertEqual(self.app.open_loop_controls_frame.cget('text'),'定时开环')
        self.assertEqual(self.app.visual_start_button.cget('text'),'启动视觉闭环')
        self.assertEqual(str(self.app.visual_start_button['state']),'disabled')
        self.assertIn('未就绪',self.app.visual_status_var.get())

    def test_manual_task_picking_never_sends_or_switches_electrodes(self):
        self.app.open_loop_input_var.set('任务选点')
        for role,eid in [('起点',190),('终点',192)]:
            self.app.open_loop_pick_var.set(role)
            with patch.object(self.app,'_canvas_to_cell',return_value=cell_from_electrode_id(eid)), \
                    patch.object(self.app,'manual_toggle_electrode') as toggle:
                self.app.on_matrix_click(SimpleNamespace(widget=self.app.manual_canvas,x=0,y=0,state=0),manual=True)
                toggle.assert_not_called()
        self.assertEqual(self.app.start_cell,cell_from_electrode_id(190))
        self.assertEqual(self.app.goal_cell,cell_from_electrode_id(192))
        self.assertEqual(self.app._active_electrode_ids(),set())
        plan=self.app.precheck_open_loop()
        self.assertEqual(plan.routes['移动'],(190,191,192))

    def test_visual_page_click_does_not_change_open_loop_group(self):
        self.app.open_loop_kind_var.set('多组四宫格');self.app.on_open_loop_kind_changed()
        self.app.open_loop_add_group();self.app.open_loop_input_var.set('任务选点')
        with patch.object(self.app,'_canvas_to_cell',return_value=cell_from_electrode_id(190)):
            self.app.on_matrix_click(SimpleNamespace(widget=self.app.path_canvas,x=0,y=0,state=0),manual=False)
        self.assertIsNone(self.app.open_loop_groups[0]['start'])

    def test_operator_rejects_simulation_and_legacy_auto_entry(self):
        self.app.mode_var.set('仿真');self.app.on_mode_changed()
        self.assertEqual(self.app.mode_var.get(),'实物')
        self.assertFalse(self.app.is_simulation_mode())
        with patch.object(self.app,'_auto_loop') as loop:
            self.app.start_auto_control();loop.assert_not_called()
        self.assertFalse(self.app.auto_running)

    def test_shared_layout_geometry_not_redesigned(self):
        legacy_root=tk.Tk();legacy_root.withdraw();legacy=STM32MatrixController(legacy_root)
        try:
            self.assertEqual(set(self.app.buttons),set(legacy.buttons))
            self.assertEqual(len(self.app.buttons),420)
            for a in (self.app,legacy):
                a.matrix_canvas=a.manual_canvas
            with patch.object(self.app.manual_canvas,'winfo_width',return_value=650), \
                    patch.object(self.app.manual_canvas,'winfo_height',return_value=600), \
                    patch.object(legacy.manual_canvas,'winfo_width',return_value=650), \
                    patch.object(legacy.manual_canvas,'winfo_height',return_value=600):
                for cell in LAYOUT_CELLS:self.assertEqual(self.app._cell_rect(cell),legacy._cell_rect(cell))
                for cell in CORNER_RESERVOIRS:
                    self.assertEqual(self.app._corner_reservoir_polygon_points(cell),legacy._corner_reservoir_polygon_points(cell))
                for cell in RESERVOIR_CELLS:
                    self.assertEqual(self.app._reservoir_connector_rect(cell),legacy._reservoir_connector_rect(cell))
        finally:legacy.on_close()

    def test_incomplete_group_names_and_focuses_missing_fields(self):
        self.app.open_loop_kind_var.set('多组四宫格');self.app.on_open_loop_kind_changed()
        gid=self.app.open_loop_add_group()
        self.app.open_loop_groups[0].update(ring=[190,191,211,210],target=211)
        self.assertIsNone(self.app.precheck_open_loop())
        status=self.app.open_loop_status_var.get()
        self.assertIn(gid,status);self.assertIn('起点',status);self.assertNotIn('None',status)
        self.assertEqual(self.app._open_loop_selected,gid)
        self.assertEqual(self.app._active_electrode_ids(),set())

    def test_missing_group_focus_moves_from_other_selected_group(self):
        self.app.open_loop_kind_var.set('多组四宫格');self.app.on_open_loop_kind_changed()
        first=self.app.open_loop_add_group()
        self.app.open_loop_groups[0].update(ring=[190,191,211,210],target=211)
        self.app.open_loop_add_group()
        self.assertIsNone(self.app.precheck_open_loop())
        self.assertEqual(self.app.open_loop_tree.selection(),(first,))
        self.assertIn('G1未设置起点',self.app.open_loop_status_var.get())
        self.assertIn('G2未设置',self.app.open_loop_status_var.get())

    def test_operator_rejects_legacy_preset_before_mutating_task(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.json'
            legacy_root=tk.Tk();legacy_root.withdraw();legacy=STM32MatrixController(legacy_root)
            try:legacy.save_settings_preset(path)
            finally:legacy.on_close()
            self.assertFalse(self.app.load_settings_preset(path))
        self.assertEqual(self.app.mode_var.get(),'实物')
        self.assertIsNone(self.app.start_cell)

    def test_operator_cannot_enter_legacy_auto_loop_even_if_flag_set(self):
        self.app.auto_running=True
        with patch.object(self.app,'_move_auto_step') as advance:
            self.app._auto_loop();advance.assert_not_called()
        self.assertFalse(self.app.auto_running)

    def test_planner_callback_cannot_start_unvalidated_visual_control(self):
        with patch.object(self.app,'_prepare_operation_start') as prepare, \
                patch.object(self.app,'_begin_operation_metrics'),patch.object(self.app,'_auto_loop'):
            self.app._start_auto_with_planned([(9,9),(9,10)])
            prepare.assert_not_called()
        self.assertFalse(self.app.auto_running)

    def test_legacy_default_square_cannot_bypass_explicit_operator_tasks(self):
        self.app.is_connected=True
        try:
            with patch.object(self.app,'_timed_mix_tick') as tick:
                self.assertFalse(self.app.start_timed_mixing());tick.assert_not_called()
        finally:self.app.is_connected=False

    def test_operator_ignores_legacy_operation_ui_callback(self):
        self.app.operation_var.set(self.app.OP_MERGE)
        self.assertFalse(self.app.on_operation_changed())
        self.assertEqual(self.app.operation_var.get(),self.app.OP_MOVE)

    def test_old_visual_electrode_switch_cannot_bypass_profile(self):
        with patch.object(self.app,'_submit_auto_electrode_changes',return_value=True) as submit:
            self.assertFalse(self.app._set_auto_active_cells({(9,10)}))
            submit.assert_not_called()
        self.assertEqual(self.app._active_electrode_ids(),set())

    def test_manual_group_editor_retains_usable_canvas(self):
        self.app.open_loop_kind_var.set('多组四宫格');self.app.on_open_loop_kind_changed()
        self.root.deiconify();self.root.update();self.root.update_idletasks()
        self.assertGreaterEqual(self.app.manual_canvas.winfo_height(),300)

    def test_selecting_pick_role_automatically_enters_non_actuating_pick_mode(self):
        self.app.open_loop_input_var.set('电极开关')
        self.app.open_loop_pick_var.set('终点')
        self.app.operator_pick_combo.event_generate('<<ComboboxSelected>>')
        self.assertEqual(self.app.open_loop_input_var.get(),'任务选点')

    def test_group_role_picker_cannot_leave_manual_switch_intent_active(self):
        self.app.open_loop_kind_var.set('多组四宫格');self.app.on_open_loop_kind_changed()
        self.assertTrue(hasattr(self.app,'open_loop_group_pick_combo'))
        self.app.open_loop_input_var.set('电极开关');self.app.open_loop_pick_var.set('四点')
        self.app.open_loop_group_pick_combo.event_generate('<<ComboboxSelected>>')
        self.assertEqual(self.app.open_loop_input_var.get(),'任务选点')


class SimulatorProfileTests(unittest.TestCase):
    def test_independent_simulator_is_serial_inert_and_keeps_420_layout(self):
        root=tk.Tk();root.withdraw();app=STM32MatrixController(root,simulation_only=True)
        try:
            app.mode_var.set('实物');app.on_mode_changed()
            self.assertEqual(app.mode_var.get(),'仿真')
            self.assertTrue(app.is_simulation_mode())
            self.assertEqual(len(app.buttons),420)
            with patch.object(app,'_timed_mix_send_line') as send:
                app.toggle_connection();send.assert_not_called()
            self.assertFalse(app.is_connected)
            self.assertIsNotNone(app.sim_camera)
        finally:app.on_close()


if __name__=='__main__':unittest.main()
