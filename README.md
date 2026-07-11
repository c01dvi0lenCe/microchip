# 数字微流控视觉平台

面向 20 x 20 核心电极阵列及 20 个外围储液池/废液池（共 420 个逻辑电极）的上位机仿真、路径规划和视觉闭环验证平台。

## 系统边界

- 所有自动任务、路径规划、视觉识别、稳定到达判断和异常恢复均在 PC 上位机运行。
- STM32F407 只执行电极状态，不处理工业相机图像。
- STM32 板载 LCD/触摸仅用于脱离电脑时的手动电极测试，不承载自动实验。
- 工业相机通过 USB3/厂商 SDK 直接连接 PC；当前仓库仅完成适配接口边界，尚未绑定最终相机 SDK。
- 外部电源参数固定记录为 `DC_PULSE=0..400 V, 300 Hz`、`VREF/ITO=200 V`；上位机不调节电源，也不设置 STM32 扫描频率。

STM32 固件是独立仓库：`https://github.com/c01dvi0lenCe/DropLet-code`。不要把固件文件放入本仓库。

## 运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

## 架构

- `main.py`：Tkinter 程序入口。
- `app_controller.py`：上位机装配入口，仅保留公共类、领域常量和初始化状态。
- `controllers/ui_controller.py`：窗口、页签和操作控件构建。
- `controllers/canvas_controller.py`：电极画布几何、绘制和点击交互。
- `controllers/operation_planning.py`：移动、循环、混合、分裂和多液滴任务规划。
- `controllers/task_control.py`：任务启停、复位、步进调试和故障注入入口。
- `controllers/multi_runtime.py`：多液滴并行调度、视觉健康检查和安全保持。
- `controllers/closed_loop_controller.py`：移动、循环、混合与分裂的闭环状态推进和恢复。
- `controllers/simulation_controller.py`：仿真参数、手动液滴和指标统计。
- `controllers/persistence_controller.py`：设置快照、撤销和预设导入导出。
- `controllers/hardware_runtime.py`：STM32 串口、电极命令和生命周期管理。
- `controllers/electrode_transaction.py`：自动任务的原子批量电极事务、ACK 和重试。
- `controllers/arrival_confirmation.py`：连续 5 帧且至少 0.25 s 的视觉稳定到达门。
- `controllers/camera_controller.py`：仿真画面和 PC 侧工业相机适配接口。
- `dmf_simulation.py`：兼容入口，保证既有导入不变。
- `dmf/layout.py`：阵列拓扑、电极编号、储液池与废液池定义。
- `dmf/planning/`：A*、液滴分配和多液滴冲突安全调度。
- `dmf/motion.py`：液滴运动模型。
- `dmf/vision.py`：仿真相机与液滴检测。
- `controllers/`：STM32 串口命令适配。
- `simulation/`：仿真参数和实验指标。
- `validation/closed_loop_chain/`：独立的软件链路验证器，不进入 GUI。

领域词汇见 `CONTEXT.md`，硬件与仿真实现状态见 `docs/implementation-status.md`。

## 验证

```powershell
python -m py_compile main.py app_controller.py dmf_simulation.py droplet_video_analysis.py
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

链路验证器重放移动、混合、分裂、循环、CSE、ZJU 和 CSC，并输出：

- `validation/closed_loop_chain/output/closed_loop_chain_summary.csv`
- `validation/closed_loop_chain/output/closed_loop_chain_summary.md`

软件 PASS 不等于实物 PASS。Keil 编译/烧录、示波器、逻辑分析仪、相机标定和真实液滴实验仍需在硬件到位后完成。

## 在另一台电脑同步

两个仓库必须分别克隆到不同目录，不要互相复制文件。新电脑首次获取上位机：

```powershell
git clone https://github.com/c01dvi0lenCe/microchip.git
cd microchip
git fetch origin
git switch codex/closed-loop-chain-validation
python -m pip install -r requirements.txt
```

新电脑首次获取 STM32 固件：

```powershell
git clone https://github.com/c01dvi0lenCe/DropLet-code.git
cd DropLet-code
git fetch origin
git switch codex/closed-loop-chain-validation
```

已有仓库时，在各自目录分别执行：

```powershell
git status
git fetch origin
git switch codex/closed-loop-chain-validation
git pull --ff-only
```

另一台电脑的 Codex 应先阅读两个仓库各自的 `AGENTS.md`。上位机还需阅读 `CONTEXT.md` 和 `docs/implementation-status.md`；固件还需阅读 `README.md` 与协议设计文档。两边都明确规定：LCD 只做手动测试，所有自动任务均由 PC 上位机执行。
