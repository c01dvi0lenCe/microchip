# 第二章B1+B4第一批实施计划

> 用户已明确批准实施现有审查/整改方案中的B1+B4；采用测试先行和独立规格/质量复查，不commit/push。保留当前未提交的独立仿真文件。

**Goal:** 修复连续证据、无进展保护、偏离语义和评价分母，不扩展B2/B3或S1–S4。

**Architecture:** 实验链新增纯逻辑EvidenceWindow/ProgressMonitor，既有recognizer/policy/runner接入；评价以外部审核参考为主表，新增纯事件区间评价。旧函数位置参数和五状态字符串保留。

**Tech Stack:** Python、unittest、现有NumPy/OpenCV/CSV接口。

## 范围与问题映射

- P2/P3/P10：到达与源确认不得跨长gap、无效/重复/逆序帧或任务上下文。EvidenceWindow使用当前消费帧号和输入时间；SDK帧号/精确ACK时钟是B2，不伪称已解决。
- P4/P5/P6：Partial/Moving/Unknown不能无限Hold。ProgressMonitor按朝目标距离减少判断净进展，另有每尝试最长时间和质量不足界限；不新增几何投影（B3）。
- P7：孤立时序冲突Unknown/Hold，持续可靠空间偏离才Deviation。普通标签允许合法跳转。
- P9及T16–T18：Unknown、缺行、空Mask、失败任务、无事件、重复事件、区间和删失保留完整分母。
- P12：正式配置最低5帧/0.25s；仅显式synthetic_test_only且非experiment的现有软件fixture可用缩短门，避免破坏旧模式隔离测试。
- P1/P11属于位置/地图B3，明确保留风险，不在本轮顺手实现。

## 任务

- [x] 运行既有局部基线；增加`tests/test_chapter2_evidence.py`，复现P2/P3/P4/P5/P6/P7/P10/P12并记录RED。
- [x] 新增`dmf/experiment/evidence.py`：`EvidenceWindow.observe(context, frame_id, timestamp_s, eligible, centroid_mm, eta_target)`；相同timestamp/ID不得累计，断档/invalid/context切换重建；稳定跨度使用窗口后缀。
- [x] 在`perception.py`中复用窗口；`recognize(obs,t,frame_id=None,context=None)`保持旧调用，记录quality/reason；temporal冲突不直接Deviation，持续空间偏离至少2帧。
- [x] `ProgressMonitor.observe(context,t,progress_mm,reliable)`以距离减少为临时进展代理；`policy.decide`新增可选observation，旧调用仍有最长尝试边界；沿用accept后才增Retry和局部Recovery预算。
- [x] `runner.py`源门共用窗口，接受任务动作后清证据/预测历史，局部epoch仅用于B1窗口隔离；不重写ACK和FramePacket。日志只追加quality/证据/进展原因字段。
- [x] 配置新增最大gap/稳定跨度/无进展与最长尝试参数；正式最低门校验，保留显式合成fixture兼容，更新现有单异常即恢复的旧断言为持续空间偏离。
- [x] B4：先写P9/缺预测/空Mask/重复/区间/不确定/删失失败测试，再修`dmf/vision/metrics.py`、`evaluation.py`及新增`event_evaluation.py`。不自动生成真实标注，不访问硬件。
- [x] 局部测试、独立规格与质量复查，再运行全量编译/unittest/7项链路验证。输出逐问题修复前后、文件清单和B2/B3残留风险。

## 核心验收实例

```python
# 输入0,.1,.2,.3,10的目标合格观测最后仍Unknown，不得跨9.7s确认。
# 源Confirmation使用相同gap规则；相同ID/时间重复不增加窗口。
# GT=[Arrived,Arrived], pred=[Arrived,Unknown] => support2/recall.5。
# 人工参考[1.,1.1],确认1.3 => delay_interval=[.2,.3]。
```

局部命令：`python -m unittest tests.test_chapter2_evidence tests.test_chapter2_policy tests.test_chapter2_runner tests.test_chapter2_evaluation_regressions tests.test_chapter2_event_metrics -v`。

全量命令沿用AGENTS.md，不放宽旧性能门限。所有内存/合成fixture只作软件行为回归，不是论文实测准确率。

## 完成验证（2026-10-21）

新增50项、局部主回归93项通过；最终全量435项中434通过、1项可选FFmpeg测试跳过（125.093s，exit0）。compileall、7项独立链路验证通过。原GUI/事务/AM/第三章代码无diff；保留既有Tk after清理警告和PyTorch3.14弃用提示，不声称已修复。规格/质量独立复查通过，混合ID可用性边界另经RED/GREEN加固。仍不commit/push。
