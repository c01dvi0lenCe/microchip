"""Chapter 1 oscilloscope test controls added alongside the existing workflows."""

from __future__ import annotations

from .common import messagebox, tk, ttk
from .scope_test_client import H4_PHASES, SCAN_TEST_FREQUENCIES_HZ, SCOPE_TEST_MODES, ScopeTestConfig


class ScopeValidationControllerMixin:
    SCOPE_MODE_OPTIONS = tuple(SCOPE_TEST_MODES)

    def _build_scope_validation_page(self, parent):
        card = tk.Frame(parent, bg=self.colors["panel"], bd=1, relief="solid")
        card.pack(fill="both", expand=True)

        tk.Label(
            card,
            text="第一章硬件示波器测试",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=(self.font_family, 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 2))

        tk.Label(
            card,
            text="测试期间固件独占ROW/COL；停止后全关并恢复正常20×21扫描。外部高压上限按本实验30 V设置。",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        form = tk.Frame(card, bg=self.colors["panel"])
        form.pack(fill="x", padx=14)

        tk.Label(form, text="测试模式", bg=self.colors["panel"], fg=self.colors["text"]).grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.scope_mode_combobox = ttk.Combobox(
            form,
            width=27,
            state="readonly",
            textvariable=self.scope_test_mode_var,
            values=self.SCOPE_MODE_OPTIONS,
        )
        self.scope_mode_combobox.grid(row=0, column=1, columnspan=3, sticky="w", padx=(8, 24), pady=5)
        self.scope_mode_combobox.bind("<<ComboboxSelected>>", self.on_scope_config_changed)

        tk.Label(form, text="H4写入相位", bg=self.colors["panel"], fg=self.colors["text"]).grid(
            row=0, column=4, sticky="w", pady=5
        )
        self.scope_phase_combobox = ttk.Combobox(
            form,
            width=16,
            state="readonly",
            textvariable=self.scope_test_phase_var,
            values=H4_PHASES,
        )
        self.scope_phase_combobox.grid(row=0, column=5, sticky="w", padx=(8, 0), pady=5)
        self.scope_phase_combobox.bind("<<ComboboxSelected>>", self.on_scope_config_changed)

        tk.Label(form, text="扫描频率", bg=self.colors["panel"], fg=self.colors["text"]).grid(
            row=3, column=0, sticky="w", pady=5
        )
        self.scope_frequency_combobox = ttk.Combobox(
            form,
            width=10,
            state="disabled",
            textvariable=self.scope_test_frequency_var,
            values=SCAN_TEST_FREQUENCIES_HZ,
        )
        self.scope_frequency_combobox.grid(row=3, column=1, sticky="w", padx=(8, 4), pady=5)
        self.scope_frequency_combobox.bind("<<ComboboxSelected>>", self.on_scope_config_changed)
        tk.Label(form, text="Hz", bg=self.colors["panel"], fg=self.colors["muted"]).grid(
            row=3, column=2, sticky="w", pady=5
        )

        self.scope_target_widgets = []
        self._build_scope_target_row(form, 1, "像素A", self.scope_test_row_var, self.scope_test_col_var)
        self._build_scope_target_row(form, 2, "相邻像素B", self.scope_test_row_b_var, self.scope_test_col_b_var)

        for col in range(6):
            form.grid_columnconfigure(col, weight=1 if col in (1, 3, 5) else 0)

        timing = tk.Frame(card, bg=self.colors["panel_alt"], bd=1, relief="solid")
        timing.pack(fill="x", padx=14, pady=(14, 8))

        tk.Label(
            timing,
            text="接线与时序",
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", padx=10, pady=(8, 3))
        self.scope_instruction_label = tk.Label(
            timing,
            text="",
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            justify="left",
            anchor="w",
            wraplength=690,
            font=(self.font_family, 9),
        )
        self.scope_instruction_label.pack(fill="x", padx=10, pady=(0, 8))

        self.scope_sync_warning_label = tk.Label(
            card,
            text="",
            bg=self.colors["panel"],
            fg=self.colors["danger"],
            justify="left",
            anchor="w",
            wraplength=690,
            font=(self.font_family, 9, "bold"),
        )
        self.scope_sync_warning_label.pack(fill="x", padx=14, pady=(2, 8))

        action_row = tk.Frame(card, bg=self.colors["panel"])
        action_row.pack(fill="x", padx=14, pady=(4, 8))
        self.btn_scope_start = self._make_button(
            action_row,
            "启动测试波形",
            self.start_scope_test,
            self.colors["accent"],
            "white",
        )
        self.btn_scope_start.pack(side="left")
        self.btn_scope_stop = self._make_button(
            action_row,
            "停止并全关",
            self.stop_scope_test,
            self.colors["danger"],
            "white",
        )
        self.btn_scope_stop.pack(side="left", padx=(8, 0))

        self.scope_status_label = tk.Label(
            action_row,
            text="测试: 待机",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9, "bold"),
        )
        self.scope_status_label.pack(side="right")

        tk.Label(
            card,
            text="示波器数据录入与文件上传按你的安排后续加入；本页当前只负责选择、启动和停止稳定测试模式。",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=(self.font_family, 9),
        ).pack(anchor="w", padx=14, pady=(0, 12))

        self.on_scope_config_changed()

    def _build_scope_target_row(self, parent, grid_row, title, row_var, col_var):
        tk.Label(parent, text=title, bg=self.colors["panel"], fg=self.colors["text"]).grid(
            row=grid_row, column=0, sticky="w", pady=5
        )
        tk.Label(parent, text="ROW", bg=self.colors["panel"], fg=self.colors["muted"]).grid(
            row=grid_row, column=1, sticky="e", pady=5
        )
        row_box = tk.Spinbox(
            parent,
            from_=1,
            to=20,
            width=5,
            textvariable=row_var,
            command=self.on_scope_config_changed,
        )
        row_box.grid(row=grid_row, column=2, sticky="w", padx=(6, 18), pady=5)
        row_box.bind("<KeyRelease>", self.on_scope_config_changed)

        tk.Label(parent, text="COL", bg=self.colors["panel"], fg=self.colors["muted"]).grid(
            row=grid_row, column=3, sticky="e", pady=5
        )
        col_box = tk.Spinbox(
            parent,
            from_=1,
            to=21,
            width=5,
            textvariable=col_var,
            command=self.on_scope_config_changed,
        )
        col_box.grid(row=grid_row, column=4, sticky="w", padx=(6, 18), pady=5)
        col_box.bind("<KeyRelease>", self.on_scope_config_changed)

        id_label = tk.Label(parent, text="ID --", bg=self.colors["panel"], fg=self.colors["accent"])
        id_label.grid(row=grid_row, column=5, sticky="w", pady=5)
        self.scope_target_widgets.append((row_box, col_box, id_label))

    def _scope_test_config(self):
        mode_label = self.scope_test_mode_var.get()
        return ScopeTestConfig(
            mode=SCOPE_TEST_MODES[mode_label],
            row=int(self.scope_test_row_var.get()),
            col=int(self.scope_test_col_var.get()),
            row_b=int(self.scope_test_row_b_var.get()),
            col_b=int(self.scope_test_col_b_var.get()),
            phase=self.scope_test_phase_var.get(),
            scan_frequency_hz=int(self.scope_test_frequency_var.get()),
        )

    def on_scope_config_changed(self, _event=None):
        try:
            config = self._scope_test_config()
            id_a = config.id_a
            id_b = config.id_b
            error = ""
            try:
                config.validate()
            except ValueError as exc:
                error = str(exc)
        except (KeyError, ValueError, tk.TclError):
            return

        self.scope_target_widgets[0][2].config(text=f"ID {id_a}")
        self.scope_target_widgets[1][2].config(text=f"ID {id_b}")
        is_h4 = config.mode == "H4"
        is_h5 = config.mode in {"H5A", "H5B"}
        is_retention = config.mode == "RET_ARRAY20"
        self.scope_phase_combobox.config(state="readonly" if is_h4 else "disabled")
        self.scope_frequency_combobox.config(state="readonly" if is_retention else "disabled")
        for widget in self.scope_target_widgets[1][:2]:
            widget.config(state="normal" if is_h5 else "disabled")

        self.scope_instruction_label.config(text=self._scope_instruction(config))
        warning = error
        if is_h4:
            warning = (
                (warning + "\n" if warning else "")
                + "H4相位是固件内部300 Hz参考相位；板上没有外部DC_PULSE同步输入，"
                "外部信号未同步时不能把结果认定为绝对HIGH/LOW相位。"
            )
        self.scope_sync_warning_label.config(text=warning)
        self._update_scope_controls_state()

    def _scope_instruction(self, config):
        if config.mode == "RET_ARRAY20":
            common = "正常TIM5 blank→COL加载→2 us建立→ROW驱动；20行逐行扫描，ROW高电平由行时隙自动计算。"
        else:
            common = "独立写入测试：ROW有效165 us；selected=COL高+ROW高，inactive=COL低+ROW高。"
        details = {
            "H3A": "探头接A的VOUT，下降沿触发。selected保持20 ms，再写inactive并保持20 ms。",
            "H3B": "探头接A的VOUT，上升沿触发。inactive保持20 ms，再写selected并保持20 ms。",
            "H3C": "探头接A的VOUT，约15 V上升沿触发。A始终selected，按300 Hz周期刷新。",
            "H4": f"探头接A的VOUT，当前写入相位为{config.phase}；inactive后至少保持10 ms。",
            "H5B": "探头接inactive像素B的VOUT。A selected、B inactive，以相同300 Hz周期重复。",
            "H5A": "探头接selected像素A的VOUT，作为H5耦合计算的主像素参考波形。",
            "H6": (
                "探头接A的VOUT−VREF，滚动/Auto连续采集2–5 s。selected保持37 ms并约3 ms刷新；"
                "首次inactive后6 ms不刷新，inactive总计24 ms，至少统计20次关断事件。"
            ),
            "RET_ARRAY20": (
                f"探头接A的VOUT；真实ROW1至ROW20循环扫描，帧频{config.scan_frequency_hz} Hz。"
                "A保持selected，其余419个像素inactive；稳定2 s后记录VSTORE/VOUT保持差异。"
            ),
        }
        if config.mode == "RET_ARRAY20":
            bus = "建议先使用固定直流母线；该设置只改变STM32扫描帧频，不控制外部高压母线。"
        elif config.mode in {"H3C", "H4", "H5A", "H5B", "H6"}:
            bus = "0/30 V、300 Hz、50%母线必须由外部脉冲电源提供。"
        else:
            bus = "DC_PULSE由外部直流电源提供，当前实验条件不超过30 V。"
        return f"{details[config.mode]}\n{common}\n{bus}"

    def _update_scope_controls_state(self):
        if not hasattr(self, "btn_scope_start"):
            return
        connected = (not self.is_simulation_mode()) and self.is_connected
        self.btn_scope_start.config(state="normal" if connected and not self.scope_test_running else "disabled")
        self.btn_scope_stop.config(state="normal" if connected and self.scope_test_running else "disabled")
        if hasattr(self, "scope_frequency_combobox"):
            retention_selected = SCOPE_TEST_MODES.get(self.scope_test_mode_var.get()) == "RET_ARRAY20"
            self.scope_frequency_combobox.config(
                state="readonly" if retention_selected and not self.scope_test_running else "disabled"
            )

    def start_scope_test(self):
        if self.is_simulation_mode() or not self.is_connected:
            self.log("第一章测试需要切换到实物模式并打开串口")
            return False
        if self.auto_running:
            self.log("自动闭环运行中，不能启动示波器测试")
            return False
        if self.hardware_state_uncertain or self.hardware_auto_owned:
            self.log("当前硬件状态未释放，请先执行全部关闭再启动测试")
            return False

        try:
            config = self._scope_test_config()
            config.validate()
        except (KeyError, ValueError, tk.TclError) as exc:
            messagebox.showwarning("测试配置无效", str(exc))
            return False

        result = self.scope_test_client.start(config)
        if not result.ok:
            failure = result.response or result.error or "未知错误"
            self.scope_status_label.config(text=f"测试: 启动失败（{failure}）", fg=self.colors["danger"])
            self.log(f"第一章测试启动失败：{result.error}")
            return False

        self.scope_test_running = True
        self.hardware_auto_owned = True
        self.hardware_state_uncertain = False
        self._clear_local_electrode_display()
        frequency_suffix = f"，设定{config.scan_frequency_hz} Hz" if config.mode == "RET_ARRAY20" else ""
        if config.mode == "RET_ARRAY20":
            response_parts = getattr(result, "response", "").split(":")
            if len(response_parts) == 8 and response_parts[:4] == ["ACK", "CH1", "START", "RET_ARRAY20"]:
                actual_hz, frame_us, row_slot_us, row_on_us = response_parts[4:]
                frequency_suffix = (
                    f"，{actual_hz} Hz / 帧{frame_us} us / 行{row_slot_us} us / ROW高{row_on_us} us"
                )
        self.scope_status_label.config(
            text=f"测试: {config.mode}运行中，A=ID{config.id_a}{frequency_suffix}",
            fg=self.colors["success"],
        )
        self.log(
            f"第一章测试已启动：{config.mode}，A=ID{config.id_a}，B=ID{config.id_b}"
            f"{frequency_suffix}"
        )
        self._update_scope_controls_state()
        return True

    def stop_scope_test(self):
        if not self.scope_test_running:
            return True
        if not self.is_connected:
            self.hardware_state_uncertain = True
            self.scope_status_label.config(text="测试: 连接中断，状态未知", fg=self.colors["danger"])
            return False

        result = self.scope_test_client.stop()
        if not result.ok:
            self.hardware_state_uncertain = True
            self.scope_status_label.config(text="测试: 停止未确认", fg=self.colors["danger"])
            self.log(f"第一章测试停止未确认：{result.error}")
            return False

        self.scope_test_running = False
        self.hardware_auto_owned = False
        self.hardware_state_uncertain = False
        self._clear_local_electrode_display()
        self.scope_status_label.config(text="测试: 已停止并全关", fg=self.colors["muted"])
        self.log("第一章测试已停止，STM32已全关并恢复正常扫描")
        self._update_scope_controls_state()
        return True
