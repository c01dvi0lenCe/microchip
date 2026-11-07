# 实验二异常机制实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. User forbids Commit/Push; retain workspace in place because prior required dependencies are untracked.

**Goal:** 在不改变首版算法/动力学的前提下执行十条确定性异常机制案例，分清决策、Applied与物理运输。

**Architecture:** 新增独立`exp2_faults`夹具/调度器，直接复用首版World、控制器、参考、特征及持久化，不编辑首版文件。独立只读派生指标适用于旧四例与新十例。审计、图稿和PDF由保存数据生成。

**Tech Stack:** Python/unittest、NumPy、Shapely、OpenCV、Matplotlib、ReportLab/PyMuPDF。

## Task 1：先测试后实现异常接口（实施代理）

创建`dmf/chapter2_geometry_sim/exp2_faults/{__init__,spec,world,runner,persistence}.py`、`run_chapter2_geometry_exp2_faults.py`及`tests/test_geometry_exp2_faults.py`。禁止编辑首版exp2及旧模块。

- [ ] 写失败测试：`len(CASES)==10`，全部不含seed；永久卡滞后位置恒定、事务仍正确生效；frame68延迟、frame69重复、drop13帧；保持捕获context；pending/预算/终止；真实转弯连续。
- [ ] 运行`python -m unittest tests.test_geometry_exp2_faults -v`，保存RED结果。
- [ ] 实现冻结的十case规格（详见同日设计文件）和专用调度器；复用类而不改变其行为。`run_case(case,geometry,pool,inputs)`返回TrialResult及干预记录，`run_suite(output)`拒绝已存在目录；保存所有Mask和原观测/替换信息。
- [ ] 运行新旧局部测试，保存GREEN；不执行实际研究案例。
- [ ] 规格复核通过后做质量复核；所有阻断项修复后才实际运行。

## Task 2：分列指标与独立审计（主代理）

创建`scripts/analyze_geometry_exp2_outcomes.py`及`tests/test_geometry_exp2_outcomes.py`。

- [ ] 手算失败测试：Complete=1.0、参考=1.2，则完成当时false、H时true；真实Update目标与当前完成任务目标不同；Complete不增加request/Applied；参考建立后离开目标则H支持false；未来参考不追认。
- [ ] 从World和真实active独立重建半径/速度/驻留参考。Update Applied使用旧激励左极限；Complete只记决策。每trial输出分列指标和事件对齐CSV。
- [ ] 对旧四例只读产生补充分析；不改原评分及结果。新十例运行后同样分析并核查干预、hash、预算、Mask/世界隔离。

## Task 3：执行与交付（主代理）

- [ ] 保存旧源码、首版全部结果和图稿的hash基线；执行10条一次性确定性开发案例，无随机调用。
- [ ] 局部/全量回归、compileall、软件链和旧成果保护验证。
- [ ] 生成两张诊断图：事件—激励—位置/参考时间线；五类机制响应与完成/最终参考分列。只用持久化数据，零新仿真。
- [ ] PDF/图稿逐页视觉检查、图例/字体/碰撞检查；保存来源hash索引和报告。
- [ ] 按实际结果写Chat审查PDF，说明未覆盖分支、模型边界和正式准入缺口；停止，不追加正式seed或参数扫描。
