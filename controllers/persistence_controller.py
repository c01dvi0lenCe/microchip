"""Undo snapshots and import/export of task presets."""

from __future__ import annotations

from .common import Path, filedialog, grid_polyline_cells, json, messagebox, time


class PersistenceControllerMixin:
    def save_settings_preset(self, path=None):
        if path is None:
            self.preset_dir.mkdir(parents=True, exist_ok=True)
            selected = filedialog.asksaveasfilename(
                title="保存仿真设置",
                initialdir=str(self.preset_dir),
                initialfile="dmf_preset.json",
                defaultextension=".json",
                filetypes=(("JSON", "*.json"), ("All files", "*.*")),
            )
            if not selected:
                return False
            path = selected
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.PRESET_SCHEMA,
            "version": self.PRESET_VERSION,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "operation": self.operation_var.get(),
            "tool": self.tool_var.get(),
            "mode": self.mode_var.get(),
            "motion_profile": self.motion_profile_var.get(),
            "vision_noise": self.vision_noise_var.get(),
            "fault_mode": self.fault_mode_var.get(),
            "settings": self._serialize_settings_snapshot(self._settings_snapshot()),
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        self.log(f"设置已保存 -> {path}")
        return True

    def load_settings_preset(self, path=None):
        if self.auto_running:
            self.log("闭环运行中，无法导入设置；请先暂停或停止")
            return False
        interactive = path is None
        if path is None:
            self.preset_dir.mkdir(parents=True, exist_ok=True)
            selected = filedialog.askopenfilename(
                title="导入仿真设置",
                initialdir=str(self.preset_dir),
                filetypes=(("JSON", "*.json"), ("All files", "*.*")),
            )
            if not selected:
                return False
            path = selected
        path = Path(path)
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            operation, tool, snapshot = self._settings_preset_from_payload(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.log(f"导入设置失败：{exc}")
            if interactive:
                messagebox.showerror("导入失败", str(exc))
            return False

        self._push_undo_snapshot()
        self.operation_var.set(operation)
        self.tool_var.set(tool)
        if payload.get("mode"):
            self.mode_var.set(payload["mode"])
        if payload.get("motion_profile"):
            self.motion_profile_var.set(payload["motion_profile"])
        if payload.get("vision_noise"):
            self.vision_noise_var.set(payload["vision_noise"])
        if payload.get("fault_mode"):
            self.fault_mode_var.set(payload["fault_mode"])
        self._restore_settings_snapshot(snapshot)
        self._update_tool_options()
        self._update_operation_specific_controls()
        self._refresh_matrix_legend(manual=False)
        self.auto_status_label.config(text=f"闭环: {self.operation_var.get()}待机", fg=self.colors["muted"])
        self.log(f"设置已导入 <- {path}")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return True

    def _settings_preset_from_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("设置文件格式不正确")
        if payload.get("schema") != self.PRESET_SCHEMA:
            raise ValueError("不是数字微流控视觉平台的设置文件")
        if payload.get("version") != self.PRESET_VERSION:
            raise ValueError(f"不支持的设置版本：{payload.get('version')}")
        operation = payload.get("operation", self.OP_MOVE)
        valid_operations = {self.OP_MOVE, self.OP_MERGE, self.OP_SPLIT, self.OP_MULTI, self.OP_LOOP}
        if operation not in valid_operations:
            raise ValueError(f"不支持的操作类型：{operation}")
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("设置文件缺少 settings 字段")
        snapshot = self._deserialize_settings_snapshot(settings)
        tool = payload.get("tool") or self._tool_options_for_operation()[0]
        previous_operation = self.operation_var.get()
        self.operation_var.set(operation)
        try:
            valid_tools = self._tool_options_for_operation()
        finally:
            self.operation_var.set(previous_operation)
        if tool not in valid_tools:
            tool = valid_tools[0]
        return operation, tool, snapshot

    def _serialize_cell(self, cell):
        if cell is None:
            return None
        return [int(cell[0]), int(cell[1])]

    def _deserialize_cell(self, value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"非法电极坐标：{value}")
        return (int(value[0]), int(value[1]))

    def _serialize_cells(self, cells):
        return [self._serialize_cell(cell) for cell in sorted(cells)]

    def _deserialize_cells(self, values):
        if values is None:
            return []
        if not isinstance(values, list):
            raise ValueError(f"非法电极坐标列表：{values}")
        return [self._deserialize_cell(value) for value in values]

    def _serialize_settings_snapshot(self, snapshot):
        return {
            "start_cell": self._serialize_cell(snapshot["start_cell"]),
            "goal_cell": self._serialize_cell(snapshot["goal_cell"]),
            "secondary_cell": self._serialize_cell(snapshot["secondary_cell"]),
            "split_left_cell": self._serialize_cell(snapshot["split_left_cell"]),
            "split_right_cell": self._serialize_cell(snapshot["split_right_cell"]),
            "loaded_reservoirs": self._serialize_cells(snapshot["loaded_reservoirs"]),
            "initial_droplet_cells": self._serialize_cells(snapshot["initial_droplet_cells"]),
            "obstacle_cells": self._serialize_cells(snapshot["obstacle_cells"]),
            "target_shape_points": [self._serialize_cell(cell) for cell in snapshot["target_shape_points"]],
            "target_shape_cells": [self._serialize_cell(cell) for cell in snapshot["target_shape_cells"]],
            "loop_path_points": [self._serialize_cell(cell) for cell in snapshot["loop_path_points"]],
            "loop_path_cells": [self._serialize_cell(cell) for cell in snapshot["loop_path_cells"]],
            "loop_routes": [
                {
                    "source": self._serialize_cell(route["source"]),
                    "path_points": [self._serialize_cell(cell) for cell in route["path_points"]],
                    "path": [self._serialize_cell(cell) for cell in route.get("path", [])],
                }
                for route in snapshot["loop_routes"]
            ],
            "loop_route_index": snapshot["loop_route_index"],
            "loop_cycles": int(snapshot["loop_cycles"]),
            "loop_interval_s": float(snapshot["loop_interval_s"]),
            "mixing_cycles": int(snapshot["mixing_cycles"]),
        }

    def _deserialize_settings_snapshot(self, data):
        snapshot = {
            "start_cell": self._deserialize_cell(data.get("start_cell", self.start_cell)),
            "goal_cell": self._deserialize_cell(data.get("goal_cell", self.goal_cell)),
            "secondary_cell": self._deserialize_cell(data.get("secondary_cell", self.secondary_cell)),
            "split_left_cell": self._deserialize_cell(data.get("split_left_cell", self.split_left_cell)),
            "split_right_cell": self._deserialize_cell(data.get("split_right_cell", self.split_right_cell)),
            "loaded_reservoirs": set(self._deserialize_cells(data.get("loaded_reservoirs", []))),
            "initial_droplet_cells": set(self._deserialize_cells(data.get("initial_droplet_cells", []))),
            "obstacle_cells": set(self._deserialize_cells(data.get("obstacle_cells", []))),
            "target_shape_points": self._deserialize_cells(data.get("target_shape_points", [])),
            "target_shape_cells": self._deserialize_cells(data.get("target_shape_cells", [])),
            "loop_path_points": self._deserialize_cells(data.get("loop_path_points", [])),
            "loop_path_cells": self._deserialize_cells(data.get("loop_path_cells", [])),
            "loop_routes": [
                {
                    "source": self._deserialize_cell(route["source"]),
                    "path_points": self._deserialize_cells(route.get("path_points", [])),
                    "path": self._deserialize_cells(route.get("path", [])),
                }
                for route in data.get("loop_routes", [])
            ],
            "loop_route_index": data.get("loop_route_index"),
            "loop_cycles": int(data.get("loop_cycles", self.loop_cycles)),
            "loop_interval_s": float(data.get("loop_interval_s", self.loop_interval_s)),
            "mixing_cycles": int(data.get("mixing_cycles", self.mixing_cycles)),
        }
        if not snapshot["target_shape_cells"] and snapshot["target_shape_points"]:
            cells = []
            for cell in snapshot["target_shape_points"]:
                if cells:
                    cells.extend(grid_polyline_cells(cells[-1], cell)[1:])
                else:
                    cells.append(cell)
            snapshot["target_shape_cells"] = cells
        return snapshot

    def _settings_snapshot(self):
        return {
            "start_cell": self.start_cell,
            "goal_cell": self.goal_cell,
            "secondary_cell": self.secondary_cell,
            "split_left_cell": self.split_left_cell,
            "split_right_cell": self.split_right_cell,
            "loaded_reservoirs": set(self.loaded_reservoirs),
            "initial_droplet_cells": set(self.initial_droplet_cells),
            "obstacle_cells": set(self.obstacle_cells),
            "target_shape_points": list(self.target_shape_points),
            "target_shape_cells": list(self.target_shape_cells),
            "loop_path_points": list(self.loop_path_points),
            "loop_path_cells": list(self.loop_path_cells),
            "loop_routes": [
                {
                    "source": route["source"],
                    "path_points": list(route["path_points"]),
                    "path": list(route.get("path", [])),
                }
                for route in self.loop_routes
            ],
            "loop_route_index": self.loop_route_index,
            "loop_cycles": self.loop_cycles,
            "loop_interval_s": self.loop_interval_s,
            "mixing_cycles": self.mixing_cycles,
        }

    def _push_undo_snapshot(self):
        if self.auto_running:
            return False
        snapshot = self._settings_snapshot()
        if self.undo_stack and self.undo_stack[-1] == snapshot:
            return False
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.max_undo_snapshots:
            self.undo_stack.pop(0)
        return True

    def _restore_settings_snapshot(self, snapshot):
        self.start_cell = snapshot["start_cell"]
        self.goal_cell = snapshot["goal_cell"]
        self.secondary_cell = snapshot["secondary_cell"]
        self.split_left_cell = snapshot["split_left_cell"]
        self.split_right_cell = snapshot["split_right_cell"]
        self.loaded_reservoirs = set(snapshot["loaded_reservoirs"])
        self.initial_droplet_cells = set(snapshot["initial_droplet_cells"])
        self.obstacle_cells = set(snapshot["obstacle_cells"])
        self.target_shape_points = list(snapshot["target_shape_points"])
        self.target_shape_cells = list(snapshot["target_shape_cells"])
        self.loop_routes = [
            {
                "source": route["source"],
                "path_points": list(route["path_points"]),
                "path": list(route.get("path", [])),
            }
            for route in snapshot["loop_routes"]
        ]
        self.loop_route_index = snapshot["loop_route_index"]
        self.loop_path_points = list(snapshot["loop_path_points"])
        self.loop_path_cells = list(snapshot["loop_path_cells"])
        self.loop_cycles = snapshot["loop_cycles"]
        self.loop_cycles_var.set(self.loop_cycles)
        self.loop_interval_s = snapshot["loop_interval_s"]
        self.loop_interval_s_var.set(self.loop_interval_s)
        self.mixing_cycles = snapshot["mixing_cycles"]
        self.mixing_cycles_var.set(self.mixing_cycles)
        self._clear_planned_operation()
        if self.loop_route_index is not None and 0 <= self.loop_route_index < len(self.loop_routes):
            route = self.loop_routes[self.loop_route_index]
            self.start_cell = route["source"]
            self.loop_path_points = route["path_points"]
            self.loop_path_cells = route.get("path", [])
        self._reset_droplets_for_operation()

    def undo_last_setting(self, refresh=True):
        if self.auto_running:
            self.log("闭环运行中，无法撤销设置；请先暂停或停止")
            return False
        if not self.undo_stack:
            self.log("没有可撤销的设置")
            return False
        snapshot = self.undo_stack.pop()
        self._restore_settings_snapshot(snapshot)
        self.log("已撤销上一步设置")
        if refresh:
            self._draw_matrix_canvas()
            self._render_sim_camera_frame()
        return True

    def on_undo_shortcut(self, _event=None):
        self.undo_last_setting()
        return "break"

    def _refresh_operation_path_cells(self):
        paths = self.operation_paths if self.operation_paths else ([self.path] if self.path else [])
        self.operation_path_cells = {cell for path in paths for cell in path}
