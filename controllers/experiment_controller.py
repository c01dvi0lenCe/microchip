"""Chapter 2 controls and main-thread display; no experiment logic lives in Tk."""
from datetime import datetime
from pathlib import Path
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .experiment_session import ExperimentSession


class ExperimentControllerMixin:
    def _init_experiment(self):
        self.experiment_session = ExperimentSession()
        self._experiment_active = False
        self._experiment_closing = False
        self._experiment_stopping = False
        self.experiment_after_id = None
        self.experiment_output_dir = None
        self.experiment_config_var = tk.StringVar(value=str(
            Path(__file__).resolve().parents[1]/'configs/chapter2_experiment.yaml'))
        self.experiment_mode_var = tk.StringVar(value='offline')
        self.experiment_status_var = tk.StringVar(value='待机：加载配置后开始，或先运行合成示例。')
        self.experiment_result_var = tk.StringVar(value='状态 —    动作 —    源 → 目标 —')
        self.experiment_hint_var = tk.StringVar()
        self._experiment_locked_widgets = []

    def _build_experiment_page(self, page):
        panel = ttk.Frame(page, padding=16)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='第二章 · 单液滴视觉闭环',
                  font=(self.font_family, 13, 'bold')).pack(anchor='w', pady=(0, 12))
        ttk.Label(panel, text='配置文件（模型、标定、相邻电极路线及阈值）').pack(anchor='w')
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=(5, 12))
        self.experiment_config_entry = ttk.Entry(row, textvariable=self.experiment_config_var)
        self.experiment_config_entry.pack(side='left', fill='x', expand=True)
        self.btn_experiment_browse = ttk.Button(row, text='选择配置', command=self.choose_experiment_config)
        self.btn_experiment_browse.pack(side='left', padx=(6, 0))
        self.btn_experiment_edit = ttk.Button(row, text='打开配置', command=self.open_experiment_config)
        self.btn_experiment_edit.pack(side='left', padx=(6, 0))
        mode_row = ttk.Frame(panel)
        mode_row.pack(fill='x', pady=(0, 8))
        ttk.Label(mode_row, text='实验模式').pack(side='left')
        self.experiment_mode_combo = ttk.Combobox(
            mode_row, textvariable=self.experiment_mode_var,
            values=('offline', 'dry_run', 'experiment'), state='readonly', width=15)
        self.experiment_mode_combo.pack(side='left', padx=8)
        self.experiment_mode_combo.bind('<<ComboboxSelected>>', self._update_experiment_hint)
        ttk.Label(panel, textvariable=self.experiment_hint_var, wraplength=610,
                  foreground=self.colors['muted']).pack(anchor='w', pady=(0, 16))
        buttons = ttk.Frame(panel)
        buttons.pack(fill='x')
        self.btn_experiment_start = ttk.Button(buttons, text='开始实验', command=self.start_experiment)
        self.btn_experiment_start.pack(side='left')
        self.btn_experiment_stop = ttk.Button(buttons, text='停止并释放输出',
                                             command=self.stop_experiment, state='disabled')
        self.btn_experiment_stop.pack(side='left', padx=8)
        self.btn_experiment_output = ttk.Button(buttons, text='打开结果目录',
                                               command=self.open_experiment_output, state='disabled')
        self.btn_experiment_output.pack(side='left')
        ttk.Separator(panel).pack(fill='x', pady=16)
        ttk.Label(panel, textvariable=self.experiment_status_var, wraplength=610,
                  font=(self.font_family, 11, 'bold')).pack(anchor='w', pady=(0, 12))
        ttk.Label(panel, textvariable=self.experiment_result_var, wraplength=610).pack(anchor='w')
        ttk.Label(panel, text='画面显示在右侧；逐帧特征、状态、动作和单步统计自动保存。',
                  foreground=self.colors['muted']).pack(anchor='w', pady=(12, 0))
        ttk.Separator(panel).pack(fill='x', pady=16)
        self.btn_experiment_demo = ttk.Button(panel, text='运行离线合成示例（无需硬件）',
                                             command=self.run_experiment_demo)
        self.btn_experiment_demo.pack(anchor='w')
        ttk.Label(panel, text='示例仅验证软件流程；正式实验需真实视频/相机、U-Net 模型和电极标定。',
                  foreground=self.colors['muted'], wraplength=610).pack(anchor='w', pady=8)
        self._update_experiment_hint()

    def _update_experiment_hint(self, _event=None):
        hints = {
            'offline': '离线视频：分析视频并记录决策，不连接 AM 串口。',
            'dry_run': '相机试运行：读取实时图像并记录决策，不发送 AM 驱动命令。',
            'experiment': '实物实验：实时图像 + AM 输出；配置中须启用输出、确认标定并填写串口。',
        }
        self.experiment_hint_var.set(hints.get(self.experiment_mode_var.get(), '请选择实验模式'))

    def choose_experiment_config(self):
        path = filedialog.askopenfilename(title='选择第二章实验配置',
                                         filetypes=(('YAML', '*.yaml *.yml'), ('All files', '*.*')))
        if path:
            self.experiment_config_var.set(path)

    def _open_experiment_path(self, path):
        try:
            if not path or not Path(path).exists():
                raise FileNotFoundError('文件或目录尚不存在')
            os.startfile(str(Path(path).resolve()))
        except OSError as exc:
            messagebox.showerror('无法打开', str(exc))

    def open_experiment_config(self):
        self._open_experiment_path(self.experiment_config_var.get())

    def open_experiment_output(self):
        self._open_experiment_path(self.experiment_output_dir)

    def run_experiment_demo(self):
        if self._experiment_active:
            return
        from scripts.create_chapter2_demo import create_demo
        try:
            folder = Path(__file__).resolve().parents[1]/'results'/('gui-demo-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            self.experiment_config_var.set(str(create_demo(folder)[0]))
            self.experiment_mode_var.set('offline')
            self._update_experiment_hint()
            self.start_experiment()
        except Exception as exc:
            self.experiment_status_var.set(f'示例生成失败：{exc}')

    def start_experiment(self):
        if self._experiment_active:
            return False
        if self.is_connected:
            messagebox.showwarning('串口正在占用', '请先关闭手动串口连接；实验会按配置文件独立连接并管理 AM。')
            return False
        if self.auto_running or self.planning_jobs.is_active:
            messagebox.showwarning('任务正在运行', '请先停止原有任务，并等待路径规划结束。')
            return False
        if self.camera_running:
            self.stop_camera()
        config_path = self.experiment_config_var.get().strip()
        if not config_path:
            messagebox.showwarning('缺少配置', '请先选择实验配置文件。')
            return False
        self.main_notebook.select(self.experiment_page)
        self.on_experiment_tab_changed()
        self._experiment_active = True
        self._experiment_stopping = False
        self._experiment_previous_mode = self.mode_var.get()
        self._lock_experiment_controls(True)
        self.btn_experiment_output.config(state='disabled')
        mode = self.experiment_mode_var.get()
        self.root.title(f'数字微流控视觉平台 - 第二章实验 [{mode}]')
        self.connection_badge.config(text=f'● 第二章 · {mode}')
        self.experiment_status_var.set(f'启动中 · {mode}')
        self.experiment_result_var.set('等待第一帧有效检测…')
        self.camera_label.config(image='', text='实验正在启动…')
        self.camera_label.image = None
        self.log(f'第二章 MODE={mode} | AM 输出={"启用" if mode == "experiment" else "禁用"}')
        try:
            self.experiment_session.start(config_path, mode)
        except Exception as exc:
            self._finish_experiment({'status': 'error', 'reason': str(exc), 'mode': mode})
            return False
        self.experiment_after_id = self.root.after(80, self._poll_experiment)
        return True

    def stop_experiment(self):
        if self._experiment_active:
            self._experiment_stopping = True
            self.experiment_session.stop()
            self.experiment_status_var.set('正在停止，等待命令释放及日志保存…')
            self.btn_experiment_stop.config(state='disabled')

    def _lock_experiment_controls(self, locked):
        if locked:
            self._experiment_locked_widgets = []
            widgets = (self.mode_combobox, self.port_combobox, self.btn_connect, self.btn_refresh,
                       self.btn_camera, self.experiment_config_entry, self.experiment_mode_combo,
                       self.btn_experiment_browse, self.btn_experiment_edit,
                       self.btn_experiment_start, self.btn_experiment_demo)
            for widget in widgets:
                self._experiment_locked_widgets.append((widget, str(widget.cget('state'))))
                widget.config(state='disabled')
        else:
            for widget, state in self._experiment_locked_widgets:
                widget.config(state=state)
            self._experiment_locked_widgets = []
        for index in (0, 1):
            self.main_notebook.tab(index, state='disabled' if locked else 'normal')
        self.btn_experiment_stop.config(state='normal' if locked else 'disabled')

    def _poll_experiment(self):
        self.experiment_after_id = None
        latest = self.experiment_session.take_latest()
        if latest is not None:
            row, image = latest
            self.experiment_result_var.set(
                f"第 {row['frame_id']} 帧    状态 {row['recognized_state']}    动作 {row['event_action']}\n"
                f"电极 {row['source_electrode']} → {row['target_electrode']}    重试 {row['retry_count']}\n"
                f"实际发送命令：{'是' if row['command_sent'] else '否'}")
            if image is not None:
                self._show_camera_frame(image)
            if not self._experiment_stopping:
                self.experiment_status_var.set(f"运行中 · {self.experiment_mode_var.get()}")
        if not self.experiment_session.running:
            report = self.experiment_session.take_report()
            if report is not None:
                self._finish_experiment(report)
                return
        self.experiment_after_id = self.root.after(80, self._poll_experiment)

    def _finish_experiment(self, report):
        self._experiment_active = False
        self._lock_experiment_controls(False)
        self.experiment_output_dir = report.get('output_dir')
        if self.experiment_output_dir and Path(self.experiment_output_dir).is_dir():
            self.btn_experiment_output.config(state='normal')
        else:
            self.btn_experiment_output.config(state='disabled')
        status = {'complete': '完成', 'incomplete': '视频结束，运输未完成',
                  'stopped': '已停止', 'error': '运行失败'}.get(report['status'], report['status'])
        self.experiment_status_var.set(f"{status} · {report.get('frames', 0)} 帧\n{report.get('reason', '')}")
        self.log(f"第二章实验{status}：{report.get('reason', '')}")
        if self.experiment_output_dir:
            self.log(f'实验结果：{self.experiment_output_dir}')
        if report.get('mode') == 'experiment':
            self.hardware_state_uncertain = report.get('release_confirmed') is not True
            if not self.hardware_state_uncertain:
                self._clear_local_electrode_display()
        if self._experiment_closing:
            self.on_close()

    def _experiment_page_selected(self):
        return hasattr(self, 'experiment_page') and self.main_notebook.select() == str(self.experiment_page)

    def on_experiment_tab_changed(self, _event=None):
        if not hasattr(self, 'camera_label') or self._experiment_active:
            return
        if self._experiment_page_selected():
            if self.camera_running:
                self.stop_camera()
            self.system_control_card.pack_forget()
            self.btn_camera.config(state='disabled')
            self.root.title('数字微流控视觉平台 - 第二章单液滴实验')
            self.connection_badge.config(text='● 第二章实验')
        else:
            if not self.system_control_card.winfo_manager():
                self.system_control_card.pack(fill='x', pady=(0, 6), before=self.main_splitter)
            self.btn_camera.config(state='normal')
            self._update_mode_ui()
