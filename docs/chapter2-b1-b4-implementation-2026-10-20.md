# 第二章B1+B4第一批改造记录

实施跨2026-10-20至2026-10-21（Asia/Shanghai）；文件日期沿用审查批次，完成验证以本节后续记录为准。

基线：当前工作区（HEAD `fe9699d7e6867ee8897056b122c8248153cadd3e`），保留此前未提交独立simulation文件。依据原差距审查和整改方案，仅实施B1/B4。未修改GUI、U-Net适配器、串口事务、固件、AM扫描或第三章；未高压实验、未生成真实研究GT、未commit/push。

## 复现与修复前后

下列输入都是内存/合成图的软件回归fixture，不是实际液滴研究数据。

| 问题 | 原行为（本轮RED确认） | 修复后行为与测试 |
|---|---|---|
| P2 | t=0,.1,.2,.3,10，最后Arrived | 长gap后仅新窗口首帧，Unknown；`test_p2_arrival_cannot_bridge_long_unobserved_gap` |
| P3 | 同样断档仍确认源 | 源/Recovery门复用EvidenceWindow，最后False；`test_p3_source_confirmation_cannot_bridge_gap` |
| P4 | Partial在t=1000仍Hold | 无进展/最长尝试有界Retry/局部Recovery/Stop，不依赖标签 |
| P5 | Moving在t=1000仍Hold | 同上；抖动必须超过历史最佳进展才刷新计时 |
| P6 | Unknown在t=1000仍Hold | 质量不足独立停止；可靠但标签未稳定仍受进展/尝试边界 |
| P7 | 单帧temporal_ok=False即Deviation | Unknown/conflict，不直接Recovery；持续可靠空间偏离至少2帧才Deviation |
| P9 | 两帧Arrived GT，预测Arrived/Unknown，支持数1、recall1 | 支持数2、recall.5、abstention.5；含Unknown预测列 |
| P10 | 实际PriorFeatures+mask链跨9.7s仍Arrived | 速度历史和确认窗各自重建，最后Unknown |
| P12 | 正式1帧/0秒配置被接受 | typed_config和三模式正式加载拒绝；仅显式非硬件合成fixture兼容缩短门 |
| 重复/无效/切换 | 重复时间可补足候选计数 | 重复ID/时间、无效帧、缺消费帧ID、任务上下文变化重建证据 |
| B4缺预测 | 只遍历预测成功行，漏掉参考 | 以参考左连接；缺行、空Mask、检测失败计入完整分母 |
| B4无事件/重复/区间 | 没有统一评价模块 | 人工区间延迟、提前/不确定、漏事件、重复、假事件和删失分开计数 |

P8合法跨状态跳转原已支持且保留，不把它当缺陷。P1位置门、P11地图退化验证归B3，本轮不实现。

首轮B1现有API反例和新接口契约共14个test method：出现13个失败断言（含子测试）及2个缺API错误，1项合法跳转保持通过；修复后14项通过。随后新增日志回归先观察到Retry行进展状态被accept清成insufficient，再改为记录决策时快照。B4首轮22个method出现37个失败断言，随后针对表头schema/未匹配缺文件/步骤倒序再观察到3个失败并修复。新增补充覆盖不计为真实样本。

## 修改文件与兼容接口

