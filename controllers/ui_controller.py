"""Tkinter layout and operation-specific control visibility."""

from __future__ import annotations

from .common import messagebox, tk, ttk


class UiControllerMixin:
    def _configure_window(self):
        self.root.title(f"数字微流控视觉平台 - {self.rows}x{self.cols} 仿真上位机")
        self.root.geometry("1360x820")
        self.root.minsize(1180, 760)
        self.root.resizable(True, True)
        self.root.configure(bg=self.colors["bg"])

    def _build_ui(self):
        self._build_header()

        content = tk.Frame(self.root, bg=self.colors["bg"])
        content.pack(fill="both", expand=True, padx=10, pady=8)

        self._build_control_card(content)
        self.cell_status_labels = []
        self.matrix_legends = {}

        self.main_splitter = tk.PanedWindow(
            content,
            orient="horizontal",
            bg=self.colors["bg"],
            sashwidth=6,
            sashrelief="flat",
            bd=0,
        )
        self.main_splitter.pack(fill="both", expand=True)

        left_panel = tk.Frame(self.main_splitter, bg=self.colors["bg"])
        left_panel.pack(fill="both", expand=True)

        self.main_notebook = ttk.Notebook(left_panel)
        manual_page = tk.Frame(self.main_notebook, bg=self.colors["bg"])
        auto_page = tk.Frame(self.main_notebook, bg=self.colors["bg"])
        scope_test_page = tk.Frame(self.main_notebook, bg=self.colors["bg"])
        self.main_notebook.add(manual_page, text="手动电极")
        self.main_notebook.add(auto_page, text="自动化路径规划")
        self.main_notebook.add(scope_test_page, text="第一章硬件测试")

        self.manual_matrix_card, self.manual_canvas = self._build_matrix_card(
            manual_page,
            "手动电极阵列",
            "手动页：只显示电极开关状态，点击任意电极切换开关",
            manual=True,
        )
        self.manual_matrix_card.pack(fill="both", expand=True)

        self._build_auto_control_card(auto_page)
        self.path_matrix_card, self.path_canvas = self._build_matrix_card(
            auto_page,
            f"{self.rows}x{self.cols} 自动化路径规划画布",
            "自动页：点击画布设置当前路径任务点、储液池、目标电极或障碍物",
            manual=False,
        )
        self.path_matrix_card.pack(fill="both", expand=True)

        self._build_scope_validation_page(scope_test_page)

        self.matrix_canvases = [self.manual_canvas, self.path_canvas]
        self.matrix_canvas = self.manual_canvas

        self.main_notebook.pack(fill="both", expand=True)

        right_panel = tk.Frame(self.main_splitter, bg=self.colors["bg"])
        self.right_splitter = tk.PanedWindow(
            right_panel,
            orient="vertical",
            bg=self.colors["bg"],
            sashwidth=6,
            sashrelief="flat",
            bd=0,
        )
        self.right_splitter.pack(fill="both", expand=True)

        self.camera_card = self._build_camera_card(self.right_splitter)
        self.log_card = self._build_log_card(self.right_splitter)
        self.right_splitter.add(self.camera_card, minsize=430, stretch="always")
        self.right_splitter.add(self.log_card, minsize=150, stretch="always")

        self.main_splitter.add(left_panel, minsize=740, stretch="always")
        self.main_splitter.add(right_panel, minsize=460, stretch="always")
        self.root.after(120, self._set_default_sash)

    def _set_default_sash(self):
        total_w = self.main_splitter.winfo_width()
        if total_w > 0:
            self.main_splitter.sash_place(0, int(total_w * 0.57), 0)

    def _build_header(self):
        header = tk.Frame(self.root, bg=self.colors["header_bg"], height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=self.colors["header_bg"])
        left.pack(side="left", fill="y", padx=14)

        self.title_label = tk.Label(
            left,
            text="数字微流控视觉平台",
            bg=self.colors["header_bg"],
            fg=self.colors["header_text"],
            font=(self.font_family, 14, "bold"),
        )
        self.title_label.pack(anchor="w", pady=(11, 0))

        self.connection_badge = tk.Label(
            header,
            text="● 仿真模式",
            bg=self.colors["header_bg"],
            fg=self.colors["accent"],
            font=(self.font_family, 11, "bold"),
            padx=14,
        )
        self.connection_badge.pack(side="right")

    def _build_control_card(self, parent):
        card = tk.Frame(parent, bg=self.colors["panel"], bd=1, relief="solid")
        card.pack(fill="x", pady=(0, 6))

        tk.Label(
            card,
            text="系统控制",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", padx=10, pady=(6, 2))

        row = tk.Frame(card, bg=self.colors["panel"])
        row.pack(fill="x", padx=10, pady=(0, 4))

        tk.Label(row, text="运行模式", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.mode_combobox = ttk.Combobox(
            row,
            width=8,
            state="readonly",
            textvariable=self.mode_var,
            values=("仿真", "实物"),
        )
        self.mode_combobox.pack(side="left", padx=(6, 12))
        self.mode_combobox.bind("<<ComboboxSelected>>", self.on_mode_changed)

        tk.Label(row, text="串口端口", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.port_combobox = ttk.Combobox(row, width=14, state="readonly")
        self.port_combobox.pack(side="left", padx=(6, 6))

        self.btn_refresh = self._make_button(row, "刷新", self.refresh_ports, self.colors["btn_off"], self.colors["text"])
        self.btn_refresh.pack(side="left")

        self.btn_connect = self._make_button(row, "打开串口", self.toggle_connection, self.colors["accent"], "white")
        self.btn_connect.pack(side="left", padx=(8, 0))

        self.btn_reset = self._make_button(row, "全部关闭", self.reset_all, self.colors["danger"], "white")
        self.btn_reset.config(activebackground=self.colors["danger_hover"])
        self.btn_reset.pack(side="right")

        self.active_count_label = tk.Label(
            row,
            text="已开启 0/0",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9, "bold"),
        )
        self.active_count_label.pack(side="right", padx=(0, 10))

    def _build_auto_control_card(self, parent):
        card = tk.Frame(parent, bg=self.colors["panel"], bd=1, relief="solid")
        card.pack(fill="x", pady=(0, 6))

        tk.Label(
            card,
            text="自动化路径规划",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", padx=10, pady=(6, 2))

        auto_row = tk.Frame(card, bg=self.colors["panel"])
        auto_row.pack(fill="x", padx=10, pady=(0, 4))

        tk.Label(auto_row, text="操作类型", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.operation_combobox = ttk.Combobox(
            auto_row,
            width=6,
            state="readonly",
            textvariable=self.operation_var,
            values=(self.OP_MOVE, self.OP_MERGE, self.OP_SPLIT, self.OP_MULTI, self.OP_LOOP),
        )
        self.operation_combobox.pack(side="left", padx=(6, 10))
        self.operation_combobox.bind("<<ComboboxSelected>>", self.on_operation_changed)

        self.mixing_cycles_frame = tk.Frame(auto_row, bg=self.colors["panel"])
        tk.Label(self.mixing_cycles_frame, text="混合圈数", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.mixing_cycles_spinbox = tk.Spinbox(
            self.mixing_cycles_frame,
            from_=1,
            to=10,
            width=3,
            textvariable=self.mixing_cycles_var,
            command=self._sync_mixing_cycles,
            font=(self.font_family, 9),
        )
        self.mixing_cycles_spinbox.pack(side="left", padx=(6, 0))

        self.loop_cycles_frame = tk.Frame(auto_row, bg=self.colors["panel"])
        tk.Label(self.loop_cycles_frame, text="循环圈数", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.loop_cycles_spinbox = tk.Spinbox(
            self.loop_cycles_frame,
            from_=1,
            to=9999,
            width=5,
            textvariable=self.loop_cycles_var,
            command=self._sync_loop_cycles,
            font=(self.font_family, 9),
        )
        self.loop_cycles_spinbox.pack(side="left", padx=(6, 0))
        tk.Label(self.loop_cycles_frame, text="间隔(s)", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left", padx=(8, 0))
        self.loop_interval_spinbox = tk.Spinbox(
            self.loop_cycles_frame,
            from_=0.0,
            to=60.0,
            increment=0.1,
            width=5,
            textvariable=self.loop_interval_s_var,
            command=self._sync_loop_interval_s,
            font=(self.font_family, 9),
        )
        self.loop_interval_spinbox.pack(side="left", padx=(6, 0))

        self.path_task_label = tk.Label(auto_row, text="路径任务", bg=self.colors["panel"], fg=self.colors["text"])
        self.path_task_label.pack(side="left")
        self.tool_combobox = ttk.Combobox(
            auto_row,
            width=11,
            state="readonly",
            textvariable=self.tool_var,
            values=self._tool_options_for_operation(),
        )
        self.tool_combobox.pack(side="left", padx=(6, 6))
        self._update_operation_specific_controls()

        self.btn_plan = self._make_button(auto_row, "规划路径", self.plan_path, self.colors["btn_off"], self.colors["text"])
        self.btn_plan.pack(side="left")

        self.btn_auto = self._make_button(auto_row, "开始闭环", self.start_auto_control, self.colors["success"], "white")
        self.btn_auto.config(activebackground=self.colors["success_hover"])
        self.btn_auto.pack(side="left", padx=(6, 0))

        self.btn_pause = self._make_button(auto_row, "暂停", self.pause_auto_control, self.colors["danger"], "white")
        self.btn_pause.config(activebackground=self.colors["danger_hover"])
        self.btn_pause.pack(side="left", padx=(6, 0))

        self.auto_status_label = tk.Label(
            auto_row,
            text="闭环: 待机",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9, "bold"),
        )
        self.auto_status_label.pack(side="right")

        step_row = tk.Frame(card, bg=self.colors["panel"])
        step_row.pack(fill="x", padx=10, pady=(0, 4))

        tk.Label(step_row, text="步进调试", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.btn_step_back = self._make_button(step_row, "回退", self.step_debug_backward, self.colors["btn_off"], self.colors["text"])
        self.btn_step_back.pack(side="left", padx=(6, 0))

        self.btn_step_forward = self._make_button(step_row, "步进", self.step_debug_forward, self.colors["btn_off"], self.colors["text"])
        self.btn_step_forward.pack(side="left", padx=(6, 0))

        self.btn_reset_sim = self._make_button(step_row, "复位仿真", self.reset_simulation, self.colors["btn_off"], self.colors["text"])
        self.btn_reset_sim.pack(side="left", padx=(6, 0))

        self.btn_toggle_debug_tests = self._make_button(
            step_row,
            "显示测试",
            self.toggle_debug_tests,
            self.colors["btn_off"],
            self.colors["text"],
        )
        self.btn_toggle_debug_tests.pack(side="left", padx=(6, 0))

        sim_param_row = tk.Frame(card, bg=self.colors["panel"])
        sim_param_row.pack(fill="x", padx=10, pady=(0, 4))

        tk.Label(sim_param_row, text="仿真参数", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        tk.Label(sim_param_row, text="运动真实度", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left", padx=(10, 0))
        self.motion_profile_combobox = ttk.Combobox(
            sim_param_row,
            width=8,
            state="readonly",
            textvariable=self.motion_profile_var,
            values=("理想", "常规", "困难"),
        )
        self.motion_profile_combobox.pack(side="left", padx=(6, 10))

        tk.Label(sim_param_row, text="视觉噪声", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.vision_noise_combobox = ttk.Combobox(
            sim_param_row,
            width=8,
            state="readonly",
            textvariable=self.vision_noise_var,
            values=("关闭", "轻微", "强噪声"),
        )
        self.vision_noise_combobox.pack(side="left", padx=(6, 10))

        tk.Label(sim_param_row, text="故障模式", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.fault_mode_combobox = ttk.Combobox(
            sim_param_row,
            width=14,
            state="readonly",
            textvariable=self.fault_mode_var,
            values=("无", "随机卡滞", "指定弱故障电极"),
        )
        self.fault_mode_combobox.pack(side="left", padx=(6, 10))

        self.btn_sim_param_help = self._make_button(
            sim_param_row,
            "参数说明",
            self.show_simulation_parameter_help,
            self.colors["btn_off"],
            self.colors["text"],
        )
        self.btn_sim_param_help.pack(side="left", padx=(0, 10))

        self.metrics_label = tk.Label(
            sim_param_row,
            text="指标: 0 步 / 0 次重规划",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9, "bold"),
        )
        self.metrics_label.pack(side="right")

        self.btn_export_metrics = self._make_button(
            sim_param_row,
            "导出指标",
            self.export_metrics_csv,
            self.colors["btn_off"],
            self.colors["text"],
        )
        self.btn_export_metrics.pack(side="right", padx=(6, 0))

        self.btn_clear_metrics = self._make_button(
            sim_param_row,
            "清空指标",
            self.clear_metrics,
            self.colors["btn_off"],
            self.colors["text"],
        )
        self.btn_clear_metrics.pack(side="right", padx=(6, 0))

        self.debug_test_row = tk.Frame(card, bg=self.colors["panel"])

        tk.Label(self.debug_test_row, text="仿真故障测试", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.btn_dropout = self._make_button(self.debug_test_row, "丢帧测试", self.simulate_detection_dropout, self.colors["btn_off"], self.colors["text"])
        self.btn_dropout.pack(side="left", padx=(6, 0))

        self.btn_drift = self._make_button(self.debug_test_row, "跑偏测试", self.simulate_drift_fault, self.colors["btn_off"], self.colors["text"])
        self.btn_drift.pack(side="left", padx=(6, 0))

        self.btn_fusion = self._make_button(self.debug_test_row, "融合测试", self.simulate_fusion_fault, self.colors["btn_off"], self.colors["text"])
        self.btn_fusion.pack(side="left", padx=(6, 0))

        self.btn_split_fail = self._make_button(self.debug_test_row, "分裂失败测试", self.simulate_split_failure_fault, self.colors["btn_off"], self.colors["text"])
        self.btn_split_fail.pack(side="left", padx=(6, 0))

        self.cleanup_row = tk.Frame(card, bg=self.colors["panel"])
        self.cleanup_row.pack(fill="x", padx=10, pady=(0, 8))

        tk.Label(self.cleanup_row, text="目标/储液池清理", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
        self.btn_undo_shape = self._make_button(self.cleanup_row, "撤销目标", self.undo_target_shape, self.colors["btn_off"], self.colors["text"])
        self.btn_undo_shape.pack(side="left", padx=(6, 0))

        self.btn_clear_shape = self._make_button(self.cleanup_row, "清空目标", self.clear_target_shape, self.colors["btn_off"], self.colors["text"])
        self.btn_clear_shape.pack(side="left", padx=(6, 0))

        self.btn_clear_load = self._make_button(self.cleanup_row, "清空储液池", self.clear_loaded_reservoirs, self.colors["btn_off"], self.colors["text"])
        self.btn_clear_load.pack(side="left", padx=(6, 0))

        self.btn_clear_initial = self._make_button(self.cleanup_row, "清空初始", self.clear_initial_droplets, self.colors["btn_off"], self.colors["text"])
        self.btn_clear_initial.pack(side="left", padx=(6, 0))

        self.btn_clear_obstacles = self._make_button(self.cleanup_row, "清空障碍", self.clear_obstacles, self.colors["btn_off"], self.colors["text"])
        self.btn_clear_obstacles.pack(side="left", padx=(6, 0))

        self.btn_save_preset = self._make_button(self.cleanup_row, "保存设置", self.save_settings_preset, self.colors["btn_off"], self.colors["text"])
        self.btn_save_preset.pack(side="right", padx=(6, 0))

        self.btn_load_preset = self._make_button(self.cleanup_row, "导入设置", self.load_settings_preset, self.colors["btn_off"], self.colors["text"])
        self.btn_load_preset.pack(side="right", padx=(6, 0))

    def _simulation_parameter_help_text(self):
        return "\n".join(
            [
                "1. 运动真实度",
                "   理想：用于功能演示，液滴稳定按规划电极移动。",
                "   常规：加入轻微响应延迟和偏移，更接近真实实验。",
                "   困难：加入更强卡滞、过冲和偏移，用于压力测试。",
                "",
                "2. 视觉噪声",
                "   关闭：仿真调试优先，正常情况下不应丢检。",
                "   轻微：模拟少量丢帧和质心抖动，验证闭环鲁棒性。",
                "   强噪声：模拟强反光、低对比和持续丢帧，用于故障演示。",
                "",
                "3. 故障模式",
                "   无：不主动注入故障。",
                "   随机卡滞：随机让部分步进变慢或卡住。",
                "   指定弱故障电极：把你设置的障碍/弱故障区用于纠偏测试。",
                "",
                "4. 异常保护",
                "   短时漏检：保持当前电极，等待视觉恢复。",
                "   超时漏检、疑似融合、严重跑偏或无法安全调度：进入保护暂停。",
                "   保护暂停后可复位、回退、重新规划或清空故障后再启动。",
            ]
        )

    def show_simulation_parameter_help(self):
        messagebox.showinfo("仿真参数说明", self._simulation_parameter_help_text())

    def toggle_debug_tests(self):
        self.debug_tests_visible = not self.debug_tests_visible
        if self.debug_tests_visible:
            self.debug_test_row.pack(fill="x", padx=10, pady=(0, 4), before=self.cleanup_row)
            self.btn_toggle_debug_tests.config(text="隐藏测试")
        else:
            self.debug_test_row.pack_forget()
            self.btn_toggle_debug_tests.config(text="显示测试")

    def _make_button(self, parent, text, command, bg, fg):
        hover = self.colors["accent_hover"] if fg == "white" else self.colors["btn_off_hover"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            font=(self.font_family, 9, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            activebackground=hover,
            activeforeground=fg,
            cursor="hand2",
        )

    def _build_matrix_card(self, parent, title, hint, manual=False):
        card = tk.Frame(parent, bg=self.colors["panel"], bd=1, relief="solid")

        top = tk.Frame(card, bg=self.colors["panel"])
        top.pack(fill="x", padx=10, pady=(6, 4))

        tk.Label(
            top,
            text=title,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")

        cell_status_label = tk.Label(
            top,
            text=hint,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9, "bold"),
        )
        cell_status_label.pack(side="right")
        self.cell_status_labels.append(cell_status_label)

        if manual:
            manual_tools = tk.Frame(card, bg=self.colors["panel"])
            manual_tools.pack(fill="x", padx=10, pady=(0, 4))

            tk.Label(manual_tools, text="手动工具", bg=self.colors["panel"], fg=self.colors["text"]).pack(side="left")
            self.manual_tool_combobox = ttk.Combobox(
                manual_tools,
                width=10,
                state="readonly",
                textvariable=self.manual_tool_var,
                values=(self.MANUAL_TOOL_TOGGLE, self.MANUAL_TOOL_DROPLET),
            )
            self.manual_tool_combobox.pack(side="left", padx=(6, 6))

            self.btn_clear_manual_droplet = self._make_button(
                manual_tools,
                "清空液滴",
                self.clear_manual_droplet,
                self.colors["btn_off"],
                self.colors["text"],
            )
            self.btn_clear_manual_droplet.pack(side="left")

        legend = tk.Frame(card, bg=self.colors["panel"])
        legend.pack(fill="x", padx=10, pady=(0, 4))
        self.matrix_legends["manual" if manual else "auto"] = legend
        self._refresh_matrix_legend(manual=manual)

        holder = tk.Frame(card, bg=self.colors["panel_alt"], bd=1, relief="solid")
        holder.pack(padx=8, pady=(0, 8))
        holder.pack_propagate(False)
        holder.config(width=660, height=610)

        canvas = tk.Canvas(holder, bg=self.colors["panel_alt"], width=650, height=600, highlightthickness=0)
        canvas.view_role = "manual" if manual else "auto"
        canvas.pack(padx=4, pady=4)
        canvas.bind("<Configure>", lambda _evt: self._draw_matrix_canvas())
        canvas.bind("<Button-1>", lambda event: self.on_matrix_click(event, manual=manual))
        canvas.bind("<Motion>", self.on_matrix_motion)
        canvas.bind("<Leave>", self.on_matrix_leave)
        return card, canvas

    def _legend_items_for_matrix(self, manual=False):
        if manual:
            return [
                ("液滴", self.colors["droplet_a"], "white"),
                ("储液池", self.colors["reservoir"], self.colors["text"]),
                ("障碍", self.colors["obstacle"], "white"),
                ("激活", self.colors["btn_on"], "white"),
            ]
        if self.operation_var.get() == self.OP_MERGE:
            droplet_items = [
                ("液滴A", self.colors["droplet_a"], "white"),
                ("液滴B", self.colors["droplet_b"], "white"),
            ]
        else:
            droplet_items = [("液滴", self.colors["droplet_a"], "white")]
        return droplet_items + [
            ("检测", self.colors["detected"], self.colors["text"]),
            ("路径", self.colors["path"], self.colors["text"]),
            ("障碍", self.colors["obstacle"], "white"),
            ("储液池", self.colors["reservoir"], self.colors["text"]),
            ("有液池", self.colors["reservoir_loaded"], self.colors["text"]),
            ("初始滴", self.colors["initial_droplet"], "white"),
            ("目标", self.colors["target_sample"], self.colors["text"]),
            ("激活", self.colors["btn_on"], "white"),
        ]

    def _refresh_matrix_legend(self, manual=False):
        legend = getattr(self, "matrix_legends", {}).get("manual" if manual else "auto")
        if legend is None:
            return
        for child in legend.winfo_children():
            child.destroy()
        for text, color, fg in self._legend_items_for_matrix(manual=manual):
            tk.Label(
                legend,
                text=text,
                bg=color,
                fg=fg,
                font=(self.font_family, 9, "bold"),
                padx=6,
                pady=1,
            ).pack(side="left", padx=(0, 6))

    def _is_manual_canvas(self, canvas=None):
        return getattr(canvas or getattr(self, "matrix_canvas", None), "view_role", "") == "manual"

    def _is_manual_page_selected(self):
        if not hasattr(self, "main_notebook"):
            return False
        try:
            selected = self.main_notebook.select()
            return bool(selected) and self.main_notebook.tab(selected, "text") == "手动电极"
        except tk.TclError:
            return False

    def _build_log_card(self, parent):
        card = tk.Frame(parent, bg=self.colors["panel"], bd=1, relief="solid")

        tk.Label(
            card,
            text="运行日志",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", padx=10, pady=(6, 4))

        log_container = tk.Frame(card, bg=self.colors["panel"])
        log_container.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        scrollbar = ttk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_container,
            height=5,
            state="disabled",
            yscrollcommand=scrollbar.set,
            bg=self.colors["log_bg"],
            fg=self.colors["log_text"],
            insertbackground=self.colors["log_text"],
            selectbackground="#D4DEE6",
            relief="solid",
            bd=1,
            font=(self.mono_font, 9),
            padx=8,
            pady=6,
        )
        self.log_text.pack(fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        return card

    def _build_camera_card(self, parent):
        card = tk.Frame(parent, bg=self.colors["panel"], bd=1, relief="solid")

        top = tk.Frame(card, bg=self.colors["panel"])
        top.pack(fill="x", padx=10, pady=(6, 2))

        tk.Label(
            top,
            text="视觉反馈",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")

        self.btn_camera = self._make_button(top, "开启预览", self.toggle_camera, self.colors["accent"], "white")
        self.btn_camera.pack(side="right")

        camera_container = tk.Frame(card, bg=self.colors["panel_alt"], bd=1, relief="solid")
        camera_container.pack(padx=8, pady=(0, 8))
        camera_container.pack_propagate(False)
        camera_container.config(width=560, height=560)

        self.camera_label = tk.Label(
            camera_container,
            bg=self.colors["panel_alt"],
            text="仿真视觉预览未开启",
            font=(self.font_family, 11),
            fg=self.colors["muted"],
        )
        self.camera_label.pack(fill="both", expand=True)
        return card

    def is_simulation_mode(self):
        return self.mode_var.get() == "仿真"

    def on_mode_changed(self, _event=None):
        if self.auto_running:
            self.stop_auto_control("切换运行模式，闭环已停止")
        if self.camera_running:
            self.stop_camera()
        if self.is_connected and self.is_simulation_mode():
            if self.ser:
                self.ser.close()
            self._set_connection_state(False)
            self.log("已切换到仿真模式，串口连接已关闭")
        self._update_mode_ui()

    def on_operation_changed(self, _event=None):
        if self.auto_running:
            self.stop_auto_control("切换操作类型")
        if self.operation_var.get() == self.OP_SPLIT and not self._valid_split_triplet():
            self._set_default_split_targets()
        self._reset_droplets_for_operation()
        self._update_tool_options()
        self._update_operation_specific_controls()
        self._refresh_matrix_legend(manual=False)
        self.path = []
        self.merge_path_b = []
        self.mixing_path = []
        self.mixing_index = 0
        self.mixing_active = False
        self.operation_paths = []
        self.operation_path_cells = set()
        self.path_index = 0
        self.path_index_b = 0
        self.loop_cycles_completed = 0
        self.current_target_cell = None
        self.current_target_cell_b = None
        self.auto_status_label.config(text=f"闭环: {self.operation_var.get()}待机", fg=self.colors["muted"])
        self.log(f"操作类型 -> {self.operation_var.get()}")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def _tool_options_for_operation(self):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            return (
                self.TOOL_MULTI_LOAD,
                self.TOOL_MULTI_INITIAL,
                self.TOOL_MULTI_SHAPE,
                self.TOOL_OBSTACLE,
            )
        if operation == self.OP_MERGE:
            return (
                self.TOOL_MERGE_A,
                self.TOOL_MERGE_B,
                self.TOOL_MERGE_POINT,
                self.TOOL_OBSTACLE,
            )
        if operation == self.OP_SPLIT:
            return (
                self.TOOL_SPLIT_SOURCE,
                self.TOOL_SPLIT_DIRECTION,
            )
        if operation == self.OP_LOOP:
            return (
                self.TOOL_LOOP_START,
                self.TOOL_LOOP_PATH,
            )
        return (
            self.TOOL_MOVE_START,
            self.TOOL_MOVE_GOAL,
            self.TOOL_OBSTACLE,
        )

    def _update_tool_options(self):
        options = self._tool_options_for_operation()
        self.tool_combobox["values"] = options
        if self.tool_var.get() not in options:
            self.tool_var.set(options[0])

    def _update_operation_specific_controls(self):
        if not hasattr(self, "mixing_cycles_frame"):
            return
        if self.operation_var.get() == self.OP_MERGE:
            if not self.mixing_cycles_frame.winfo_manager():
                self.mixing_cycles_frame.pack(side="left", padx=(0, 10), before=self.path_task_label)
        else:
            self.mixing_cycles_frame.pack_forget()
        if self.operation_var.get() == self.OP_LOOP:
            if not self.loop_cycles_frame.winfo_manager():
                self.loop_cycles_frame.pack(side="left", padx=(0, 10), before=self.path_task_label)
        else:
            self.loop_cycles_frame.pack_forget()
