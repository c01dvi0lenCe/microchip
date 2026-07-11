"""Closed-loop state progression and recovery for DMF operations."""

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


class ClosedLoopControllerMixin:
    def _begin_current_step(self):
        if self.path_index >= len(self.path) - 1:
            self.stop_auto_control("到达目标")
            return
        current = self.path[self.path_index]
        target = self.path[self.path_index + 1]
        self.current_target_cell = target
        self.step_start_time = time.monotonic()
        self.step_extension_used = False
        self.arrival_confirmation.reset()
        self.log_feedback("状态机", f"释放当前电极 {self._cell_label(current)}", force=True)
        self._set_auto_active_cells({target}, stage="DRIVE_TARGET", action="drive")
        self.log_feedback("状态机", f"开启目标电极 {self._cell_label(target)}，等待视觉确认", force=True)
        self.log(f"闭环步进：关闭 {self._cell_label(current)}，开启 {self._cell_label(target)}")

    def _begin_merge_step(self):
        active = set()
        if self.path_index < len(self.path) - 1:
            self.current_target_cell = self.path[self.path_index + 1]
            active.add(self.current_target_cell)
        else:
            self.current_target_cell = self.goal_cell
            active.add(self.current_target_cell)

        if self.path_index_b < len(self.merge_path_b) - 1:
            self.current_target_cell_b = self.merge_path_b[self.path_index_b + 1]
            active.add(self.current_target_cell_b)
        else:
            self.current_target_cell_b = self.goal_cell
            active.add(self.current_target_cell_b)

        self.step_start_time = time.monotonic()
        self.step_extension_used = False
        self.arrival_confirmation.reset()
        self._set_auto_active_cells(active)
        self.log(
            "混合汇合步进："
            f"A->{self._cell_label(self.current_target_cell)} | "
            f"B->{self._cell_label(self.current_target_cell_b)}"
        )

    def _begin_mixing_phase(self):
        self.mixing_active = True
        self.mixing_index = 0
        self.sim_droplet.reset(self.goal_cell)
        self.sim_droplets = [self.sim_droplet]
        self.current_target_cell_b = None
        self.log_feedback("混合", "A/B 已到达混合点，进入四宫格混合循环", force=True)
        self._begin_mixing_step()

    def _begin_mixing_step(self):
        if self.mixing_index >= len(self.mixing_path) - 1:
            self._set_auto_active_cells({self.goal_cell})
            self._render_sim_camera_frame()
            self.stop_auto_control("混合完成，四宫格循环结束")
            return
        current = self.mixing_path[self.mixing_index]
        target = self.mixing_path[self.mixing_index + 1]
        self.current_target_cell = target
        self.step_start_time = time.monotonic()
        self.step_extension_used = False
        self.arrival_confirmation.reset()
        self.log_feedback("状态机", f"释放当前电极 {self._cell_label(current)}", force=True)
        self._set_auto_active_cells({target}, stage="DRIVE_TARGET", action="drive")
        self.log_feedback("状态机", f"开启目标电极 {self._cell_label(target)}，等待视觉确认", force=True)
        self.log(f"四宫格混合：关闭 {self._cell_label(current)}，开启 {self._cell_label(target)}")

    def _begin_split_operation(self):
        self.split_progress = 0.0
        self.split_attempts = 0
        self.split_retry_release_until = 0.0
        self.sim_droplet.reset(self.start_cell)
        self.sim_droplets = [self.sim_droplet]
        self.step_start_time = time.monotonic()
        self.last_detection_time = self.step_start_time
        self.arrival_confirmation.reset()
        self.current_target_cell = self.split_left_cell
        self.current_target_cell_b = self.split_right_cell
        self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
        self.log(
            "分裂拉伸：关闭源电极，开启 "
            f"{self._cell_label(self.split_left_cell)} / {self._cell_label(self.split_right_cell)}"
        )

    def _begin_loop_operation(self):
        self.loop_cycles_completed = 0
        self.loop_wait_until = 0.0
        if self.loop_assignments:
            self.multi_step_index = 0
            self.multi_step_start_time = time.monotonic()
            self.step_extension_used = False
            self.multi_arrival_confirmation.reset()
            self.sim_droplets = []
            self.multi_droplet_visible = []
            for assignment in self.loop_assignments:
                droplet = SimulatedDroplet(assignment.source, speed_cells_per_sec=2.5)
                start_cell = self._scheduled_cell_at(assignment.scheduled_path, 0)
                if start_cell is not None:
                    droplet.reset(start_cell)
                    self.multi_droplet_visible.append(True)
                else:
                    droplet.reset(assignment.source)
                    self.multi_droplet_visible.append(False)
                self.sim_droplets.append(droplet)
            max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
            self.current_target_cell = None
            self.current_target_cell_b = None
            self._set_auto_active_cells(self._loop_active_cells_for_phase(0, 0.0))
            self.log(f"多液滴循环启动：{len(self.loop_assignments)} 滴，调度步 {max_steps - 1}")
            return
        self._begin_current_step()

    def _auto_loop(self):
        if not self.auto_running:
            return

        now = time.monotonic()
        dt_s = min(0.12, max(0.0, now - self.last_auto_update_time))
        self.last_auto_update_time = now

        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            self._multi_auto_step(now, dt_s)
        elif operation == self.OP_MERGE:
            self._merge_auto_step(now, dt_s)
        elif operation == self.OP_SPLIT:
            self._split_auto_step(now, dt_s)
        elif operation == self.OP_LOOP:
            self._loop_auto_step(now, dt_s)
        else:
            self._move_auto_step(now, dt_s)

        if self.auto_running:
            self.auto_after_id = self.root.after(AUTO_LOOP_INTERVAL_MS, self._auto_loop)

    def _move_auto_step(self, now, dt_s):
        if self.current_target_cell is not None:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        detection = self._render_and_check_detection(now)
        if not self.auto_running:
            return
        if detection is not None:
            if self.current_target_cell is not None and not self._single_detection_on_track(detection):
                self.log_feedback(
                    "移动纠偏",
                    f"检测到 {self._cell_label(detection.cell)} 偏离当前/下一目标，准备从检测位置重规划",
                    force=True,
                )
                self._recover_single_droplet(detection.cell, now, "检测到液滴偏离计划电极")
                return
            if (
                self.current_target_cell is not None
                and self._single_target_stably_detected(detection, self.current_target_cell, now)
            ):
                self.log_feedback(
                    "移动",
                    f"视觉确认进入 {self._cell_label(self.current_target_cell)}，推进到下一步",
                    force=True,
                )
                self._handle_step_reached()

        if self.auto_running and self.current_target_cell is not None:
            if self._step_wait_expired(now):
                self.log_feedback(
                    "移动纠偏",
                    f"{self._cell_label(self.current_target_cell)} 未在 {self.step_timeout_s:.1f}s 内到达，触发超时重规划",
                    force=True,
                )
                self._handle_step_timeout(now)

    def _loop_auto_step(self, now, dt_s):
        if self.loop_assignments:
            self._loop_multi_auto_step(now, dt_s)
            return
        if self.loop_wait_until > 0.0:
            if now < self.loop_wait_until:
                self._render_sim_camera_frame(force_display=False)
                return
            self.loop_wait_until = 0.0
            self._begin_current_step()
            return
        if self.current_target_cell is not None:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        detection = self._render_and_check_detection(now)
        if not self.auto_running:
            return
        if detection is not None:
            if self.current_target_cell is not None and not self._single_detection_on_track(detection):
                self.log_feedback(
                    "循环纠偏",
                    f"检测到 {self._cell_label(detection.cell)} 偏离当前循环路径，进入保护停止",
                    force=True,
                )
                self.stop_auto_control("循环液滴偏离当前/下一目标电极")
                return
            if (
                self.current_target_cell is not None
                and self._single_target_stably_detected(detection, self.current_target_cell, now)
            ):
                self.log_feedback(
                    "循环",
                    f"视觉确认进入 {self._cell_label(self.current_target_cell)}，推进循环路径",
                    force=True,
                )
                self._handle_loop_step_reached()

        if self.auto_running and self.current_target_cell is not None:
            if self._step_wait_expired(now):
                self.log_feedback(
                    "循环纠偏",
                    f"{self._cell_label(self.current_target_cell)} 未在 {self.step_timeout_s:.1f}s 内到达，停止循环",
                    force=True,
                )
                self.stop_auto_control("循环单步超时")

    def _merge_auto_step(self, now, dt_s):
        if self.mixing_active:
            self._mixing_auto_step(now, dt_s)
            return

        if self.current_target_cell is not None and self.path_index < len(self.path) - 1:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )
        if self.current_target_cell_b is not None and self.path_index_b < len(self.merge_path_b) - 1:
            self.sim_droplet_b.update_towards(
                self.current_target_cell_b,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        self._render_and_check_detection(now)
        if not self.auto_running:
            return

        expected_targets = set()
        if self.path_index < len(self.path) - 1 and self.current_target_cell is not None:
            expected_targets.add(self.current_target_cell)
        if self.path_index_b < len(self.merge_path_b) - 1 and self.current_target_cell_b is not None:
            expected_targets.add(self.current_target_cell_b)
        advanced = self._merge_targets_stably_detected(expected_targets, now)
        if advanced:
            if self.path_index < len(self.path) - 1:
                self.path_index += 1
            if self.path_index_b < len(self.merge_path_b) - 1:
                self.path_index_b += 1

        done_a = self.path_index >= len(self.path) - 1
        done_b = self.path_index_b >= len(self.merge_path_b) - 1
        if done_a and done_b:
            self._begin_mixing_phase()
            return

        if advanced:
            self.log_feedback(
                "混合",
                f"两路当前目标均通过稳定视觉确认，推进 A:{self.path_index}/{len(self.path) - 1} B:{self.path_index_b}/{len(self.merge_path_b) - 1}",
                force=True,
            )
            self._begin_merge_step()
        elif self._step_wait_expired(now):
            self.log_feedback("混合纠偏", "混合汇合单步超时，进入停止保护", force=True)
            self.stop_auto_control("混合汇合单步超时")

    def _merge_targets_stably_detected(self, expected_targets, now):
        both_moving_to_same_target = (
            self.path_index < len(self.path) - 1
            and self.path_index_b < len(self.merge_path_b) - 1
            and self.current_target_cell is not None
            and self.current_target_cell == self.current_target_cell_b
        )
        if both_moving_to_same_target:
            detected = (
                set(expected_targets)
                if len(self.latest_detections) == 1
                and self.detected_cells == [self.current_target_cell]
                else set()
            )
        else:
            detected = set(self.detected_cells)
        return self.arrival_confirmation.observe(expected_targets, detected, now)

    def _mixing_auto_step(self, now, dt_s):
        if self.current_target_cell is not None and self.mixing_index < len(self.mixing_path) - 1:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        detection = self._render_and_check_detection(now)
        if not self.auto_running:
            return

        if (
            detection is not None
            and self.current_target_cell is not None
            and self._single_target_stably_detected(detection, self.current_target_cell, now)
        ):
            self.mixing_index += 1
            if self.mixing_index >= len(self.mixing_path) - 1:
                self.stop_auto_control("混合完成，四宫格循环结束")
                return
            self.log_feedback(
                "混合",
                f"四宫格循环进度 {self.mixing_index}/{len(self.mixing_path) - 1}",
                force=True,
            )
            self._begin_mixing_step()
        elif self._step_wait_expired(now):
            self.log_feedback("混合纠偏", "四宫格混合单步超时，进入停止保护", force=True)
            self.stop_auto_control("四宫格混合单步超时")

    def _split_auto_step(self, now, dt_s):
        if now < self.split_retry_release_until:
            self._set_auto_active_cells(set())
            self.sim_droplet.reset(self.start_cell)
            self.sim_droplets = [self.sim_droplet]
            self.log_feedback(
                "分裂纠偏",
                f"释放回缩阶段，源电极和两侧目标暂时关闭，{self.split_retry_release_until - now:.2f}s 后重拉",
                key="split_release_phase",
                interval_s=0.2,
            )
            self._render_and_check_detection(now)
            return

        if self.split_retry_release_until:
            self.split_retry_release_until = 0.0
            self.step_start_time = now
            self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
            self.log_feedback(
                "分裂纠偏",
                f"重新开启两侧目标电极，开始第 {self.split_attempts + 1} 次拉伸",
                force=True,
            )

        self.split_progress = min(1.0, self.split_progress + dt_s / self.split_stretch_duration_s)
        source_r, source_c = self.start_cell
        left_r, left_c = self.split_left_cell
        right_r, right_c = self.split_right_cell
        forced_failure_active = self.split_forced_failures_remaining > 0

        if self.split_progress < 0.55 or forced_failure_active:
            self.log_feedback(
                "分裂",
                f"拉伸阶段 progress={self.split_progress:.2f}，关闭源电极并保持左右目标电极",
                key="split_stretch_phase",
                interval_s=0.35,
            )
            self.sim_droplet.position = (
                source_r + (left_r + right_r - 2 * source_r) * 0.25 * self.split_progress,
                source_c + (left_c + right_c - 2 * source_c) * 0.25 * self.split_progress,
            )
            self.sim_droplets = [self.sim_droplet]
        else:
            self.log_feedback(
                "分裂",
                f"断裂确认阶段 progress={self.split_progress:.2f}，观察是否形成两个稳定子滴",
                key="split_break_phase",
                interval_s=0.35,
            )
            t = (self.split_progress - 0.55) / 0.45
            left_pos = (source_r + (left_r - source_r) * t, source_c + (left_c - source_c) * t)
            right_pos = (source_r + (right_r - source_r) * t, source_c + (right_c - source_c) * t)
            self.sim_droplet.position = left_pos
            self.sim_droplet_b.position = right_pos
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]

        self._render_and_check_detection(now)
        if not self.auto_running:
            return

        if self.split_progress >= 1.0:
            if self._split_success_detected(now):
                self.log_feedback("分裂", "视觉确认两个子滴稳定，关闭源电极并保持左右目标", force=True)
                self.sim_droplet.reset(self.split_left_cell)
                self.sim_droplet_b.reset(self.split_right_cell)
                self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
                self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
                self._render_sim_camera_frame()
                self.stop_auto_control("分裂完成，已生成两个子液滴")
                return
            if not forced_failure_active and now - self.step_start_time < self.split_stretch_duration_s + 0.35:
                self.log_feedback(
                    "分裂",
                    f"已形成两侧候选子滴，稳定帧 {self.arrival_confirmation.stable_count}/5，继续保持两侧电极",
                    key="split_stable_wait",
                    interval_s=0.2,
                )
                return
            self._handle_split_not_separated(now)
            return

        if now - self.step_start_time > self.step_timeout_s:
            self.log_feedback("分裂纠偏", "分裂过程超时，按未拉开处理并准备重拉", force=True)
            self._handle_split_not_separated(now)

    def _split_success_detected(self, now):
        if self.split_forced_failures_remaining > 0:
            self.split_forced_failures_remaining -= 1
            return False
        return self.arrival_confirmation.observe(
            {self.split_left_cell, self.split_right_cell},
            self.detected_cells,
            now,
        )

    def _handle_split_not_separated(self, now):
        self._record_metric_split_failure()
        if self.split_attempts >= self.max_split_attempts:
            self.log_feedback(
                "分裂纠偏",
                f"连续 {self.split_attempts + 1} 次未检测到两滴，停止保护",
                force=True,
            )
            self.stop_auto_control("分裂失败：未检测到两个稳定子滴")
            return

        self.split_attempts += 1
        self.split_progress = 0.0
        self.step_start_time = now
        self.arrival_confirmation.reset()
        self.split_retry_release_until = now + self.split_relax_duration_s
        self.sim_droplet.reset(self.start_cell)
        self.sim_droplets = [self.sim_droplet]
        self._set_auto_active_cells(set())
        self.log_feedback(
            "分裂纠偏",
            f"未检测到两个子滴，先释放回缩 {self.split_relax_duration_s:.2f}s，随后重拉 "
            f"({self.split_attempts}/{self.max_split_attempts})",
            force=True,
        )
        self._draw_matrix_canvas()

    def _render_and_check_detection(self, now):
        hide_droplet = now < self.drop_frame_until
        detection = self._render_sim_camera_frame(hide_droplet=hide_droplet, force_display=False)
        if detection is not None:
            self.last_detection_time = now
            return detection
        self._record_metric_dropout()
        elapsed = now - self.last_detection_time
        self.log_feedback(
            "视觉",
            f"检测暂时丢失 {elapsed:.2f}s，保持当前激活电极等待恢复",
            key="vision_dropout_wait",
            interval_s=0.25,
        )
        if elapsed > self.detection_timeout_s:
            self.log_feedback("视觉", "检测丢失超过阈值，停止闭环并关闭自动推进", force=True)
            self.stop_auto_control(f"检测丢失超过 {self.detection_timeout_s:.1f} s")
        return None

    def _single_target_stably_detected(self, detection, target, now):
        detected = {target} if detection_in_cell(detection, target) else set()
        confirmed = self.arrival_confirmation.observe({target}, detected, now)
        if not confirmed and detected:
            self.log_feedback(
                "视觉确认",
                f"{self._cell_label(target)} 稳定帧 {self.arrival_confirmation.stable_count}/5，继续保持目标电极",
                key="arrival_stability",
                interval_s=0.2,
            )
        return confirmed

    def _step_wait_expired(self, now):
        elapsed = now - self.step_start_time
        if self.step_replanned:
            return elapsed >= self.step_timeout_s
        if elapsed >= self.step_timeout_s + self.step_extension_s:
            return True
        if elapsed >= self.step_timeout_s and not self.step_extension_used:
            self.step_extension_used = True
            self.log_feedback(
                "状态机",
                f"初始等待 {self.step_timeout_s:.1f}s 未稳定到达，延长驱动 {self.step_extension_s:.1f}s",
                force=True,
            )
        return False

    def _single_detection_on_track(self, detection):
        expected = []
        if self.path_index < len(self.path):
            expected.append(self.path[self.path_index])
        if self.current_target_cell is not None:
            expected.append(self.current_target_cell)
        return any(detection_in_cell(detection, cell, tolerance_cells=0.55) for cell in expected)

    def _recover_single_droplet(self, detected_cell, now, reason):
        if self.recovery_attempts >= self.max_recovery_attempts:
            self.log_feedback("移动纠偏", "纠偏次数已达上限，进入保护停止", force=True)
            self.stop_auto_control(f"{reason}，超过最大纠偏次数")
            return
        new_path = self.planner.plan(detected_cell, self.goal_cell, self._routing_obstacles(detected_cell, self.goal_cell))
        if len(new_path) < 2:
            self.log_feedback(
                "移动纠偏",
                f"从 {self._cell_label(detected_cell)} 到目标无可行回正路径",
                force=True,
            )
            self.stop_auto_control(f"{reason}，从检测位置无法回到目标")
            return
        self.recovery_attempts += 1
        self.sim_droplet.reset(detected_cell)
        self.path = new_path
        self._record_metric_replan()
        self.operation_paths = [new_path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.merge_path_b = []
        self.current_target_cell = new_path[1]
        self.current_target_cell_b = None
        self.step_replanned = True
        self.step_start_time = now
        self.step_extension_used = False
        self.arrival_confirmation.reset()
        self._set_auto_active_cells({self.current_target_cell})
        self.log_feedback(
            "移动纠偏",
            f"新路径 {len(new_path) - 1} 步，关闭检测位置并开启 {self._cell_label(self.current_target_cell)}",
            force=True,
        )
        self.log(
            f"{reason}：已从 {self._cell_label(detected_cell)} "
            f"重新规划并拉回，纠偏 {self.recovery_attempts}/{self.max_recovery_attempts}"
        )
        self._draw_matrix_canvas()

    def _handle_step_reached(self):
        self._record_step_event(
            "VISION_CONFIRM",
            target_cell=self.current_target_cell,
            detected_cell=self.detected_cell,
            action="advance",
        )
        if self.path_index + 1 >= len(self.path) - 1:
            self.stop_auto_control("到达目标")
            return
        self.path_index += 1
        self.step_replanned = False
        self.recovery_attempts = 0
        self._begin_current_step()

    def _handle_loop_step_reached(self):
        self._record_step_event(
            "VISION_CONFIRM",
            target_cell=self.current_target_cell,
            detected_cell=self.detected_cell,
            action="loop_advance",
        )
        if not self.path:
            self.stop_auto_control("循环路径为空")
            return
        if self.path_index + 1 >= len(self.path) - 1:
            self.loop_cycles_completed += 1
            target_cycles = self._sync_loop_cycles()
            if self.loop_cycles_completed >= target_cycles:
                self.stop_auto_control(f"循环完成 {self.loop_cycles_completed}/{target_cycles} 圈")
                return
            self.path_index = 0
            self.step_replanned = False
            self.recovery_attempts = 0
            self.sim_droplet.reset(self.path[0])
            interval_s = self._sync_loop_interval_s()
            if interval_s > 0:
                self.current_target_cell = None
                self.loop_wait_until = time.monotonic() + interval_s
                self._set_auto_active_cells({self.path[0]})
                self.log(f"循环完成 {self.loop_cycles_completed}/{target_cycles} 圈，等待 {interval_s:.1f}s 后进入下一圈")
                return
            self.log(f"循环完成 {self.loop_cycles_completed}/{target_cycles} 圈，重新进入下一圈")
            self._begin_current_step()
            return
        self.path_index += 1
        self.step_replanned = False
        self.recovery_attempts = 0
        self._begin_current_step()

    def _handle_step_timeout(self, now):
        self._record_metric_stall()
        if self.step_replanned:
            self.log_feedback("移动纠偏", "重规划后的单步仍超时，停止自动控制", force=True)
            self.stop_auto_control("单步超时，重规划后仍未到达")
            return

        current = self.detected_cell or self.sim_droplet.cell
        if current == self.goal_cell:
            self.log_feedback("移动", "超时检查时液滴已在目标电极，结束任务", force=True)
            self.stop_auto_control("到达目标")
            return

        new_path = self.planner.plan(current, self.goal_cell, self._routing_obstacles(current, self.goal_cell))
        if len(new_path) < 2:
            self.log_feedback(
                "移动纠偏",
                f"超时后从 {self._cell_label(current)} 无法重新规划到目标",
                force=True,
            )
            self.stop_auto_control("单步超时且无法重规划")
            return

        self.path = new_path
        self.operation_paths = [new_path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.current_target_cell = new_path[1]
        self.current_target_cell_b = None
        self.step_replanned = True
        self.step_start_time = now
        self.step_extension_used = False
        self.arrival_confirmation.reset()
        self._set_auto_active_cells({self.current_target_cell})
        self.log_feedback(
            "移动纠偏",
            f"超时后生成新路径 {len(new_path) - 1} 步，下一目标 {self._cell_label(self.current_target_cell)}",
            force=True,
        )
        self.log(f"单步超时，已从 {self._cell_label(current)} 重规划")
        self._draw_matrix_canvas()

    def _set_auto_active_cells(self, cells, stage="ELECTRODE_SWITCH", action="switch"):
        old_cells = set(self.active_auto_cells)
        new_cells = set(cells)
        off_cells = old_cells - new_cells
        on_cells = new_cells - old_cells
        changes = {
            electrode_id(cell[0], cell[1], self.cols): 0
            for cell in off_cells
        }
        changes.update(
            {
                electrode_id(cell[0], cell[1], self.cols): 1
                for cell in on_cells
            }
        )
        if changes and not self._submit_auto_electrode_changes(changes):
            return False

        for cell in off_cells:
            eid = electrode_id(cell[0], cell[1], self.cols)
            self.update_ui_only(eid, 0)
            if self.is_simulation_mode():
                self.send_command(HardwareProtocol.set_electrode(eid, 0), log_send=False)
        for cell in on_cells:
            eid = electrode_id(cell[0], cell[1], self.cols)
            self.update_ui_only(eid, 1)
            if self.is_simulation_mode():
                self.send_command(HardwareProtocol.set_electrode(eid, 1), log_send=False)
        self.active_auto_cells = new_cells
        if on_cells or off_cells:
            target_cell = sorted(on_cells)[0] if on_cells else None
            self._record_step_event(
                stage,
                target_cell=target_cell,
                detected_cell=self.detected_cell,
                on_cells=on_cells,
                off_cells=off_cells,
                action=action,
            )
            self.log_feedback(
                "电极开关",
                f"开启 {len(on_cells)} 个，关闭 {len(off_cells)} 个，当前保持 {len(new_cells)} 个",
                key="auto_switch_summary",
                interval_s=0.2,
            )
        return True
