"""Simulation preview and the placeholder hardware-camera adapter."""

from __future__ import annotations

from .common import (
    CAMERA_DISPLAY_INTERVAL_S,
    CAMERA_PREVIEW_MAX_PX,
    HardwareProtocol,
    Image,
    ImageDraw,
    ImageFont,
    ImageTk,
    MATRIX_DISPLAY_INTERVAL_S,
    RESAMPLE_FILTER,
    messagebox,
    threading,
    time,
)


class CameraControllerMixin:
    def _render_sim_camera_frame(self, hide_droplet=False, force_display=True):
        if not hasattr(self, "camera_label"):
            return None
        context = self._camera_render_context()
        context["hide_droplet"] = hide_droplet or context["hide_droplet"]
        context["noise_profile"] = self._vision_noise_profile()
        frame = self.sim_camera.render(**context)
        detections = self.detector.detect_all(frame)
        if detections:
            self.latest_detections = detections
            self.detected_positions = [detection.grid_position for detection in detections]
            self.detected_cells = [detection.cell for detection in detections]
            self.detected_position = detections[0].grid_position
            self.detected_cell = detections[0].cell
        else:
            self.latest_detections = []
            self.detected_positions = []
            self.detected_cells = []
            self.detected_position = None
            self.detected_cell = None
        now = time.monotonic()
        if force_display or now - self.last_camera_display_time >= CAMERA_DISPLAY_INTERVAL_S:
            self._show_camera_frame(frame)
            self.last_camera_display_time = now
        if force_display or now - self.last_matrix_display_time >= MATRIX_DISPLAY_INTERVAL_S:
            self._draw_matrix_canvas()
            self.last_matrix_display_time = now
        return detections[0] if detections else None

    def _show_camera_frame(self, frame_rgb):
        image = Image.fromarray(frame_rgb)
        label_w = self.camera_label.winfo_width()
        label_h = self.camera_label.winfo_height()
        target_w = min(label_w if label_w > 8 else CAMERA_PREVIEW_MAX_PX, CAMERA_PREVIEW_MAX_PX)
        target_h = min(label_h if label_h > 8 else CAMERA_PREVIEW_MAX_PX, CAMERA_PREVIEW_MAX_PX)
        image.thumbnail((target_w, target_h), RESAMPLE_FILTER)
        photo = ImageTk.PhotoImage(image=image)
        self._update_camera_label(photo)

    def toggle_camera(self):
        if self.camera_running:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        if self.is_simulation_mode():
            self.camera_running = True
            self.btn_camera.config(text="关闭预览", bg=self.colors["danger"], activebackground=self.colors["danger_hover"])
            self.log("仿真视觉预览已开启")
            self._camera_preview_loop()
            return

        if not self.is_connected:
            messagebox.showwarning("提示", "请先连接 STM32 设备")
            return
        self.send_command(HardwareProtocol.camera_start())
        self.camera_running = True
        self.btn_camera.config(text="关闭预览", bg=self.colors["danger"], activebackground=self.colors["danger_hover"])
        self.camera_thread = threading.Thread(target=self.update_camera, daemon=True)
        self.camera_thread.start()
        self.log("STM32 摄像头预览已开启")

    def stop_camera(self):
        if self.auto_running:
            self.stop_auto_control("关闭视觉预览")
        if self.camera_after_id is not None:
            try:
                self.root.after_cancel(self.camera_after_id)
            except Exception:
                pass
            self.camera_after_id = None
        if not self.is_simulation_mode() and self.is_connected:
            self.send_command(HardwareProtocol.camera_stop())
        self.camera_running = False
        if self.camera_thread:
            self.camera_thread.join(timeout=1)
            self.camera_thread = None
        self.btn_camera.config(text="开启预览", bg=self.colors["accent"], activebackground=self.colors["accent_hover"])
        self.camera_label.config(image="", text="仿真视觉预览未开启", font=(self.font_family, 12), fg=self.colors["muted"])
        self.camera_label.image = None
        self.log("视觉预览已关闭")

    def _camera_preview_loop(self):
        if not self.camera_running or self.auto_running or not self.is_simulation_mode():
            return
        self._render_sim_camera_frame(force_display=False)
        self.camera_after_id = self.root.after(120, self._camera_preview_loop)

    def update_camera(self):
        while self.camera_running and self.is_connected and not self.stop_event.is_set():
            self.send_command(HardwareProtocol.camera_get(), log_send=False)
            image = self._generate_test_image()
            self.root.after(0, self._update_camera_from_image, image)
            time.sleep(0.2)

    def _generate_test_image(self):
        width, height = 640, 480
        image = Image.new("RGB", (width, height), color="white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = ImageFont.load_default()
        draw.text((18, 18), "Hardware camera interface placeholder", fill="black", font=font)
        draw.text((18, 48), f"Time: {time.strftime('%H:%M:%S')}", fill="black", font=font)
        draw.text((18, 78), "Use upper-computer OpenCV for closed-loop feedback", fill="black", font=font)
        return image

    def _update_camera_from_image(self, image):
        label_w = self.camera_label.winfo_width()
        label_h = self.camera_label.winfo_height()
        image = image.copy()
        target_w = min(label_w if label_w > 8 else CAMERA_PREVIEW_MAX_PX, CAMERA_PREVIEW_MAX_PX)
        target_h = min(label_h if label_h > 8 else CAMERA_PREVIEW_MAX_PX, CAMERA_PREVIEW_MAX_PX)
        image.thumbnail((target_w, target_h), RESAMPLE_FILTER)
        photo = ImageTk.PhotoImage(image=image)
        self._update_camera_label(photo)

    def _update_camera_label(self, photo):
        self.camera_label.config(image=photo, text="")
        self.camera_label.image = photo
