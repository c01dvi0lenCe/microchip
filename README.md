# 数字微流控视觉平台

面向 20 x 20 核心电极阵列及外围储液池/废液池的上位机仿真、路径规划和视觉闭环验证平台。

## 运行

```powershell
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
- `controllers/camera_controller.py`：仿真画面和实物相机占位适配。
- `dmf_simulation.py`：兼容入口，保证既有导入不变。
- `dmf/layout.py`：阵列拓扑、电极编号、储液池与废液池定义。
- `dmf/planning/`：A*、液滴分配和多液滴冲突安全调度。
- `dmf/motion.py`：液滴运动模型。
- `dmf/vision.py`：仿真相机与液滴检测。
- `controllers/`：STM32 串口命令适配。
- `simulation/`：仿真参数和实验指标。

领域词汇见 `CONTEXT.md`，硬件与仿真实现状态见 `docs/implementation-status.md`。

## 验证

```powershell
python -m py_compile main.py app_controller.py dmf_simulation.py droplet_video_analysis.py
python -m unittest discover -s tests -v
```
