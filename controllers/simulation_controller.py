"""Simulation profiles, manual droplets, metrics, and visual context."""

from __future__ import annotations

from .common import (
    AUTO_LOOP_INTERVAL_MS,
    CORE_CELLS,
    LAYOUT_CELLS,
    MotionProfile,
    OperationMetrics,
    Path,
    RESERVOIR_CONNECTIONS,
    SimulatedDroplet,
    StepEvent,
    VisionNoiseProfile,
    csv,
    filedialog,
    math,
    time,
)


class SimulationControllerMixin:
    def _motion_profile(self):
        mode = self.motion_profile_var.get()
        fault_mode = self.fault_mode_var.get()
        if mode == "困难":
            stuck = 0.18
            jitter = 0.07
            delay = 0.10
            split_fail = 0.35
        elif mode == "常规":
            stuck = 0.04
            jitter = 0.03
            delay = 0.04
            split_fail = 0.12
        else:
            stuck = 0.0
            jitter = 0.0
            delay = 0.0
            split_fail = 0.0
        if fault_mode == "随机卡滞":
            stuck = max(stuck, 0.25)
        return MotionProfile(
            name=mode,
            response_delay_s=delay,
            speed_scale=1.0,
            position_jitter_cells=jitter,
            stuck_probability=stuck,
            overshoot_probability=0.03 if mode == "困难" else 0.0,
            split_failure_probability=split_fail,
        )

    def _vision_noise_profile(self):
        mode = self.vision_noise_var.get()
        if mode == "强噪声":
            return VisionNoiseProfile(name=mode, drop_frame_rate=1.0, jitter_cells=0.18, low_contrast=0.35)
        if mode == "轻微":
            return VisionNoiseProfile(name=mode, drop_frame_rate=0.05, jitter_cells=0.06, low_contrast=0.12)
        return VisionNoiseProfile(name=mode)

    def _weak_fault_cells_for_run(self):
        if self.fault_mode_var.get() == "指定弱故障电极":
            return set(self.weak_fault_cells or self.obstacle_cells)
        return set()

    def _new_operation_metrics(self, operation=None):
        return OperationMetrics(operation=operation or self.operation_var.get())

    def _begin_operation_metrics(self):
        self.operation_metrics = self._new_operation_metrics(self.operation_var.get())
        self.operation_metrics_history.append(self.operation_metrics)
        self._refresh_metrics_label()

    def _record_step_event(self, stage, target_cell=None, detected_cell=None, on_cells=(), off_cells=(), action=""):
        if self.operation_metrics is None:
            return
        duration_s = 0.0
        if self.step_start_time:
            duration_s = max(0.0, time.monotonic() - self.step_start_time)
        self.operation_metrics.record_event(
            StepEvent(
                stage=stage,
                target_cell=target_cell,
                detected_cell=detected_cell,
                on_cells=tuple(sorted(on_cells)),
                off_cells=tuple(sorted(off_cells)),
                duration_s=duration_s,
                action=action,
            )
        )
        self._refresh_metrics_label()

    def _record_metric_replan(self):
        if self.operation_metrics is not None:
            self.operation_metrics.record_replan()
            self._refresh_metrics_label()

    def _record_metric_dropout(self):
        if self.operation_metrics is not None:
            self.operation_metrics.record_dropout()
            self._refresh_metrics_label()

    def _record_metric_stall(self):
        if self.operation_metrics is not None:
            self.operation_metrics.record_stall()
            self._refresh_metrics_label()

    def _record_metric_split_failure(self):
        if self.operation_metrics is not None:
            self.operation_metrics.record_split_failure()
            self._refresh_metrics_label()

    def _refresh_metrics_label(self):
        if not hasattr(self, "metrics_label"):
            return
        metrics = self.operation_metrics
        if metrics is None:
            self.metrics_label.config(text="指标: 0 步 / 0 次重规划")
            return
        self.metrics_label.config(
            text=f"指标: {metrics.total_steps} 步 / {metrics.replan_count} 次重规划 / {metrics.dropout_count} 次丢帧"
        )

    def clear_metrics(self):
        self.operation_metrics = None
        self.operation_metrics_history.clear()
        self._refresh_metrics_label()
        self.log("仿真指标已清空")

    def export_metrics_csv(self, path=None):
        if path is None:
            selected = filedialog.asksaveasfilename(
                title="导出仿真指标",
                defaultextension=".csv",
                filetypes=(("CSV", "*.csv"), ("All files", "*.*")),
            )
            if not selected:
                return False
            path = selected
        path = Path(path)
        rows = [metrics.to_csv_row() for metrics in self.operation_metrics_history]
        if self.operation_metrics is not None and self.operation_metrics not in self.operation_metrics_history:
            rows.append(self.operation_metrics.to_csv_row())
        fieldnames = [
            "operation",
            "success",
            "total_steps",
            "average_step_time_s",
            "replan_count",
            "dropout_count",
            "stall_count",
            "split_failure_count",
            "electrode_switch_count",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self.log(f"仿真指标已导出: {path}")
        return True

    def _reset_droplets_for_operation(self):
        operation = self.operation_var.get()
        self.split_progress = 0.0
        self.split_attempts = 0
        self.split_retry_release_until = 0.0
        if operation == self.OP_MULTI:
            if self.multi_assignments:
                self.sim_droplets = [
                    SimulatedDroplet(assignment.source, speed_cells_per_sec=3.2)
                    for assignment in self.multi_assignments
                ]
                self.multi_droplet_visible = [
                    self._multi_cell_is_visible_droplet(
                        assignment,
                        self._scheduled_cell_at(assignment.scheduled_path, 0),
                    )
                    for assignment in self.multi_assignments
                ]
            else:
                self.sim_droplets = []
                self.multi_droplet_visible = []
            return
        if operation == self.OP_LOOP and self.loop_routes:
            self.sim_droplets = [
                SimulatedDroplet(route["source"], speed_cells_per_sec=2.5)
                for route in self.loop_routes
            ]
            if len(self.sim_droplets) == 1:
                self.sim_droplet = self.sim_droplets[0]
            return
        self.sim_droplet.reset(self.start_cell)
        if operation == self.OP_MERGE:
            self.sim_droplet_b.reset(self.secondary_cell)
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
        else:
            self.sim_droplets = [self.sim_droplet]

    def _droplet_positions(self):
        if self.operation_var.get() == self.OP_MULTI:
            return [
                droplet.position
                for droplet, visible in zip(self.sim_droplets, self.multi_droplet_visible)
                if visible
            ]
        return [droplet.position for droplet in self.sim_droplets]

    def _droplet_marker_colors(self):
        return (self.colors["droplet_a"], self.colors["droplet_b"])

    def _hex_to_rgb(self, color):
        color = color.lstrip("#")
        return tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))

    def _camera_droplet_colors(self):
        if self.operation_var.get() == self.OP_MULTI:
            if not self.multi_assignments:
                count = len(self.initial_droplet_cells)
                return [
                    self._hex_to_rgb(self.multi_droplet_colors[idx % len(self.multi_droplet_colors)])
                    for idx in range(count)
                ]
            return [
                self._hex_to_rgb(self.multi_droplet_colors[idx % len(self.multi_droplet_colors)])
                for idx, visible in enumerate(self.multi_droplet_visible)
                if visible
            ]
        if self.operation_var.get() == self.OP_LOOP and len(self.sim_droplets) > 1:
            return [
                self._hex_to_rgb(self.multi_droplet_colors[idx % len(self.multi_droplet_colors)])
                for idx, _droplet in enumerate(self.sim_droplets)
            ]
        marker_colors = self._droplet_marker_colors()
        return [
            self._hex_to_rgb(marker_colors[idx % len(marker_colors)])
            for idx, _droplet in enumerate(self.sim_droplets)
        ]

    def _display_droplet_shapes(self, manual_view=False):
        positions = self._manual_droplet_positions() if manual_view else self._display_droplet_positions()
        operation = self.operation_var.get()
        if not positions:
            return []
        if operation == self.OP_MERGE and (self.mixing_active or self.mixing_index > 0):
            return ["horizontal_ellipse"] * len(positions)
        if (
            operation == self.OP_SPLIT
            and len(self.sim_droplets) >= 2
            and self.split_progress >= 0.55
        ):
            return ["horizontal_ellipse"] * len(positions)
        return ["circle"] * len(positions)

    def _display_droplet_positions(self):
        positions = self._droplet_positions()
        if self.operation_var.get() == self.OP_MULTI and not positions and not self.multi_assignments:
            return list(sorted(self.initial_droplet_cells))
        if self.operation_var.get() == self.OP_LOOP and self.loop_routes and not positions:
            return [route["source"] for route in self.loop_routes]
        return positions

    def set_manual_droplet(self, cell):
        if cell not in LAYOUT_CELLS:
            self.log("手动液滴位置需要落在电极或储液池上")
            return False
        existing = next((droplet for droplet in self.manual_droplets if droplet.cell == cell), None)
        if existing is not None:
            self.manual_droplets.remove(existing)
            self._sync_manual_droplet_alias()
            self.log(f"手动仿真液滴已移除 -> {self._cell_label(cell)}")
            self._draw_matrix_canvas()
            if self.is_simulation_mode():
                self._render_sim_camera_frame()
            return True
        self.manual_droplets.append(SimulatedDroplet(cell, speed_cells_per_sec=3.0))
        self._sync_manual_droplet_alias()
        self.manual_last_update_time = time.monotonic()
        self.log(f"手动仿真液滴 {len(self.manual_droplets)} -> {self._cell_label(cell)}")
        self._draw_matrix_canvas()
        if self.is_simulation_mode():
            self._render_sim_camera_frame()
        return True

    def clear_manual_droplet(self):
        if not self.manual_droplets:
            return
        self.manual_droplets.clear()
        self.manual_droplet = None
        self.log("手动仿真液滴已清空")
        self._draw_matrix_canvas()
        if self.is_simulation_mode():
            self._render_sim_camera_frame()

    def _sync_manual_droplet_alias(self):
        self.manual_droplet = self.manual_droplets[0] if self.manual_droplets else None

    def _manual_droplet_positions(self):
        return [droplet.position for droplet in self.manual_droplets]

    def _manual_neighbor_cells(self, cell):
        neighbors = set()
        row, col = cell
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            candidate = (row + dr, col + dc)
            if candidate in CORE_CELLS and cell in CORE_CELLS:
                neighbors.add(candidate)
        for source, target in RESERVOIR_CONNECTIONS.items():
            if source == cell:
                neighbors.add(target)
            if target == cell:
                neighbors.add(source)
        return neighbors

    def _manual_active_target(self, droplet, blocked_cells=()):
        current = droplet.cell
        blocked = set(blocked_cells)
        if current in self._active_cells() and current not in self.obstacle_cells and current not in blocked:
            distance_to_center = math.hypot(droplet.position[0] - current[0], droplet.position[1] - current[1])
            if distance_to_center > 0.04:
                return current
        candidates = [
            cell
            for cell in self._manual_neighbor_cells(current)
            if cell in self._active_cells() and cell not in self.obstacle_cells and cell not in blocked
        ]
        if not candidates:
            return None
        pos_row, pos_col = droplet.position
        return min(candidates, key=lambda cell: (math.hypot(cell[0] - pos_row, cell[1] - pos_col), cell))

    def _update_manual_droplet_motion(self, dt_s):
        if not self.manual_droplets or self.auto_running or not self.is_simulation_mode():
            return False
        current_cells = {droplet.cell for droplet in self.manual_droplets}
        reserved_targets = set()
        moved = False
        for droplet in self.manual_droplets:
            blocked = (current_cells - {droplet.cell}) | reserved_targets
            target = self._manual_active_target(droplet, blocked)
            if target is None:
                continue
            before = droplet.position
            after = droplet.update_towards(target, dt_s)
            if math.hypot(after[0] - target[0], after[1] - target[1]) <= 0.04:
                droplet.reset(target)
            moved = moved or after != before
            reserved_targets.add(target)
        self._sync_manual_droplet_alias()
        return moved

    def _schedule_manual_simulation_loop(self):
        if self.manual_after_id is None:
            self.manual_after_id = self.root.after(AUTO_LOOP_INTERVAL_MS, self._manual_simulation_loop)

    def _manual_simulation_loop(self):
        self.manual_after_id = None
        now = time.monotonic()
        dt_s = min(0.25, max(0.0, now - self.manual_last_update_time))
        self.manual_last_update_time = now
        if self._update_manual_droplet_motion(dt_s):
            self._draw_matrix_canvas()
            self._render_sim_camera_frame(force_display=False)
        self._schedule_manual_simulation_loop()

    def _camera_render_context(self, manual_view=None):
        if manual_view is None:
            manual_view = self._is_manual_page_selected() and not self.auto_running
        if manual_view:
            positions = self._manual_droplet_positions()
            return {
                "droplet_position": positions[0] if positions else self.sim_droplet.position,
                "obstacles": self.obstacle_cells,
                "path": set(),
                "active_cells": self._active_cells(),
                "loaded_reservoirs": self.loaded_reservoirs,
                "target_shape_cells": set(),
                "target_cells": set(),
                "start_cell": None,
                "goal_cell": None,
                "hide_droplet": not positions,
                "droplet_positions": positions,
                "droplet_colors": [
                    self._hex_to_rgb(self.multi_droplet_colors[idx % len(self.multi_droplet_colors)])
                    for idx, _position in enumerate(positions)
                ],
                "droplet_shapes": self._display_droplet_shapes(manual_view=True),
            }

        operation = self.operation_var.get()
        visible_positions = self._display_droplet_positions()
        show_setup_markers = self._show_setup_markers()
        preview_path_cells = self.operation_path_cells
        if operation == self.OP_LOOP and not preview_path_cells:
            preview_path_cells = {
                cell
                for path in self._loop_preview_paths()
                for cell in path
            }
        return {
            "droplet_position": visible_positions[0] if visible_positions else self.sim_droplet.position,
            "obstacles": self.obstacle_cells,
            "path": preview_path_cells,
            "active_cells": self._active_cells(),
            "loaded_reservoirs": self.loaded_reservoirs,
            "target_shape_cells": self.target_shape_cells,
            "target_cells": self.multi_targets,
            "start_cell": self.start_cell if show_setup_markers and operation != self.OP_MULTI else None,
            "goal_cell": self.goal_cell if show_setup_markers and operation != self.OP_MULTI else None,
            "hide_droplet": False,
            "droplet_positions": visible_positions,
            "droplet_colors": self._camera_droplet_colors(),
            "droplet_shapes": self._display_droplet_shapes(manual_view=False),
        }

    def _show_setup_markers(self):
        if self.auto_running:
            return False
        if self.mixing_active or self.mixing_index > 0:
            return False
        if self.path_index > 0 or self.path_index_b > 0:
            return False
        return True

    def _clear_planned_operation(self):
        self.path = []
        self.merge_path_b = []
        self.mixing_path = []
        self.mixing_index = 0
        self.mixing_active = False
        self.operation_paths = []
        self.operation_path_cells = set()
        self.path_index = 0
        self.path_index_b = 0
        self.current_target_cell = None
        self.current_target_cell_b = None
        self.multi_assignments = []
        self.multi_targets = []
        self.multi_droplet_visible = []
        self.multi_step_index = 0
        self.loop_assignments = []
        self.loop_cycles_completed = 0
        self.detected_position = None
        self.detected_positions = []
        self.detected_cell = None
        self.detected_cells = []
        self.latest_detections = []
        self.recovery_attempts = 0
