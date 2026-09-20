"""Tkinter composition root for the digital microfluidics visual platform."""

from controllers.common import (
    AStarPlanner,
    DropletDetector,
    ELECTRODE_PITCH_MM,
    GRID_COLS,
    GRID_ROWS,
    LAYOUT_CELLS,
    Path,
    RESERVOIR_CONNECTIONS,
    SimulatedCamera,
    SimulatedDroplet,
    threading,
    time,
    tk,
)
from controllers.ui_controller import UiControllerMixin
from controllers.simulation_controller import SimulationControllerMixin
from controllers.persistence_controller import PersistenceControllerMixin
from controllers.hardware_runtime import HardwareRuntimeMixin
from controllers.canvas_controller import CanvasControllerMixin
from controllers.closed_loop_controller import ClosedLoopControllerMixin
from controllers.multi_runtime import MultiRuntimeMixin
from controllers.operation_planning import OperationPlanningMixin
from controllers.camera_controller import CameraControllerMixin
from controllers.arrival_confirmation import ArrivalConfirmationGate
from controllers.electrode_transaction import ElectrodeTransactionClient
from controllers.task_control import TaskControlMixin
from controllers.scope_test_client import H4_PHASES, SCAN_TEST_FREQUENCIES_HZ, ScopeTestClient
from controllers.scope_validation_controller import ScopeValidationControllerMixin


class STM32MatrixController(
    UiControllerMixin,
    SimulationControllerMixin,
    PersistenceControllerMixin,
    HardwareRuntimeMixin,
    CanvasControllerMixin,
    OperationPlanningMixin,
    TaskControlMixin,
    MultiRuntimeMixin,
    ClosedLoopControllerMixin,
    CameraControllerMixin,
    ScopeValidationControllerMixin,
):
    PRESET_SCHEMA = "dmf_visual_platform_settings"
    PRESET_VERSION = 1

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
        self.hardware_state_uncertain = False
        self.hardware_auto_owned = False
        self.active_channels = 0
        self.stop_event = threading.Event()
        self.electrode_transactions = ElectrodeTransactionClient(
            self._send_transaction_line,
            electrode_count=self.total_channels,
            ack_timeout_s=0.45,
            max_retries=2,
        )
        self.scope_test_client = ScopeTestClient(self._send_scope_test_line)
        self.scope_test_running = False

        self.camera_running = False
        self.hardware_camera_adapter = None
        self.camera_thread = None
        self.camera_after_id = None
        self.auto_after_id = None

        self.mode_var = tk.StringVar(value="仿真")
        self.operation_var = tk.StringVar(value=self.OP_MOVE)
        self.tool_var = tk.StringVar(value=self.TOOL_MOVE_START)
        self.manual_tool_var = tk.StringVar(value=self.MANUAL_TOOL_TOGGLE)
        self.scope_test_mode_var = tk.StringVar(value=self.SCOPE_MODE_OPTIONS[0])
        self.scope_test_phase_var = tk.StringVar(value=H4_PHASES[0])
        self.scope_test_row_var = tk.IntVar(value=1)
        self.scope_test_col_var = tk.IntVar(value=1)
        self.scope_test_row_b_var = tk.IntVar(value=1)
        self.scope_test_col_b_var = tk.IntVar(value=2)
        self.scope_test_frequency_var = tk.IntVar(value=SCAN_TEST_FREQUENCIES_HZ[-1])
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
        self.preset_dir = Path(__file__).resolve().parent / "presets"
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
        self.multi_step_duration_s = 1.2
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
        self.arrival_confirmation = ArrivalConfirmationGate(stable_frames=5, minimum_duration_s=0.25)
        self.multi_arrival_confirmation = ArrivalConfirmationGate(stable_frames=5, minimum_duration_s=0.25)
        self.detection_timeout_s = 12.0
        self.step_timeout_s = 8.0
        self.step_extension_s = 4.0
        self.protective_timeout_s = 20.0
        self.step_extension_used = False
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
        self.root.after(25, lambda: self._render_sim_camera_frame(force_display=True))
        self._schedule_manual_simulation_loop()

        self.recv_thread = threading.Thread(target=self.receive_data, daemon=True)
        self.recv_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-z>", self.on_undo_shortcut)
        self.root.bind("<Control-Z>", self.on_undo_shortcut)
