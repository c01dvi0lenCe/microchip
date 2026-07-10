# 数字微流控视觉平台

面向 20 x 20 核心电极阵列及外围储液池/废液池的上位机仿真、路径规划和视觉闭环验证平台。

## 运行

```powershell
python main.py
```

## 架构

- `main.py`：Tkinter 程序入口。
- `app_controller.py`：当前上位机界面编排；后续逐步抽取闭环任务状态。
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