| 文件 | 改造 |
|---|---|
| `dmf/experiment/evidence.py`（新增） | EvidenceWindow、ProgressMonitor纯逻辑 |
| `dmf/experiment/perception.py` | invalid/conflict/Deviation分离；窗口；消费帧重复防污染；接受新动作后可清运动历史 |
| `dmf/experiment/policy.py` | 标签无关的净进展/最长尝试/质量时限；仍accept后增计数，局部恢复预算不随尝试清零 |
| `dmf/experiment/runner.py` | 源门共用窗口、局部任务上下文、动作后清证据；保留旧接收时间屏障 |
| `dmf/experiment/config.py`、`configs/chapter2_experiment.yaml` | 集中参数与正式最低门校验 |
| `dmf/experiment/logging.py` | 只追加quality/state_reason/progress_status三列 |
| `dmf/vision/metrics.py` | 全分母五类GT×六列预测、支持数/弃权、不确定GT及条件五类矩阵 |
| `dmf/vision/evaluation.py` | 参考左连接、漏预测/失败分母、缺文件/重复键错误、px schema守卫 |
| `dmf/vision/event_evaluation.py`（新增） | 严格外部人工区间事件评价，不读取控制阈值 |
| `tests/test_chapter2_evidence.py`（新增） | P2–P7/P10/P12、窗口/预算/质量/模式/日志回归 |
| `tests/test_chapter2_evaluation_regressions.py`（新增） | P9、完整分母、空Mask/缺文件/重复/schema回归 |
| `tests/test_chapter2_event_metrics.py`（新增） | 区间、漏事件、真假/不确定/删失、重复、完整路径及顺序 |
| `tests/test_chapter2_policy.py`、`tests/test_chapter2_runner.py` | 旧“孤立异常即恢复”断言改为持续空间偏离；原ACK前帧保护保留 |
| `docs/chapter2-experiment.md`、`docs/implementation-status.md` | 实际行为、完成边界与风险同步 |
| `docs/superpowers/plans/2026-10-20-chapter2-b1-b4-execution.md` | 本轮执行与验收记录 |

`StateRecognizer.recognize(obs,t,frame_id=None,context=None)`和`Confirmation.observe(ok,t,...)`保留原位置调用。`EventController.decide(state,t,source_confirmed=False,*,observation=None)`只新增可选观测；旧调用也有有界时限。`StateConfig`/`ControlConfig`新字段在尾部追加。

证据使用输入时间与当前消费帧ID：最少帧数、最短跨度、最大间隔、质心/覆盖稳定后缀；context改变重建。无效/冲突不复用旧状态。当前负目标距离为净进展代理，不冒称沿源目标方向投影。正式调用经load_config/typed_config约束；低门限直接构造仅用于软件单元测试。

## 外部人工事件评价契约

不提供真实标注数据。本模块只评价调用方提供的独立人工参考；人工来源字段本身不是审核真实性证明，完整性和审核身份仍需外部管理。

```python
from dmf.vision.event_evaluation import evaluate_events

# 仅演示schema的手工数字，不是正式研究GT。
identity = dict(trial_id='fixture', task_id='task', clock_domain='video:fixture')
manifest = [dict(identity, eligible=True, step_ids=[0])]
references = [dict(identity, step_id=0, status='arrived',
    observation_start_s=0., observation_end_s=2.,
    arrival_lower_s=1., arrival_upper_s=1.1,
    annotation_source='human', reviewed=True,
    provenance='software example only; not actual annotation')]
predictions = [dict(identity, step_id=0, action='Complete', timestamp_s=1.3)]
metrics = evaluate_events(predictions, references, manifest)
# per_step[0]的delay_lower_s=.2, delay_upper_s=.3（浮点容差）。
```

每个合格trial/计划step都在分母中，失败或缺参考不删除。reference.status支持arrived/not_arrived/uncertain/occluded/right_censored，后四类不得伪填到达区间。任务/step/clock必须显式匹配；不猜单位/时钟变换。Update/Complete才是确认，其他动作忽略并计数。每步按最早确认评价一次，重复另外标记，不能用后来正确事件抹去提前事件。任务步骤倒序或重复不能完成路径。

主路径完成率分母为全部eligible trial，另外提供明确标注的条件率；到达召回以全部已知到达step为分母。early_event_rate是可判读且有确认的step条件率，其分母显式输出，不与漏事件率混为一谈。所有率同时有绝对计数/denominators；不确定、遮挡、右删失、缺参考和观察区间外事件分别保留。这里的路径指标是识别回放评价，不是实物运输成功率。

