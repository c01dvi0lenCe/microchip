"""Electrode canvas geometry, rendering, legends, and click handling."""

from __future__ import annotations

from .common import (
    BOARD_FRAME_MM,
    CORNER_RESERVOIRS,
    LAYOUT_CELLS,
    MAX_CANVAS_PATH_ARROWS,
    RESERVOIR_CELLS,
    SIDE_RESERVOIR_LARGE,
    SIDE_RESERVOIR_SMALL,
    cell_center_mm,
    cell_from_electrode_id,
    electrode_id,
    is_reservoir_cell,
    math,
    time,
    tk,
)


class CanvasControllerMixin:
    def _grid_geometry(self):
        width = max(1, self.matrix_canvas.winfo_width())
        height = max(1, self.matrix_canvas.winfo_height())
        board_left, board_top, board_size = self._board_geometry()
        px_per_mm = board_size / BOARD_FRAME_MM
        cell_size = max(1, px_per_mm * self.pitch_mm)
        grid_w = cell_size * self.cols
        grid_h = cell_size * self.rows
        left = board_left + (BOARD_FRAME_MM - self.cols * self.pitch_mm) * 0.5 * px_per_mm
        top = board_top + (BOARD_FRAME_MM - self.rows * self.pitch_mm) * 0.5 * px_per_mm
        return left, top, grid_w, grid_h, cell_size

    def _board_geometry(self):
        width = max(1, self.matrix_canvas.winfo_width())
        height = max(1, self.matrix_canvas.winfo_height())
        margin = 6
        board_size = max(1, min(width, height) - 2 * margin)
        return (width - board_size) / 2, (height - board_size) / 2, board_size

    def _cell_rect(self, cell):
        if is_reservoir_cell(cell):
            return self._reservoir_rect(cell)
        left, top, _, _, cell_size = self._grid_geometry()
        row, col = cell
        x0 = left + col * cell_size
        y0 = top + row * cell_size
        return x0, y0, x0 + cell_size, y0 + cell_size

    def _canvas_to_cell(self, x, y):
        for cell in RESERVOIR_CELLS:
            if cell in CORNER_RESERVOIRS:
                if self._point_in_corner_reservoir(cell, x, y):
                    return cell
                continue
            x0, y0, x1, y1 = self._reservoir_rect(cell)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return cell
        left, top, grid_w, grid_h, cell_size = self._grid_geometry()
        if x < left or y < top or x >= left + grid_w or y >= top + grid_h:
            return None
        col = int((x - left) // cell_size)
        row = int((y - top) // cell_size)
        if 0 <= row < self.rows and 0 <= col < self.cols:
            cell = (row, col)
            if is_reservoir_cell(cell):
                return None
            return cell
        return None

    def _reservoir_side(self, cell):
        row, col = cell
        if cell in CORNER_RESERVOIRS:
            if row < 0 and col < 0:
                return "top_left"
            if row < 0:
                return "top_right"
            if col < 0:
                return "bottom_left"
            return "bottom_right"
        if row < 0:
            return "top"
        if row >= self.rows:
            return "bottom"
        if col < 0:
            return "left"
        if col >= self.cols:
            return "right"
        return "core"

    def _point_in_corner_reservoir(self, cell, x, y):
        if cell not in CORNER_RESERVOIRS:
            return False
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in self._corner_reservoir_rects(cell))

    def _reservoir_rect(self, cell):
        left, top, _, _, cell_size = self._grid_geometry()
        row, col = cell
        side = self._reservoir_side(cell)
        pad_size = cell_size * (2.05 if cell in SIDE_RESERVOIR_LARGE else 0.85)
        if cell in CORNER_RESERVOIRS:
            rects = self._corner_reservoir_rects(cell)
            return (
                min(rect[0] for rect in rects),
                min(rect[1] for rect in rects),
                max(rect[2] for rect in rects),
                max(rect[3] for rect in rects),
            )
        if side == "top":
            cx = left + (col + 0.5) * cell_size
            cy = top + (row + 0.5) * cell_size
        elif side == "bottom":
            cx = left + (col + 0.5) * cell_size
            cy = top + (row + 0.5) * cell_size
        elif side == "left":
            cx = left + (col + 0.5) * cell_size
            cy = top + (row + 0.5) * cell_size
        elif side == "right":
            cx = left + (col + 0.5) * cell_size
            cy = top + (row + 0.5) * cell_size
        elif side == "top_left":
            cx = left - 1.05 * cell_size
            cy = top - 1.05 * cell_size
        elif side == "top_right":
            cx = left + (self.cols + 1.05) * cell_size
            cy = top - 1.05 * cell_size
        elif side == "bottom_left":
            cx = left - 1.05 * cell_size
            cy = top + (self.rows + 1.05) * cell_size
        else:
            cx = left + (self.cols + 1.05) * cell_size
            cy = top + (self.rows + 1.05) * cell_size
        if cell in SIDE_RESERVOIR_LARGE:
            if side == "top":
                cy = top - 2.0 * cell_size
            elif side == "bottom":
                cy = top + (self.rows + 2.0) * cell_size
            elif side == "left":
                cx = left - 2.0 * cell_size
            elif side == "right":
                cx = left + (self.cols + 2.0) * cell_size
        half = pad_size / 2
        return cx - half, cy - half, cx + half, cy + half

    def _corner_reservoir_rects(self, cell):
        left, top, _, _, cell_size = self._grid_geometry()
        side = self._reservoir_side(cell)
        def rect_at(row, col):
            return (
                left + col * cell_size,
                top + row * cell_size,
                left + (col + 1) * cell_size,
                top + (row + 1) * cell_size,
            )
        if side == "top_left":
            return [rect_at(row, col) for row, col in ((-1, -1), (-1, 0), (0, -1))]
        if side == "top_right":
            return [rect_at(row, col) for row, col in ((-1, self.cols - 1), (-1, self.cols), (0, self.cols))]
        if side == "bottom_left":
            return [rect_at(row, col) for row, col in ((self.rows - 1, -1), (self.rows, -1), (self.rows, 0))]
        return [
            rect_at(row, col)
            for row, col in (
                (self.rows - 1, self.cols),
                (self.rows, self.cols - 1),
                (self.rows, self.cols),
            )
        ]

    def _corner_reservoir_polygon_points(self, cell):
        left, top, _, _, cell_size = self._grid_geometry()
        right = left + self.cols * cell_size
        bottom = top + self.rows * cell_size
        side = self._reservoir_side(cell)
        if side == "top_left":
            return [
                (left - cell_size, top - cell_size),
                (left + cell_size, top - cell_size),
                (left + cell_size, top),
                (left, top),
                (left, top + cell_size),
                (left - cell_size, top + cell_size),
            ]
        if side == "top_right":
            return [
                (right - cell_size, top - cell_size),
                (right + cell_size, top - cell_size),
                (right + cell_size, top + cell_size),
                (right, top + cell_size),
                (right, top),
                (right - cell_size, top),
            ]
        if side == "bottom_left":
            return [
                (left - cell_size, bottom - cell_size),
                (left, bottom - cell_size),
                (left, bottom),
                (left + cell_size, bottom),
                (left + cell_size, bottom + cell_size),
                (left - cell_size, bottom + cell_size),
            ]
        return [
            (right, bottom - cell_size),
            (right + cell_size, bottom - cell_size),
            (right + cell_size, bottom + cell_size),
            (right - cell_size, bottom + cell_size),
            (right - cell_size, bottom),
            (right, bottom),
        ]

    def _reservoir_connector_rect(self, cell):
        left, top, _, _, cell_size = self._grid_geometry()
        row, col = cell
        side = self._reservoir_side(cell)
        width = cell_size * 0.46
        if cell in CORNER_RESERVOIRS:
            return None
        if side == "top" and cell in SIDE_RESERVOIR_SMALL:
            cx = left + (col + 0.5) * cell_size
            return cx - width / 2, top - cell_size, cx + width / 2, top
        if side == "top":
            cx = left + (col + 0.5) * cell_size
            return cx - width / 2, top - 3 * cell_size, cx + width / 2, top - cell_size
        if side == "bottom" and cell in SIDE_RESERVOIR_SMALL:
            cx = left + (col + 0.5) * cell_size
            return cx - width / 2, top + self.rows * cell_size, cx + width / 2, top + (self.rows + 1) * cell_size
        if side == "bottom":
            cx = left + (col + 0.5) * cell_size
            return cx - width / 2, top + (self.rows + 1) * cell_size, cx + width / 2, top + (self.rows + 3) * cell_size
        if side == "left" and cell in SIDE_RESERVOIR_SMALL:
            cy = top + (row + 0.5) * cell_size
            return left - cell_size, cy - width / 2, left, cy + width / 2
        if side == "left":
            cy = top + (row + 0.5) * cell_size
            return left - 3 * cell_size, cy - width / 2, left - cell_size, cy + width / 2
        if side == "right" and cell in SIDE_RESERVOIR_SMALL:
            cy = top + (row + 0.5) * cell_size
            return left + self.cols * cell_size, cy - width / 2, left + (self.cols + 1) * cell_size, cy + width / 2
        cy = top + (row + 0.5) * cell_size
        return left + (self.cols + 1) * cell_size, cy - width / 2, left + (self.cols + 3) * cell_size, cy + width / 2

    def _active_cells(self):
        return {
            cell_from_electrode_id(eid, self.cols)
            for eid, info in self.buttons.items()
            if info["state"] == 1
        }

    def _draw_matrix_canvas(self):
        canvases = getattr(self, "matrix_canvases", None)
        if not canvases:
            if not hasattr(self, "matrix_canvas"):
                return
            self._draw_matrix_canvas_one()
            return

        previous_canvas = getattr(self, "matrix_canvas", None)
        for canvas in canvases:
            if not canvas.winfo_exists():
                continue
            self.matrix_canvas = canvas
            self._draw_matrix_canvas_one()
        if previous_canvas is not None and previous_canvas.winfo_exists():
            self.matrix_canvas = previous_canvas

    def _draw_matrix_canvas_one(self):
        if not hasattr(self, "matrix_canvas"):
            return
        canvas = self.matrix_canvas
        manual_view = self._is_manual_canvas(canvas)
        canvas.delete("all")
        left, top, grid_w, grid_h, cell_size = self._grid_geometry()
        board_left, board_top, board_size = self._board_geometry()
        canvas.create_rectangle(
            board_left,
            board_top,
            board_left + board_size,
            board_top + board_size,
            fill=self.colors["electrode_fill"],
            outline="#7A2E86",
            width=2,
        )

        for row in range(self.rows):
            for col in range(self.cols):
                cell = (row, col)
                if not is_reservoir_cell(cell):
                    self._draw_cell(cell, fill=self.colors["electrode_fill"], outline=self.colors["electrode_outline"])

        for cell in sorted(RESERVOIR_CELLS):
            self._draw_cell(cell, fill=self.colors["reservoir"], outline=self.colors["reservoir_edge"], width=2)

        if not manual_view:
            for cell in self.target_shape_cells:
                self._draw_cell(cell, fill=self.colors["target_shape"], outline="#A896E8")

        for cell in sorted(self.obstacle_cells):
            self._draw_cell(cell, fill=self.colors["obstacle"], outline="#343D45", width=2)

        if not manual_view:
            paths = self.operation_paths if self.operation_paths else ([self.path] if self.path else [])
            if not paths and self.operation_var.get() == self.OP_LOOP:
                paths = self._loop_preview_paths()
            if self.operation_paths and self.operation_path_cells:
                path_cells = self.operation_path_cells
            else:
                path_cells = {cell for path in paths for cell in path}
            for cell in sorted(path_cells, key=lambda item: (item[0], item[1])):
                self._draw_cell(cell, fill=self.colors["path"], outline="")
            arrow_stride = max(1, math.ceil(len(paths) / MAX_CANVAS_PATH_ARROWS)) if paths else 1
            for path_index, path in enumerate(paths):
                if path_index % arrow_stride != 0:
                    continue
                self._draw_path_arrow(path, self._path_arrow_color(path_index))

        for cell in sorted(self.loaded_reservoirs, key=lambda item: electrode_id(item[0], item[1], self.cols)):
            self._draw_cell(cell, fill=self.colors["reservoir_loaded"], outline=self.colors["reservoir_loaded_edge"], width=3)

        if not manual_view:
            for cell in sorted(self.initial_droplet_cells):
                self._draw_cell(cell, fill=self.colors["initial_droplet"], outline="#3E2F8F", width=2)

        if not manual_view:
            for idx, cell in enumerate(self.multi_targets, start=1):
                self._draw_cell(cell, fill=self.colors["target_sample"], outline="#8B6A13", width=2)
                self._draw_cell_text(cell, f"T{idx}", fill="#3A2A00")

        for cell in self._active_cells():
            self._draw_cell(cell, fill=self.colors["btn_on"], outline="")
        operation = self.operation_var.get()
        if manual_view:
            for idx, droplet in enumerate(self.manual_droplets, start=1):
                color = self.multi_droplet_colors[(idx - 1) % len(self.multi_droplet_colors)]
                self._draw_position_marker(droplet.position, color, radius_scale=0.34)
                if len(self.manual_droplets) > 1:
                    self._draw_position_text(droplet.position, str(idx), fill="white")
            if self.hover_cell is not None:
                self._draw_cell(self.hover_cell, fill="", outline="#1F2A33", width=2)
            return

        if self._show_setup_markers():
            if operation != self.OP_MULTI:
                self._draw_cell(self.start_cell, fill=self.colors["droplet_a_bg"], outline=self.colors["droplet_a"], width=2)
            if operation in (self.OP_MOVE, self.OP_MERGE):
                self._draw_cell(self.goal_cell, fill="#F2B9B9", outline="#8E3030", width=2)
            if operation == self.OP_MERGE:
                self._draw_cell(self.secondary_cell, fill=self.colors["droplet_b_bg"], outline=self.colors["droplet_b"], width=2)
            if operation == self.OP_SPLIT:
                self._draw_cell(self.split_left_cell, fill="#F3D58A", outline="#8B6A13", width=2)
                self._draw_cell(self.split_right_cell, fill="#F3D58A", outline="#8B6A13", width=2)

        if self.current_target_cell is not None:
            self._draw_cell(self.current_target_cell, fill="", outline="#F08A24", width=3)
        if self.current_target_cell_b is not None:
            self._draw_cell(self.current_target_cell_b, fill="", outline="#F08A24", width=3)

        if operation == self.OP_MULTI:
            for idx, droplet in enumerate(self.sim_droplets, start=1):
                if idx - 1 >= len(self.multi_droplet_visible) or not self.multi_droplet_visible[idx - 1]:
                    continue
                color = self.multi_droplet_colors[(idx - 1) % len(self.multi_droplet_colors)]
                self._draw_position_marker(droplet.position, color, radius_scale=0.34)
                self._draw_position_text(droplet.position, str(idx), fill="white")
        elif operation == self.OP_LOOP and len(self.sim_droplets) > 1:
            for idx, droplet in enumerate(self.sim_droplets, start=1):
                if self.multi_droplet_visible and (idx - 1 >= len(self.multi_droplet_visible) or not self.multi_droplet_visible[idx - 1]):
                    continue
                color = self.multi_droplet_colors[(idx - 1) % len(self.multi_droplet_colors)]
                self._draw_position_marker(droplet.position, color, radius_scale=0.34)
                self._draw_position_text(droplet.position, str(idx), fill="white")
        else:
            droplet_shapes = self._display_droplet_shapes(manual_view=False)
            for idx, droplet in enumerate(self.sim_droplets):
                color = self._droplet_marker_colors()[idx % 2]
                shape = droplet_shapes[idx] if idx < len(droplet_shapes) else "circle"
                self._draw_position_marker(droplet.position, color, radius_scale=0.34, shape=shape)
                if operation in (self.OP_MERGE, self.OP_SPLIT) and len(self.sim_droplets) > 1:
                    self._draw_position_text(droplet.position, "A" if idx == 0 else "B", fill="white")
        for detected_position in self.detected_positions:
            self._draw_position_marker(detected_position, self.colors["detected"], radius_scale=0.18, hollow=True)

        if self.hover_cell is not None:
            self._draw_cell(self.hover_cell, fill="", outline="#1F2A33", width=2)

    def _draw_cell(self, cell, fill="", outline="#C6D0D8", width=1):
        if cell in CORNER_RESERVOIRS:
            self._draw_corner_reservoir(cell, fill, outline, width)
            return
        if is_reservoir_cell(cell):
            self._draw_reservoir_pad(cell, fill, outline, width)
            return
        x0, y0, x1, y1 = self._cell_rect(cell)
        self.matrix_canvas.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill=fill, outline=outline, width=width)

    def _path_arrow_cells(self, path):
        cells = [cell for cell in path if cell in LAYOUT_CELLS]
        if len(cells) < 2:
            return []
        compressed = [cells[0]]
        previous_direction = None
        for previous, current in zip(cells, cells[1:]):
            direction = (
                0 if current[0] == previous[0] else (1 if current[0] > previous[0] else -1),
                0 if current[1] == previous[1] else (1 if current[1] > previous[1] else -1),
            )
            if previous_direction is not None and direction != previous_direction:
                compressed.append(previous)
            previous_direction = direction
        compressed.append(cells[-1])
        return compressed

    def _cell_center_on_canvas(self, cell):
        x0, y0, x1, y1 = self._cell_rect(cell)
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _path_arrow_color(self, path_index):
        operation = self.operation_var.get()
        if operation in (self.OP_MULTI, self.OP_LOOP):
            return self.multi_droplet_colors[path_index % len(self.multi_droplet_colors)]
        if operation in (self.OP_MERGE, self.OP_SPLIT):
            if path_index == 0:
                return self.colors["droplet_a"]
            if path_index == 1:
                return self.colors["droplet_b"]
        return "#2B6FB8"

    def _draw_path_arrow(self, path, color="#2B6FB8"):
        arrow_cells = self._path_arrow_cells(path)
        if len(arrow_cells) < 2:
            return
        coords = []
        for cell in arrow_cells:
            coords.extend(self._cell_center_on_canvas(cell))
        if len(coords) < 4:
            return
        _, _, _, _, cell_size = self._grid_geometry()
        self.matrix_canvas.create_line(
            *coords,
            fill=color,
            width=max(2, int(cell_size * 0.16)),
            arrow=tk.LAST,
            arrowshape=(cell_size * 0.85, cell_size * 1.05, cell_size * 0.38),
        )

    def _draw_reservoir_pad(self, cell, fill, outline, width):
        x0, y0, x1, y1 = self._cell_rect(cell)
        self._draw_toothed_rect(x0, y0, x1, y1, fill, outline, width)

    def _draw_toothed_rect(self, x0, y0, x1, y1, fill, outline, width=1):
        size = min(max(1.0, x1 - x0), max(1.0, y1 - y0))
        points = self._toothed_rect_points(x0, y0, x1, y1, size * 0.06)
        flat_points = [coord for point in points for coord in point]
        self.matrix_canvas.create_polygon(flat_points, fill=fill, outline=outline, width=width)

    def _toothed_rect_points(self, x0, y0, x1, y1, amplitude):
        width = max(1.0, x1 - x0)
        height = max(1.0, y1 - y0)
        teeth_x = max(4, int(width / max(2.0, amplitude)))
        teeth_y = max(4, int(height / max(2.0, amplitude)))
        points = []
        for i in range(teeth_x * 2 + 1):
            x = x0 + width * i / (teeth_x * 2)
            y = y0 + (amplitude if i % 2 else 0)
            points.append((x, y))
        for i in range(1, teeth_y * 2 + 1):
            x = x1 - (amplitude if i % 2 else 0)
            y = y0 + height * i / (teeth_y * 2)
            points.append((x, y))
        for i in range(1, teeth_x * 2 + 1):
            x = x1 - width * i / (teeth_x * 2)
            y = y1 - (amplitude if i % 2 else 0)
            points.append((x, y))
        for i in range(1, teeth_y * 2 + 1):
            x = x0 + (amplitude if i % 2 else 0)
            y = y1 - height * i / (teeth_y * 2)
            points.append((x, y))
        points.append(points[0])
        return points

    def _draw_corner_reservoir(self, cell, fill, outline, width):
        points = self._corner_reservoir_polygon_points(cell)
        self.matrix_canvas.create_polygon(points, fill=fill, outline=outline, width=width)

    def _draw_reservoir_connector(self, cell):
        return

    def _draw_position_marker(self, position, color, radius_scale=0.3, hollow=False, shape="circle"):
        row, col = position
        left, top, _, _, cell_size = self._grid_geometry()
        cx = left + (col + 0.5) * cell_size
        cy = top + (row + 0.5) * cell_size
        radius = max(4, cell_size * radius_scale)
        fill = "" if hollow else color
        if shape == "horizontal_ellipse":
            rx = max(radius, cell_size * 0.48)
            ry = max(3, cell_size * 0.27)
        else:
            rx = radius
            ry = radius
        self.matrix_canvas.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, fill=fill, outline=color, width=3)

    def _draw_position_text(self, position, text, fill="#1F2A33"):
        row, col = position
        left, top, _, _, cell_size = self._grid_geometry()
        cx = left + (col + 0.5) * cell_size
        cy = top + (row + 0.5) * cell_size
        self.matrix_canvas.create_text(cx, cy, text=text, fill=fill, font=(self.font_family, 8, "bold"))

    def _draw_cell_text(self, cell, text, fill="#1F2A33"):
        x0, y0, x1, y1 = self._cell_rect(cell)
        size = max(7, int(min(x1 - x0, y1 - y0) * 0.26))
        self.matrix_canvas.create_text(
            (x0 + x1) / 2,
            (y0 + y1) / 2,
            text=text,
            fill=fill,
            font=(self.font_family, size, "bold"),
        )

    def on_matrix_click(self, event, manual=False):
        self.matrix_canvas = event.widget
        cell = self._canvas_to_cell(event.x, event.y)
        if cell is None:
            return
        shift_pressed = bool(getattr(event, "state", 0) & 0x0001)

        if manual:
            if self.manual_tool_var.get() == self.MANUAL_TOOL_DROPLET:
                self.set_manual_droplet(cell)
                self._update_cell_status(cell)
                return
            self.manual_toggle_electrode(cell, additive=shift_pressed)
            self.manual_last_update_time = time.monotonic()
            self._update_cell_status(cell)
            self._draw_matrix_canvas()
            if self.is_simulation_mode():
                self._render_sim_camera_frame()
            return

        tool = self.tool_var.get()
        if self.auto_running:
            self.log("闭环运行中，路径编辑已忽略")
            return

        if tool == self.TOOL_OBSTACLE:
            row, col = cell
            if is_reservoir_cell(cell) or not (0 <= row < self.rows and 0 <= col < self.cols):
                self.log("设置障碍物时请点击中间 20x20 阵列")
                return
            self._push_undo_snapshot()
            self._clear_planned_operation()
            if cell in self.obstacle_cells:
                self.obstacle_cells.remove(cell)
                self.log(f"障碍物已移除 -> {self._cell_label(cell)}")
            else:
                self.obstacle_cells.add(cell)
                self.log(f"障碍物已添加 -> {self._cell_label(cell)}")
        elif tool == self.TOOL_MULTI_LOAD:
            if not is_reservoir_cell(cell):
                self.log("设置储液池时请点击四周储液池")
                return
            if cell in CORNER_RESERVOIRS:
                self.log("四角为废液池，不作为加样储液池")
                return
            self._push_undo_snapshot()
            self._clear_planned_operation()
            if cell in self.loaded_reservoirs:
                self.loaded_reservoirs.remove(cell)
                self.log(f"储液池已设为空 -> {self._cell_label(cell)}")
            else:
                self.loaded_reservoirs.add(cell)
                self.log(f"储液池已设为有液 -> {self._cell_label(cell)}")
            self._reset_droplets_for_operation()
        elif tool == self.TOOL_MULTI_INITIAL:
            row, col = cell
            if is_reservoir_cell(cell) or not (0 <= row < self.rows and 0 <= col < self.cols):
                self.log("设置初始液滴时请点击中间 20x20 阵列")
                return
            self._push_undo_snapshot()
            self._clear_planned_operation()
            if cell in self.initial_droplet_cells:
                self.initial_droplet_cells.remove(cell)
                self.log(f"初始液滴已移除 -> {self._cell_label(cell)}")
            else:
                self.initial_droplet_cells.add(cell)
                self.log(f"初始液滴已添加 -> {self._cell_label(cell)}")
            self._reset_droplets_for_operation()
        elif tool == self.TOOL_LOOP_START:
            if self._toggle_existing_loop_droplet(cell):
                return
            if not self._is_core_array_cell(cell):
                self.log("设置循环液滴时请点击中间 20x20 阵列")
                return
            if shift_pressed:
                if not any(route["source"] == cell for route in self.loop_routes):
                    self.log(f"当前位置没有可取消的循环液滴 -> {self._cell_label(cell)}")
                    return
                self._push_undo_snapshot()
                self._clear_planned_operation()
                if self._remove_loop_droplet(cell):
                    self.log(f"循环液滴已取消 -> {self._cell_label(cell)}")
            else:
                if any(route["source"] == cell for route in self.loop_routes):
                    self.log(f"循环液滴已存在 -> {self._cell_label(cell)}")
                    return
                self._push_undo_snapshot()
                self._clear_planned_operation()
                idx = self._place_loop_droplet(cell)
                if idx is None:
                    self.log("循环液滴放置失败")
                    return
                self.log(f"循环液滴 D{idx + 1} 已放置 -> {self._cell_label(cell)}")
        elif tool == self.TOOL_LOOP_SELECT:
            if not self._is_core_array_cell(cell):
                self.log("选择循环液滴时请点击中间 20x20 阵列")
                return
            idx = self._select_loop_droplet(cell)
            if idx is None:
                self.log(f"当前位置没有循环液滴 -> {self._cell_label(cell)}")
                return
            self.log(f"已选择循环液滴 D{idx + 1} -> {self._cell_label(cell)}")
        elif tool == self.TOOL_LOOP_PATH:
            if not self._is_core_array_cell(cell):
                self.log("设置循环路径时请点击中间 20x20 阵列")
                return
            result = self._handle_loop_path_cell(cell, record_undo=True)
            if result == "selected":
                current_index = (self.loop_route_index or 0) + 1
                self.log(f"已选择循环液滴 D{current_index} -> {self._cell_label(cell)}")
                self._update_cell_status(cell)
                self._draw_matrix_canvas()
                if self.is_simulation_mode():
                    self._render_sim_camera_frame()
                return
            if result == "unchanged":
                self.log(f"循环路径点未变化 -> {self._cell_label(cell)}")
                return
            if result != "appended":
                self.log("循环路径点添加失败，请先设置循环液滴")
                return
            current_index = (self.loop_route_index or 0) + 1
            self.log(f"循环液滴 D{current_index} 路径点 {len(self.loop_path_points)} -> {self._cell_label(cell)}")
        elif tool == self.TOOL_MULTI_SHAPE:
            if self._toggle_existing_target_shape_cell(cell):
                return
            row, col = cell
            if is_reservoir_cell(cell) or not (0 <= row < self.rows and 0 <= col < self.cols):
                self.log("设置目标电极时请点击中间 20x20 阵列")
                return
            if cell in self.target_shape_cells:
                self.log(f"目标电极已存在 -> {self._cell_label(cell)}")
                return
            self._push_undo_snapshot()
            self._clear_planned_operation()
            self.target_shape_points.append(cell)
            self._rebuild_target_shape_cells()
            self._reset_droplets_for_operation()
            self.log(f"目标电极 {len(self.target_shape_cells)} -> {self._cell_label(cell)}")
        elif tool in (self.TOOL_MOVE_START, self.TOOL_MERGE_A, self.TOOL_SPLIT_SOURCE):
            self._push_undo_snapshot()
            self._clear_planned_operation()
            self.start_cell = cell
            if tool == self.TOOL_SPLIT_SOURCE:
                self._set_default_split_targets()
            self._reset_droplets_for_operation()
            label = (
                "起点"
                if tool == self.TOOL_MOVE_START
                else ("液滴A" if tool == self.TOOL_MERGE_A else "源液滴")
            )
            self.log(f"{label} -> {self._cell_label(cell)}")
        elif tool == self.TOOL_SPLIT_DIRECTION:
            if not self._is_core_array_cell(cell):
                self.log("设置分裂方向时请点击中间 20x20 阵列")
                return
            self._push_undo_snapshot()
            if not self._set_split_direction_from_cell(cell):
                if self.undo_stack:
                    self.undo_stack.pop()
                self.log("分裂方向无效：请选择源液滴上下左右相邻电极，且反向电极也必须存在")
                return
            self._clear_planned_operation()
            self.log(
                "分裂方向 -> "
                f"{self._cell_label(self.split_left_cell)} / {self._cell_label(self.split_right_cell)}"
            )
        elif tool in (self.TOOL_MOVE_GOAL, self.TOOL_MERGE_POINT):
            self._push_undo_snapshot()
            self.goal_cell = cell
            self._clear_planned_operation()
            label = "终点" if tool == self.TOOL_MOVE_GOAL else "混合点"
            self.log(f"{label} -> {self._cell_label(cell)}")
        elif tool == self.TOOL_MERGE_B:
            self._push_undo_snapshot()
            self.secondary_cell = cell
            self._clear_planned_operation()
            self._reset_droplets_for_operation()
            self.log(f"液滴B -> {self._cell_label(cell)}")
        elif tool == self.TOOL_SPLIT_LEFT:
            self.split_left_cell = cell
            self._clear_planned_operation()
            self.log(f"左子滴目标 -> {self._cell_label(cell)}")
        elif tool == self.TOOL_SPLIT_RIGHT:
            self.split_right_cell = cell
            self._clear_planned_operation()
            self.log(f"右子滴目标 -> {self._cell_label(cell)}")
        else:
            self.log("请选择路径任务，或切换到手动电极页直接开关电极")
            return

        self._update_cell_status(cell)
        self._draw_matrix_canvas()
        if self.is_simulation_mode():
            self._render_sim_camera_frame()

    def on_matrix_motion(self, event):
        self.matrix_canvas = event.widget
        cell = self._canvas_to_cell(event.x, event.y)
        if cell != self.hover_cell:
            self.hover_cell = cell
            self._draw_matrix_canvas()
        if cell is not None:
            self._update_cell_status(cell)

    def on_matrix_leave(self, event):
        self.matrix_canvas = event.widget
        self.hover_cell = None
        self._draw_matrix_canvas()

    def _update_cell_status(self, cell):
        if cell is None:
            return
        x_mm, y_mm = cell_center_mm(cell, self.pitch_mm)
        text = f"{self._cell_label(cell)} | 中心 ({x_mm:.1f}, {y_mm:.1f}) mm"
        labels = getattr(self, "cell_status_labels", [])
        if not labels and hasattr(self, "cell_status_label"):
            labels = [self.cell_status_label]
        for label in labels:
            if label.winfo_exists():
                label.config(text=text)

    def _cell_label(self, cell):
        row, col = cell
        suffix = " 储液池" if is_reservoir_cell(cell) else ""
        return f"R{row + 1:02d} C{col + 1:02d} / ID {electrode_id(row, col, self.cols)}{suffix}"
