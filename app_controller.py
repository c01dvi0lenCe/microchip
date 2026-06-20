import csv
import math
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk
import serial
import serial.tools.list_ports

from controllers.hardware_controller import HardwareProtocol
from dmf_simulation import (
    AStarPlanner,
    BOARD_FRAME_MM,
    CORE_CELLS,
    CORNER_RESERVOIRS,
    DropletDetector,
    ELECTRODE_PITCH_MM,
    GRID_COLS,
    GRID_ROWS,
    INITIAL_DROPLET_CAPACITY,
    LAYOUT_CELLS,
    MultiDropletAssignment,
    RESERVOIR_CELLS,
    RESERVOIR_CONNECTIONS,
    RESERVOIR_DROPLET_CAPACITY,
    SIDE_RESERVOIR_LARGE,
    SIDE_RESERVOIR_SMALL,
    SimulatedCamera,
    SimulatedDroplet,
    build_multi_droplet_assignments,
    cell_center_mm,
    cell_from_electrode_id,
    detection_in_cell,
    electrode_id,
    grid_polyline_cells,
    is_reservoir_cell,
    schedule_multi_paths,
)
from simulation.metrics import OperationMetrics, StepEvent
from simulation.profiles import MotionProfile, VisionNoiseProfile


try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow < 10 compatibility.
    RESAMPLE_FILTER = Image.LANCZOS

CAMERA_PREVIEW_MAX_PX = 520
AUTO_LOOP_INTERVAL_MS = 70
CAMERA_DISPLAY_INTERVAL_S = 0.08
MATRIX_DISPLAY_INTERVAL_S = 0.12


