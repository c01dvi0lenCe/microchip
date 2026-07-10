"""Planning entry points for move, loop, mixing, split, and multi-droplet tasks."""

from __future__ import annotations

from .common import (
    CORNER_RESERVOIRS,
    INITIAL_DROPLET_CAPACITY,
    MultiDropletAssignment,
    RESERVOIR_CELLS,
    RESERVOIR_DROPLET_CAPACITY,
    build_multi_droplet_assignments,
    grid_polyline_cells,
    is_reservoir_cell,
    math,
    schedule_multi_paths,
    tk,
)


class OperationPlanningMixin:
    def _routing_obstacles(self, *allowed_cells):
        allowed = {cell for cell in allowed_cells if cell is not None}
        return set(self.obstacle_cells) - allowed

    def _sync_mixing_cycles(self):
        try:
            cycles = int(self.mixing_cycles_var.get())
        except (TypeError, tk.TclError, ValueError):
            cycles = self.mixing_cycles
        cycles = max(1, min(10, cycles))
        self.mixing_cycles = cycles
        try:
            if self.mixing_cycles_var.get() != cycles:
                self.mixing_cycles_var.set(cycles)
        except tk.TclError:
            pass
        return cycles

    def _sync_loop_cycles(self):
        try:
            cycles = int(self.loop_cycles_var.get())
        except (TypeError, tk.TclError, ValueError):
            cycles = self.loop_cycles
        cycles = max(1, min(9999, cycles))
        self.loop_cycles = cycles
        try:
            if self.loop_cycles_var.get() != cycles:
                self.loop_cycles_var.set(cycles)
        except tk.TclError:
            pass
        return cycles

    def _sync_loop_interval_s(self):
        try:
            interval_s = float(self.loop_interval_s_var.get())
        except (TypeError, tk.TclError, ValueError):
            interval_s = self.loop_interval_s
        interval_s = max(0.0, min(60.0, interval_s))
        interval_s = round(interval_s, 1)
        self.loop_interval_s = interval_s
        try:
            if float(self.loop_interval_s_var.get()) != interval_s:
                self.loop_interval_s_var.set(interval_s)
        except (tk.TclError, ValueError):
            pass
        return interval_s

    def _loop_interval_step_count(self, interval_s=None):
        interval = self._sync_loop_interval_s() if interval_s is None else max(0.0, float(interval_s))
        if interval <= 0:
            return 0
        return max(1, math.ceil(interval / self.multi_step_duration_s))

    def _is_core_array_cell(self, cell):
        row, col = cell
        return not is_reservoir_cell(cell) and 0 <= row < self.rows and 0 <= col < self.cols

    def _place_loop_droplet(self, cell):
        if not self._is_core_array_cell(cell):
            return None
        for idx, route in enumerate(self.loop_routes):
            if route["source"] == cell:
                return idx
        route = {"source": cell, "path_points": [], "path": []}
        self.loop_routes.append(route)
        self.loop_path_points = []
        self.loop_path_cells = []
        self._reset_droplets_for_operation()
        return len(self.loop_routes) - 1

    def _remove_loop_droplet(self, cell):
        for idx, route in enumerate(self.loop_routes):
            if route["source"] != cell:
                continue
            self.loop_routes.pop(idx)
            if self.loop_route_index == idx:
                self.loop_route_index = None
                self.loop_path_points = []
                self.loop_path_cells = []
            elif self.loop_route_index is not None and self.loop_route_index > idx:
                self.loop_route_index -= 1
            self._reset_droplets_for_operation()
            return True
        return False

    def _toggle_existing_loop_droplet(self, cell):
        if not self._is_core_array_cell(cell):
            return False
        if not any(route["source"] == cell for route in self.loop_routes):
            return False
        self._push_undo_snapshot()
        self._clear_planned_operation()
        removed = self._remove_loop_droplet(cell)
        if removed:
            self.log(f"循环液滴已取消 -> {self._cell_label(cell)}")
        self._update_cell_status(cell)
        self._draw_matrix_canvas()
        if self.is_simulation_mode():
            self._render_sim_camera_frame()
        return removed

    def _select_loop_droplet(self, cell):
        if not self._is_core_array_cell(cell):
            return None
        for idx, route in enumerate(self.loop_routes):
            if route["source"] == cell:
                self.loop_route_index = idx
                self.start_cell = cell
                self.loop_path_points = route["path_points"]
                self._rebuild_loop_path_cells()
                self._reset_droplets_for_operation()
                return idx
        return None

    def _current_loop_route(self):
        if self.loop_route_index is None:
            return None
        if not (0 <= self.loop_route_index < len(self.loop_routes)):
            return None
        return self.loop_routes[self.loop_route_index]

    def _append_loop_path_point(self, cell):
        if not self._is_core_array_cell(cell):
            return False
        route = self._current_loop_route()
        if route is None:
            return False
        if route["path_points"] and route["path_points"][-1] == cell:
            return False
        route["path_points"].append(cell)
        self.loop_path_points = route["path_points"]
        self._rebuild_loop_path_cells()
        self._reset_droplets_for_operation()
        return True

    def _handle_loop_path_cell(self, cell, record_undo=False):
        if not self._is_core_array_cell(cell):
            return None
        if self._select_loop_droplet(cell) is not None:
            return "selected"
        route = self._current_loop_route()
        if route is not None and route["path_points"] and route["path_points"][-1] == cell:
            return "unchanged"
        if record_undo:
            self._push_undo_snapshot()
        self._clear_planned_operation()
        if not self._append_loop_path_point(cell):
            return None
        return "appended"

    def _loop_route_path(self, route):
        source = route["source"]
        if not self._is_core_array_cell(source):
            return []
        points = [source]
        points.extend(cell for cell in route["path_points"] if self._is_core_array_cell(cell))
        if len(points) < 2:
            return []
        if points[-1] != source:
            points.append(source)
        return grid_polyline_cells(points, self.rows, self.cols)

    def _expanded_loop_path(self, path, cycles, interval_s=0.0):
        if not path:
            return []
        interval_steps = self._loop_interval_step_count(interval_s)
        expanded = list(path)
        for _ in range(max(0, cycles - 1)):
            expanded.extend([path[-1]] * interval_steps)
            expanded.extend(path[1:])
        return expanded

    def _loop_preview_paths(self):
        if self.loop_routes:
            return [route.get("path", []) or self._loop_route_path(route) for route in self.loop_routes]
        return [self.loop_path_cells] if self.loop_path_cells else []

    def _rebuild_loop_path_cells(self):
        route = self._current_loop_route()
        if route is not None:
            route["path"] = self._loop_route_path(route)
            self.start_cell = route["source"]
            self.loop_path_points = route["path_points"]
            self.loop_path_cells = route["path"]
            return self.loop_path_cells
        if not self._is_core_array_cell(self.start_cell):
            self.loop_path_cells = []
            return []
        points = [self.start_cell]
        points.extend(cell for cell in self.loop_path_points if self._is_core_array_cell(cell))
        if len(points) < 2:
            self.loop_path_cells = []
            return []
        closed_points = list(points)
        if closed_points[-1] != self.start_cell:
            closed_points.append(self.start_cell)
        self.loop_path_cells = grid_polyline_cells(closed_points, self.rows, self.cols)
        return self.loop_path_cells

    def _build_mixing_path(self, mix_cell):
        row, col = mix_cell
        cycles = self._sync_mixing_cycles()
        orientations = ((1, 1), (1, -1), (-1, 1), (-1, -1))
        for dr, dc in orientations:
            cycle = [
                mix_cell,
                (row, col + dc),
                (row + dr, col + dc),
                (row + dr, col),
                mix_cell,
            ]
            if all(self._is_valid_mixing_cell(cell, mix_cell) for cell in cycle):
                path = [mix_cell]
                for _ in range(cycles):
                    path.extend(cycle[1:])
                return path
        return [mix_cell]

    def _is_valid_mixing_cell(self, cell, mix_cell):
        row, col = cell
        if is_reservoir_cell(cell) or not (0 <= row < self.rows and 0 <= col < self.cols):
            return False
        return cell == mix_cell or cell not in self.obstacle_cells

    def _set_default_split_targets(self):
        row, col = self.start_cell
        if 0 < col < self.cols - 1:
            self.split_left_cell = (row, col - 1)
            self.split_right_cell = (row, col + 1)
        elif 0 < row < self.rows - 1:
            self.split_left_cell = (row - 1, col)
            self.split_right_cell = (row + 1, col)
        else:
            self.log("当前源液滴在边角，无法自动生成反向相邻分裂电极")
            return
        self.log(
            "分裂目标自动设为 "
            f"{self._cell_label(self.split_left_cell)} / {self._cell_label(self.split_right_cell)}"
        )

    def _set_split_direction_from_cell(self, cell):
        if not self._is_core_array_cell(cell):
            return False
        sr, sc = self.start_cell
        row, col = cell
        dr = row - sr
        dc = col - sc
        if abs(dr) + abs(dc) != 1:
            return False
        opposite = (sr - dr, sc - dc)
        if not self._is_core_array_cell(opposite):
            return False
        targets = [cell, opposite]
        if dr:
            targets.sort(key=lambda item: item[0])
        else:
            targets.sort(key=lambda item: item[1])
        self.split_left_cell, self.split_right_cell = targets
        return True

    def _valid_split_triplet(self):
        sr, sc = self.start_cell
        lr, lc = self.split_left_cell
        rr, rc = self.split_right_cell
        dl = (lr - sr, lc - sc)
        dr = (rr - sr, rc - sc)
        return (
            abs(dl[0]) + abs(dl[1]) == 1
            and abs(dr[0]) + abs(dr[1]) == 1
            and dl[0] == -dr[0]
            and dl[1] == -dr[1]
        )

    def plan_path(self, reset_droplet=False):
        operation = self.operation_var.get()
        self.last_plan_error = ""
        if reset_droplet:
            self._reset_droplets_for_operation()

        if operation == self.OP_MULTI:
            return self._plan_multi_paths()
        if operation == self.OP_MERGE:
            return self._plan_merge_paths()
        if operation == self.OP_SPLIT:
            return self._plan_split_paths()
        if operation == self.OP_LOOP:
            return self._plan_loop_path()
        return self._plan_move_path()

    def _plan_multi_paths(self):
        multi_sources = self._multi_source_cells()
        if not multi_sources:
            return self._handle_plan_failed("多液滴规划失败：请先设置储液池或阵列初始液滴")
        if not self.target_shape_cells:
            return self._handle_plan_failed("多液滴规划失败：请先在中间阵列设置目标电极")
        if (
            not self.loaded_reservoirs
            and self.initial_droplet_cells
            and len(self.target_shape_cells) != len(self.initial_droplet_cells)
        ):
            return self._handle_plan_failed(
                "多液滴规划失败：未设置储液池时，目标电极数量必须等于初始液滴数量；"
                f"当前初始液滴 {len(self.initial_droplet_cells)} 滴，目标 {len(self.target_shape_cells)} 个"
            )
        source_capacity = self._multi_source_capacities()
        total_capacity = sum(source_capacity.values())
        if total_capacity < len(self.target_shape_cells):
            return self._handle_plan_failed(
                "多液滴规划失败：目标电极数量超过可用液滴数；"
                f"当前可用 {total_capacity} 滴，目标 {len(self.target_shape_cells)} 个"
            )

        assignments = build_multi_droplet_assignments(
            multi_sources,
            self.target_shape_cells,
            self.planner,
            self._routing_obstacles(*multi_sources, *self.target_shape_cells),
            source_capacity=source_capacity,
        )
        if not assignments:
            return self._handle_plan_failed("多液滴规划失败：目标电极存在无法避碰的路径")

        self.path = []
        self.merge_path_b = []
        self.multi_assignments = assignments
        self.multi_targets = [assignment.target for assignment in assignments]
        self.operation_paths = [assignment.path for assignment in assignments]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.path_index_b = 0
        self.multi_step_index = 0
        self.current_target_cell = None
        self.current_target_cell_b = None
        self._reset_droplets_for_operation()
        max_steps = max(len(assignment.scheduled_path) for assignment in assignments)
        self.auto_status_label.config(text=f"闭环: 多液滴 {len(assignments)} 滴 / {max_steps - 1} 步", fg=self.colors["accent"])
        self.log(f"多液滴规划完成：{len(self.multi_targets)} 个目标电极将全部填满")
        round_count = max(getattr(assignment, "round_index", 1) for assignment in assignments)
        if round_count > 1:
            self.log(
                f"目标较密集或数量较多，已自动拆为 {round_count} 轮并行调度；"
                "每一步由路径冲突、回吸风险和目标液区关系动态决定可同时行动的液滴数"
            )
        merge_regions = self._target_merge_regions()
        if merge_regions:
            self.log(f"相邻目标电极将视为 {len(merge_regions)} 个连通液区，普通运输区仍避免相邻/对角拉扯")
        for assignment in assignments:
            self.log(
                f"D{assignment.droplet_id}(第 {getattr(assignment, 'round_index', 1)} 轮): {self._cell_label(assignment.source)} -> "
                f"{self._cell_label(assignment.target)} / {len(assignment.path) - 1} 步"
            )
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return assignments

    def _multi_source_cells(self):
        return (set(self.loaded_reservoirs) - set(CORNER_RESERVOIRS)) | set(self.initial_droplet_cells)

    def _multi_source_capacities(self):
        capacities = {}
        for cell in self.loaded_reservoirs:
            if cell in CORNER_RESERVOIRS:
                continue
            capacities[cell] = RESERVOIR_DROPLET_CAPACITY
        for cell in self.initial_droplet_cells:
            capacities[cell] = capacities.get(cell, 0) + INITIAL_DROPLET_CAPACITY
        return capacities

    def _target_merge_regions(self):
        targets = set(self.multi_targets or self.target_shape_cells)
        regions = []
        while targets:
            start = targets.pop()
            stack = [start]
            region = {start}
            while stack:
                row, col = stack.pop()
                for nxt in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                    if nxt not in targets:
                        continue
                    targets.remove(nxt)
                    region.add(nxt)
                    stack.append(nxt)
            if len(region) > 1:
                regions.append(region)
        return regions

    def _plan_move_path(self):
        path = self.planner.plan(
            self.start_cell,
            self.goal_cell,
            self._routing_obstacles(self.start_cell, self.goal_cell),
        )
        if not path:
            return self._handle_plan_failed("移动路径规划失败：起点到终点无可行路径")
        self.path = path
        self.merge_path_b = []
        self.operation_paths = [path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.path_index_b = 0
        self.current_target_cell = path[1] if len(path) > 1 else None
        self.current_target_cell_b = None
        self.auto_status_label.config(text=f"闭环: 移动 {len(path)} 格", fg=self.colors["accent"])
        self.log(f"移动路径完成：{len(path)} 格，{len(path) - 1} 步")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return path

    def _plan_loop_path(self):
        route_specs = self.loop_routes if self.loop_routes else [
            {"source": self.start_cell, "path_points": self.loop_path_points, "path": self.loop_path_cells}
        ]
        if not route_specs:
            return self._handle_plan_failed("循环规划失败：请先在中间阵列设置循环液滴")

        cycles = self._sync_loop_cycles()
        interval_s = self._sync_loop_interval_s()
        cycle_paths = []
        for idx, route in enumerate(route_specs, start=1):
            if not self._is_core_array_cell(route["source"]):
                return self._handle_plan_failed(f"循环规划失败：D{idx} 起点不在中间阵列")
            if not route["path_points"]:
                return self._handle_plan_failed(f"循环规划失败：请给 D{idx} 至少设置 1 个循环路径点")
            path = self._loop_route_path(route)
            if len(path) < 3 or path[0] != path[-1]:
                return self._handle_plan_failed(f"循环规划失败：D{idx} 路径无法闭合回起点")
            blocked = set(path) & set(self.obstacle_cells)
            if blocked:
                blocked_text = " / ".join(self._cell_label(cell) for cell in sorted(blocked)[:4])
                return self._handle_plan_failed(f"循环规划失败：D{idx} 路径经过障碍物 {blocked_text}")
            route["path"] = path
            cycle_paths.append(path)

        if len(cycle_paths) > 1:
            scheduled_paths = schedule_multi_paths(cycle_paths)
            if len(scheduled_paths) != len(cycle_paths):
                return self._handle_plan_failed("循环规划失败：多个循环路径之间存在无法调度的冲突")
            self.loop_assignments = [
                MultiDropletAssignment(
                    droplet_id=idx,
                    source=route["source"],
                    target=route["source"],
                    path=cycle_paths[idx - 1],
                    scheduled_path=scheduled_paths[idx - 1],
                )
                for idx, route in enumerate(route_specs, start=1)
            ]
            self.path = []
            self.merge_path_b = []
            self.operation_paths = cycle_paths
            self._refresh_operation_path_cells()
            self.path_index = 0
            self.path_index_b = 0
            self.multi_step_index = 0
            self.loop_cycles_completed = 0
            self.current_target_cell = None
            self.current_target_cell_b = None
            self._reset_droplets_for_operation()
            max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
            self.auto_status_label.config(text=f"闭环: 多液滴循环 {len(self.loop_assignments)} 滴 / {cycles} 圈", fg=self.colors["accent"])
            self.log(f"多液滴循环规划完成：{len(self.loop_assignments)} 滴，计划 {cycles} 圈，间隔 {interval_s:.1f}s，调度 {max_steps - 1} 步")
            self._draw_matrix_canvas()
            self._render_sim_camera_frame()
            return self.loop_assignments

        path = cycle_paths[0]
        self.path = path
        self.merge_path_b = []
        self.loop_assignments = []
        self.operation_paths = [path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.path_index_b = 0
        self.loop_cycles_completed = 0
        self.current_target_cell = path[1] if len(path) > 1 else None
        self.current_target_cell_b = None
        self._reset_droplets_for_operation()
        self.auto_status_label.config(text=f"闭环: 循环 {cycles} 圈 / {len(path) - 1} 步每圈", fg=self.colors["accent"])
        self.log(f"循环路径完成：{len(cycle_paths[0]) - 1} 步/圈，计划 {cycles} 圈，间隔 {interval_s:.1f}s")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return path

    def _plan_merge_paths(self):
        route_obstacles = self._routing_obstacles(self.start_cell, self.secondary_cell, self.goal_cell)
        path_a = self.planner.plan(self.start_cell, self.goal_cell, route_obstacles)
        path_b = self.planner.plan(self.secondary_cell, self.goal_cell, route_obstacles)
        if not path_a or not path_b:
            return self._handle_plan_failed("混合路径规划失败：液滴A或液滴B无法到达混合点")
        mixing_path = self._build_mixing_path(self.goal_cell)
        if len(mixing_path) < 5:
            return self._handle_plan_failed("混合路径规划失败：混合点周围无法形成四宫格混合路径")
        self.path = path_a
        self.merge_path_b = path_b
        self.mixing_path = mixing_path
        self.mixing_index = 0
        self.mixing_active = False
        self.operation_paths = [path_a, path_b, mixing_path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.path_index_b = 0
        self.current_target_cell = path_a[1] if len(path_a) > 1 else self.goal_cell
        self.current_target_cell_b = path_b[1] if len(path_b) > 1 else self.goal_cell
        mix_steps = len(mixing_path) - 1
        self.auto_status_label.config(text=f"闭环: 混合 A{len(path_a)} / B{len(path_b)} 格 + {mix_steps} 步", fg=self.colors["accent"])
        self.log(f"混合路径完成：A {len(path_a) - 1} 步，B {len(path_b) - 1} 步，四宫格混合 {mix_steps} 步")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return self.operation_paths

    def _plan_split_paths(self):
        protected = {self.start_cell, self.split_left_cell, self.split_right_cell}
        if protected & set(RESERVOIR_CELLS):
            return self._handle_plan_failed("分裂规划失败：储液池不用于三电极分裂")
        if self.split_left_cell == self.split_right_cell or self.start_cell in (self.split_left_cell, self.split_right_cell):
            return self._handle_plan_failed("分裂规划失败：源液滴、左子滴和右子滴必须是不同电极")
        if not self._valid_split_triplet():
            return self._handle_plan_failed("分裂规划失败：请选择源电极两侧相邻且方向相反的左/右子滴电极")
        path_l = [self.start_cell, self.split_left_cell]
        path_r = [self.start_cell, self.split_right_cell]
        self.path = path_l
        self.merge_path_b = path_r
        self.operation_paths = [path_l, path_r]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.path_index_b = 0
        self.current_target_cell = self.split_left_cell
        self.current_target_cell_b = self.split_right_cell
        self.auto_status_label.config(text="闭环: 分裂待启动", fg=self.colors["accent"])
        self.log(f"分裂规划完成：{self._cell_label(self.start_cell)} -> 左/右子滴目标")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return self.operation_paths

    def _handle_plan_failed(self, message):
        self.last_plan_error = message
        self.path = []
        self.merge_path_b = []
        self.operation_paths = []
        self.operation_path_cells = set()
        self.current_target_cell = None
        self.current_target_cell_b = None
        self.multi_assignments = []
        self.multi_targets = []
        self.multi_step_index = 0
        self.auto_status_label.config(text="闭环: 无可行路径", fg=self.colors["danger"])
        self.log(message)
        self._draw_matrix_canvas()
        return []

    def _rebuild_target_shape_cells(self):
        cells = []
        seen = set()
        for cell in self.target_shape_points:
            row, col = cell
            if cell in seen or not (0 <= row < self.rows and 0 <= col < self.cols):
                continue
            cells.append(cell)
            seen.add(cell)
        self.target_shape_cells = cells

    def _toggle_existing_target_shape_cell(self, cell):
        if cell not in self.target_shape_cells:
            return False
        self._push_undo_snapshot()
        self._clear_planned_operation()
        self.target_shape_points = [point for point in self.target_shape_points if point != cell]
        self._rebuild_target_shape_cells()
        self._reset_droplets_for_operation()
        self.log(f"目标电极已取消 -> {self._cell_label(cell)}")
        self._update_cell_status(cell)
        self._draw_matrix_canvas()
        if self.is_simulation_mode():
            self._render_sim_camera_frame()
        return True

    def undo_target_shape(self):
        if self.auto_running:
            self.stop_auto_control("编辑目标电极")
        if self.operation_var.get() == self.OP_LOOP:
            if not self.loop_path_points:
                self.log("循环路径点为空，无法撤销")
                return
            self._push_undo_snapshot()
            removed = self.loop_path_points.pop()
            self._clear_planned_operation()
            self._rebuild_loop_path_cells()
            self._reset_droplets_for_operation()
            self.log(f"已撤销循环路径点 -> {self._cell_label(removed)}")
            self._draw_matrix_canvas()
            self._render_sim_camera_frame()
            return
        if not self.target_shape_points:
            self.log("目标电极为空，无法撤销")
            return
        self._push_undo_snapshot()
        removed = self.target_shape_points.pop()
        self._clear_planned_operation()
        self._rebuild_target_shape_cells()
        self._reset_droplets_for_operation()
        self.log(f"已撤销目标电极 -> {self._cell_label(removed)}")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def clear_target_shape(self):
        if self.auto_running:
            self.stop_auto_control("清空目标电极")
        if self.operation_var.get() == self.OP_LOOP:
            if not self.loop_path_points and not self.loop_path_cells:
                self.log("循环路径已为空")
                return
            self._push_undo_snapshot()
            self._clear_planned_operation()
            self.loop_path_points = []
            self.loop_path_cells = []
            self._reset_droplets_for_operation()
            self.log("循环路径已清空")
            self._draw_matrix_canvas()
            self._render_sim_camera_frame()
            return
        if not self.target_shape_points and not self.target_shape_cells:
            self.log("目标电极已为空")
            return
        self._push_undo_snapshot()
        self._clear_planned_operation()
        self.target_shape_points = []
        self.target_shape_cells = []
        self._reset_droplets_for_operation()
        self.log("目标电极已清空")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def clear_loaded_reservoirs(self):
        if self.auto_running:
            self.stop_auto_control("清空储液池")
        if not self.loaded_reservoirs:
            self.log("储液池已为空")
            return
        self._push_undo_snapshot()
        self._clear_planned_operation()
        self.loaded_reservoirs.clear()
        self._reset_droplets_for_operation()
        self.log("储液池已清空")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def clear_initial_droplets(self):
        if self.auto_running:
            self.stop_auto_control("清空初始液滴")
        if not self.initial_droplet_cells:
            self.log("初始液滴已为空")
            return
        self._push_undo_snapshot()
        self._clear_planned_operation()
        self.initial_droplet_cells.clear()
        self._reset_droplets_for_operation()
        self.log("初始液滴已清空")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def clear_obstacles(self):
        if self.auto_running:
            self.stop_auto_control("清空障碍物")
        if not self.obstacle_cells:
            self.log("障碍物已为空")
            return
        self._push_undo_snapshot()
        self._clear_planned_operation()
        self.obstacle_cells.clear()
        self._reset_droplets_for_operation()
        self.log("障碍物已清空")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