## 回归命令

```powershell
python -m unittest tests.test_chapter2_evidence tests.test_chapter2_policy tests.test_chapter2_runner tests.test_chapter2_evaluation_regressions tests.test_chapter2_event_metrics tests.test_vision_framework tests.test_vision_cli -v
python -m unittest tests.test_chapter2_adapters tests.test_experiment_session tests.test_experiment_gui tests.test_recording_timeline -v
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

局部主回归已实际通过93项，B1新增20项、B4新增30项。独立规格与质量复查均PASS；质量复查还补出了“显式帧号→缺帧号→旧帧号”的边界，新增用例先RED再GREEN，现保留显式ID高水位并在ID可用性变化时清窗。首轮全量434项中433通过、1项可选视频测试跳过。

2026-10-21最终验证：边界修复后`python -m unittest discover -s tests -q`运行435项，434通过、1项因未设置DMF_FFMPEG跳过，125.093s、exit0；compileall通过，move/mix/split/loop/CSE/ZJU/CSC七项独立链路均PASS。未放宽性能门限。全量出现已有Tk定时回调在销毁后的非致命清理警告，PyTorch3.14适配测试也有已有弃用提示；本轮不声称修复这两项范围外问题。受保护GUI/事务/AM/第三章源码diff为空。

模式/适配器/会话/GUI/录像专项另实际运行33项，全部通过（8.617s），随后再次运行七项链路验证通过。独立质量审查原结论为无Critical/Important、可交付，附混合ID的非阻断建议；该建议由主代理通过RED/GREEN和最终全量验证修复。请求的修复后二次独立质量复查因审查代理资源限制未完成，不能把它写成再次独立批准。

既有独立simulation模块仅在全量回归中运行其单元测试，本轮没有新建/扫描或混用其成果。

## 尚未解决与下一阶段

历史边界说明：以下是B1+B4交付时的待办。2026-10-21已继续实施B2+B3软件部分，
最新实际状态与验证见[第二批改造记录](chapter2-b2-b3-implementation-2026-10-21.md)；
真实曝光映射、真实模型/标注、物理标定与高压实验仍未完成，不回写或伪造本阶段历史测试结果。

- B2：FramePacket仍未透传SDK捕获号/曝光映射；本轮局部epoch和消费ID不能证明物理曝光晚于APPLIED。仍使用execute返回后的保守主机接收屏障，没有改协议。下一步先写旧帧/重复SDK号/跨clock/下一步ACK失败回归，再包裹现有事务observer获取实际ACK接收stamp，设计可幂等消费事件。
- B3：Arrived仍缺目标位置硬门、rho电极面积覆盖和有向进展/横偏；退化地图直接加载检查及模板/实测质量也未完成。下一步先手算双分母、ROI/实测中心/斜向进展/退化地图测试，再复用现有交集和标定模块实现，不替换地图编号或扩展外围运输。
- 新稳定跨度/净进展epsilon只是软件初值，缺真实Pilot辨识。低帧率可能无法满足最大gap而保护退出，不能声称连续窗已证明所有相机帧率都可用。
- 真实U-Net权重、独立人工Mask/状态/到达区间、对应真实地图与时钟材料仍缺失；本轮没有真实准确率、物理延迟、真实Recovery效果结论。
- B4要求调用方提供完整审核参考和trial清单；代码不能证明人工provenance真实，也不能发现调用方从清单删除了整条失败试验。正式评测须冻结资源/任务/审核版本与hash，按采集批次划分后再开展S1–S4。
- 当前实验frames.csv(mm)到通用评价(px)/事件(clock)的显式adapter尚未实现，直接输入会报错，而不是默默给错指标。

仅在本批回归和原链路兼容验收完成后，再讨论后续仿真接入或S1–S4正式评测；不把此前simulation结果转换为真实研究成果。