class STM32MatrixController:
    OP_MOVE = "移动"
    OP_MERGE = "混合"
    OP_SPLIT = "分裂"
    OP_MULTI = "多液滴"
    OP_LOOP = "循环"

    TOOL_MOVE_START = "设置起点"
    TOOL_MOVE_GOAL = "设置终点"
    TOOL_MERGE_A = "设置液滴A"
    TOOL_MERGE_B = "设置液滴B"
    TOOL_MERGE_POINT = "设置混合点"
    TOOL_SPLIT_SOURCE = "设置源液滴"
    TOOL_SPLIT_LEFT = "设置左子滴"
    TOOL_SPLIT_RIGHT = "设置右子滴"
    TOOL_SPLIT_DIRECTION = "设置分裂方向"
    TOOL_MULTI_LOAD = "设置储液池"
    TOOL_MULTI_INITIAL = "设置初始液滴"
    TOOL_MULTI_SHAPE = "设置目标电极"
    TOOL_LOOP_START = "设置循环液滴"
    TOOL_LOOP_SELECT = "选择循环液滴"
    TOOL_LOOP_PATH = "设置循环路径"
    TOOL_OBSTACLE = "设置障碍物"
    TOOL_MANUAL = "手动电极"
    MANUAL_TOOL_TOGGLE = "开关电极"
    MANUAL_TOOL_DROPLET = "设置液滴"

    def __init__(self, root):
        self.root = root
        self.rows = GRID_ROWS
        self.cols = GRID_COLS
        self.pitch_mm = ELECTRODE_PITCH_MM
        self.total_channels = len(LAYOUT_CELLS)

        self.ser = None
        self.is_connected = False
        self.active_channels = 0
        self.stop_event = threading.Event()

        self.camera_running = False
        self.camera_thread = None
        self.camera_after_id = None
        self.auto_after_id = None

        self.mode_var = tk.StringVar(value="仿真")
        self.operation_var = tk.StringVar(value=self.OP_MOVE)
        self.tool_var = tk.StringVar(value=self.TOOL_MOVE_START)
        self.manual_tool_var = tk.StringVar(value=self.MANUAL_TOOL_TOGGLE)
        self.motion_profile_var = tk.StringVar(value="理想")
        self.vision_noise_var = tk.StringVar(value="关闭")
        self.fault_mode_var = tk.StringVar(value="无")
        self.auto_running = False

        self.start_cell = (1, 1)
        self.goal_cell = (18, 18)
        self.secondary_cell = (1, 4)
        self.split_left_cell = (1, 0)
        self.split_right_cell = (1, 2)
        self.path = []
        self.operation_paths = []
        self.operation_path_cells = set()
        self.merge_path_b = []
        self.mixing_path = []
        self.mixing_index = 0
        self.mixing_active = False
        self.mixing_cycles = 2
        self.mixing_cycles_var = tk.IntVar(value=self.mixing_cycles)
        self.loop_path_points = []
        self.loop_path_cells = []
        self.loop_cycles = 3
        self.loop_cycles_var = tk.IntVar(value=self.loop_cycles)
        self.loop_interval_s = 0.0
        self.loop_interval_s_var = tk.DoubleVar(value=self.loop_interval_s)
        self.loop_cycles_completed = 0
        self.loop_wait_until = 0.0
        self.loop_routes = []
        self.loop_route_index = None
        self.loop_assignments = []
        self.undo_stack = []
        self.max_undo_snapshots = 100
        self.path_index = 0
        self.path_index_b = 0
        self.hover_cell = None
        self.detected_position = None
        self.detected_positions = []
        self.detected_cell = None
        self.detected_cells = []
        self.latest_detections = []
        self.recovery_attempts = 0
        self.detected_cells = []
        self.latest_detections = []
        self.current_target_cell = None
        self.current_target_cell_b = None
        self.active_auto_cells = set()
        self.loaded_reservoirs = set()
        self.initial_droplet_cells = set()
        self.obstacle_cells = set()
        self.weak_fault_cells = set()
        self.target_shape_points = []
        self.target_shape_cells = []
        self.multi_assignments = []
        self.multi_targets = []
        self.multi_droplet_visible = []
        self.multi_step_index = 0
        self.multi_step_start_time = 0.0
        self.multi_step_duration_s = 0.85
        self.last_plan_error = ""
        self.debug_tests_visible = False
        self.manual_droplet = None
        self.manual_droplets = []
        self.manual_after_id = None
        self.manual_last_update_time = time.monotonic()

        self.sim_camera = SimulatedCamera(self.rows, self.cols, frame_size=(720, 720))
        self.detector = DropletDetector(self.sim_camera)
        self.planner = AStarPlanner(
            self.rows,
            self.cols,
            valid_cells=LAYOUT_CELLS,
            extra_edges=RESERVOIR_CONNECTIONS,
        )
        self.sim_droplet = SimulatedDroplet(self.start_cell, speed_cells_per_sec=2.5)
        self.sim_droplet_b = SimulatedDroplet(self.secondary_cell, speed_cells_per_sec=2.5)
        self.sim_droplets = [self.sim_droplet]
        self.split_progress = 0.0
        self.split_attempts = 0
        self.max_split_attempts = 2
        self.split_stretch_duration_s = 1.15
        self.split_relax_duration_s = 0.35
        self.split_retry_release_until = 0.0
        self.split_forced_failures_remaining = 0
        self.last_auto_update_time = 0.0
        self.last_detection_time = 0.0
        self.step_start_time = 0.0
        self.step_replanned = False
        self.drop_frame_until = 0.0
        self.detection_timeout_s = 0.5
        self.step_timeout_s = 2.0
        self.recovery_attempts = 0
        self.max_recovery_attempts = 3
        self.feedback_log_times = {}
        self.last_camera_display_time = 0.0
        self.last_matrix_display_time = 0.0
        self.operation_metrics = None
        self.operation_metrics_history = []

        self.font_family = "Microsoft YaHei UI"
        self.mono_font = "Consolas"
        self.colors = {
            "bg": "#E7ECEF",
            "header_bg": "#D2DAE1",
            "header_text": "#1F2A33",
            "panel": "#FFFFFF",
            "panel_alt": "#F4F7F9",
            "text": "#22313C",
            "muted": "#5F6E78",
            "accent": "#3B6E8F",
            "accent_hover": "#325F7B",
            "success": "#2F8F83",
            "success_hover": "#27786D",
            "danger": "#BF4D4D",
            "danger_hover": "#A84141",
            "btn_off": "#E1E8EE",
            "btn_off_hover": "#D2DCE4",
            "btn_on": "#3E8D73",
            "btn_on_hover": "#347A64",
            "log_bg": "#F6F9FB",
            "log_text": "#2A3742",
            "electrode_fill": "#FFFFFF",
            "electrode_outline": "#C6D0D8",
            "path": "#D9E8F8",
            "obstacle": "#59646E",
            "reservoir": "#B65B4D",
            "reservoir_edge": "#7D332B",
            "reservoir_loaded": "#E68F45",
            "reservoir_loaded_edge": "#93521D",
            "initial_droplet": "#6C5CE7",
            "target_shape": "#DCD2FF",
            "target_sample": "#F5CA51",
            "droplet": "#1852C2",
            "droplet_a": "#1852C2",
            "droplet_b": "#B23A48",
            "droplet_a_bg": "#DDEBFF",
            "droplet_b_bg": "#FFE2EC",
            "detected": "#F2B84B",
        }
        self.multi_droplet_colors = [
            self.colors["droplet_a"],
            self.colors["droplet_b"],
            "#9B4DCA",
            "#007B83",
            "#C77D00",
            "#4E7A2E",
            "#2F5F9A",
            "#7D4F2A",
        ]

        self.buttons = {eid: {"state": 0, "hover": False} for eid in range(1, self.total_channels + 1)}

        self._configure_window()
        self._build_ui()
        self.refresh_ports()
        self._set_connection_state(False)
        self._set_active_count(0)
        self._update_mode_ui()
        self._render_sim_camera_frame(force_display=False)
        self._schedule_manual_simulation_loop()

        self.recv_thread = threading.Thread(target=self.receive_data, daemon=True)
        self.recv_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-z>", self.on_undo_shortcut)
        self.root.bind("<Control-Z>", self.on_undo_shortcut)

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
        self.main_notebook.add(manual_page, text="手动电极")
        self.main_notebook.add(auto_page, text="自动化路径规划")

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

    def _simulation_parameter_help_text(self):
        return (
            "运动真实度：控制液滴单步响应时间、随机偏移、过冲和卡滞概率；"
            "理想用于功能演示，常规接近真实实验，困难用于压力测试。\n"
            "视觉噪声：模拟相机检测丢帧、质心抖动、低对比和强反光；"
            "关闭用于调试，轻微/强噪声用于验证闭环鲁棒性。\n"
            "故障模式：无表示正常电极；随机卡滞会让部分步进变慢或卡住；"
            "指定弱故障电极会把你设置的障碍/弱故障区域用于纠偏测试。\n"
            "异常保护：检测到丢滴、疑似融合、跑偏或无法安全调度时，系统保持当前安全电极，"
            "停止自动推进，等待复位、回退或重新规划。"
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
        legend_items = [
            ("液滴", self.colors["droplet_a"], "white"),
            ("储液池", self.colors["reservoir"], self.colors["text"]),
            ("障碍", self.colors["obstacle"], "white"),
            ("激活", self.colors["btn_on"], "white"),
        ]
        if not manual:
            legend_items = [
                ("液滴A", self.colors["droplet_a"], "white"),
                ("液滴B", self.colors["droplet_b"], "white"),
                ("检测", self.colors["detected"], self.colors["text"]),
                ("路径", self.colors["path"], self.colors["text"]),
                ("障碍", self.colors["obstacle"], "white"),
                ("储液池", self.colors["reservoir"], self.colors["text"]),
                ("有液池", self.colors["reservoir_loaded"], self.colors["text"]),
                ("初始滴", self.colors["initial_droplet"], "white"),
                ("目标", self.colors["target_sample"], self.colors["text"]),
                ("激活", self.colors["btn_on"], "white"),
            ]
        for text, color, fg in legend_items:
            tk.Label(
                legend,
                text=text,
                bg=color,
                fg=fg,
                font=(self.font_family, 9, "bold"),
                padx=6,
                pady=1,
            ).pack(side="left", padx=(0, 6))

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
                    self._scheduled_cell_at(assignment.scheduled_path, 0) is not None
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
            manual_view = self._is_manual_page_selected()
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
            self.auto_status_label.config(text="闭环: 实物模式仅手动", fg=self.colors["muted"])

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
                self.log(f"成功连接到 {port}")
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

    def toggle_electrode(self, eid):
        if self.auto_running:
            self.log("闭环运行中，手动电极操作已忽略")
            return
        current_state = self.buttons[eid]["state"]
        new_state = 1 if current_state == 0 else 0
        self._set_electrode_state(eid, new_state)

    def _active_electrode_ids(self):
        return {eid for eid, info in self.buttons.items() if info["state"] == 1}

    def _set_electrode_state(self, eid, state, log_send=True):
        if eid not in self.buttons:
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

    def reset_all(self):
        if self.auto_running:
            self.stop_auto_control("全部关闭")
        self.log("正在关闭所有电极...")
        for info in self.buttons.values():
            info["state"] = 0
        self.active_auto_cells = set()
        self._set_active_count(0)
        self._draw_matrix_canvas()

        if self.is_simulation_mode():
            self.log("仿真后端 -> 全部电极关闭")
            self._render_sim_camera_frame()
            return
        if not self.is_connected:
            self.log("串口未连接，仅关闭本地显示")
            return
        for eid in range(1, self.total_channels + 1):
            self.send_command(HardwareProtocol.set_electrode(eid, 0), log_send=False)
            time.sleep(0.005)
        self.log("已向 STM32 发送全部关闭命令")

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
            for path_index, path in enumerate(paths):
                for cell in path:
                    self._draw_cell(cell, fill=self.colors["path"], outline="")
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
            for idx, droplet in enumerate(self.sim_droplets):
                color = self._droplet_marker_colors()[idx % 2]
                self._draw_position_marker(droplet.position, color, radius_scale=0.34)
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

    def _draw_position_marker(self, position, color, radius_scale=0.3, hollow=False):
        row, col = position
        left, top, _, _, cell_size = self._grid_geometry()
        cx = left + (col + 0.5) * cell_size
        cy = top + (row + 0.5) * cell_size
        radius = max(4, cell_size * radius_scale)
        fill = "" if hollow else color
        self.matrix_canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=fill, outline=color, width=3)

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
        merge_regions = self._target_merge_regions()
        if merge_regions:
            self.log(f"相邻目标电极将视为 {len(merge_regions)} 个连通液区，移动过程中仍避免提前接触")
        for assignment in assignments:
            self.log(
                f"D{assignment.droplet_id}: {self._cell_label(assignment.source)} -> "
                f"{self._cell_label(assignment.target)} / {len(assignment.path) - 1} 步"
            )
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()
        return assignments

    def _multi_source_cells(self):
        return set(self.loaded_reservoirs) | set(self.initial_droplet_cells)

    def _multi_source_capacities(self):
        capacities = {}
        for cell in self.loaded_reservoirs:
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

    def _planned_step_count(self, planned):
        if not planned:
            return 0
        if hasattr(planned[0], "scheduled_path"):
            return max(max(0, len(assignment.scheduled_path) - 1) for assignment in planned)
        if isinstance(planned[0], tuple):
            return max(0, len(planned) - 1)
        return sum(max(0, len(path) - 1) for path in planned)

    def _operation_ready_to_start(self, planned):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            return bool(planned)
        if operation == self.OP_SPLIT:
            return bool(planned)
        if operation == self.OP_MERGE:
            return bool(planned) and len(planned) >= 3 and len(self.mixing_path) > 1
        return bool(planned) and len(planned) >= 2

    def _prepare_operation_start(self):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            self._begin_multi_operation()
        elif operation == self.OP_SPLIT:
            self._begin_split_operation()
        elif operation == self.OP_MERGE:
            self._begin_merge_step()
        elif operation == self.OP_LOOP:
            self._begin_loop_operation()
        else:
            self._begin_current_step()

    def _operation_running_label(self):
        return f"闭环: {self.operation_var.get()}运行中"

    def start_auto_control(self):
        if not self.is_simulation_mode():
            messagebox.showinfo("提示", "第一版闭环演示仅在仿真模式运行")
            return
        if self.operation_var.get() == self.OP_MOVE and self.start_cell == self.goal_cell:
            self.log("起点已在终点，无需启动闭环")
            return

        planned = self.plan_path(reset_droplet=True)
        if not self._operation_ready_to_start(planned):
            return

        self._begin_operation_metrics()
        self.auto_running = True
        self.camera_running = True
        self.btn_camera.config(text="关闭预览", bg=self.colors["danger"], activebackground=self.colors["danger_hover"])
        if self.camera_after_id is not None:
            self.root.after_cancel(self.camera_after_id)
            self.camera_after_id = None

        now = time.monotonic()
        self.last_auto_update_time = now
        self.last_detection_time = now
        self.step_replanned = False
        self.recovery_attempts = 0
        self.feedback_log_times.clear()
        self._prepare_operation_start()
        self.auto_status_label.config(text=self._operation_running_label(), fg=self.colors["success"])
        self.log(f"{self.operation_var.get()}闭环控制已启动")
        self._auto_loop()

    def pause_auto_control(self):
        if self.auto_running:
            self.stop_auto_control("用户暂停")
        else:
            self.auto_status_label.config(text="闭环: 已暂停", fg=self.colors["muted"])

    def stop_auto_control(self, reason=""):
        self.auto_running = False
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        self._set_auto_active_cells(set())
        self.current_target_cell = None
        self.current_target_cell_b = None
        self.mixing_active = False
        self.auto_status_label.config(text="闭环: 已停止", fg=self.colors["muted"])
        if reason:
            self.log(f"闭环停止：{reason}")
        self._draw_matrix_canvas()

    def reset_simulation(self):
        self.stop_auto_control("复位仿真")
        self._clear_planned_operation()
        self.detected_position = None
        self.detected_positions = []
        self.detected_cell = None
        self.drop_frame_until = 0.0
        self.manual_droplets.clear()
        self.manual_droplet = None
        self._reset_droplets_for_operation()
        for info in self.buttons.values():
            info["state"] = 0
        self.active_auto_cells = set()
        self._set_active_count(0)
        self.auto_status_label.config(text="闭环: 仿真待机", fg=self.colors["muted"])
        self.log("仿真已复位")
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def step_debug_forward(self):
        self._debug_step_path(1)

    def step_debug_backward(self):
        self._debug_step_path(-1)

    def _debug_step_path(self, direction):
        if not self.is_simulation_mode():
            messagebox.showinfo("提示", "路径步进调试当前仅用于仿真模式")
            return

        self._pause_auto_for_debug_step()
        planned = self._ensure_debug_plan()
        if not self._operation_ready_to_start(planned):
            return

        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            changed = self._debug_step_multi(direction)
        elif operation == self.OP_LOOP and self.loop_assignments:
            changed = self._debug_step_loop_multi(direction)
        elif operation == self.OP_MERGE:
            changed = self._debug_step_merge(direction)
        elif operation == self.OP_SPLIT:
            changed = self._debug_step_split(direction)
        else:
            changed = self._debug_step_single_path(direction)

        if changed:
            self.step_start_time = time.monotonic()
            self.last_detection_time = self.step_start_time
            self.step_replanned = False
            self.auto_status_label.config(text="闭环: 手动步进调试", fg=self.colors["accent"])
        self._draw_matrix_canvas()
        self._render_sim_camera_frame()

    def _pause_auto_for_debug_step(self):
        if not self.auto_running:
            return
        self.auto_running = False
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        self.log("自动闭环已暂停，进入手动步进调试")

    def _ensure_debug_plan(self):
        operation = self.operation_var.get()
        if operation == self.OP_MULTI and self.multi_assignments:
            return self.multi_assignments
        if operation == self.OP_LOOP and self.loop_assignments:
            return self.loop_assignments
        if operation in (self.OP_MERGE, self.OP_SPLIT) and self.operation_paths:
            return self.operation_paths
        if operation in (self.OP_MOVE, self.OP_LOOP) and self.path:
            return self.path
        return self.plan_path(reset_droplet=True)

    def _debug_step_merge(self, direction):
        if not self.path or not self.merge_path_b:
            return False

        merge_arrived = self.path_index >= len(self.path) - 1 and self.path_index_b >= len(self.merge_path_b) - 1
        if direction > 0 and merge_arrived:
            return self._debug_step_mixing(direction)
        if direction < 0 and (self.mixing_active or self.mixing_index > 0):
            return self._debug_step_mixing(direction)

        self.mixing_active = False
        self.mixing_index = 0
        return self._debug_step_dual_paths(direction, "混合")

    def _debug_step_single_path(self, direction):
        if not self.path:
            return False
        next_index = self._clamp_index(self.path_index + direction, len(self.path))
        if next_index == self.path_index:
            self.log("调试步进已在路径边界")
            return False
        self.path_index = next_index
        current = self.path[self.path_index]
        self.sim_droplet.reset(current)
        self.sim_droplets = [self.sim_droplet]
        self.current_target_cell = self.path[self.path_index + 1] if self.path_index < len(self.path) - 1 else None
        self.current_target_cell_b = None
        self._set_auto_active_cells(self._debug_single_active_for_path(self.path, self.path_index))
        self.log(
            f"调试{'步进' if direction > 0 else '回退'}："
            f"{self._cell_label(current)} ({self.path_index}/{len(self.path) - 1})"
        )
        return True

    def _debug_step_dual_paths(self, direction, label):
        if not self.path or not self.merge_path_b:
            return False
        next_a = self._clamp_index(self.path_index + direction, len(self.path))
        next_b = self._clamp_index(self.path_index_b + direction, len(self.merge_path_b))
        if next_a == self.path_index and next_b == self.path_index_b:
            self.log(f"{label}调试步进已在路径边界")
            return False

        self.path_index = next_a
        self.path_index_b = next_b
        cell_a = self.path[self.path_index]
        cell_b = self.merge_path_b[self.path_index_b]
        self.sim_droplet.reset(cell_a)
        self.sim_droplet_b.reset(cell_b)
        if self.path_index >= len(self.path) - 1 and self.path_index_b >= len(self.merge_path_b) - 1:
            self.sim_droplet.reset(self.goal_cell)
            self.sim_droplets = [self.sim_droplet]
            active = {self.goal_cell}
        else:
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
            active = self._debug_single_active_for_path(self.path, self.path_index)
            active.update(self._debug_single_active_for_path(self.merge_path_b, self.path_index_b))
        self.current_target_cell = self.path[self.path_index + 1] if self.path_index < len(self.path) - 1 else self.goal_cell
        self.current_target_cell_b = (
            self.merge_path_b[self.path_index_b + 1]
            if self.path_index_b < len(self.merge_path_b) - 1
            else self.goal_cell
        )
        self._set_auto_active_cells(active)
        self.log(
            f"{label}调试{'步进' if direction > 0 else '回退'}："
            f"A {self.path_index}/{len(self.path) - 1}，B {self.path_index_b}/{len(self.merge_path_b) - 1}"
        )
        return True

    def _debug_step_mixing(self, direction):
        if len(self.mixing_path) < 2:
            self.log("四宫格混合路径为空，无法步进")
            return False

        if direction < 0 and self.mixing_index <= 0:
            self.mixing_active = False
            return self._debug_step_dual_paths(direction, "混合")

        next_index = self._clamp_index(self.mixing_index + direction, len(self.mixing_path))
        if next_index == self.mixing_index:
            self.log("四宫格混合调试步进已在路径边界")
            return False

        self.mixing_active = True
        self.mixing_index = next_index
        current = self.mixing_path[self.mixing_index]
        self.sim_droplet.reset(current)
        self.sim_droplets = [self.sim_droplet]
        self.current_target_cell = (
            self.mixing_path[self.mixing_index + 1]
            if self.mixing_index < len(self.mixing_path) - 1
            else current
        )
        self.current_target_cell_b = None
        active = {self.current_target_cell} if self.current_target_cell is not None else {current}
        self._set_auto_active_cells(active)
        self.log(
            f"四宫格混合调试{'步进' if direction > 0 else '回退'}："
            f"{self.mixing_index}/{len(self.mixing_path) - 1}，"
            f"当前 {self._cell_label(current)}，下一目标 {self._cell_label(self.current_target_cell)}"
        )
        return True

    def _debug_step_split(self, direction):
        if not self.path or not self.merge_path_b:
            return False
        next_index = self._clamp_index(self.path_index + direction, 2)
        if next_index == self.path_index:
            self.log("分裂调试步进已在路径边界")
            return False

        self.path_index = next_index
        self.path_index_b = next_index
        if next_index == 0:
            self.split_progress = 0.0
            self.sim_droplet.reset(self.start_cell)
            self.sim_droplets = [self.sim_droplet]
            self.current_target_cell = self.split_left_cell
            self.current_target_cell_b = self.split_right_cell
            self._set_auto_active_cells(set())
            self.log(f"分裂调试回退：{self._cell_label(self.start_cell)}，源电极保持关闭")
        else:
            self.split_progress = 1.0
            self.sim_droplet.reset(self.split_left_cell)
            self.sim_droplet_b.reset(self.split_right_cell)
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
            self.current_target_cell = self.split_left_cell
            self.current_target_cell_b = self.split_right_cell
            self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
            self.log(
                "分裂调试步进："
                f"{self._cell_label(self.split_left_cell)} / {self._cell_label(self.split_right_cell)}"
            )
        return True

    def _debug_step_multi(self, direction):
        if not self.multi_assignments:
            return False
        max_steps = max(len(assignment.scheduled_path) for assignment in self.multi_assignments)
        next_step = self._clamp_index(self.multi_step_index + direction, max_steps)
        if next_step == self.multi_step_index:
            self.log("多液滴调试步进已在调度边界")
            return False

        if len(self.sim_droplets) != len(self.multi_assignments):
            self.sim_droplets = [
                SimulatedDroplet(assignment.source, speed_cells_per_sec=3.2)
                for assignment in self.multi_assignments
            ]
        self.multi_step_index = next_step
        self.multi_step_start_time = time.monotonic()
        self.multi_droplet_visible = []
        for idx, assignment in enumerate(self.multi_assignments):
            cell = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            if cell is None:
                self.sim_droplets[idx].reset(assignment.source)
                self.multi_droplet_visible.append(False)
            else:
                self.sim_droplets[idx].reset(cell)
                self.multi_droplet_visible.append(True)
        self._set_auto_active_cells(self._multi_active_cells_for_phase(self.multi_step_index, 0.0))
        self.log(f"多液滴调试{'步进' if direction > 0 else '回退'}：{self.multi_step_index}/{max_steps - 1}")
        return True

    def _debug_step_loop_multi(self, direction):
        if not self.loop_assignments:
            return False
        max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
        next_step = self._clamp_index(self.multi_step_index + direction, max_steps)
        if next_step == self.multi_step_index:
            self.log("多液滴循环调试步进已在调度边界")
            return False

        self.multi_step_index = next_step
        self.multi_step_start_time = time.monotonic()
        self.sim_droplets = []
        self.multi_droplet_visible = []
        for assignment in self.loop_assignments:
            cell = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            droplet = SimulatedDroplet(assignment.source, speed_cells_per_sec=2.5)
            if cell is None:
                droplet.reset(assignment.source)
                self.multi_droplet_visible.append(False)
            else:
                droplet.reset(cell)
                self.multi_droplet_visible.append(True)
            self.sim_droplets.append(droplet)
        self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, 0.0))
        self.log(f"多液滴循环调试{'步进' if direction > 0 else '回退'}：{self.multi_step_index}/{max_steps - 1}")
        return True

    @staticmethod
    def _clamp_index(index, length):
        if length <= 0:
            return 0
        return max(0, min(length - 1, index))

    @staticmethod
    def _debug_active_for_path(path, index):
        if not path:
            return set()
        active = {path[index]}
        if index < len(path) - 1:
            active.add(path[index + 1])
        return active

    @staticmethod
    def _debug_single_active_for_path(path, index):
        if not path:
            return set()
        if index < len(path) - 1:
            return {path[index + 1]}
        return {path[index]}

    def simulate_detection_dropout(self):
        self.drop_frame_until = time.monotonic() + 0.8
        self.log("已触发 0.8 s 检测丢帧测试")
        if self.is_simulation_mode() and not self.auto_running:
            self._render_sim_camera_frame(hide_droplet=True)

    def simulate_drift_fault(self):
        if self.operation_var.get() == self.OP_MULTI and self.sim_droplets:
            for idx, visible in enumerate(self.multi_droplet_visible):
                if not visible:
                    continue
                self.sim_droplets[idx].position = self._offset_position(self.sim_droplets[idx].position, 2, 1)
                self.log(f"已注入 D{idx + 1} 跑偏测试")
                break
            else:
                self.log("当前没有已出滴的多液滴可注入跑偏")
        else:
            self.sim_droplet.position = self._offset_position(self.sim_droplet.position, 2, 1)
            self.log("已注入单液滴跑偏测试")
        self._render_sim_camera_frame()

    def simulate_fusion_fault(self):
        if self.operation_var.get() != self.OP_MULTI:
            self.log("融合测试仅用于多液滴模式")
            return
        visible_indices = [idx for idx, visible in enumerate(self.multi_droplet_visible) if visible]
        if len(visible_indices) < 2:
            self.log("至少需要两滴已出液滴才能注入融合测试")
            return
        first, second = visible_indices[:2]
        self.sim_droplets[second].position = self.sim_droplets[first].position
        self.log(f"已注入 D{first + 1}/D{second + 1} 融合测试")
        self._render_sim_camera_frame()

    def simulate_split_failure_fault(self):
        if self.operation_var.get() != self.OP_SPLIT:
            self.log("分裂失败测试仅用于分裂模式")
            return
        self.split_forced_failures_remaining += 1
        self.log(f"已注入 1 次分裂失败测试，剩余 {self.split_forced_failures_remaining} 次")
        if self.is_simulation_mode() and not self.auto_running:
            self._render_sim_camera_frame()

    def _offset_position(self, position, row_delta, col_delta):
        row = max(0, min(self.rows - 1, int(round(position[0] + row_delta))))
        col = max(0, min(self.cols - 1, int(round(position[1] + col_delta))))
        return float(row), float(col)

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

    def _begin_current_step(self):
        if self.path_index >= len(self.path) - 1:
            self.stop_auto_control("到达目标")
            return
        current = self.path[self.path_index]
        target = self.path[self.path_index + 1]
        self.current_target_cell = target
        self.step_start_time = time.monotonic()
        self.log_feedback("状态机", f"释放当前电极 {self._cell_label(current)}", force=True)
        self._set_auto_active_cells({target}, stage="DRIVE_TARGET", action="drive")
        self.log_feedback("状态机", f"开启目标电极 {self._cell_label(target)}，等待视觉确认", force=True)
        self.log(f"闭环步进：关闭 {self._cell_label(current)}，开启 {self._cell_label(target)}")

    def _begin_merge_step(self):
        active = set()
        if self.path_index < len(self.path) - 1:
            self.current_target_cell = self.path[self.path_index + 1]
            active.add(self.current_target_cell)
        else:
            self.current_target_cell = self.goal_cell
            active.add(self.current_target_cell)

        if self.path_index_b < len(self.merge_path_b) - 1:
            self.current_target_cell_b = self.merge_path_b[self.path_index_b + 1]
            active.add(self.current_target_cell_b)
        else:
            self.current_target_cell_b = self.goal_cell
            active.add(self.current_target_cell_b)

        self.step_start_time = time.monotonic()
        self._set_auto_active_cells(active)
        self.log(
            "混合汇合步进："
            f"A->{self._cell_label(self.current_target_cell)} | "
            f"B->{self._cell_label(self.current_target_cell_b)}"
        )

    def _begin_mixing_phase(self):
        self.mixing_active = True
        self.mixing_index = 0
        self.sim_droplet.reset(self.goal_cell)
        self.sim_droplets = [self.sim_droplet]
        self.current_target_cell_b = None
        self.log_feedback("混合", "A/B 已到达混合点，进入四宫格混合循环", force=True)
        self._begin_mixing_step()

    def _begin_mixing_step(self):
        if self.mixing_index >= len(self.mixing_path) - 1:
            self._set_auto_active_cells({self.goal_cell})
            self._render_sim_camera_frame()
            self.stop_auto_control("混合完成，四宫格循环结束")
            return
        current = self.mixing_path[self.mixing_index]
        target = self.mixing_path[self.mixing_index + 1]
        self.current_target_cell = target
        self.step_start_time = time.monotonic()
        self.log_feedback("状态机", f"释放当前电极 {self._cell_label(current)}", force=True)
        self._set_auto_active_cells({target}, stage="DRIVE_TARGET", action="drive")
        self.log_feedback("状态机", f"开启目标电极 {self._cell_label(target)}，等待视觉确认", force=True)
        self.log(f"四宫格混合：关闭 {self._cell_label(current)}，开启 {self._cell_label(target)}")

    def _begin_split_operation(self):
        self.split_progress = 0.0
        self.split_attempts = 0
        self.split_retry_release_until = 0.0
        self.sim_droplet.reset(self.start_cell)
        self.sim_droplets = [self.sim_droplet]
        self.step_start_time = time.monotonic()
        self.last_detection_time = self.step_start_time
        self.current_target_cell = self.split_left_cell
        self.current_target_cell_b = self.split_right_cell
        self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
        self.log(
            "分裂拉伸：关闭源电极，开启 "
            f"{self._cell_label(self.split_left_cell)} / {self._cell_label(self.split_right_cell)}"
        )

    def _begin_multi_operation(self):
        if not self.multi_assignments:
            self.stop_auto_control("多液滴任务为空")
            return
        self.multi_step_index = 0
        self.multi_step_start_time = time.monotonic()
        self.sim_droplets = []
        self.multi_droplet_visible = []
        for assignment in self.multi_assignments:
            droplet = SimulatedDroplet(assignment.source, speed_cells_per_sec=3.2)
            start_cell = self._scheduled_cell_at(assignment.scheduled_path, 0)
            if start_cell is not None:
                droplet.reset(start_cell)
                self.multi_droplet_visible.append(True)
                if is_reservoir_cell(assignment.source):
                    self.log(f"D{assignment.droplet_id} 从储液池 {self._cell_label(assignment.source)} 准备出滴")
                else:
                    self.log(f"D{assignment.droplet_id} 初始液滴位于 {self._cell_label(assignment.source)}")
            else:
                droplet.reset(assignment.source)
                self.multi_droplet_visible.append(False)
            self.sim_droplets.append(droplet)
        self._set_auto_active_cells(self._multi_active_cells_for_phase(0, 0.0))
        self.log(f"多液滴出滴启动：{len(self.multi_assignments)} 滴")

    def _begin_loop_operation(self):
        self.loop_cycles_completed = 0
        self.loop_wait_until = 0.0
        if self.loop_assignments:
            self.multi_step_index = 0
            self.multi_step_start_time = time.monotonic()
            self.sim_droplets = []
            self.multi_droplet_visible = []
            for assignment in self.loop_assignments:
                droplet = SimulatedDroplet(assignment.source, speed_cells_per_sec=2.5)
                start_cell = self._scheduled_cell_at(assignment.scheduled_path, 0)
                if start_cell is not None:
                    droplet.reset(start_cell)
                    self.multi_droplet_visible.append(True)
                else:
                    droplet.reset(assignment.source)
                    self.multi_droplet_visible.append(False)
                self.sim_droplets.append(droplet)
            max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
            self.current_target_cell = None
            self.current_target_cell_b = None
            self._set_auto_active_cells(self._loop_active_cells_for_phase(0, 0.0))
            self.log(f"多液滴循环启动：{len(self.loop_assignments)} 滴，调度步 {max_steps - 1}")
            return
        self._begin_current_step()

    def _auto_loop(self):
        if not self.auto_running:
            return

        now = time.monotonic()
        dt_s = min(0.12, max(0.0, now - self.last_auto_update_time))
        self.last_auto_update_time = now

        operation = self.operation_var.get()
        if operation == self.OP_MULTI:
            self._multi_auto_step(now, dt_s)
        elif operation == self.OP_MERGE:
            self._merge_auto_step(now, dt_s)
        elif operation == self.OP_SPLIT:
            self._split_auto_step(now, dt_s)
        elif operation == self.OP_LOOP:
            self._loop_auto_step(now, dt_s)
        else:
            self._move_auto_step(now, dt_s)

        if self.auto_running:
            self.auto_after_id = self.root.after(AUTO_LOOP_INTERVAL_MS, self._auto_loop)

    def _multi_auto_step(self, now, dt_s):
        if not self.multi_assignments:
            self.stop_auto_control("多液滴任务为空")
            return

        max_steps = max(len(assignment.scheduled_path) for assignment in self.multi_assignments)
        if self.multi_step_index >= max_steps - 1:
            self._render_sim_camera_frame()
            self.stop_auto_control("多液滴全部到达目标电极")
            return

        next_step = self.multi_step_index + 1
        step_elapsed = now - self.multi_step_start_time
        phase_progress = min(1.0, max(0.0, step_elapsed / self.multi_step_duration_s))
        self._set_auto_active_cells(self._multi_active_cells_for_phase(self.multi_step_index, phase_progress))

        for idx, assignment in enumerate(self.multi_assignments):
            current = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            target = self._scheduled_cell_at(assignment.scheduled_path, next_step)
            if current is None and target is None:
                self.multi_droplet_visible[idx] = False
                continue
            if target is None:
                self.multi_droplet_visible[idx] = False
                continue
            if current is None:
                if phase_progress >= 0.62:
                    self.sim_droplets[idx].reset(target)
                    self.multi_droplet_visible[idx] = True
                else:
                    self.multi_droplet_visible[idx] = False
            else:
                self.multi_droplet_visible[idx] = True
                self.sim_droplets[idx].update_towards(
                    target,
                    dt_s,
                    motion_profile=self._motion_profile(),
                    weak_fault_cells=self._weak_fault_cells_for_run(),
                )

        self._render_sim_camera_frame(force_display=False)
        if not self.auto_running:
            return
        if not self._check_multi_visual_health(max_steps):
            return

        if step_elapsed >= self.multi_step_duration_s:
            for idx, assignment in enumerate(self.multi_assignments):
                previous_cell = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
                cell = self._scheduled_cell_at(assignment.scheduled_path, next_step)
                if cell is None:
                    self.multi_droplet_visible[idx] = False
                else:
                    self.multi_droplet_visible[idx] = True
                    self.sim_droplets[idx].reset(cell)
                    if previous_cell is None:
                        self.log_feedback(
                            "储液池出滴",
                            f"D{assignment.droplet_id} 已从 {self._cell_label(assignment.source)} 形成单滴并进入调度",
                            force=True,
                        )
                        self.log(f"D{assignment.droplet_id} 从储液池 {self._cell_label(assignment.source)} 出滴")
            self.multi_step_index = next_step
            self.multi_step_start_time = now
            self._set_auto_active_cells(self._multi_active_cells_for_phase(self.multi_step_index, 0.0))
            self.log_feedback(
                "多液滴调度",
                f"视觉/时间步确认进入第 {self.multi_step_index} 步，重新计算本轮激活电极",
                force=True,
            )
            self.log(f"多液滴调度步进 {self.multi_step_index}/{max_steps - 1}")

        if self.multi_step_index >= max_steps - 1:
            self._render_sim_camera_frame()
            self.stop_auto_control("多液滴全部到达目标电极")

    def _multi_active_cells_for_phase(self, step, phase_progress):
        active = set()
        for assignment in self.multi_assignments:
            current = self._scheduled_cell_at(assignment.scheduled_path, step)
            nxt = self._scheduled_cell_at(assignment.scheduled_path, step + 1)
            if current is None and nxt is None:
                continue
            if nxt is None:
                continue
            if current is None:
                active.add(nxt)
                continue
            if current == nxt:
                active.add(current)
                continue
            active.add(nxt)
        return active

    def _multi_active_cells_for_step(self, step):
        return self._multi_active_cells_for_phase(step, 0.0)

    def _loop_active_cells_for_phase(self, step, phase_progress):
        active = set()
        for assignment in self.loop_assignments:
            current = self._scheduled_cell_at(assignment.scheduled_path, step)
            nxt = self._scheduled_cell_at(assignment.scheduled_path, step + 1)
            if current is None and nxt is None:
                continue
            if nxt is None:
                continue
            if current == nxt:
                active.add(current)
                continue
            active.add(nxt)
        return active

    def _loop_active_cells_for_step(self, step):
        return self._loop_active_cells_for_phase(step, 0.0)

    def _check_multi_visual_health(self, max_steps):
        visible_indices = [idx for idx, visible in enumerate(self.multi_droplet_visible) if visible]
        visible_count = len(visible_indices)
        if visible_count == 0:
            return True

        detected_count = len(self.latest_detections)
        if detected_count < visible_count and self.multi_step_index < max_steps - 1:
            hold_cells = set(self.detected_cells) or {
                self.sim_droplets[idx].cell for idx in visible_indices
            }
            self.log_feedback(
                "多液滴保护",
                f"应见 {visible_count} 滴，仅检测到 {detected_count} 滴，按疑似融合/遮挡处理并保持 {len(hold_cells)} 个电极",
                force=True,
            )
            self._pause_multi_with_hold(
                f"视觉检测到 {detected_count}/{visible_count} 滴，疑似融合或遮挡，已进入保护保持",
                hold_cells,
            )
            return False

        if visible_count == 1 and detected_count == 1:
            idx = visible_indices[0]
            detection = self.latest_detections[0]
            allowed = self._multi_allowed_cells_for_index(idx)
            if detection.cell not in allowed:
                allowed_text = " / ".join(self._cell_label(cell) for cell in allowed)
                self.log_feedback(
                    "多液滴纠偏",
                    f"D{idx + 1} 检测在 {self._cell_label(detection.cell)}，不在允许区 {allowed_text}，尝试单滴回正",
                    force=True,
                )
                return self._recover_single_visible_multi_droplet(idx, detection.cell)

        if visible_count > 1 and detected_count == visible_count:
            allowed = set()
            for idx in visible_indices:
                allowed.update(self._multi_allowed_cells_for_index(idx))
            off_cells = [cell for cell in self.detected_cells if cell not in allowed]
            if off_cells:
                off_text = " / ".join(self._cell_label(cell) for cell in off_cells)
                self.log_feedback(
                    "多液滴保护",
                    f"检测到偏离调度的液滴位置 {off_text}，多滴身份可能混淆，暂停调度",
                    force=True,
                )
                self._pause_multi_with_hold(
                    "检测到多液滴偏离调度轨迹，身份可能混淆，已进入保护保持",
                    set(off_cells) | {self.sim_droplets[idx].cell for idx in visible_indices},
                )
                return False
        return True

    def _multi_allowed_cells_for_index(self, idx):
        assignment = self.multi_assignments[idx]
        current = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
        nxt = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index + 1)
        return {cell for cell in (current, nxt) if cell is not None}

    def _recover_single_visible_multi_droplet(self, idx, detected_cell):
        assignment = self.multi_assignments[idx]
        if self.recovery_attempts >= self.max_recovery_attempts:
            self.log_feedback("多液滴纠偏", "纠偏次数达到上限，改为保护保持", force=True)
            self._pause_multi_with_hold("多液滴纠偏超过最大次数，已进入保护保持", {detected_cell})
            return False
        path = self.planner.plan(detected_cell, assignment.target)
        if len(path) < 2:
            self.log_feedback(
                "多液滴纠偏",
                f"D{assignment.droplet_id} 从 {self._cell_label(detected_cell)} 无法回到目标 {self._cell_label(assignment.target)}",
                force=True,
            )
            self._pause_multi_with_hold("多液滴跑偏后无法从检测位置回到目标，已进入保护保持", {detected_cell})
            return False

        self.recovery_attempts += 1
        assignment.path = path
        assignment.scheduled_path = path
        self.multi_step_index = 0
        self.multi_step_start_time = time.monotonic()
        self.sim_droplets[idx].reset(detected_cell)
        self.multi_droplet_visible[idx] = True
        self.operation_paths = [item.path for item in self.multi_assignments]
        self._refresh_operation_path_cells()
        self._set_auto_active_cells(self._multi_active_cells_for_phase(0, 0.0))
        self.log_feedback(
            "多液滴纠偏",
            f"D{assignment.droplet_id} 已重建 {len(path) - 1} 步路径，并重置多液滴调度索引",
            force=True,
        )
        self.log(
            f"D{assignment.droplet_id} 跑偏：已从 {self._cell_label(detected_cell)} "
            f"重规划回 {self._cell_label(assignment.target)}"
        )
        return True

    def _pause_multi_with_hold(self, reason, hold_cells):
        self.auto_running = False
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        valid_hold = {cell for cell in hold_cells if cell is not None}
        self._set_auto_active_cells(valid_hold)
        self.current_target_cell = None
        self.current_target_cell_b = None
        if valid_hold:
            hold_text = " / ".join(self._cell_label(cell) for cell in sorted(valid_hold))
            self.auto_status_label.config(text=f"闭环: 保护暂停，保持安全电极 {hold_text}", fg=self.colors["danger"])
            self.log_feedback("异常保护", f"保持电极：{hold_text}", force=True)
        else:
            self.auto_status_label.config(text="闭环: 保护暂停，等待人工复位或重新规划", fg=self.colors["danger"])
        self.log(reason)
        self._draw_matrix_canvas()

    @staticmethod
    def _scheduled_cell_at(path, step):
        if step < len(path):
            return path[step]
        return path[-1]

    @staticmethod
    def _position_in_cell(position, cell, tolerance=0.08):
        return math.hypot(position[0] - cell[0], position[1] - cell[1]) <= tolerance

    def _move_auto_step(self, now, dt_s):
        if self.current_target_cell is not None:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        detection = self._render_and_check_detection(now)
        if not self.auto_running:
            return
        if detection is not None:
            if self.current_target_cell is not None and not self._single_detection_on_track(detection):
                self.log_feedback(
                    "移动纠偏",
                    f"检测到 {self._cell_label(detection.cell)} 偏离当前/下一目标，准备从检测位置重规划",
                    force=True,
                )
                self._recover_single_droplet(detection.cell, now, "检测到液滴偏离计划电极")
                return
            if self.current_target_cell is not None and detection_in_cell(detection, self.current_target_cell):
                self.log_feedback(
                    "移动",
                    f"视觉确认进入 {self._cell_label(self.current_target_cell)}，推进到下一步",
                    force=True,
                )
                self._handle_step_reached()

        if self.auto_running and self.current_target_cell is not None:
            if now - self.step_start_time > self.step_timeout_s:
                self.log_feedback(
                    "移动纠偏",
                    f"{self._cell_label(self.current_target_cell)} 未在 {self.step_timeout_s:.1f}s 内到达，触发超时重规划",
                    force=True,
                )
                self._handle_step_timeout(now)

    def _loop_auto_step(self, now, dt_s):
        if self.loop_assignments:
            self._loop_multi_auto_step(now, dt_s)
            return
        if self.loop_wait_until > 0.0:
            if now < self.loop_wait_until:
                self._render_sim_camera_frame(force_display=False)
                return
            self.loop_wait_until = 0.0
            self._begin_current_step()
            return
        if self.current_target_cell is not None:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        detection = self._render_and_check_detection(now)
        if not self.auto_running:
            return
        if detection is not None:
            if self.current_target_cell is not None and not self._single_detection_on_track(detection):
                self.log_feedback(
                    "循环纠偏",
                    f"检测到 {self._cell_label(detection.cell)} 偏离当前循环路径，进入保护停止",
                    force=True,
                )
                self.stop_auto_control("循环液滴偏离当前/下一目标电极")
                return
            if self.current_target_cell is not None and detection_in_cell(detection, self.current_target_cell):
                self.log_feedback(
                    "循环",
                    f"视觉确认进入 {self._cell_label(self.current_target_cell)}，推进循环路径",
                    force=True,
                )
                self._handle_loop_step_reached()

        if self.auto_running and self.current_target_cell is not None:
            if now - self.step_start_time > self.step_timeout_s:
                self.log_feedback(
                    "循环纠偏",
                    f"{self._cell_label(self.current_target_cell)} 未在 {self.step_timeout_s:.1f}s 内到达，停止循环",
                    force=True,
                )
                self.stop_auto_control("循环单步超时")

    def _loop_multi_auto_step(self, now, dt_s):
        if not self.loop_assignments:
            self.stop_auto_control("多液滴循环任务为空")
            return

        if self.loop_wait_until:
            if now < self.loop_wait_until:
                self._set_auto_active_cells({assignment.source for assignment in self.loop_assignments})
                self._render_sim_camera_frame(force_display=False)
                return
            self.loop_wait_until = 0.0
            self.multi_step_start_time = now
            self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, 0.0))

        max_steps = max(len(assignment.scheduled_path) for assignment in self.loop_assignments)
        if self.multi_step_index >= max_steps - 1:
            self._handle_multi_loop_cycle_finished(now, max_steps)
            return

        next_step = self.multi_step_index + 1
        step_elapsed = now - self.multi_step_start_time
        phase_progress = min(1.0, max(0.0, step_elapsed / self.multi_step_duration_s))
        self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, phase_progress))

        for idx, assignment in enumerate(self.loop_assignments):
            current = self._scheduled_cell_at(assignment.scheduled_path, self.multi_step_index)
            target = self._scheduled_cell_at(assignment.scheduled_path, next_step)
            if current is None and target is None:
                self.multi_droplet_visible[idx] = False
                continue
            if target is None:
                self.multi_droplet_visible[idx] = False
                continue
            self.multi_droplet_visible[idx] = True
            if current is None or current == target:
                self.sim_droplets[idx].reset(target)
            else:
                self.sim_droplets[idx].update_towards(
                    target,
                    dt_s,
                    motion_profile=self._motion_profile(),
                    weak_fault_cells=self._weak_fault_cells_for_run(),
                )

        self._render_sim_camera_frame(force_display=False)
        if step_elapsed >= self.multi_step_duration_s:
            for idx, assignment in enumerate(self.loop_assignments):
                cell = self._scheduled_cell_at(assignment.scheduled_path, next_step)
                if cell is None:
                    self.multi_droplet_visible[idx] = False
                else:
                    self.multi_droplet_visible[idx] = True
                    self.sim_droplets[idx].reset(cell)
            self.multi_step_index = next_step
            self.multi_step_start_time = now
            self._set_auto_active_cells(self._loop_active_cells_for_phase(self.multi_step_index, 0.0))
            self.log_feedback(
                "多液滴循环",
                f"调度步进 {self.multi_step_index}/{max_steps - 1}",
                key="multi_loop_step",
                interval_s=0.3,
            )

        if self.multi_step_index >= max_steps - 1:
            self._render_sim_camera_frame()
            self._handle_multi_loop_cycle_finished(now, max_steps)

    def _handle_multi_loop_cycle_finished(self, now, max_steps):
        self.loop_cycles_completed += 1
        target_cycles = self._sync_loop_cycles()
        if self.loop_cycles_completed >= target_cycles:
            self.stop_auto_control(f"多液滴循环完成 {self.loop_cycles_completed}/{target_cycles} 圈")
            return
        self.multi_step_index = 0
        self.multi_step_start_time = now
        interval_s = self._sync_loop_interval_s()
        for idx, assignment in enumerate(self.loop_assignments):
            self.sim_droplets[idx].reset(assignment.source)
            self.multi_droplet_visible[idx] = True
        if interval_s > 0:
            self.loop_wait_until = now + interval_s
            self._set_auto_active_cells({assignment.source for assignment in self.loop_assignments})
            self.log_feedback(
                "多液滴循环",
                f"完成 {self.loop_cycles_completed}/{target_cycles} 圈，等待 {interval_s:.1f}s 后进入下一圈",
                force=True,
            )
            return
        self._set_auto_active_cells(self._loop_active_cells_for_phase(0, 0.0))
        self.log_feedback(
            "多液滴循环",
            f"完成 {self.loop_cycles_completed}/{target_cycles} 圈，重新进入下一圈（单圈 {max_steps - 1} 步）",
            force=True,
        )

    def _merge_auto_step(self, now, dt_s):
        if self.mixing_active:
            self._mixing_auto_step(now, dt_s)
            return

        if self.current_target_cell is not None and self.path_index < len(self.path) - 1:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )
        if self.current_target_cell_b is not None and self.path_index_b < len(self.merge_path_b) - 1:
            self.sim_droplet_b.update_towards(
                self.current_target_cell_b,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        self._render_and_check_detection(now)
        if not self.auto_running:
            return

        advanced = False
        if self.current_target_cell is not None and self.sim_droplet.cell == self.current_target_cell:
            if self.path_index < len(self.path) - 1:
                self.path_index += 1
                advanced = True
        if self.current_target_cell_b is not None and self.sim_droplet_b.cell == self.current_target_cell_b:
            if self.path_index_b < len(self.merge_path_b) - 1:
                self.path_index_b += 1
                advanced = True

        done_a = self.path_index >= len(self.path) - 1
        done_b = self.path_index_b >= len(self.merge_path_b) - 1
        if done_a and done_b:
            self._begin_mixing_phase()
            return

        if advanced:
            self.log_feedback(
                "混合",
                f"至少一路液滴到达当前目标，推进 A:{self.path_index}/{len(self.path) - 1} B:{self.path_index_b}/{len(self.merge_path_b) - 1}",
                force=True,
            )
            self._begin_merge_step()
        elif now - self.step_start_time > self.step_timeout_s:
            self.log_feedback("混合纠偏", "混合汇合单步超时，进入停止保护", force=True)
            self.stop_auto_control("混合汇合单步超时")

    def _mixing_auto_step(self, now, dt_s):
        if self.current_target_cell is not None and self.mixing_index < len(self.mixing_path) - 1:
            self.sim_droplet.update_towards(
                self.current_target_cell,
                dt_s,
                motion_profile=self._motion_profile(),
                weak_fault_cells=self._weak_fault_cells_for_run(),
            )

        self._render_and_check_detection(now)
        if not self.auto_running:
            return

        if self.current_target_cell is not None and self.sim_droplet.cell == self.current_target_cell:
            self.mixing_index += 1
            if self.mixing_index >= len(self.mixing_path) - 1:
                self.stop_auto_control("混合完成，四宫格循环结束")
                return
            self.log_feedback(
                "混合",
                f"四宫格循环进度 {self.mixing_index}/{len(self.mixing_path) - 1}",
                force=True,
            )
            self._begin_mixing_step()
        elif now - self.step_start_time > self.step_timeout_s:
            self.log_feedback("混合纠偏", "四宫格混合单步超时，进入停止保护", force=True)
            self.stop_auto_control("四宫格混合单步超时")

    def _split_auto_step(self, now, dt_s):
        if now < self.split_retry_release_until:
            self._set_auto_active_cells(set())
            self.sim_droplet.reset(self.start_cell)
            self.sim_droplets = [self.sim_droplet]
            self.log_feedback(
                "分裂纠偏",
                f"释放回缩阶段，源电极和两侧目标暂时关闭，{self.split_retry_release_until - now:.2f}s 后重拉",
                key="split_release_phase",
                interval_s=0.2,
            )
            self._render_and_check_detection(now)
            return

        if self.split_retry_release_until:
            self.split_retry_release_until = 0.0
            self.step_start_time = now
            self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
            self.log_feedback(
                "分裂纠偏",
                f"重新开启两侧目标电极，开始第 {self.split_attempts + 1} 次拉伸",
                force=True,
            )

        self.split_progress = min(1.0, self.split_progress + dt_s / self.split_stretch_duration_s)
        source_r, source_c = self.start_cell
        left_r, left_c = self.split_left_cell
        right_r, right_c = self.split_right_cell
        forced_failure_active = self.split_forced_failures_remaining > 0

        if self.split_progress < 0.55 or forced_failure_active:
            self.log_feedback(
                "分裂",
                f"拉伸阶段 progress={self.split_progress:.2f}，关闭源电极并保持左右目标电极",
                key="split_stretch_phase",
                interval_s=0.35,
            )
            self.sim_droplet.position = (
                source_r + (left_r + right_r - 2 * source_r) * 0.25 * self.split_progress,
                source_c + (left_c + right_c - 2 * source_c) * 0.25 * self.split_progress,
            )
            self.sim_droplets = [self.sim_droplet]
        else:
            self.log_feedback(
                "分裂",
                f"断裂确认阶段 progress={self.split_progress:.2f}，观察是否形成两个稳定子滴",
                key="split_break_phase",
                interval_s=0.35,
            )
            t = (self.split_progress - 0.55) / 0.45
            left_pos = (source_r + (left_r - source_r) * t, source_c + (left_c - source_c) * t)
            right_pos = (source_r + (right_r - source_r) * t, source_c + (right_c - source_c) * t)
            self.sim_droplet.position = left_pos
            self.sim_droplet_b.position = right_pos
            self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]

        self._render_and_check_detection(now)
        if not self.auto_running:
            return

        if self.split_progress >= 1.0:
            if self._split_success_detected():
                self.log_feedback("分裂", "视觉确认两个子滴稳定，关闭源电极并保持左右目标", force=True)
                self.sim_droplet.reset(self.split_left_cell)
                self.sim_droplet_b.reset(self.split_right_cell)
                self.sim_droplets = [self.sim_droplet, self.sim_droplet_b]
                self._set_auto_active_cells({self.split_left_cell, self.split_right_cell})
                self._render_sim_camera_frame()
                self.stop_auto_control("分裂完成，已生成两个子液滴")
                return
            self._handle_split_not_separated(now)
            return

        if now - self.step_start_time > self.step_timeout_s:
            self.log_feedback("分裂纠偏", "分裂过程超时，按未拉开处理并准备重拉", force=True)
            self._handle_split_not_separated(now)

    def _split_success_detected(self):
        if self.split_forced_failures_remaining > 0:
            self.split_forced_failures_remaining -= 1
            return False
        detected = set(self.detected_cells)
        return (
            len(self.latest_detections) >= 2
            and self.split_left_cell in detected
            and self.split_right_cell in detected
        )

    def _handle_split_not_separated(self, now):
        self._record_metric_split_failure()
        if self.split_attempts >= self.max_split_attempts:
            self.log_feedback(
                "分裂纠偏",
                f"连续 {self.split_attempts + 1} 次未检测到两滴，停止保护",
                force=True,
            )
            self.stop_auto_control("分裂失败：未检测到两个稳定子滴")
            return

        self.split_attempts += 1
        self.split_progress = 0.0
        self.step_start_time = now
        self.split_retry_release_until = now + self.split_relax_duration_s
        self.sim_droplet.reset(self.start_cell)
        self.sim_droplets = [self.sim_droplet]
        self._set_auto_active_cells(set())
        self.log_feedback(
            "分裂纠偏",
            f"未检测到两个子滴，先释放回缩 {self.split_relax_duration_s:.2f}s，随后重拉 "
            f"({self.split_attempts}/{self.max_split_attempts})",
            force=True,
        )
        self._draw_matrix_canvas()

    def _render_and_check_detection(self, now):
        hide_droplet = now < self.drop_frame_until
        detection = self._render_sim_camera_frame(hide_droplet=hide_droplet, force_display=False)
        if detection is not None:
            self.last_detection_time = now
            return detection
        self._record_metric_dropout()
        elapsed = now - self.last_detection_time
        self.log_feedback(
            "视觉",
            f"检测暂时丢失 {elapsed:.2f}s，保持当前激活电极等待恢复",
            key="vision_dropout_wait",
            interval_s=0.25,
        )
        if elapsed > self.detection_timeout_s:
            self.log_feedback("视觉", "检测丢失超过阈值，停止闭环并关闭自动推进", force=True)
            self.stop_auto_control("检测丢失超过 0.5 s")
        return None

    def _single_detection_on_track(self, detection):
        expected = []
        if self.path_index < len(self.path):
            expected.append(self.path[self.path_index])
        if self.current_target_cell is not None:
            expected.append(self.current_target_cell)
        return any(detection_in_cell(detection, cell, tolerance_cells=0.55) for cell in expected)

    def _recover_single_droplet(self, detected_cell, now, reason):
        if self.recovery_attempts >= self.max_recovery_attempts:
            self.log_feedback("移动纠偏", "纠偏次数已达上限，进入保护停止", force=True)
            self.stop_auto_control(f"{reason}，超过最大纠偏次数")
            return
        new_path = self.planner.plan(detected_cell, self.goal_cell, self._routing_obstacles(detected_cell, self.goal_cell))
        if len(new_path) < 2:
            self.log_feedback(
                "移动纠偏",
                f"从 {self._cell_label(detected_cell)} 到目标无可行回正路径",
                force=True,
            )
            self.stop_auto_control(f"{reason}，从检测位置无法回到目标")
            return
        self.recovery_attempts += 1
        self.sim_droplet.reset(detected_cell)
        self.path = new_path
        self._record_metric_replan()
        self.operation_paths = [new_path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.merge_path_b = []
        self.current_target_cell = new_path[1]
        self.current_target_cell_b = None
        self.step_replanned = True
        self.step_start_time = now
        self._set_auto_active_cells({self.current_target_cell})
        self.log_feedback(
            "移动纠偏",
            f"新路径 {len(new_path) - 1} 步，关闭检测位置并开启 {self._cell_label(self.current_target_cell)}",
            force=True,
        )
        self.log(
            f"{reason}：已从 {self._cell_label(detected_cell)} "
            f"重新规划并拉回，纠偏 {self.recovery_attempts}/{self.max_recovery_attempts}"
        )
        self._draw_matrix_canvas()

    def _handle_step_reached(self):
        self._record_step_event(
            "VISION_CONFIRM",
            target_cell=self.current_target_cell,
            detected_cell=self.detected_cell,
            action="advance",
        )
        if self.path_index + 1 >= len(self.path) - 1:
            self.stop_auto_control("到达目标")
            return
        self.path_index += 1
        self.step_replanned = False
        self.recovery_attempts = 0
        self._begin_current_step()

    def _handle_loop_step_reached(self):
        self._record_step_event(
            "VISION_CONFIRM",
            target_cell=self.current_target_cell,
            detected_cell=self.detected_cell,
            action="loop_advance",
        )
        if not self.path:
            self.stop_auto_control("循环路径为空")
            return
        if self.path_index + 1 >= len(self.path) - 1:
            self.loop_cycles_completed += 1
            target_cycles = self._sync_loop_cycles()
            if self.loop_cycles_completed >= target_cycles:
                self.stop_auto_control(f"循环完成 {self.loop_cycles_completed}/{target_cycles} 圈")
                return
            self.path_index = 0
            self.step_replanned = False
            self.recovery_attempts = 0
            self.sim_droplet.reset(self.path[0])
            interval_s = self._sync_loop_interval_s()
            if interval_s > 0:
                self.current_target_cell = None
                self.loop_wait_until = time.monotonic() + interval_s
                self._set_auto_active_cells({self.path[0]})
                self.log(f"循环完成 {self.loop_cycles_completed}/{target_cycles} 圈，等待 {interval_s:.1f}s 后进入下一圈")
                return
            self.log(f"循环完成 {self.loop_cycles_completed}/{target_cycles} 圈，重新进入下一圈")
            self._begin_current_step()
            return
        self.path_index += 1
        self.step_replanned = False
        self.recovery_attempts = 0
        self._begin_current_step()

    def _handle_step_timeout(self, now):
        self._record_metric_stall()
        if self.step_replanned:
            self.log_feedback("移动纠偏", "重规划后的单步仍超时，停止自动控制", force=True)
            self.stop_auto_control("单步超时，重规划后仍未到达")
            return

        current = self.detected_cell or self.sim_droplet.cell
        if current == self.goal_cell:
            self.log_feedback("移动", "超时检查时液滴已在目标电极，结束任务", force=True)
            self.stop_auto_control("到达目标")
            return

        new_path = self.planner.plan(current, self.goal_cell, self._routing_obstacles(current, self.goal_cell))
        if len(new_path) < 2:
            self.log_feedback(
                "移动纠偏",
                f"超时后从 {self._cell_label(current)} 无法重新规划到目标",
                force=True,
            )
            self.stop_auto_control("单步超时且无法重规划")
            return

        self.path = new_path
        self.operation_paths = [new_path]
        self._refresh_operation_path_cells()
        self.path_index = 0
        self.current_target_cell = new_path[1]
        self.current_target_cell_b = None
        self.step_replanned = True
        self.step_start_time = now
        self._set_auto_active_cells({self.current_target_cell})
        self.log_feedback(
            "移动纠偏",
            f"超时后生成新路径 {len(new_path) - 1} 步，下一目标 {self._cell_label(self.current_target_cell)}",
            force=True,
        )
        self.log(f"单步超时，已从 {self._cell_label(current)} 重规划")
        self._draw_matrix_canvas()

    def _set_auto_active_cells(self, cells, stage="ELECTRODE_SWITCH", action="switch"):
        old_cells = set(self.active_auto_cells)
        new_cells = set(cells)
        off_cells = old_cells - new_cells
        on_cells = new_cells - old_cells
        for cell in off_cells:
            eid = electrode_id(cell[0], cell[1], self.cols)
            self.update_ui_only(eid, 0)
            self.send_command(HardwareProtocol.set_electrode(eid, 0), log_send=False)
        for cell in on_cells:
            eid = electrode_id(cell[0], cell[1], self.cols)
            self.update_ui_only(eid, 1)
            self.send_command(HardwareProtocol.set_electrode(eid, 1), log_send=False)
        self.active_auto_cells = new_cells
        if on_cells or off_cells:
            target_cell = sorted(on_cells)[0] if on_cells else None
            self._record_step_event(
                stage,
                target_cell=target_cell,
                detected_cell=self.detected_cell,
                on_cells=on_cells,
                off_cells=off_cells,
                action=action,
            )
            self.log_feedback(
                "电极开关",
                f"开启 {len(on_cells)} 个，关闭 {len(off_cells)} 个，当前保持 {len(new_cells)} 个",
                key="auto_switch_summary",
                interval_s=0.2,
            )

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

    def receive_data(self):
        while not self.stop_event.is_set():
            if self.is_connected and self.ser:
                try:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                        if line:
                            if line.startswith("SYNC:"):
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
