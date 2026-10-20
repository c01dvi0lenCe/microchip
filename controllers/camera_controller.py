"""Simulation preview and a PC-side industrial-camera adapter seam."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import Future

import cv2

from .common import (
    CAMERA_DISPLAY_INTERVAL_S,
    CAMERA_PREVIEW_MAX_PX,
    Image,
    ImageTk,
    MATRIX_DISPLAY_INTERVAL_S,
    RESAMPLE_FILTER,
    time,
)
from dmf.experiment.sources import LiveSource
from dmf.vision.config import load_yaml
from dmf.vision.image_io import write_image

CAMERA_MEDIA_ROOT = Path(r"D:\I\ZJU\有源矩阵\视觉-工业相机")


class CameraControllerMixin:
    def _camera_idle_text(self):
        if self.is_simulation_mode():
            return "仿真视觉预览未开启"
        if getattr(self, "hardware_camera_adapter", None) is None:
            return "MVS 工业相机待连接（USB3 直连电脑）"
        return "工业相机预览未开启"

    def _render_sim_camera_frame(self, hide_droplet=False, force_display=True):
        if self._experiment_active or self._experiment_page_selected():
            return None
        if not self.is_simulation_mode() or not hasattr(self, "camera_label"):
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
        target_w, target_h = self._camera_preview_target_size()
        image.thumbnail((target_w, target_h), RESAMPLE_FILTER)
        photo = ImageTk.PhotoImage(image=image, master=self.camera_label)
        self._update_camera_label(photo)


    def toggle_camera(self):
        if self.camera_running:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        if self._experiment_active or self._experiment_page_selected():
            return
        source = getattr(self, '_hardware_camera_source', None)
        if (self.camera_thread and self.camera_thread.is_alive()) or (source is not None and source.worker.is_alive()):
            self.log("相机正在关闭，请稍候再启动")
            return
        if self.is_simulation_mode():
            self.btn_camera_record.config(state="disabled")
            self.camera_running = True
            self.btn_camera.config(text="关闭预览", bg=self.colors["danger"], activebackground=self.colors["danger_hover"])
            self.log("仿真视觉预览已开启")
            self._camera_preview_loop()
            return

        adapter = getattr(self, "hardware_camera_adapter", None)
        if adapter is None:
            try:
                config_path = Path(__file__).resolve().parents[1] / "configs" / "camera_mvs.yaml"
                config = load_yaml(config_path)
                source_config = config["source"]
                self._hardware_camera_source = LiveSource(source_config,
                    electrode_stream=self.electrode_event_stream)
                self._hardware_camera_queue = queue.Queue(maxsize=1)
                self._hardware_camera_stop = threading.Event()
                self.camera_running = True
                self.btn_camera.config(text="关闭预览", bg=self.colors["danger"],
                                       activebackground=self.colors["danger_hover"])
                self.btn_camera_record.config(state="normal")
                self.btn_camera_photo.config(state="normal")
                self.camera_thread = threading.Thread(
                    target=self._hardware_camera_worker, daemon=True,
                    name="mvs-camera-preview",
                )
                self.camera_thread.start()
                self.camera_after_id = self.root.after(40, self._poll_hardware_camera)
                self.log(f"MVS 相机连接中：{config.get('camera_model', 'Hikrobot')}，"
                         f"序列号 {source_config.get('parameters', {}).get('serial_number', '自动选择')}")
            except Exception as exc:
                self.camera_running = False
                self.btn_camera_record.config(state="disabled")
                self.btn_camera_photo.config(state="disabled")
                self.camera_label.config(image="", text=f"相机启动失败：{exc}",
                                          font=(self.font_family, 11), fg=self.colors["danger"])
                self.camera_label.image = None
                self.log(f"MVS 相机预览启动失败：{exc}")
        else:
            self.log("检测到外部工业相机适配器；请使用 MVS 配置启动相机预览")

    def _hardware_camera_worker(self):
        source = self._hardware_camera_source
        try:
            while not self._hardware_camera_stop.is_set():
                try:
                    packet = next(source)
                except TimeoutError:
                    continue
                self._put_latest_camera_packet(packet)
        except Exception as exc:
            if not self._hardware_camera_stop.is_set():
                self._put_latest_camera_packet(exc)
        finally:
            source.close()

    def toggle_camera_recording(self):
        if getattr(self, "camera_recording", False):
            self._request_camera_recording_stop()
            return
        if not self.camera_running or self.is_simulation_mode():
            self.log("请先在实物模式开启工业相机预览，再开始录像")
            return
        path = self._camera_recording_output_path()
        self._submit_camera_recording_command("start_recording", path)

    @staticmethod
    def _camera_recording_output_path():
        now = datetime.now()
        folder = CAMERA_MEDIA_ROOT / "视频" / f"{now:%Y-%m-%d}"
        return folder / f"camera_{now:%Y%m%d_%H%M%S_%f}.avi"

    def take_camera_photo(self):
        if not self.camera_running or self.is_simulation_mode():
            self.log("请先在实物模式开启工业相机预览，再拍照")
            return
        frame = getattr(self, "latest_camera_frame_bgr", None)
        if frame is None:
            self.log("尚未收到相机画面，暂时不能拍照")
            return
        now = datetime.now()
        folder = CAMERA_MEDIA_ROOT / "照片" / f"{now:%Y-%m-%d}"
        path = folder / f"camera_{now:%Y%m%d_%H%M%S_%f}.png"
        self.btn_camera_photo.config(state="disabled")
        future = Future()

        def write_photo():
            try:
                if not write_image(path, frame):
                    raise OSError("OpenCV failed to write the image")
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(str(path))

        threading.Thread(target=write_photo, daemon=True, name="camera-photo-writer").start()
        self.root.after(40, lambda: self._poll_camera_photo(future))

    def _poll_camera_photo(self, future):
        if not future.done():
            self.root.after(40, lambda: self._poll_camera_photo(future))
            return
        try:
            path = future.result()
        except Exception as exc:
            self.log(f"拍照失败：{exc}")
        else:
            self.log(f"照片已保存：{path}")
        if self.camera_running:
            self.btn_camera_photo.config(state="normal")

    def _request_camera_recording_stop(self):
        self._submit_camera_recording_command("stop_recording")

    def _submit_camera_recording_command(self, method, *args):
        source = getattr(self, "_hardware_camera_source", None)
        if source is None:
            self.log("相机未连接，无法操作录像")
            return
        self.btn_camera_record.config(state="disabled")
        future = source.submit_camera_command(method, *args)
        self.root.after(40, lambda: self._poll_camera_recording_command(future, method))

    def _poll_camera_recording_command(self, future, method):
        if not future.done():
            self.root.after(40, lambda: self._poll_camera_recording_command(future, method))
            return
        try:
            path = future.result()
        except Exception as exc:
            self.camera_recording = False
            self.camera_recording_started_at = None
            self._cancel_camera_recording_timer()
            self.camera_recording_timer_label.config(text="录像失败")
            if self.camera_running:
                self.btn_camera_record.config(text="开始录像", state="normal")
            self.log(f"相机录像操作失败：{exc}")
            return
        if method == "start_recording":
            if not self.camera_running:
                self.log('预览已关闭，录像已在后台结束；请检查同目录的完整性记录')
                return
            self.camera_recording = True
            self.camera_recording_started_at = time.monotonic()
            self.camera_recording_elapsed_s = 0
            self._update_camera_recording_timer()
            self.btn_camera_record.config(text="停止录像", state="normal")
            self.log(f"开始录像：{path}")
        else:
            self.camera_recording = False
            if self.camera_recording_started_at is not None:
                self.camera_recording_elapsed_s = time.monotonic() - self.camera_recording_started_at
            self.camera_recording_started_at = None
            self._cancel_camera_recording_timer()
            self.camera_recording_timer_label.config(
                text=f"录像时长 {self._format_recording_duration(self.camera_recording_elapsed_s)}"
            )
            if self.camera_running:
                self.btn_camera_record.config(text="开始录像", state="normal")
            self.log(f"录像已保存：{path}")
            self.log("逐帧时间、电极命令/ACK及帧状态对照已保存到录像同目录")

    @staticmethod
    def _format_recording_duration(seconds):
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _update_camera_recording_timer(self):
        if not self.camera_recording or self.camera_recording_started_at is None:
            return
        self.camera_recording_elapsed_s = time.monotonic() - self.camera_recording_started_at
        duration = self._format_recording_duration(self.camera_recording_elapsed_s)
        self.camera_recording_timer_label.config(text=f"录像时长 {duration}")
        self.camera_recording_timer_after_id = self.root.after(1000, self._update_camera_recording_timer)

    def _cancel_camera_recording_timer(self):
        if self.camera_recording_timer_after_id is None:
            return
        try:
            self.root.after_cancel(self.camera_recording_timer_after_id)
        except Exception:
            pass
        self.camera_recording_timer_after_id = None

    def _put_latest_camera_packet(self, packet):
        try:
            self._hardware_camera_queue.put_nowait(packet)
        except queue.Full:
            try:
                self._hardware_camera_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._hardware_camera_queue.put_nowait(packet)
            except queue.Full:
                pass

    def _poll_hardware_camera(self):
        self.camera_after_id = None
        try:
            item = self._hardware_camera_queue.get_nowait()
        except queue.Empty:
            item = None
        if isinstance(item, Exception):
            self._hardware_camera_failed(item)
            return
        if item is not None:
            self.latest_camera_frame_bgr = item.image_bgr
            frame_rgb = cv2.cvtColor(item.image_bgr, cv2.COLOR_BGR2RGB)
            self._show_camera_frame(frame_rgb)
        if self.camera_running:
            self.camera_after_id = self.root.after(40, self._poll_hardware_camera)

    def _hardware_camera_failed(self, error):
        self.camera_running = False
        self.camera_recording = False
        self._cancel_camera_recording_timer()
        if self.camera_recording_started_at is not None:
            self.camera_recording_elapsed_s = time.monotonic() - self.camera_recording_started_at
            self.camera_recording_timer_label.config(
                text=f"录像中断 {self._format_recording_duration(self.camera_recording_elapsed_s)}"
            )
        self.camera_recording_started_at = None
        self._hardware_camera_stop.set()
        if self._hardware_camera_source is not None:
            self._hardware_camera_source.close()
        self.btn_camera.config(text="开启预览", bg=self.colors["accent"],
                               activebackground=self.colors["accent_hover"])
        self.btn_camera_record.config(text="开始录像", state="disabled")
        self.btn_camera_photo.config(state="disabled")
        self.camera_label.config(image="", text=f"相机采集失败：{error}",
                                 font=(self.font_family, 11), fg=self.colors["danger"])
        self.camera_label.image = None
        self.log(f"MVS 相机采集失败：{error}")

    def stop_camera(self):
        if self.auto_running:
            self.stop_auto_control("关闭视觉预览")
        if self.camera_recording and getattr(self, "_hardware_camera_source", None) is not None:
            self._hardware_camera_source.submit_camera_command("stop_recording")
            self.log("正在后台结束录像并保存 AVI")
        self._cancel_camera_recording_timer()
        if self.camera_recording_started_at is not None:
            self.camera_recording_elapsed_s = time.monotonic() - self.camera_recording_started_at
            self.camera_recording_timer_label.config(
                text=f"录像时长 {self._format_recording_duration(self.camera_recording_elapsed_s)}"
            )
        self.camera_recording_started_at = None
        if self.camera_after_id is not None:
            try:
                self.root.after_cancel(self.camera_after_id)
            except Exception:
                pass
            self.camera_after_id = None
        self.camera_running = False
        if hasattr(self, "_hardware_camera_stop"):
            self._hardware_camera_stop.set()
        if hasattr(self, "_hardware_camera_source"):
            self._hardware_camera_source.close()
        if self.camera_thread:
            thread = self.camera_thread
            source = getattr(self, "_hardware_camera_source", None)
            if thread.is_alive() or (source is not None and source.worker.is_alive()):
                self.root.after(50, lambda: self._reap_camera_thread(thread, source))
            else:
                self.camera_thread = None
                self._hardware_camera_source = None
        self.btn_camera.config(text="开启预览", bg=self.colors["accent"], activebackground=self.colors["accent_hover"])
        self.btn_camera_record.config(text="开始录像", state="disabled")
        self.btn_camera_photo.config(state="disabled")
        self.camera_recording = False
        self.latest_camera_frame_bgr = None
        self.camera_label.config(image="", text=self._camera_idle_text(), font=(self.font_family, 12), fg=self.colors["muted"])
        self.camera_label.image = None
        self.log("视觉预览已关闭")

    def _reap_camera_thread(self, thread, source):
        if thread.is_alive() or (source is not None and source.worker.is_alive()):
            self.root.after(50, lambda: self._reap_camera_thread(thread, source))
            return
        if self.camera_thread is thread:
            self.camera_thread = None
        if self._hardware_camera_source is source:
            self._hardware_camera_source = None
        if source is not None and source.close_error:
            self.log(f"录像结束时保存失败：{source.close_error}")

    def _camera_preview_loop(self):
        if not self.camera_running or self.auto_running or not self.is_simulation_mode():
            return
        self._render_sim_camera_frame(force_display=False)
        self.camera_after_id = self.root.after(120, self._camera_preview_loop)

    def _update_camera_from_image(self, image):
        image = image.copy()
        target_w, target_h = self._camera_preview_target_size()
        image.thumbnail((target_w, target_h), RESAMPLE_FILTER)
        photo = ImageTk.PhotoImage(image=image, master=self.camera_label)
        self._update_camera_label(photo)


    def _update_camera_label(self, photo):
        self.camera_label.config(image=photo, text="")
        self.camera_label.image = photo

    def _camera_preview_target_size(self):
        label_w = self.camera_label.winfo_width()
        label_h = self.camera_label.winfo_height()
        if label_w <= 8 or label_h <= 8:
            # The first frame is requested during application construction.
            # Resolve Tk geometry first so that frame and later redraws use the
            # same dimensions instead of jumping from 520 px to the laid-out size.
            self.root.update_idletasks()
            label_w = self.camera_label.winfo_width()
            label_h = self.camera_label.winfo_height()
        target_w = min(label_w if label_w > 8 else CAMERA_PREVIEW_MAX_PX, CAMERA_PREVIEW_MAX_PX)
        target_h = min(label_h if label_h > 8 else CAMERA_PREVIEW_MAX_PX, CAMERA_PREVIEW_MAX_PX)
        return target_w, target_h
