import tkinter as tk
import csv
import tempfile
import time
import unittest
from pathlib import Path

from dmf_simulation import StepEvent, electrode_id
from main import STM32MatrixController


class MainControllerLayoutTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - depends on local display.
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.app = STM32MatrixController(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        if getattr(self, "app", None) is not None:
            try:
                self.app.on_close()
            except tk.TclError:
                pass

    def test_main_notebook_defaults_to_manual_electrode_page(self):
        tabs = [self.app.main_notebook.tab(tab_id, "text") for tab_id in self.app.main_notebook.tabs()]
        self.assertEqual(tabs[:2], ["手动电极", "自动化路径规划"])
        self.assertEqual(self.app.main_notebook.tab(self.app.main_notebook.select(), "text"), "手动电极")

    def test_obstacle_tool_is_available_only_for_automatic_planning(self):
        self.assertIn(self.app.TOOL_OBSTACLE, self.app._tool_options_for_operation())
        self.assertNotIn(self.app.TOOL_MANUAL, self.app._tool_options_for_operation())

    def test_multi_planner_can_use_initial_core_droplets_without_reservoirs(self):
        self.app.operation_var.set(self.app.OP_MULTI)
        self.app._update_tool_options()
        self.assertIn(self.app.TOOL_MULTI_INITIAL, self.app._tool_options_for_operation())
        self.app.loaded_reservoirs.clear()
        self.app.initial_droplet_cells = {(4, 4)}
        self.app.target_shape_points = [(4, 6)]
        self.app._rebuild_target_shape_cells()

        assignments = self.app.plan_path()

        self.assertTrue(assignments)
        self.assertEqual(assignments[0].source, (4, 4))
        self.assertEqual(assignments[0].target, (4, 6))

    def test_merge_operation_is_named_mixing(self):
        self.assertEqual(self.app.OP_MERGE, "混合")
        self.app.operation_var.set(self.app.OP_MERGE)
        self.assertIn("设置混合点", self.app._tool_options_for_operation())

    def test_mixing_cycles_control_is_visible_only_for_mixing(self):
        self.assertEqual(self.app.operation_var.get(), self.app.OP_MOVE)
        self.assertEqual(self.app.mixing_cycles_frame.winfo_manager(), "")

        self.app.operation_var.set(self.app.OP_MERGE)
        self.app.on_operation_changed()
        self.root.update_idletasks()
        self.assertNotEqual(self.app.mixing_cycles_frame.winfo_manager(), "")

        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.on_operation_changed()
        self.root.update_idletasks()
        self.assertEqual(self.app.mixing_cycles_frame.winfo_manager(), "")

    def test_mixing_path_uses_four_cell_cycle(self):
        path = self.app._build_mixing_path((5, 5))
        self.assertGreaterEqual(len(path), 5)
        self.assertEqual(path[0], (5, 5))
        self.assertEqual(path[-1], (5, 5))
        self.assertGreaterEqual(len(set(path)), 4)

    def test_debug_fault_tests_are_hidden_by_default(self):
        self.assertFalse(self.app.debug_tests_visible)
        self.assertEqual(self.app.debug_test_row.winfo_manager(), "")

    def test_manual_canvas_is_marked_manual_view(self):
        self.assertTrue(self.app._is_manual_canvas(self.app.manual_canvas))
        self.assertFalse(self.app._is_manual_canvas(self.app.path_canvas))

    def test_manual_simulation_can_set_droplet_on_core_cell(self):
        self.app.set_manual_droplet((3, 4))

        self.assertIsNotNone(self.app.manual_droplet)
        self.assertEqual(self.app.manual_droplet.cell, (3, 4))

    def test_manual_simulation_can_set_multiple_droplets(self):
        self.app.set_manual_droplet((3, 4))
        self.app.set_manual_droplet((5, 6))

        cells = {droplet.cell for droplet in self.app.manual_droplets}

        self.assertEqual(cells, {(3, 4), (5, 6)})

    def test_manual_simulation_clicking_existing_droplet_removes_it(self):
        self.app.set_manual_droplet((3, 4))
        self.app.set_manual_droplet((5, 6))
        self.app.set_manual_droplet((3, 4))

        cells = {droplet.cell for droplet in self.app.manual_droplets}

        self.assertEqual(cells, {(5, 6)})

    def test_manual_simulation_moves_to_active_adjacent_electrode(self):
        self.app.set_manual_droplet((3, 3))
        self.app.update_ui_only(electrode_id(3, 4, self.app.cols), 1)

        moved = self.app._update_manual_droplet_motion(0.5)

        self.assertTrue(moved)
        self.assertEqual(self.app.manual_droplet.cell, (3, 4))

    def test_manual_multiple_droplets_move_to_separate_active_neighbors(self):
        self.app.set_manual_droplet((3, 3))
        self.app.set_manual_droplet((5, 5))
        self.app.update_ui_only(electrode_id(3, 4, self.app.cols), 1)
        self.app.update_ui_only(electrode_id(5, 6, self.app.cols), 1)

        moved = self.app._update_manual_droplet_motion(0.5)
        cells = {droplet.cell for droplet in self.app.manual_droplets}

        self.assertTrue(moved)
        self.assertEqual(cells, {(3, 4), (5, 6)})

    def test_manual_droplet_snaps_to_target_cell_center(self):
        self.app.set_manual_droplet((3, 3))
        self.app.update_ui_only(electrode_id(3, 4, self.app.cols), 1)

        self.app._update_manual_droplet_motion(0.323)

        self.assertEqual(self.app.manual_droplet.position, (3.0, 4.0))

    def test_manual_non_adjacent_electrode_clicks_can_stay_active_without_shift(self):
        self.app.manual_toggle_electrode((3, 3), additive=False)
        self.app.manual_toggle_electrode((5, 5), additive=False)

        self.assertEqual(self.app._active_cells(), {(3, 3), (5, 5)})

    def test_manual_adjacent_electrode_click_without_shift_keeps_only_new_neighbor(self):
        self.app.manual_toggle_electrode((3, 3), additive=False)
        self.app.manual_toggle_electrode((3, 4), additive=False)

        self.assertEqual(self.app._active_cells(), {(3, 4)})

    def test_manual_electrode_shift_click_adds_another_active(self):
        self.app.manual_toggle_electrode((3, 3), additive=False)
        self.app.manual_toggle_electrode((3, 4), additive=True)

        self.assertEqual(self.app._active_cells(), {(3, 3), (3, 4)})

    def test_top_corner_reservoir_does_not_overlap_core_array(self):
        self.app.matrix_canvas = self.app.manual_canvas
        self.root.update_idletasks()
        left, top, _, _, _ = self.app._grid_geometry()

        rects = self.app._corner_reservoir_rects((-1, -1))

        self.assertTrue(rects)
        self.assertFalse(any(x1 > left and y1 > top for _x0, _y0, x1, y1 in rects))

    def test_corner_reservoir_uses_three_cell_l_shape_touching_core_corner(self):
        self.app.matrix_canvas = self.app.manual_canvas
        self.root.update_idletasks()
        left, top, _, _, cell_size = self.app._grid_geometry()

        rects = self.app._corner_reservoir_rects((-1, -1))
        covered_cells = {
            (round((y0 - top) / cell_size), round((x0 - left) / cell_size))
            for x0, y0, _x1, _y1 in rects
        }

        self.assertEqual(covered_cells, {(-1, -1), (-1, 0), (0, -1)})

    def test_manual_droplet_continues_to_center_after_rounding_into_target_cell(self):
        self.app.set_manual_droplet((3, 3))
        self.app.update_ui_only(electrode_id(3, 4, self.app.cols), 1)

        self.app._update_manual_droplet_motion(0.2)
        self.app._update_manual_droplet_motion(0.2)

        self.assertEqual(self.app.manual_droplet.position, (3.0, 4.0))

    def test_manual_camera_context_hides_automatic_goal_marker(self):
        self.app.set_manual_droplet((2, 2))

        context = self.app._camera_render_context(manual_view=True)

        self.assertIsNone(context["start_cell"])
        self.assertIsNone(context["goal_cell"])
        self.assertEqual(context["droplet_positions"], [self.app.manual_droplet.position])

    def test_droplet_a_b_colors_do_not_match_active_electrode(self):
        colors = self.app._droplet_marker_colors()
        self.assertGreaterEqual(len(colors), 2)
        self.assertNotEqual(colors[0], colors[1])
        self.assertNotIn(self.app.colors["btn_on"], colors[:2])

    def test_base_electrode_canvas_colors_are_white(self):
        self.assertEqual(self.app.colors["electrode_fill"], "#FFFFFF")
        self.assertEqual(self.app.colors["reservoir"], "#B65B4D")

    def test_mixing_cycle_count_controls_mixing_path_length(self):
        self.app.mixing_cycles_var.set(3)

        path = self.app._build_mixing_path((5, 5))

        self.assertEqual(len(path) - 1, 12)

    def test_loop_operation_exposes_start_and_path_tools(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.on_operation_changed()

        options = self.app._tool_options_for_operation()

        self.assertIn(self.app.TOOL_LOOP_START, options)
        self.assertIn(self.app.TOOL_LOOP_PATH, options)
        self.assertNotIn(getattr(self.app, "TOOL_LOOP_SELECT", "选择循环液滴"), options)
        self.assertNotIn(self.app.TOOL_OBSTACLE, options)

    def test_loop_cycle_count_accepts_thousands_and_uses_wider_spinbox(self):
        self.app.loop_cycles_var.set(9999)

        cycles = self.app._sync_loop_cycles()

        self.assertEqual(cycles, 9999)
        self.assertGreaterEqual(int(self.app.loop_cycles_spinbox.cget("to")), 9999)
        self.assertGreaterEqual(int(self.app.loop_cycles_spinbox.cget("width")), 5)

    def test_loop_droplet_placement_and_shift_cancel_are_separate_from_selection(self):
        self.app.operation_var.set(self.app.OP_LOOP)

        first = self.app._place_loop_droplet((2, 2))
        second = self.app._place_loop_droplet((8, 8))
        removed = self.app._remove_loop_droplet((2, 2))

        self.assertEqual(first, 0)
        self.assertEqual(second, 1)
        self.assertTrue(removed)
        self.assertEqual([route["source"] for route in self.app.loop_routes], [(8, 8)])
        self.assertIsNone(self.app.loop_route_index)

    def test_loop_path_points_apply_only_to_selected_droplet(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app._place_loop_droplet((2, 2))
        self.app._place_loop_droplet((8, 8))

        self.assertFalse(self.app._append_loop_path_point((2, 4)))
        selected = self.app._handle_loop_path_cell((8, 8))
        appended = self.app._handle_loop_path_cell((8, 10))

        self.assertEqual(selected, "selected")
        self.assertEqual(appended, "appended")
        self.assertTrue(appended)
        self.assertEqual(self.app.loop_routes[0]["path_points"], [])
        self.assertEqual(self.app.loop_routes[1]["path_points"], [(8, 10)])

    def test_path_arrow_points_follow_route_turns(self):
        self.assertEqual(
            self.app._path_arrow_cells([(2, 2), (2, 3), (2, 6), (3, 6), (5, 6)]),
            [(2, 2), (2, 6), (5, 6)],
        )
        self.assertEqual(
            self.app._path_arrow_cells([(2, 2), (2, 3), (2, 2)]),
            [(2, 2), (2, 3), (2, 2)],
        )

    def test_loop_cycle_count_control_is_visible_only_for_loop(self):
        self.assertEqual(self.app.loop_cycles_frame.winfo_manager(), "")

        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.on_operation_changed()
        self.root.update_idletasks()
        self.assertNotEqual(self.app.loop_cycles_frame.winfo_manager(), "")

        self.app.operation_var.set(self.app.OP_MOVE)
        self.app.on_operation_changed()
        self.root.update_idletasks()
        self.assertEqual(self.app.loop_cycles_frame.winfo_manager(), "")

    def test_loop_interval_seconds_insert_wait_steps_between_cycles(self):
        path = [(1, 1), (1, 2), (1, 1)]

        expanded = self.app._expanded_loop_path(path, cycles=2, interval_s=1.7)

        self.assertEqual(expanded, [(1, 1), (1, 2), (1, 1), (1, 1), (1, 1), (1, 2), (1, 1)])

    def test_loop_interval_seconds_are_synced_with_loop_controls(self):
        self.app.loop_interval_s_var.set(120.0)

        interval_s = self.app._sync_loop_interval_s()

        self.assertEqual(interval_s, 60.0)
        self.assertEqual(self.app.loop_interval_s_var.get(), 60.0)

    def test_loop_path_closes_user_points_back_to_start(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.start_cell = (2, 2)
        self.app.loop_path_points = [(2, 4), (4, 4), (4, 2)]

        cells = self.app._rebuild_loop_path_cells()

        self.assertEqual(cells[0], (2, 2))
        self.assertEqual(cells[-1], (2, 2))
        self.assertIn((2, 3), cells)
        self.assertIn((4, 3), cells)
        self.assertGreaterEqual(len(cells), 8)

    def test_loop_planner_uses_custom_closed_path(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.start_cell = (2, 2)
        self.app.loop_path_points = [(2, 4), (4, 4), (4, 2)]

        path = self.app.plan_path()

        self.assertTrue(path)
        self.assertEqual(path[0], (2, 2))
        self.assertEqual(path[-1], (2, 2))
        self.assertEqual(self.app.current_target_cell, path[1])
        self.assertEqual(self.app.operation_paths, [path])

    def test_loop_step_restarts_until_configured_cycle_count(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.loop_cycles_var.set(2)
        self.app.path = [(1, 1), (1, 2), (1, 1)]
        self.app.operation_paths = [self.app.path]
        self.app.path_index = 1
        self.app.loop_cycles_completed = 0
        self.app.auto_running = True

        self.app._handle_loop_step_reached()

        self.assertTrue(self.app.auto_running)
        self.assertEqual(self.app.loop_cycles_completed, 1)
        self.assertEqual(self.app.path_index, 0)
        self.assertEqual(self.app.current_target_cell, (1, 2))

    def test_single_loop_waits_by_seconds_between_cycles(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.loop_cycles_var.set(2)
        self.app.loop_interval_s_var.set(1.5)
        self.app.path = [(1, 1), (1, 2), (1, 1)]
        self.app.operation_paths = [self.app.path]
        self.app.path_index = 1
        self.app.loop_cycles_completed = 0
        self.app.auto_running = True

        self.app._handle_loop_step_reached()

        self.assertTrue(self.app.loop_wait_until > time.monotonic())
        self.assertIsNone(self.app.current_target_cell)
        self.assertEqual(self.app.active_auto_cells, {(1, 1)})

    def test_loop_debug_uses_existing_planned_path(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.path = [(1, 1), (1, 2), (1, 1)]
        self.app.operation_paths = [self.app.path]

        planned = self.app._ensure_debug_plan()

        self.assertEqual(planned, self.app.path)

    def test_loop_clear_target_buttons_clear_loop_path_points(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.start_cell = (2, 2)
        self.app.loop_path_points = [(2, 4), (4, 4)]
        self.app._rebuild_loop_path_cells()

        self.app.clear_target_shape()

        self.assertEqual(self.app.loop_path_points, [])
        self.assertEqual(self.app.loop_path_cells, [])

    def test_loop_can_store_multiple_droplet_routes(self):
        self.app.operation_var.set(self.app.OP_LOOP)

        first = self.app._place_loop_droplet((2, 2))
        self.app._select_loop_droplet((2, 2))
        self.app._append_loop_path_point((2, 4))
        second = self.app._place_loop_droplet((8, 8))
        self.app._select_loop_droplet((8, 8))
        self.app._append_loop_path_point((8, 10))

        self.assertEqual(len(self.app.loop_routes), 2)
        self.assertEqual(self.app.loop_routes[first]["source"], (2, 2))
        self.assertEqual(self.app.loop_routes[first]["path_points"], [(2, 4)])
        self.assertEqual(self.app.loop_routes[second]["source"], (8, 8))
        self.assertEqual(self.app.loop_routes[second]["path_points"], [(8, 10)])

    def test_loop_planner_builds_scheduled_paths_for_multiple_droplets(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app._place_loop_droplet((2, 2))
        self.app._select_loop_droplet((2, 2))
        self.app._append_loop_path_point((2, 4))
        self.app._place_loop_droplet((8, 8))
        self.app._select_loop_droplet((8, 8))
        self.app._append_loop_path_point((8, 10))

        planned = self.app.plan_path()

        self.assertEqual(len(planned), 2)
        self.assertEqual(len(self.app.sim_droplets), 2)
        self.assertTrue(all(item.path[0] == item.path[-1] for item in planned))
        self.assertEqual(self.app.operation_paths, [item.path for item in planned])

    def test_multi_loop_planner_does_not_expand_thousand_cycles(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.loop_cycles_var.set(1000)
        self.app._place_loop_droplet((2, 2))
        self.app._select_loop_droplet((2, 2))
        self.app._append_loop_path_point((2, 4))
        self.app._place_loop_droplet((8, 8))
        self.app._select_loop_droplet((8, 8))
        self.app._append_loop_path_point((8, 10))

        planned = self.app.plan_path()

        self.assertEqual(len(planned), 2)
        self.assertLess(max(len(item.scheduled_path) for item in planned), 20)
        self.assertEqual(self.app.loop_cycles, 1000)

    def test_multi_loop_step_uses_scheduled_active_cells(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app._place_loop_droplet((2, 2))
        self.app._select_loop_droplet((2, 2))
        self.app._append_loop_path_point((2, 4))
        self.app._place_loop_droplet((8, 8))
        self.app._select_loop_droplet((8, 8))
        self.app._append_loop_path_point((8, 10))
        self.app.plan_path()

        self.app._begin_loop_operation()

        expected = {
            self.app._scheduled_cell_at(item.scheduled_path, 1)
            for item in self.app.loop_assignments
        }
        self.assertEqual(self.app.active_auto_cells, expected)

    def test_multi_loop_restarts_next_cycle_without_replanning_expanded_path(self):
        self.app.operation_var.set(self.app.OP_LOOP)
        self.app.loop_cycles_var.set(2)
        self.app._place_loop_droplet((2, 2))
        self.app._select_loop_droplet((2, 2))
        self.app._append_loop_path_point((2, 4))
        self.app._place_loop_droplet((8, 8))
        self.app._select_loop_droplet((8, 8))
        self.app._append_loop_path_point((8, 10))
        self.app.plan_path()
        self.app.auto_running = True
        self.app._begin_loop_operation()
        max_steps = max(len(item.scheduled_path) for item in self.app.loop_assignments)
        self.app.multi_step_index = max_steps - 1

        self.app._loop_multi_auto_step(time.monotonic(), 0.0)

        self.assertTrue(self.app.auto_running)
        self.assertEqual(self.app.loop_cycles_completed, 1)
        self.assertEqual(self.app.multi_step_index, 0)

    def test_mixing_debug_step_enters_four_cell_cycle_after_merge_arrives(self):
        self.app.operation_var.set(self.app.OP_MERGE)
        self.app.goal_cell = (5, 5)
        self.app.path = [(5, 3), (5, 4), (5, 5)]
        self.app.merge_path_b = [(7, 5), (6, 5), (5, 5)]
        self.app.mixing_path = self.app._build_mixing_path(self.app.goal_cell)
        self.app.operation_paths = [self.app.path, self.app.merge_path_b, self.app.mixing_path]
        self.app.path_index = len(self.app.path) - 1
        self.app.path_index_b = len(self.app.merge_path_b) - 1
        self.app.mixing_index = 0

        changed = self.app._debug_step_merge(1)

        self.assertTrue(changed)
        self.assertTrue(self.app.mixing_active)
        self.assertEqual(self.app.mixing_index, 1)
        self.assertEqual(self.app.sim_droplet.cell, self.app.mixing_path[1])
        self.assertEqual(len(self.app.sim_droplets), 1)

    def test_split_operation_activates_only_side_electrodes(self):
        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.start_cell = (5, 5)
        self.app.split_left_cell = (5, 4)
        self.app.split_right_cell = (5, 6)

        self.app._begin_split_operation()

        self.assertEqual(self.app.active_auto_cells, {(5, 4), (5, 6)})
        self.assertNotIn((5, 5), self.app._active_cells())

    def test_split_operation_exposes_source_and_direction_only(self):
        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.on_operation_changed()

        self.assertEqual(
            self.app._tool_options_for_operation(),
            (self.app.TOOL_SPLIT_SOURCE, self.app.TOOL_SPLIT_DIRECTION),
        )

    def test_split_direction_sets_opposite_adjacent_targets(self):
        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.start_cell = (5, 5)

        changed = self.app._set_split_direction_from_cell((5, 6))

        self.assertTrue(changed)
        self.assertEqual(self.app.split_left_cell, (5, 4))
        self.assertEqual(self.app.split_right_cell, (5, 6))

    def test_split_direction_rejects_non_adjacent_or_edge_opposite(self):
        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.start_cell = (0, 0)
        self.app.split_left_cell = (1, 1)
        self.app.split_right_cell = (1, 2)

        self.assertFalse(self.app._set_split_direction_from_cell((0, 1)))
        self.assertEqual(self.app.split_left_cell, (1, 1))
        self.assertEqual(self.app.split_right_cell, (1, 2))

    def test_undo_setting_restores_target_shape_without_touching_manual_electrodes(self):
        self.app.operation_var.set(self.app.OP_MULTI)
        self.app._push_undo_snapshot()
        self.app.target_shape_points.append((5, 5))
        self.app._rebuild_target_shape_cells()
        self.app.update_ui_only(electrode_id(3, 3, self.app.cols), 1)

        restored = self.app.undo_last_setting()

        self.assertTrue(restored)
        self.assertEqual(self.app.target_shape_points, [])
        self.assertEqual(self.app.target_shape_cells, [])
        self.assertEqual(self.app.buttons[electrode_id(3, 3, self.app.cols)]["state"], 1)

    def test_undo_setting_is_blocked_while_auto_running(self):
        self.app._push_undo_snapshot()
        self.app.start_cell = (7, 7)
        self.app.auto_running = True

        restored = self.app.undo_last_setting()

        self.assertFalse(restored)
        self.assertEqual(self.app.start_cell, (7, 7))

    def test_split_failure_releases_and_retries_before_success(self):
        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.start_cell = (5, 5)
        self.app.split_left_cell = (5, 4)
        self.app.split_right_cell = (5, 6)
        self.app.auto_running = True
        self.app._begin_split_operation()
        self.app.split_forced_failures_remaining = 1
        self.app.split_progress = 1.0

        self.app._split_auto_step(time.monotonic(), 0.0)

        self.assertTrue(self.app.auto_running)
        self.assertEqual(self.app.split_attempts, 1)
        self.assertEqual(self.app.split_progress, 0.0)
        self.assertEqual(self.app.active_auto_cells, set())
        self.assertEqual(len(self.app.sim_droplets), 1)

    def test_split_failure_stops_after_retry_limit(self):
        self.app.operation_var.set(self.app.OP_SPLIT)
        self.app.start_cell = (5, 5)
        self.app.split_left_cell = (5, 4)
        self.app.split_right_cell = (5, 6)
        self.app.auto_running = True
        self.app._begin_split_operation()
        self.app.split_attempts = self.app.max_split_attempts
        self.app.split_forced_failures_remaining = 1
        self.app.split_progress = 1.0

        self.app._split_auto_step(time.monotonic(), 0.0)

        self.assertFalse(self.app.auto_running)
        self.assertEqual(self.app.active_auto_cells, set())

    def test_closed_loop_first_step_only_activates_next_electrode(self):
        self.app.operation_var.set(self.app.OP_MOVE)
        self.app.start_cell = (3, 3)
        self.app.goal_cell = (3, 5)
        self.app.path = [(3, 3), (3, 4), (3, 5)]
        self.app.operation_paths = [self.app.path]
        self.app.path_index = 0

        self.app._begin_current_step()

        self.assertEqual(self.app.active_auto_cells, {(3, 4)})
        self.assertNotIn((3, 3), self.app._active_cells())

    def test_camera_context_hides_setup_markers_after_debug_progress(self):
        self.app.operation_var.set(self.app.OP_MERGE)
        self.app.start_cell = (3, 3)
        self.app.secondary_cell = (5, 3)
        self.app.goal_cell = (4, 4)
        self.app.path = [(3, 3), (4, 3), (4, 4)]
        self.app.merge_path_b = [(5, 3), (5, 4), (4, 4)]
        self.app.operation_paths = [self.app.path, self.app.merge_path_b]
        self.app.path_index = 1
        self.app.path_index_b = 1

        context = self.app._camera_render_context(manual_view=False)

        self.assertIsNone(context["start_cell"])
        self.assertIsNone(context["goal_cell"])

    def test_camera_context_shows_setup_markers_before_debug_progress(self):
        self.app.operation_var.set(self.app.OP_MERGE)
        self.app.start_cell = (3, 3)
        self.app.goal_cell = (4, 4)
        self.app.path_index = 0
        self.app.path_index_b = 0
        self.app.mixing_index = 0
        self.app.mixing_active = False

        context = self.app._camera_render_context(manual_view=False)

        self.assertEqual(context["start_cell"], (3, 3))
        self.assertEqual(context["goal_cell"], (4, 4))

    def test_move_planner_routes_around_user_obstacle(self):
        self.app.operation_var.set(self.app.OP_MOVE)
        self.app.start_cell = (0, 0)
        self.app.goal_cell = (0, 2)
        self.app.obstacle_cells = {(0, 1)}

        path = self.app.plan_path()

        self.assertTrue(path)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (0, 2))
        self.assertNotIn((0, 1), path)

    def test_simulation_profile_controls_are_available(self):
        self.assertIn("理想", self.app.motion_profile_combobox["values"])
        self.assertIn("强噪声", self.app.vision_noise_combobox["values"])
        self.assertIn("指定弱故障电极", self.app.fault_mode_combobox["values"])

        self.app.motion_profile_var.set("困难")
        self.app.vision_noise_var.set("强噪声")

        self.assertGreater(self.app._motion_profile().stuck_probability, 0.0)
        self.assertGreater(self.app._vision_noise_profile().drop_frame_rate, 0.0)

    def test_auto_switch_records_break_before_make_metrics(self):
        commands = []
        self.app.send_command = lambda command, log_send=True: commands.append(command) or True
        self.app.operation_metrics = self.app._new_operation_metrics("move")
        self.app.active_auto_cells = {(3, 3)}
        self.app.update_ui_only(electrode_id(3, 3, self.app.cols), 1)

        self.app._set_auto_active_cells({(3, 4)}, stage="DRIVE_TARGET", action="advance")

        self.assertEqual(
            commands,
            [
                f"SET:{electrode_id(3, 3, self.app.cols)}:0",
                f"SET:{electrode_id(3, 4, self.app.cols)}:1",
            ],
        )
        self.assertEqual(self.app.operation_metrics.electrode_switch_count, 2)
        self.assertEqual(self.app.operation_metrics.events[-1].stage, "DRIVE_TARGET")

    def test_detection_dropout_counts_and_holds_before_timeout(self):
        self.app.operation_metrics = self.app._new_operation_metrics("move")
        now = time.monotonic()
        self.app.last_detection_time = now
        self.app.auto_running = True
        self.app.vision_noise_var.set("强噪声")

        detection = self.app._render_and_check_detection(now + 0.1)

        self.assertIsNone(detection)
        self.assertTrue(self.app.auto_running)
        self.assertEqual(self.app.operation_metrics.dropout_count, 1)

    def test_metrics_export_writes_csv_rows(self):
        self.app.operation_metrics_history = [self.app._new_operation_metrics("move")]
        self.app.operation_metrics_history[0].record_event(
            StepEvent(stage="DRIVE_TARGET", target_cell=(3, 4), on_cells=((3, 4),), duration_s=0.5)
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "metrics.csv"
            self.app.export_metrics_csv(path)
            with path.open("r", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["operation"], "move")
        self.assertEqual(rows[0]["total_steps"], "1")


if __name__ == "__main__":
    unittest.main()
