"""Runtime scheduling and visual safety for concurrent droplets."""

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
    replan_multi_assignments_after_fault,
    time,
)


class MultiRuntimeMixin:
    def _begin_multi_operation(self):
        if not self.multi_assignments:
            self.stop_auto_control("多液滴任务为空")
            return
        self.multi_step_index = 0
        self.multi_step_start_time = time.monotonic()
        self.step_extension_used = False
        self.multi_arrival_confirmation.reset()
        self.multi_completed_droplet_ids = {
            assignment.droplet_id
            for assignment in self.multi_assignments
            if assignment.source == assignment.target
        }
        self._record_multi_plan_metrics()
        self.sim_droplets = []
        self.multi_droplet_visible = []
        for assignment in self.multi_assignments:
            droplet = SimulatedDroplet(assignment.source, speed_cells_per_sec=3.2)
            start_cell = self._scheduled_cell_at(assignment.scheduled_path, 0)
            if start_cell is not None:
                droplet.reset(start_cell)
                self.multi_droplet_visible.append(self._multi_cell_is_visible_droplet(assignment, start_cell))
                if is_reservoir_cell(assignment.source):
                    self.log(f"D{assignment.droplet_id} 从储液池 {self._cell_label(assignment.source)} 准备出滴")
                else:
                    self.log(f"D{assignment.droplet_id} 初始液滴位于 {self._cell_label(assignment.source)}")
            else:
                droplet.reset(assignment.source)
                self.multi_droplet_visible.append(False)
            self.sim_droplets.append(droplet)
        self._set_auto_active_cells(self._multi_active_cells_for_phase(0, 0.0))
        self.log(f"多液滴出滴启动：{len(self.multi_assignments)} 滴")

    def _multi_auto_step(self, now, dt_s):
        if not self.multi_assignments:
            self.stop_auto_control("多液滴任务为空")
            return

        if len(self.multi_completed_droplet_ids) == len(self.multi_assignments):
            self._finish_multi_success()
            return
        max_steps = max(len(assignment.scheduled_path) for assignment in self.multi_assignments)
        if self.multi_step_index >= max_steps - 1:
            self._render_sim_camera_frame()
            self._finish_multi_success()
            return

        next_step = self.multi_step_index + 1
        step_elapsed = now - self.multi_step_start_time
        phase_progress = min(1.0, max(0.0, step_elapsed / self.multi_step_duration_s))
        self._set_auto_active_cells(self._multi_active_cells_for_phase(self.multi_step_index, phase_progress))

        for idx, assignment in enumerate(self.multi_assignments):
            current = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            target = self._scheduled_cell_at(assignment.scheduled_path, next_step)
            if current is None and target is None:
                self.multi_droplet_visible[idx] = False
                continue
            if target is None:
                self.multi_droplet_visible[idx] = False
                continue
            if current is None:
                if phase_progress >= 0.62:
                    self.sim_droplets[idx].reset(target)
                    self.multi_droplet_visible[idx] = self._multi_cell_is_visible_droplet(assignment, target)
                else:
                    self.multi_droplet_visible[idx] = False
            elif is_reservoir_cell(current):
                if target in CORE_CELLS and phase_progress >= 0.62:
                    self.sim_droplets[idx].reset(target)
                    self.multi_droplet_visible[idx] = True
                else:
                    self.sim_droplets[idx].reset(current)
                    self.multi_droplet_visible[idx] = False
            else:
                self.multi_droplet_visible[idx] = True
                self.sim_droplets[idx].update_towards(
                    target,
                    dt_s,
                    motion_profile=self._motion_profile(),
                    weak_fault_cells=self._weak_fault_cells_for_run(),
                )

        self._render_sim_camera_frame(force_display=False)
        if not self.auto_running:
            return
        if not self._check_multi_visual_health(max_steps):
            return

        expected_targets = self._scheduled_expected_target_cells(self.multi_assignments, next_step)
        visually_confirmed = self.multi_arrival_confirmation.observe(
            expected_targets,
            self.detected_cells,
            now,
        )
        if not expected_targets:
            visually_confirmed = step_elapsed >= self.multi_step_duration_s

        if visually_confirmed:
            for idx, assignment in enumerate(self.multi_assignments):
                previous_cell = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
                cell = self._scheduled_cell_at(assignment.scheduled_path, next_step)
                if cell is None:
                    self.multi_droplet_visible[idx] = False
                else:
                    self.sim_droplets[idx].reset(cell)
                    self.multi_droplet_visible[idx] = self._multi_cell_is_visible_droplet(assignment, cell)
                    if is_reservoir_cell(previous_cell) and cell in CORE_CELLS:
                        self.log_feedback(
                            "储液池出滴",
                            f"D{assignment.droplet_id} 已从 {self._cell_label(assignment.source)} 形成单滴并进入调度",
                            force=True,
                        )
                        self.log(f"D{assignment.droplet_id} 从储液池 {self._cell_label(assignment.source)} 出滴")
                    if cell == assignment.target:
                        self.multi_completed_droplet_ids.add(assignment.droplet_id)
            self.multi_step_index = next_step
            self.multi_step_start_time = now
            self.step_extension_used = False
            self.multi_arrival_confirmation.reset()
            self._set_auto_active_cells(self._multi_active_cells_for_phase(self.multi_step_index, 0.0))
            self.log_feedback(
                "多液滴调度",
                f"视觉/时间步确认进入第 {self.multi_step_index} 步，重新计算本轮激活电极",
                force=True,
            )
            self.log(f"多液滴调度步进 {self.multi_step_index}/{max_steps - 1}")
        elif step_elapsed >= self.step_timeout_s + self.step_extension_s:
            hold_cells = set(self.detected_cells) or {
                droplet.cell
                for idx, droplet in enumerate(self.sim_droplets)
                if idx < len(self.multi_droplet_visible) and self.multi_droplet_visible[idx]
            }
            self._pause_multi_with_hold(
                f"多液滴调度等待 {step_elapsed:.1f}s 仍未通过稳定视觉确认，已保护保持",
                hold_cells,
            )
            return
        elif step_elapsed >= self.step_timeout_s and not self.step_extension_used:
            self.step_extension_used = True
            self.log_feedback(
                "多液滴调度",
                f"初始等待 {self.step_timeout_s:.1f}s 未全部稳定到达，延长 {self.step_extension_s:.1f}s",
                force=True,
            )

        if self.multi_step_index >= max_steps - 1:
            self._render_sim_camera_frame()
            if len(self.multi_completed_droplet_ids) == len(self.multi_assignments):
                self._finish_multi_success()

    def _record_multi_plan_metrics(self):
        metrics = self.operation_metrics
        if metrics is None:
            return
        metrics.planning_status = "success"
        metrics.faulty_electrodes = sorted(self.faulty_electrodes)
        metrics.assignment_time_ms = self.multi_plan_metrics.get("assignment_time_ms", 0.0)
        metrics.routing_time_ms = self.multi_plan_metrics.get("routing_time_ms", 0.0)
        metrics.scheduling_time_ms = self.multi_plan_metrics.get("scheduling_time_ms", 0.0)
        metrics.total_planning_time_ms = self.multi_plan_metrics.get("total_planning_time_ms", 0.0)
        metrics.path_lengths = {
            item.droplet_id: max(0, len(item.path) - 1) for item in self.multi_assignments
        }
        metrics.scheduled_makespan_steps = max(
            (max(0, len(item.scheduled_path) - 1) for item in self.multi_assignments),
            default=0,
        )
        metrics.wait_steps_by_droplet = {
            item.droplet_id: sum(
                previous is not None and current is not None and previous == current
                for previous, current in zip(item.scheduled_path, item.scheduled_path[1:])
            )
            for item in self.multi_assignments
        }
        metrics.release_delay_steps_by_droplet = {
            item.droplet_id: next(
                (step for step, cell in enumerate(item.scheduled_path) if cell is not None),
                len(item.scheduled_path),
            )
            for item in self.multi_assignments
        }

    def _finish_multi_success(self):
        self._mark_operation_success()
        self.stop_auto_control("多液滴全部到达目标电极")

    def replan_after_fault(self, fault_cell):
        if not self.is_simulation_mode() or not self.auto_running or self.operation_var.get() != self.OP_MULTI:
            self.log("运行时故障全局重排仅适用于正在运行的多液滴仿真")
            return False
        if fault_cell not in CORE_CELLS:
            self.log("运行时故障电极必须位于中间20x20阵列")
            return False
        if fault_cell in self.faulty_electrodes:
            self.log(f"故障电极已存在 -> {self._cell_label(fault_cell)}")
            return False
        positions = {
            assignment.droplet_id: self.sim_droplets[idx].cell
            for idx, assignment in enumerate(self.multi_assignments)
            if idx < len(self.sim_droplets)
        }
        self.faulty_electrodes.add(fault_cell)
        self.log(f"运行时确认故障电极 {self._cell_label(fault_cell)}，开始全部未完成液滴全局重排")
        if fault_cell in positions.values():
            if self.operation_metrics is not None:
                metrics = self.operation_metrics
                metrics.faulty_electrodes = sorted(self.faulty_electrodes)
                metrics.record_fault_replan(0.0, None)
                metrics.planning_status = "protective_pause"
                self._refresh_metrics_label()
            self._pause_multi_with_hold("故障电极当前被液滴占据，无法安全迁移，进入保护暂停", set(positions.values()))
            return False

        started_ns = time.perf_counter_ns()
        result = replan_multi_assignments_after_fault(
            self.multi_assignments,
            positions,
            self.multi_completed_droplet_ids,
            self.obstacle_cells,
            self.faulty_electrodes,
            self.planner,
        )
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        nominal = result.nominal_remaining_length
        detour = (
            (result.fault_remaining_length - nominal) / nominal
            if result.status == "success" and nominal > 0
            else (0.0 if result.status == "success" and nominal == 0 else None)
        )
        if self.operation_metrics is not None:
            metrics = self.operation_metrics
            metrics.faulty_electrodes = sorted(self.faulty_electrodes)
            metrics.record_fault_replan(elapsed_ms, detour)
            metrics.planning_status = result.status if result.status != "success" else "success"
            metrics.routing_time_ms += result.routing_time_ms
            metrics.scheduling_time_ms += result.scheduling_time_ms
            self._refresh_metrics_label()
        self.log(
            f"故障全局重排结果: {result.status}; routing={result.routing_time_ms:.3f} ms, "
            f"scheduling={result.scheduling_time_ms:.3f} ms, total={elapsed_ms:.3f} ms, detour={detour}"
        )
        if result.status != "success":
            self._pause_multi_with_hold(
                f"故障后全局重排 {result.status}: {result.reason}",
                set(positions.values()),
            )
            return False

        self.multi_assignments = result.assignments
        self.multi_targets = [item.target for item in self.multi_assignments]
        self.operation_paths = [item.path for item in self.multi_assignments]
        self._refresh_operation_path_cells()
        self.multi_step_index = 0
        self.multi_step_start_time = time.monotonic()
        self.step_extension_used = False
        self.multi_arrival_confirmation.reset()
        for idx, assignment in enumerate(self.multi_assignments):
            current = positions.get(assignment.droplet_id, assignment.target)
            self.sim_droplets[idx].reset(current)
            self.multi_droplet_visible[idx] = self._multi_cell_is_visible_droplet(
                assignment,
                self._scheduled_cell_at(assignment.scheduled_path, 0),
            )
        self._set_auto_active_cells(self._multi_active_cells_for_phase(0, 0.0))
        self.log("故障后剩余任务已使用新局部时间轴继续执行")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return True

    def inject_runtime_fault_from_entry(self):
        if not self.is_simulation_mode():
            self.log("仿真故障注入仅在仿真模式可用")
            return False
        try:
            electrode = int(self.runtime_fault_id_var.get())
            row, col = divmod(electrode - 1, self.cols)
            cell = (row, col)
        except (TypeError, ValueError):
            self.log("请输入1至400的核心阵列电极编号")
            return False
        if electrode < 1 or electrode > self.rows * self.cols:
            self.log("请输入1至400的核心阵列电极编号")
            return False
        return self.replan_after_fault(cell)

    def _multi_active_cells_for_phase(self, step, phase_progress):
        active = set()
        for assignment in self.multi_assignments:
            current = self._scheduled_cell_at(assignment.scheduled_path, step)
            nxt = self._scheduled_cell_at(assignment.scheduled_path, step + 1)
            if current is None and nxt is None:
                continue
            if nxt is None:
                continue
            if current is None:
                active.add(nxt)
                continue
            if current == nxt:
                active.add(current)
                continue
            active.add(nxt)
        active.update(self._dispensed_reservoir_hold_cells(self.multi_assignments, step))
        return active

    def _multi_active_cells_for_step(self, step):
        return self._multi_active_cells_for_phase(step, 0.0)

    def _scheduled_expected_target_cells(self, assignments, step):
        return {
            cell
            for assignment in assignments
            for cell in (self._scheduled_cell_at(assignment.scheduled_path, step),)
            if cell in CORE_CELLS
        }

    def _loop_active_cells_for_phase(self, step, phase_progress):
        active = set()
        for assignment in self.loop_assignments:
            current = self._scheduled_cell_at(assignment.scheduled_path, step)
            nxt = self._scheduled_cell_at(assignment.scheduled_path, step + 1)
            if current is None and nxt is None:
                continue
            if nxt is None:
                continue
            if current == nxt:
                active.add(current)
                continue
            active.add(nxt)
        return active

    def _loop_active_cells_for_step(self, step):
        return self._loop_active_cells_for_phase(step, 0.0)

    def _check_multi_visual_health(self, max_steps):
        visible_indices = [idx for idx, visible in enumerate(self.multi_droplet_visible) if visible]
        visible_count = len(visible_indices)
        if visible_count == 0:
            return True

        detected_count = len(self.latest_detections)
        if detected_count < visible_count and self.multi_step_index < max_steps - 1:
            self._record_metric_dropout()
            now = time.monotonic()
            elapsed = now - self.last_detection_time
            hold_cells = set(self.detected_cells) or {
                self.sim_droplets[idx].cell for idx in visible_indices
            }
            if elapsed <= self.detection_timeout_s:
                self.log_feedback(
                    "多液滴视觉",
                    f"暂时检测到 {detected_count}/{visible_count} 滴，保持当前电极等待恢复 {elapsed:.2f}s",
                    key="multi_visual_dropout_wait",
                    interval_s=0.35,
                )
                return False
            self.log_feedback(
                "多液滴保护",
                f"应见 {visible_count} 滴，仅检测到 {detected_count} 滴，按疑似融合/遮挡处理并保持 {len(hold_cells)} 个电极",
                force=True,
            )
            self._pause_multi_with_hold(
                f"视觉检测到 {detected_count}/{visible_count} 滴，疑似融合或遮挡，已进入保护保持",
                hold_cells,
            )
            return False
        if detected_count >= visible_count:
            self.last_detection_time = time.monotonic()

        if visible_count == 1 and detected_count == 1:
            idx = visible_indices[0]
            detection = self.latest_detections[0]
            allowed = self._multi_allowed_cells_for_index(idx)
            if detection.cell not in allowed:
                allowed_text = " / ".join(self._cell_label(cell) for cell in allowed)
                self.log_feedback(
                    "多液滴纠偏",
                    f"D{idx + 1} 检测在 {self._cell_label(detection.cell)}，不在允许区 {allowed_text}，尝试单滴回正",
                    force=True,
                )
                return self._recover_single_visible_multi_droplet(idx, detection.cell)

        if visible_count > 1 and detected_count == visible_count:
            allowed = set()
            for idx in visible_indices:
                allowed.update(self._multi_allowed_cells_for_index(idx))
            off_cells = [cell for cell in self.detected_cells if cell not in allowed]
            if off_cells:
                off_text = " / ".join(self._cell_label(cell) for cell in off_cells)
                self.log_feedback(
                    "多液滴保护",
                    f"检测到偏离调度的液滴位置 {off_text}，多滴身份可能混淆，暂停调度",
                    force=True,
                )
                self._pause_multi_with_hold(
                    "检测到多液滴偏离调度轨迹，身份可能混淆，已进入保护保持",
                    set(off_cells) | {self.sim_droplets[idx].cell for idx in visible_indices},
                )
                return False
        return True

    def _multi_allowed_cells_for_index(self, idx):
        assignment = self.multi_assignments[idx]
        current = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
        nxt = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index + 1)
        return {cell for cell in (current, nxt) if cell is not None}

    def _recover_single_visible_multi_droplet(self, idx, detected_cell):
        assignment = self.multi_assignments[idx]
        if self.recovery_attempts >= self.max_recovery_attempts:
            self.log_feedback("多液滴纠偏", "纠偏次数达到上限，改为保护保持", force=True)
            self._pause_multi_with_hold("多液滴纠偏超过最大次数，已进入保护保持", {detected_cell})
            return False
        path = self.planner.plan(detected_cell, assignment.target, self._routing_obstacles(detected_cell, assignment.target) | self.faulty_electrodes)
        if len(path) < 2:
            self.log_feedback(
                "多液滴纠偏",
                f"D{assignment.droplet_id} 从 {self._cell_label(detected_cell)} 无法回到目标 {self._cell_label(assignment.target)}",
                force=True,
            )
            self._pause_multi_with_hold("多液滴跑偏后无法从检测位置回到目标，已进入保护保持", {detected_cell})
            return False

        self.recovery_attempts += 1
        if self.operation_metrics is not None:
            self.operation_metrics.record_deviation_replan()
        assignment.path = path
        assignment.scheduled_path = path
        self.multi_step_index = 0
        self.multi_step_start_time = time.monotonic()
        self.sim_droplets[idx].reset(detected_cell)
        self.multi_droplet_visible[idx] = True
        self.operation_paths = [item.path for item in self.multi_assignments]
        self._refresh_operation_path_cells()
        self._set_auto_active_cells(self._multi_active_cells_for_phase(0, 0.0))
        self.log_feedback(
            "多液滴纠偏",
            f"D{assignment.droplet_id} 已重建 {len(path) - 1} 步路径，并重置多液滴调度索引",
            force=True,
        )
        self.log(
            f"D{assignment.droplet_id} 跑偏：已从 {self._cell_label(detected_cell)} "
            f"重规划回 {self._cell_label(assignment.target)}"
        )
        return True

    def _pause_multi_with_hold(self, reason, hold_cells):
        self.auto_running = False
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        valid_hold = {cell for cell in hold_cells if cell is not None}
        if self.operation_metrics is not None and self.operation_metrics.planning_status not in {"unreachable", "protective_pause"}:
            self.operation_metrics.planning_status = "protective_pause"
        self._set_auto_active_cells(valid_hold)
        self.current_target_cell = None
        self.current_target_cell_b = None
        if valid_hold:
            hold_text = " / ".join(self._cell_label(cell) for cell in sorted(valid_hold))
            self.auto_status_label.config(text=f"闭环: 保护暂停，保持安全电极 {hold_text}", fg=self.colors["danger"])
            self.log_feedback("异常保护", f"保持电极：{hold_text}", force=True)
        else:
            self.auto_status_label.config(text="闭环: 保护暂停，等待人工复位或重新规划", fg=self.colors["danger"])
        self.log(reason)
        self._draw_matrix_canvas()

    @staticmethod
    def _scheduled_cell_at(path, step):
        if step < len(path):
            return path[step]
        return path[-1]

    @staticmethod
    def _position_in_cell(position, cell, tolerance=0.08):
        return math.hypot(position[0] - cell[0], position[1] - cell[1]) <= tolerance

    def _loop_multi_auto_step(self, now, dt_s):
        if not self.loop_assignments:
            self.stop_auto_control("多液滴循环任务为空")
            return

        if self.loop_wait_until:
            if now < self.loop_wait_until:
                self._set_auto_active_cells({assignment.source for assignment in self.loop_assignments})
                self._render_sim_camera_frame(force_display=False)
                return
            self.loop_wait_until = 0.0
            self.multi_step_start_time = now
            self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, 0.0))

        max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
        if self.multi_step_index >= max_steps - 1:
            self._handle_multi_loop_cycle_finished(now, max_steps)
            return

        next_step = self.multi_step_index + 1
        step_elapsed = now - self.multi_step_start_time
        phase_progress = min(1.0, max(0.0, step_elapsed / self.multi_step_duration_s))
        self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, phase_progress))

        for idx, assignment in enumerate(self.loop_assignments):
            current = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            target = self._scheduled_cell_at(assignment.scheduled_path, next_step)
            if current is None and target is None:
                self.multi_droplet_visible[idx] = False
                continue
            if target is None:
                self.multi_droplet_visible[idx] = False
                continue
            self.multi_droplet_visible[idx] = True
            if current is None or current == target:
                self.sim_droplets[idx].reset(target)
            else:
                self.sim_droplets[idx].update_towards(
                    target,
                    dt_s,
                    motion_profile=self._motion_profile(),
                    weak_fault_cells=self._weak_fault_cells_for_run(),
                )

        self._render_sim_camera_frame(force_display=False)
        expected_targets = self._scheduled_expected_target_cells(self.loop_assignments, next_step)
        visually_confirmed = self.multi_arrival_confirmation.observe(
            expected_targets,
            self.detected_cells,
            now,
        )
        if not expected_targets:
            visually_confirmed = step_elapsed >= self.multi_step_duration_s

        if visually_confirmed:
            for idx, assignment in enumerate(self.loop_assignments):
                cell = self._scheduled_cell_at(assignment.scheduled_path, next_step)
                if cell is None:
                    self.multi_droplet_visible[idx] = False
                else:
                    self.multi_droplet_visible[idx] = True
                    self.sim_droplets[idx].reset(cell)
            self.multi_step_index = next_step
            self.multi_step_start_time = now
            self.step_extension_used = False
            self.multi_arrival_confirmation.reset()
            self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, 0.0))
            self.log_feedback(
                "多液滴循环",
                f"调度步进 {self.multi_step_index}/{max_steps - 1}",
                key="multi_loop_step",
                interval_s=0.3,
            )
        elif step_elapsed >= self.step_timeout_s + self.step_extension_s:
            self._pause_multi_with_hold(
                f"多液滴循环等待 {step_elapsed:.1f}s 仍未通过稳定视觉确认，已保护保持",
                set(self.detected_cells),
            )
            return
        elif step_elapsed >= self.step_timeout_s and not self.step_extension_used:
            self.step_extension_used = True
            self.log_feedback(
                "多液滴循环",
                f"初始等待 {self.step_timeout_s:.1f}s 未全部稳定到达，延长 {self.step_extension_s:.1f}s",
                force=True,
            )

        if self.multi_step_index >= max_steps - 1:
            self._render_sim_camera_frame()
            self._handle_multi_loop_cycle_finished(now, max_steps)

    def _handle_multi_loop_cycle_finished(self, now, max_steps):
        self.loop_cycles_completed += 1
        target_cycles = self._sync_loop_cycles()
        if self.loop_cycles_completed >= target_cycles:
            self._mark_operation_success()
            self.stop_auto_control(f"多液滴循环完成 {self.loop_cycles_completed}/{target_cycles} 圈")
            return
        self.multi_step_index = 0
        self.multi_step_start_time = now
        self.step_extension_used = False
        self.multi_arrival_confirmation.reset()
        interval_s = self._sync_loop_interval_s()
        for idx, assignment in enumerate(self.loop_assignments):
            self.sim_droplets[idx].reset(assignment.source)
            self.multi_droplet_visible[idx] = True
        if interval_s > 0:
            self.loop_wait_until = now + interval_s
            self._set_auto_active_cells({assignment.source for assignment in self.loop_assignments})
            self.log_feedback(
                "多液滴循环",
                f"完成 {self.loop_cycles_completed}/{target_cycles} 圈，等待 {interval_s:.1f}s 后进入下一圈",
                force=True,
            )
            return
        self._set_auto_active_cells(self._loop_active_cells_for_phase(0, 0.0))
        self.log_feedback(
            "多液滴循环",
            f"完成 {self.loop_cycles_completed}/{target_cycles} 圈，重新进入下一圈（单圈 {max_steps - 1} 步）",
            force=True,
        )
