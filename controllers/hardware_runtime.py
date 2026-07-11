"""STM32 serial transport, electrode commands, logging, and shutdown."""

from __future__ import annotations

from .common import HardwareProtocol, cell_from_electrode_id, electrode_id, messagebox, serial, time, tk


class HardwareRuntimeMixin:
    def _update_mode_ui(self):
        if self.is_simulation_mode():
            self.port_combobox.config(state="disabled")
            self.btn_refresh.config(state="disabled")
            self.btn_connect.config(state="disabled")
            self._set_connection_state(False)
            self.auto_status_label.config(text="闭环: 仿真待机", fg=self.colors["muted"])
        else:
            self.port_combobox.config(state="readonly")
            self.btn_refresh.config(state="normal")
            self.btn_connect.config(state="normal")
            self._set_connection_state(self.is_connected, self.port_combobox.get())
            self.auto_status_label.config(text="闭环: 实物待机（相机适配器未配置）", fg=self.colors["muted"])

    def _set_connection_state(self, connected, port_name=""):
        self.is_connected = connected
        if self.is_simulation_mode() and not connected:
            self.btn_connect.config(text="打开串口", bg=self.colors["accent"], activebackground=self.colors["accent_hover"])
            self.connection_badge.config(text="● 仿真模式", fg=self.colors["accent"])
        elif connected:
            self.btn_connect.config(text="关闭串口", bg=self.colors["success"], activebackground=self.colors["success_hover"])
            self.connection_badge.config(text=f"● 已连接 {port_name}", fg="#23695F")
        else:
            self.btn_connect.config(text="打开串口", bg=self.colors["accent"], activebackground=self.colors["accent_hover"])
            self.connection_badge.config(text="● 未连接", fg="#A33F3F")

    def _set_active_count(self, count):
        self.active_channels = count
        fg = self.colors["accent"] if count > 0 else self.colors["muted"]
        self.active_count_label.config(text=f"已开启 {count}/{self.total_channels}", fg=fg)

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combobox["values"] = ports
        if ports:
            current = self.port_combobox.get()
            if current not in ports and self.port_combobox.cget("state") != "disabled":
                self.port_combobox.current(0)
            self.log(f"检测到 {len(ports)} 个串口")
        else:
            self.port_combobox.set("")
            self.log("未检测到可用串口")

    def toggle_connection(self):
        if self.is_simulation_mode():
            self.log("仿真模式不需要打开串口")
            return

        if not self.is_connected:
            try:
                port = self.port_combobox.get()
                if not port:
                    messagebox.showwarning("提示", "请选择串口")
                    return
                self.ser = serial.Serial(port, 115200, timeout=0.5)
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass
                self._set_connection_state(True, port)
                if not self.electrode_transactions.all_off():
                    self.hardware_state_uncertain = True
                    self.log(f"连接到 {port}，但会话同步 ALL_OFF 未确认，已断开")
                    self.ser.close()
                    self._set_connection_state(False)
                    return
                self.hardware_state_uncertain = False
                self.hardware_auto_owned = False
                self._clear_local_electrode_display()
                self.log(f"成功连接到 {port}，STM32 已确认 ALL_OFF，会话序列已同步")
            except Exception as exc:
                messagebox.showerror("错误", str(exc))
        else:
            if self.ser:
                self.ser.close()
            self._set_connection_state(False)
            self.log("串口已断开")

    def send_command(self, command, log_send=True):
        if self.is_simulation_mode():
            if log_send:
                self.log(f"仿真执行 -> {command}")
            return True

        if self.is_connected and self.ser:
            full_cmd = command + "\r\n"
            try:
                self.ser.write(full_cmd.encode("utf-8"))
                if log_send:
                    self.log(f"发送 -> {command}")
                return True
            except Exception as exc:
                self.log(f"发送出错: {exc}")
                self.toggle_connection()
                return False

        if log_send:
            self.log(f"未发送(串口未连接) -> {command}")
        return False

    def _send_transaction_line(self, command):
        return self.send_command(command, log_send=False)

    def _submit_auto_electrode_changes(self, changes):
        if self.is_simulation_mode() or not changes:
            return True
        result = self.electrode_transactions.apply_changes(changes)
        if result.applied:
            self.hardware_auto_owned = True
            self.log_feedback(
                "批量提交",
                f"事务 {result.sequence} 已在扫描帧边界生效，尝试 {result.attempts} 次",
                key="electrode_transaction_applied",
                interval_s=0.2,
            )
            return True

        self.auto_running = False
        emergency_off = self.electrode_transactions.all_off()
        if emergency_off:
            self.hardware_state_uncertain = False
            self.hardware_auto_owned = False
            self._clear_local_electrode_display()
            status = "闭环: 通信失败，已安全全关"
        else:
            self.hardware_state_uncertain = True
            self.hardware_auto_owned = True
            status = "闭环: 通信中断，硬件状态未知"
        self.auto_status_label.config(text=status, fg=self.colors["danger"])
        self.log_feedback(
            "通信保护",
            f"事务 {result.sequence} 未确认生效：{result.error}；"
            + ("已确认 ALL_OFF" if emergency_off else "ALL_OFF 也未确认，禁止手动操作"),
            force=True,
        )
        return False

    def toggle_electrode(self, eid):
        if self.auto_running:
            self.log("闭环运行中，手动电极操作已忽略")
            return
        if self._hardware_manual_control_blocked():
            return
        current_state = self.buttons[eid]["state"]
        new_state = 1 if current_state == 0 else 0
        self._set_electrode_state(eid, new_state)

    def _active_electrode_ids(self):
        return {eid for eid, info in self.buttons.items() if info["state"] == 1}

    def _set_electrode_state(self, eid, state, log_send=True):
        if eid not in self.buttons:
            return
        if self._hardware_manual_control_blocked():
            return
        state = 1 if state else 0
        if self.buttons[eid]["state"] == state:
            return
        self.update_ui_only(eid, state)
        self.send_command(HardwareProtocol.set_electrode(eid, state), log_send=log_send)

    def manual_toggle_electrode(self, cell, additive=False):
        if self.auto_running:
            self.log("闭环运行中，手动电极操作已忽略")
            return
        if self._hardware_manual_control_blocked():
            return
        eid = electrode_id(cell[0], cell[1], self.cols)
        active_ids = self._active_electrode_ids()
        current_state = self.buttons[eid]["state"]

        if additive:
            self._set_electrode_state(eid, 0 if current_state else 1)
            return

        if current_state:
            self._set_electrode_state(eid, 0)
            return

        active_neighbor_ids = {
            active_id
            for active_id in active_ids
            if cell_from_electrode_id(active_id, self.cols) in self._manual_neighbor_cells(cell)
        }
        for active_id in sorted(active_neighbor_ids):
            self._set_electrode_state(active_id, 0)
        self._set_electrode_state(eid, 1)

    def _hardware_manual_control_blocked(self):
        if self.is_simulation_mode():
            return False
        if self.hardware_state_uncertain:
            self.log("硬件状态未知，禁止手动操作；请重新连接并确认 ALL_OFF")
            return True
        if self.hardware_auto_owned:
            self.log("PC 自动控制仍占有电极；请先全部关闭以释放手动控制")
            return True
        return False

    def _clear_local_electrode_display(self):
        for info in self.buttons.values():
            info["state"] = 0
        self.active_auto_cells = set()
        self._set_active_count(0)
        self._draw_matrix_canvas()

    def _release_hardware_auto_ownership(self):
        if self.is_simulation_mode() or not self.hardware_auto_owned:
            return True
        if not self.is_connected or not self.electrode_transactions.all_off():
            self.hardware_state_uncertain = True
            self.log("自动任务结束时 ALL_OFF 未确认，硬件状态未知并保持手动锁定")
            return False
        self.hardware_state_uncertain = False
        self.hardware_auto_owned = False
        self._clear_local_electrode_display()
        self.log("自动任务结束：STM32 已确认 ALL_OFF，手动控制已释放")
        return True

    def reset_all(self):
        if self.auto_running:
            self.stop_auto_control("全部关闭")
        self.log("正在关闭所有电极...")

        if not self.is_simulation_mode() and self.is_connected:
            if not self.electrode_transactions.all_off():
                self.hardware_state_uncertain = True
                self.hardware_auto_owned = True
                self.log("紧急 ALL_OFF 未收到确认，硬件电极状态未知")
                self.auto_status_label.config(text="闭环: 硬件状态未知", fg=self.colors["danger"])
                return
            self.hardware_state_uncertain = False
            self.hardware_auto_owned = False

        self._clear_local_electrode_display()

        if self.is_simulation_mode():
            self.log("仿真后端 -> 全部电极关闭")
            self._render_sim_camera_frame()
            return
        if not self.is_connected:
            self.log("串口未连接，仅关闭本地显示")
            return
        self.log("STM32 已确认紧急 ALL_OFF")

    def update_ui_only(self, eid, state):
        if eid not in self.buttons:
            return
        old_state = self.buttons[eid]["state"]
        self.buttons[eid]["state"] = 1 if state else 0
        if old_state != self.buttons[eid]["state"]:
            delta = 1 if self.buttons[eid]["state"] == 1 else -1
            new_count = max(0, min(self.total_channels, self.active_channels + delta))
            self._set_active_count(new_count)
        self._draw_matrix_canvas()

    def receive_data(self):
        while not self.stop_event.is_set():
            if self.is_connected and self.ser:
                try:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                        if line:
                            if self.electrode_transactions.feed_line(line):
                                if line.startswith("ERR:"):
                                    self.root.after(0, self.log, f"STM32 协议错误 <- {line}")
                            elif line.startswith("SYNC:"):
                                parts = line.split(":")
                                if len(parts) == 3:
                                    try:
                                        p_id = int(parts[1])
                                        p_state = int(parts[2])
                                        self.root.after(0, self.update_ui_only, p_id, p_state)
                                    except ValueError:
                                        self.root.after(0, self.log, f"同步数据格式错误: {line}")
                            else:
                                self.root.after(0, self.log, f"收到 <- {line}")
                except Exception as exc:
                    self.root.after(0, self.log, f"接收错误: {exc}")
                    time.sleep(1)
            time.sleep(0.01)

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def log_feedback(self, action, msg, key=None, interval_s=0.6, force=False):
        log_key = key or f"{action}:{msg}"
        now = time.monotonic()
        last = self.feedback_log_times.get(log_key, 0.0)
        if not force and now - last < interval_s:
            return
        self.feedback_log_times[log_key] = now
        self.log(f"修正反馈[{action}] {msg}")

    def on_close(self):
        self.stop_event.set()
        self.auto_running = False
        self.camera_running = False
        for after_id in (self.auto_after_id, self.camera_after_id, self.manual_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
        if self.ser and self.ser.is_open:
            self.ser.close()
        if self.camera_thread:
            self.camera_thread.join(timeout=1)
        self.root.destroy()
