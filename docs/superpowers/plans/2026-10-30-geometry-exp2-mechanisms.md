# 实验二因果闭环机制 Implementation Plan

> For agentic workers: use subagent-driven-development, TDD and sequential spec/quality review. User prohibits Commit/Push; work in current checkout because required prior research dependencies are untracked. No worktree/branch mutation.

**Goal:** 实现已确认的单活动目标替换闭环，验收确定性机制并生成四组n=1开发案例和Chat审查包。

**Architecture:** 新增独立exp2层；复用Gerber/有效轮廓/原Mask特征/RawAssessor/GateRunner。World与控制器隔离，参考只读取持久化truth。

**Tech Stack:** Python、NumPy、Shapely、OpenCV；Matplotlib与ReportLab/PyMuPDF只处理新开发输出。

## Task 1：保护、测试与独立核心

新增`dmf/chapter2_geometry_sim/exp2/{__init__,spec,world,controller,reference,runner,persistence}.py`、`run_chapter2_geometry_exp2.py`、`tests/test_geometry_exp2.py`。配置用不可变dataclass快照，路径/参数/开发身份完整；不修改旧配置。

- [ ] 记录Git及全部现有源码/冻结摘要；既有RawAssessor/GateRunner/轮廓测试先运行。
- [ ] 测试先行，缺失模块产生RED；确定性参数与API依据spec，不调用正式随机入口。
- [ ] World使用规格中的有界松弛积分，原子单活动目标/有限事务、任意切换p/v连续、无交叠不迁移、保存实际轮廓/phase/angle/area及积分时间。
- [ ] 控制器只接受frame/Mask特征/time/context，分开P0/transport/recovery/pending/complete/stopped；所有方法共同计时与预算。
- [ ] 参考及评分独立读取truth/控制事件，保存3计划步与互斥终止，区分request/Applied、工作流/独立路径完成。
- [ ] runner固定四个normal机制trial，无seed/RNG；曝光采样当前世界、排队递交、step切换不瞬移；固定H=40，终端后仍固定随访。

核心验收示例（具体类名可在同职责范围内选用，测试应使用实际实现）：

```python
world.request(191, 'Start')
before = world.snapshot()
world.advance(0.04)
assert world.active == 191
assert world.snapshot()['x_mm'] == before['x_mm']
# Moving retarget must keep state at the exact Applied boundary.
position, velocity = world.position.copy(), world.velocity.copy()
# At retarget application (without integrating a time interval):
# assert_allclose(world.position, position); assert_allclose(world.velocity, velocity)
```

- [ ] 把每项边界写成可手算测试，运行RED→GREEN；规格审查通过后再质量审查，关闭重要问题。

## Task 2：机制演示、持久化与独立复核

- [ ] 运行四方法normal各一次，非正式性能批次；另两个预声明Applied时间机制反例比较后续World，允许正常方法全部相同/失败。
- [ ] 保存World/实际逐帧Mask/曝光与递交表/门与窗口/事件/3步计划/评分/config/源码和输入hash；拒绝覆盖目录。
- [ ] 只读独立核验每Mask特征、事务顺序、active与request/Applied身份、面积/质心、全部事件来源和分母；不以原评分器给自身重打分替代独立检查。

## Task 3：验证与审查包

新增独立绘图/打包脚本，只读取本轮新数据。旧图不重画。

- [ ] 四组运动/覆盖与控制联合时间线；早/晚切换反例；必要编号/单位/图例/SIMULATION，解释性文字移图注。
- [ ] 局部及全量测试、compileall、diff、software chain与旧文件摘要保护；只报告实际结果。
- [ ] 打包一份Chat审查PDF，包含模型变化、全部开发记录、失败、测试、数据来源和正式运行尚未准入事项；逐页渲染核查。
- [ ] 更新任务实际状态后停止，不启动正式seed或实物AM输出。
