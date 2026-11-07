# Chapter 2 Causal Simulation Implementation Plan

> **For agentic workers:** 使用测试先行及独立审查执行；用户已要求直接完成。保留未提交改动，不commit/push。

**Goal:** 自动运行具有物理反作用、虚拟相机、独立真值和配对A/B/C对照的单液滴simulation。

**Architecture:** 新增 `dmf/chapter2_sim`，共享地图只读；不改实验硬件链和多滴调度。离散积分、相机事件队列和控制策略由纯Python虚拟时间驱动。

**Tech Stack:** Python/NumPy/OpenCV/PyYAML/unittest/Matplotlib。

## 文件与步骤

- [x] `tests/test_chapter2_sim.py`：先测试地图420与非规则外围、动作响应、独立真值、噪声/曝光/掉帧、面积分母、稳定窗、旧帧、重复事件和闭环，再实现对应代码。
- [x] `dmf/chapter2_sim/config.py`、`geometry.py`、`world.py`：类型化配置、只读420地图适配、归一化单位和控制响应物理模型。验证无动作不迁移、有限速度、Retry/Recovery改变位置、失败不假成功。
- [x] `dmf/chapter2_sim/vision.py`、`control.py`、`runner.py`：虚拟曝光/处理时间、掩模、特征/五状态、A/B/C、epoch与单次消费、日志和指标。运行 `python -m unittest tests.test_chapter2_sim -v` 后先进行单场景冒烟。
- [x] `dmf/chapter2_sim/batch.py`、`tests/test_chapter2_sim_batch.py`：配对seed、Wilson/bootstrap、完整分母、阈值扫描、manifest及CSV；先测试再实现。
- [x] `dmf/chapter2_sim/plotting.py`、`run_chapter2_simulation.py`、`configs/chapter2_simulation.yaml`：可重复CLI及四类PNG/PDF/SVG图，simulation标记与绘图源数据。
- [x] `docs/chapter2-simulation.md`：真值/模型/指标/命令/局限/实际结果。先完成单元和冒烟，再批量20seed和扫描，审查图表，执行仓库全量回归。

## 固定接口

`run_trial(config, scenario, seed, method) -> TrialResult`；TrialResult包含 `metrics: dict`、`frames: list[dict]`、`truth: list[dict]`、`events: list[dict]`。config为 `SimConfig`，场景与方法分别是字符串和A/B/C。metrics至少包含scenario/seed/method/simulation/path_complete/early_updates/transport_steps/confirmed_steps/confirmation_delay_s/total_time_s/retries/recoveries/status。run_batch只在核心冒烟通过后调用。

全部字段单位显式 `_s` 或归一化pitch；仅导入map/vision纯模块，不导入串口、相机SDK或第三章规划。全量验收按AGENTS.md三条命令运行。原有核心文件diff应为空。

## 完成记录

新增33项测试通过；最终全量385项中384通过、1项可选FFmpeg集成测试跳过。编译通过，独立链路7/7通过。曾有一次全量运行出现Tk线程清理异常并未正常结束；相关9项GUI测试独立通过，最终单独全量复跑exit0，但仍有非致命after回调清理警告。未修改范围外GUI来隐藏该问题。

正式420+180试验位于`results/chapter2_simulation_20261020_final`，与前次原始CSV逐文件哈希一致；最终源码/输出哈希核对通过。四图字体/碰撞通过，多panel对齐通过；科研绘图的300-dpi PNG/非TIFF警告已解释，使用PDF/SVG作为线图交付。独立规格和代码质量审查均PASS。无commit/push。
