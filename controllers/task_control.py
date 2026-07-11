"""Task lifecycle, manual stepping, reset, and simulation fault controls."""

from __future__ import annotations

from .common import (
    AUTO_LOOP_INTERVAL_MS,
    CORE_CELLS,
    CORNER_RESERVOIRS,
    HardwareProtocol,
    SimulatedDroplet,
    detection_in_cell,
    electrode_id,
    is_reservoir_cell,
    math,
    messagebox,
    time,
)


class TaskControlMixin:
    def _planned_step_count(self, planned):
        if not planned:
            return 0
        if hasattr(planned[0], "scheduled_path"):
            return max(max(0, len(assignment.scheduled_path) - 1) for assignment in planned)
        if isinstance(planned[0], tuple):
            return max(0, len(planned) - 1)
        return sum(max(0, len(path) - 1) for path in planned)

    def _operation_ready_to_start(self, planned):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            return bool(planned)
        if operation == self.OP_SPLIT:
            return bool(planned)
        if operation == self.OP_MERGE:
            return bool(planned) and len(planned) >= 3 and len(self.mixing_path) > 1
        return bool(planned) and len(planned) >= 2

    def _prepare_operation_start(self):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            self._begin_multi_operation()
        elif operation == self.OP_SPLIT:
            self._begin_split_operation()
        elif operation == self.OP_MERGE:
            self._begin_merge_step()
        elif operation == self.OP_LOOP:
            self._begin_loop_operation()
        else:
            self._begin_current_step()

    def _operation_running_label(self):
        return f"闭环: {self.operation_var.get()}运行中"

    def start_auto_control(self):
        if not self.is_simulation_mode():
            messagebox.showinfo("提示", "第一版闭环演示仅在仿真模式运行")
            return
        if self.operation_var.get() == self.OP_MOVE and self.start_cell == self.goal_cell:
            self.log("起点已在终点，无需启动闭环")
            return

        planned = self.plan_path(reset_droplet=True)
        if not self._operation_ready_to_start(planned):
            return

        self._begin_operation_metrics()
        self.auto_running = True
        self.camera_running = True
        self.btn_camera.config(text="关闭预览", bg=self.colors["danger"], activebackground=self.colors["danger_hover"])
        if self.camera_after_id is not None:
            self.root.after_cancel(self.camera_after_id)
            self.camera_after_id = None

        now = time.monotonic()
        self.last_auto_update_time = now
        self.last_detection_time = now
        self.step_replanned = False
        self.step_extension_used = False
        self.arrival_confirmation.reset()
        self.multi_arrival_confirmation.reset()
        self.recovery_attempts = 0
        self.feedback_log_times.clear()
        self._prepare_operation_start()
        self.auto_status_label.config(text=self._operation_running_label(), fg=self.colors["success"])
        self.log(f"{self.operation_var.get()}闭环控制已启动")
        self._auto_loop()

    def pause_auto_control(self):
        if self.auto_running:
            self.stop_auto_control("用户暂停")
        else:
            self.auto_status_label.config(text="闭环: 已暂停", fg=self.colors["muted"])

    def stop_auto_control(self, reason=""):
        self.auto_running = False
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        self._set_auto_active_cells(set())
        self._release_hardware_auto_ownership()
        self.current_target_cell = None
        self.current_target_cell_b = None
        self.mixing_active = False
        self.auto_status_label.config(text="闭环: 已停止", fg=self.colors["muted"])
        if reason:
            self.log(f"闭环停止：{reason}")
        self._draw_matrix_canvas()

    def reset_simulation(self):
        self.stop_auto_control("复位仿真")
        self._clear_planned_operation()
        self.detected_position = None
        self.detected_positions = []
        self.detected_cell = None
        self.drop_frame_until = 0.0
        self.manual_droplets.clear()
        self.manual_droplet = None
        self._reset_droplets_for_operation()
        for info in self.buttons.values():
            info["state"] = 0
        self.active_auto_cells = set()
        self._set_active_count(0)
        self.auto_status_label.config(text="闭环: 仿真待机", fg=self.colors["muted"])
        self.log("仿真已复位")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def step_debug_forward(self):
        self._debug_step_path(1)

    def step_debug_backward(self):
        self._debug_step_path(-1)

    def _debug_step_path(self, direction):
        if not self.is_simulation_mode():
            messagebox.showinfo("提示", "路径步进调试当前仅用于仿真模式")
            return

        self._pause_auto_for_debug_step()
        planned = self._ensure_debug_plan()
        if not self._operation_ready_to_start(planned):
            return

        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            changed = self._debug_step_multi(direction)
        elif operation == self.OP_LOOP and self.loop_assignments:
            changed = self._debug_step_loop_multi(direction)
        elif operation == self.OP_MERGE:
            changed = self._debug_step_merge(direction)
        elif operation == self.OP_SPLIT:
            changed = self._debug_step_split(direction)
        else:
            changed = self._debug_step_single_path(direction)

        if changed:
            self.step_start_time = time.monotonic()
            self.last_detection_time = self.step_start_time
            self.step_replanned = False
            self.auto_status_label.config(text="闭环: 手动步进调试", fg=self.colors["accent"])
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def _pause_auto_for_debug_step(self):
        if not self.auto_running:
            return
        self.auto_running = False
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        self.log("自动闭环已暂停，进入手动步进调试")

    def _ensure_debug_plan(self):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI and self.multi_assignments:
            return self.multi_assignments
        if operation == self.OP_LOOP and self.loop_assignments:
            return self.loop_assignments
        if operation in (self.OP_MERGE, self.OP_SPLIT) and self.operation_paths:
            return self.operation_paths
        if operation in (self.OP_MOVE, self.OP_LOOP) and self.path:
            return self.path
        return self.plan_path(reset_droplet=True)

    def _debug_step_merge(self, direction):
        if not self.path or not self.merge_path_b:
            return False

        merge_arrived = self.path_index >= len(self.path) - 1 and self.path_index_b >= len(self.merge_path_b) - 1
        if direction > 0 and merge_arrived:
            return self._debug_step_mixing(direction)
        if direction < 0 and (self.mixing_active or self.mixing_index > 0):
            return self._debug_step_mixing(direction)

        self.mixing_active = False
        self.mixing_index = 0
        return self._debug_step_dual_paths(direction, "混合")

    def _debug_step_single_path(self, direction):
        if not self.path:
            return False
        next_index = self._clamp_index(self.path_index + direction, len(self.path))
        if next_index == self.path_index:
            self.log("调试步进已在路径边界")
            return False
        self.path_index = next_index
        current = self.path[self.path_index]
        self.sim_droplet.reset(current)
        self.sim_droplets = [self.sim_droplet]
        self.current_target_cell = self.path[self.path_index + 1] if self.path_index < len(self.path) - 1 else None
        self.current_target_cell_b = None
        self._set_auto_active_cells(self._debug_single_active_for_path(self.path, self.path_index))
        self.log(
            f"调试{'步进' if direction > 0 else '回退'}："
            f"{self._cell_label(current)} ({self.path_index}/{len(self.path) - 1})"
        )
        return True

    def _debug_step_dual_paths(self, direction, label):
        if not self.path or not self.merge_path_b:
            return False
        next_a = self._clamp_index(self.path_index + direction, len(self.path))
        next_b = self._clamp_index(self.path_index_b + direction, len(self.merge_path_b))
        if next_a == self.path_index and next_b == self.path_index_b:
            self.log(f"{label}调试步进已在路径边界")
            return False

        self.path_index = next_a
        self.path_index_b = next_b
        cell_a = self.path[self.path_index]
        cell_b = self.merge_path_b[self.path_index_b]
        self.sim_droplet.reset(cell_a)
        self.sim_droplet_b.reset(cell_b)
        if self.path_index >= len(self.path) - 1 and self.path_index_b >= len(self.merge_path_b) - 1:
            self.sim_droplet.reset(self.goal_cell)
            self.sim_droplets = [self.sim_droplet]
            active = {self.goal_cell}
        else:
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
            active = self._debug_single_active_for_path(self.path, self.path_index)
            active.update(self._debug_single_active_for_path(self.merge_path_b, self.path_index_b))
        self.current_target_cell = self.path[self.path_index + 1] if self.path_index < len(self.path) - 1 else self.goal_cell
        self.current_target_cell_b = (
            self.merge_path_b[self.path_index_b + 1]
            if self.path_index_b < len(self.merge_path_b) - 1
            else self.goal_cell
        )
        self._set_auto_active_cells(active)
        self.log(
            f"{label}调试{'步进' if direction > 0 else '回退'}："
            f"A {self.path_index}/{len(self.path) - 1}，B {self.path_index_b}/{len(self.merge_path_b) - 1}"
        )
        return True

    def _debug_step_mixing(self, direction):
        if len(self.mixing_path) < 2:
            self.log("四宫格混合路径为空，无法步进")
            return False

        if direction < 0 and self.mixing_index <= 0:
            self.mixing_active = False
            return self._debug_step_dual_paths(direction, "混合")

        next_index = self._clamp_index(self.mixing_index + direction, len(self.mixing_path))
        if next_index == self.mixing_index:
            self.log("四宫格混合调试步进已在路径边界")
            return False

        self.mixing_active = True
        self.mixing_index = next_index
        current = self.mixing_path[self.mixing_index]
        self.sim_droplet.reset(current)
        self.sim_droplets = [self.sim_droplet]
        self.current_target_cell = (
            self.mixing_path[self.mixing_index + 1]
            if self.mixing_index < len(self.mixing_path) - 1
            else current
        )
        self.current_target_cell_b = None
        self._set_auto_active_cells({current})
        self.log(
            f"四宫格混合调试{'步进' if direction > 0 else '回退'}："
            f"{self.mixing_index}/{len(self.mixing_path) - 1}，"
            f"当前 {self._cell_label(current)}，下一目标 {self._cell_label(self.current_target_cell)}"
        )
        return True

    def _debug_step_split(self, direction):
        if not self.path or not self.merge_path_b:
            return False
        next_index = self._clamp_index(self.path_index + direction, 2)
        if next_index == self.path_index:
            self.log("分裂调试步进已在路径边界")
            return False

        self.path_index = next_index
        self.path_index_b = next_index
        if next_index == 0:
            self.split_progress = 0.0
            self.sim_droplet.reset(self.start_cell)
            self.sim_droplets = [self.sim_droplet]
            self.current_target_cell = self.split_left_cell
            self.current_target_cell_b = self.split_right_cell
            self._set_auto_active_cells(set())
            self.log(f"分裂调试回退：{self._cell_label(self.start_cell)}，源电极保持关闭")
        else:
            self.split_progress = 1.0
            self.sim_droplet.reset(self.split_left_cell)
            self.sim_droplet_b.reset(self.split_right_cell)
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
            self.current_target_cell = self.split_left_cell
            self.current_target_cell_b = self.split_right_cell
            self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
            self.log(
                "分裂调试步进："
                f"{self._cell_label(self.split_left_cell)} / {self._cell_label(self.split_right_cell)}"
            )
        return True

    def _debug_step_multi(self, direction):
        if not self.multi_assignments:
            return False
        max_steps = max(len(assignment.scheduled_path) for assignment in self.multi_assignments)
        next_step = self._clamp_index(self.multi_step_index + direction, max_steps)
        if next_step == self.multi_step_index:
            self.log("多液滴调试步进已在调度边界")
            return False

        if len(self.sim_droplets) != len(self.multi_assignments):
            self.sim_droplets = [
                SimulatedDroplet(assignment.source, speed_cells_per_sec=3.2)
                for assignment in self.multi_assignments
            ]
        self.multi_step_index = next_step
        self.multi_step_start_time = time.monotonic()
        self.multi_droplet_visible = []
        for idx, assignment in enumerate(self.multi_assignments):
            cell = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            if cell is None:
                self.sim_droplets[idx].reset(assignment.source)
                self.multi_droplet_visible.append(False)
            else:
                self.sim_droplets[idx].reset(cell)
                self.multi_droplet_visible.append(self._multi_cell_is_visible_droplet(assignment, cell))
        self._set_auto_active_cells(self._scheduled_active_cells_for_assignments(self.multi_assignments, self.multi_step_index))
        self.log(f"多液滴调试{'步进' if direction > 0 else '回退'}：{self.multi_step_index}/{max_steps - 1}")
        return True

    def _debug_step_loop_multi(self, direction):
        if not self.loop_assignments:
            return False
        max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
        next_step = self._clamp_index(self.multi_step_index + direction, max_steps)
        if next_step == self.multi_step_index:
            self.log("多液滴循环调试步进已在调度边界")
            return False

        self.multi_step_index = next_step
        self.multi_step_start_time = time.monotonic()
        self.sim_droplets = []
        self.multi_droplet_visible = []
        for assignment in self.loop_assignments:
            cell = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            droplet = SimulatedDroplet(assignment.source, speed_cells_per_sec=2.5)
            if cell is None:
                droplet.reset(assignment.source)
                self.multi_droplet_visible.append(False)
            else:
                droplet.reset(cell)
                self.multi_droplet_visible.append(True)
            self.sim_droplets.append(droplet)
        self._set_auto_active_cells(self._scheduled_active_cells_for_assignments(self.loop_assignments, self.multi_step_index))
        self.log(f"多液滴循环调试{'步进' if direction > 0 else '回退'}：{self.multi_step_index}/{max_steps - 1}")
        return True

    @staticmethod
    def _clamp_index(index, length):
        if length <= 0:
            return 0
        return max(0, min(length - 1, index))

    @staticmethod
    def _debug_active_for_path(path, index):
        if not path:
            return set()
        active = {path[index]}
        if index < len(path) - 1:
            active.add(path[index + 1])
        return active

    @staticmethod
    def _debug_single_active_for_path(path, index):
        if not path:
            return set()
        return {path[index]}

    def _scheduled_active_cells_for_assignments(self, assignments, step):
        active = {
            cell
            for assignment in assignments
            for cell in (self._scheduled_cell_at(assignment.scheduled_path, step),)
            if cell is not None
        }
        active.update(self._dispensed_reservoir_hold_cells(assignments, step))
        return active

    def _dispensed_reservoir_hold_cells(self, assignments, step):
        holds = set()
        for assignment in assignments:
            source = assignment.source
            if source not in self.loaded_reservoirs or source in CORNER_RESERVOIRS or not is_reservoir_cell(source):
                continue
            current = self._scheduled_cell_at(assignment.scheduled_path, step)
            if current is not None and current != source:
                holds.add(source)
        return holds

    @staticmethod
    def _multi_cell_is_visible_droplet(_assignment, cell):
        return cell in CORE_CELLS

    def simulate_detection_dropout(self):
        self.drop_frame_until = time.monotonic() + 0.8
        self.log("已触发 0.8 s 检测丢帧测试")
        if self.is_simulation_mode() and not self.auto_running:
            self._render_sim_camera_frame(hide_droplet=True)

    def simulate_drift_fault(self):
        if self.operation_var.get() == self.OP_MULTI and self.sim_droplets:
            for idx, visible in enumerate(self.multi_droplet_visible):
                if not visible:
                    continue
                self.sim_droplets[idx].position = self._offset_position(self.sim_droplets[idx].position, 2, 1)
                self.log(f"已注入 D{idx + 1} 跑偏测试")
                break
            else:
                self.log("当前没有已出滴的多液滴可注入跑偏")
        else:
            self.sim_droplet.position = self._offset_position(self.sim_droplet.position, 2, 1)
            self.log("已注入单液滴跑偏测试")
        self._render_sim_camera_frame()

    def simulate_fusion_fault(self):
        if self.operation_var.get() != self.OP_MULTI:
            self.log("融合测试仅用于多液滴模式")
            return
        visible_indices = [idx for idx, visible in enumerate(self.multi_droplet_visible) if visible]
        if len(visible_indices) < 2:
            self.log("至少需要两滴已出液滴才能注入融合测试")
            return
        first, second = visible_indices[:2]
        self.sim_droplets[second].position = self.sim_droplets[first].position
        self.log(f"已注入 D{first + 1}/D{second + 1} 融合测试")
        self._render_sim_camera_frame()

    def simulate_split_failure_fault(self):
        if self.operation_var.get() != self.OP_SPLIT:
            self.log("分裂失败测试仅用于分裂模式")
            return
        self.split_forced_failures_remaining += 1
        self.log(f"已注入 1 次分裂失败测试，剩余 {self.split_forced_failures_remaining} 次")
        if self.is_simulation_mode() and not self.auto_running:
            self._render_sim_camera_frame()

    def _offset_position(self, position, row_delta, col_delta):
        row = max(0, min(self.rows - 1, int(round(position[0] + row_delta))))
        col = max(0, min(self.cols - 1, int(round(position[1] + col_delta))))
        return float(row), float(col)
