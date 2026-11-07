# Chapter 2 Research Gap Remediation Implementation Plan

> **For agentic workers:** 分阶段实施并记录复现/回归。2026-10-21更新：用户先批准B1+B4，随后批准并已实施B2+B3软件部分；C/D/E及真实材料/物理验证仍为后续方案。提交仍需用户明确确认。

**Goal:** 以最小改动补齐单液滴视觉状态、到达因果、离线消融和事件评测，使研究结论有可追溯的真实数据依据。

**Architecture:** 保留 `run_experiment`、第二章GUI、U-Net适配器、有限Retry/局部Recovery和原子事务客户端。特征只增补明确字段，连续证据与任务上下文集中为纯逻辑模块；S1–S4采用独立离线benchmark，共用冻结分割缓存，不接AM。复用既有地图、Pilot审核和事务事件旁路，不改第一章AM时序、固件或第三章规划。

**Tech Stack:** Python、NumPy/OpenCV、dataclass、YAML、CSV/JSON、现有ONNX/TorchScript适配器、unittest。

审查基线：`fe9699d`；历史参考：`e198777`。完整证据及G01–G12见[审查报告](../../chapter2-research-gap-audit-2026-10-20.md)。B1+B4边界见[首批记录](../../chapter2-b1-b4-implementation-2026-10-20.md)，B2+B3实际接口与484项最终回归见[第二批记录](../../chapter2-b2-b3-implementation-2026-10-21.md)。下列接口示意并非每个类型都原样实现；以实际记录/代码为准，S1–S4 CLI仍为拟议。

## 1. 修改边界与文件清单

| 文件 | 计划改动/职责 | 阶段 |
| --- | --- | --- |
| `dmf/experiment/evidence.py`（新增） | 步/尝试上下文、连续证据窗、确认事件、幂等消费、观测质量 | B1/B2 |
| `dmf/experiment/perception.py` | 保留五状态语言；接入双覆盖、距离、方向进展；分离观测冲突与真实偏离 | B1/B3 |
| `dmf/experiment/policy.py` | 加入与标签无关的无进展/最长尝试边界，沿用有限Retry/Recovery | B1 |
| `dmf/experiment/runner.py` | 显式epoch、APPLIED屏障、事件一次消费、阶段时间记录、映射到旧日志字段 | B1/B2 |
| `dmf/experiment/config.py` | 新窗口/进展参数及正式模式最小5帧/0.25s约束；低帧率证据不足诊断 | B1/B3 |
| `dmf/vision/contracts.py` | FramePacket增加可选FrameTiming，保留原位置参数及字段语义 | B2 |
| `dmf/experiment/sources.py` | 保留SDK帧号/接收双时钟；记录队列覆盖；可等待关闭完成 | B2/E |
| `dmf/experiment/actuator.py` | CommandResult增加实际APPLIED接收时间和事务关联，复用observer | B2 |
| `dmf/experiment/logging.py` | 新字段版本、事件表、延迟各段；老CSV字段保留 | B2 |
| `dmf/vision/features.py` | 同一交集计数生成eta/rho；实测中心一致；区域mask缓存 | B3 |
| `dmf/vision/calibration.py`、`dmf/vision/config.py` | 统一直接加载的非退化、坐标、图像尺度、地图质量验证 | B3 |
| `configs/chapter2_experiment.yaml` | 只在实施相应阶段时新增参数说明，不凭合成视频填写正式研究阈值 | B1/B3 |
| `dmf/experiment/benchmark.py`（新增） | 独立S1–S4离线评测、固定任务时间段、读取共同分割缓存 | D |
| `dmf/vision/event_evaluation.py`（新增） | 完整任务分母、人工到达区间、早更新/延迟/漏事件/路径识别指标 | B4/D |
| `dmf/vision/metrics.py`、`dmf/vision/evaluation.py` | 保留Unknown列、缺预测、漏检，输出完整分母 | B4 |
| `dmf/vision/pilot_annotation.py`、`pilot_annotation_gui.py` | 独立双人事件参考、版本/审核校验，保持既有Mask审核流程 | C |
| `scripts/evaluate_chapter2_baselines.py`（新增） | 离线build-cache/run/evaluate CLI；不通过旧baseline注册器重复实现U-Net | D |
| `configs/chapter2_benchmark.yaml`（新增） | 四组显式开关、冻结参数文件、资源manifest、任务/GT清单 | D |
| `controllers/experiment_controller.py`、`experiment_session.py` | 收尾状态显示和等待设备释放，不改变算法策略 | E |
| `tests/test_chapter2_*.py`、`test_recording_timeline.py` | 扩展现有逻辑/因果/模式隔离回归 | B |
| `tests/test_chapter2_evidence.py`、`test_chapter2_benchmark.py`、`test_chapter2_event_metrics.py`（新增） | 覆盖新纯逻辑与评测契约 | B/D |
| `docs/chapter2-experiment.md`、`docs/implementation-status.md` | 与实际证据和schema同步，不把合成回归计为实测 | 各阶段 |

初期不改 `controllers/electrode_transaction.py` 的发送、ACK、重试和扫描语义。优先包裹已有observer获得实际接收时间；若发现共享事务本身的新缺陷，另列变更和回归，不顺手重构。统一旧CLI的unet注册不是完成本目标的前置条件，暂保留其现行为。

## 2. 建议模块接口

### 2.1 帧时序与任务归属

在 `dmf/vision/contracts.py` 定义可选元数据，旧构造方式保持有效：

```python
@dataclass(frozen=True)
class FrameTiming:
    capture_frame_id: int | None
    receive_monotonic_ns: int | None
    receive_perf_counter_ns: int | None
    device_ticks_raw: int | None
    clock_domain: str
    timing_quality: str  # exposure_mapped / host_receive / video_pts / fps_unverified

# FramePacket现有字段全部保留，尾部增加：
# timing: FrameTiming | None = None
```

接收时钟、perf_counter、UTC、设备ticks不得直接相减；需要同域或已记录变换。设备ticks不确定频率时只保留原值，不转换为秒。离线录像时间表保留原始anchor/SDK帧号，而不只传相对秒。

在 `dmf/experiment/evidence.py` 定义：

```python
@dataclass(frozen=True)
class StepContext:
    run_id: str
    step_index: int
    attempt_index: int
    epoch: int
    source_id: int
    target_id: int
    applied_receive_ns: int | None
    clock_domain: str

@dataclass(frozen=True)
class ArrivalEvent:
    event_id: str
    context: StepContext
    first_frame_id: int
    last_frame_id: int
    evidence_start_s: float
    evidence_end_s: float
    confirmed_at_ns: int | None
```

事件ID由run/step/attempt/epoch及首次确认帧确定，重放相同输入保持确定性。`ArrivalEventLedger.consume(event) -> bool` 仅允许相同step被首次消费；在确认现epoch后才能消费。Retry/Recovery/Update进入新的epoch，清证据但不随意清累计恢复次数。各类任务上下文不能仅用源/目标对代替，路线可重复访问同一对。

CommandResult保留原字段，新增可空 `request_id`、`applied_monotonic_ns`、`applied_perf_counter_ns`；`SerialTransport`包装已有transaction observer，按当前request/sequence提取applied stamp并继续转发日志。offline/dry_run字段为空并明确simulated，不能伪造真实ACK。

### 2.2 几何特征

`dmf/vision/features.py` 增加纯函数 `region_overlap(mask, region_mask) -> RegionOverlap`，返回交集、液滴面积、电极面积、eta_droplet、rho_electrode；空液滴标invalid，空/裁剪不完整电极标invalid，不用0填充未知分母。保留 `coverage_for_region` 的既有含义。

实验Observation增补 `target_electrode_coverage`、`source_intersection_px`、`progress_mm`、`progress_fraction`、`lateral_error_mm`、`velocity_parallel_mm_s` 和质量原因；原 `eta_source/eta_target` 不改名换分母。通用与实验目标距离统一用实际像素多边形中心映射到mm。

`transport_projection(point_mm, source_mm, target_mm)` 返回定向距离和横向偏差，源目标重合直接报错。所有面积特征用同一mask/同一坐标地图；记录图像尺寸、ROI变换和map hash。先只输出rho用于研究分析，是否纳入Arrived硬门必须经真实尺寸分层验证。

### 2.3 质量、状态与连续证据

`Recognition`包含 `observation_quality`（reliable/invalid/conflict）、`motion_state`（原5类或Unknown）、`reason_codes`、`arrival_event`。原有状态字符串可继续供GUI/旧CSV使用。

`EvidenceWindow.observe(context, frame_id, timestamp_s, eligible, centroid_mm, eta_target) -> bool` 应同时满足：当前context、时钟有效、唯一新帧、最少帧数、最短时间、最大来帧间隔、窗口位置/覆盖稳定条件。invalid、冲突、epoch改变、目标改变、重复/逆序时间、长gap按明确原因重置；Source Confirmation复用同一窗口语义。

观测冲突先Unknown/Hold，不凭一帧预测失败触发Recovery。真实Deviation需持续可靠的空间偏离证据；可合法从Stationary直接Arrived、Moving直接Arrived或任意有效状态进入确认Deviation，不强迫线性状态顺序。候选改变仍重建到达证据。

`ProgressMonitor.observe(context, t_s, progress_mm, reliable) -> status` 只看历史，输出progress/no_progress/insufficient/attempt_expired。Partial形态静止、标签抖动和零净进展都能到达有界处理；不可靠观测用独立超时，不能自动转真实Deviation。

### 2.4 离线与评测接口

`benchmark.build_mask_cache(resource_manifest) -> cache_manifest` 仅做一次共同U-Net推理与hash；`benchmark.run_variant(cache_manifest, task_manifest, variant, frozen_parameters) -> output_manifest` 不访问GT、不打开串口、不自行改变输入任务段。

`event_evaluation.evaluate_events(predictions, references, trial_manifest) -> metrics` 以全部合格参考任务为主表左连接预测，保持漏事件/无到达/遮挡/删失；不能只遍历成功预测。

评测读取实验CSV必须经显式adapter，并记录px/mm与时钟域转换；实验帧缺video_id/mask_path等时不能猜默认值。算法确认帧和在线decision实际时刻分开输出。

## 3. 阶段A：冻结口径与材料清单（无控制代码变更）

- [ ] 核对本报告的G01–G12及P1–P12，选定本轮实际实施范围。
- [ ] 固定eta/rho、进展、横向偏差、观测质量、真实Deviation和人工到达区间定义。
- [ ] 固定S1–S4的信息开关及共同mask/任务输入，不强行要求单帧基线输出完整五类。
- [ ] 固定路径成功、提前更新、到达漏检、延迟分母和未知/删失规则。
- [ ] 建立资源manifest：模型/训练预处理/训练批次、原视频、地图、时间表、任务意图、人工审核版本及hash；缺失项明确记录为missing，不填合成替代品。

验收：每个研究指标都有可检查的分子/分母、时间域和所需材料；没有以算法阈值生成GT。此阶段完成不能声称模型或实物链完成。

## 4. 阶段B1：修复连续性、状态语义和无进展边界

先处理G01/G02/G03/G08，限定在第二章模块。

- [x] 把审查P2/P3/P10的断档样例、Partial停滞和单异常帧写为失败回归，确认现版本确实失败。
- [x] 引入EvidenceWindow和ProgressMonitor；源确认、Arrived共用gap和局部epoch规则，非完整B2任务因果证明。
- [x] 到达保留正式最低5帧/0.25s；允许参数更保守；仅显式非硬件合成fixture可缩短门，不用于正式控制或正式消融。
- [x] 分离invalid/conflict与confirmed Deviation，保留既有历史防污染与合法跨状态跳转。
- [x] 把无进展、最长尝试、质量不足分别映射到既有有限Retry/Recovery/Stop，记录不同原因。
- [x] 验证新增回归及原第二章策略/runner测试，检查低采样率和目标距离净进展/抖动；有向投影留B3。

已实施B1窗口的测试示例（完整StepContext仍留B2）：

```python
def test_gap_breaks_arrival_window(self):
    window = EvidenceWindow(min_frames=5, min_duration_s=.25, max_gap_s=.2,
                            max_centroid_span_mm=.2, max_coverage_span=.15)
    context = ('r', 0, 0, 1, 190, 191)
    values = [window.observe(context, i, t, True, (1., 1.), .9)
              for i, t in enumerate((0., .1, .2, .3, 10.))]
    self.assertEqual(values, [False] * 5)
```

本批验收：T05–T10及T15的B1连续性部分由对应回归覆盖；T15有向几何/位置部分仍留B3。各标签长期无进展均有有界终态；孤立冲突不Recovery；没有增加A*、失败电极绕路或全局重规划。阈值的单元测试值只用于软件行为验证，不转作正式实验标定。

## 5. 阶段B2：任务因果、精确软件时刻和事件幂等

- [x] 先写T11–T14/T21失败回归：旧帧、重复SDK号、相同步重复事件、下一步ACK失败、不同clock_domain。
- [x] 给FramePacket增加可选FrameTiming，LiveSource透传SDK元数据和队列覆盖数；兼容旧构造。
- [x] 使用现有observer得到实际APPLIED接收stamp；CommandResult传递请求关联，不改变串口发包/重试时序。
- [x] runner维护StepContext，只有当前epoch新鲜观测才进入证据；事件一次消费。
- [x] 拒绝ACK前接收旧帧；对先拍后收但无法映射曝光的帧记录causality_unknown，区分软件屏障和物理因果证明。
- [x] 增加ingest/segmentation/feature/decision/transaction/ACK时间，接收→ingest含转换/队列等待；图像落盘单列。未测物理曝光→驱动延迟。
- [x] 保持运输Retry、恢复重试、通信重试三个计数，并在frame/step/event表中可关联。

验收：每步最多一个成功Update/Complete事件；过期/重复帧不推进；一次事务仍遵守原协议且同序列最多两次通信重试；offline/dry_run永不创建transport；不能把不同时间域直接相减。未有曝光映射时只报告receive→ACK软件链路。

## 6. 阶段B3：几何与地图质量

- [x] 先写T01–T04/T15的手算测试，包括小滴/大滴、源残留、正交/斜向进展、实测override中心、ROI平移。
- [x] 同一交集生成eta/rho，缓存电极mask，不在每帧重复构造整套420掩模；只计算当前源/目标及必要候选。
- [x] 计算有符号p/e_perp及方向速度；统一目标距离，Arrived位置采用实际目标polygon+既有容差，不新增未标定中心距离/rho硬阈值。
- [x] 加入地图四角有限性、凸性/方向、面积/单应矩阵可逆性、点/ROI边界、可选图像尺寸与版本记录；四角全重合必拒绝。
- [x] 增加校准质量manifest接口：外部独立审核点、中心/边缘误差、有效范围、pitch单位、模板/实测区域来源；未生成真实审核点，不改变现Pilot版本失效机制。
- [x] 统一通用extractor与PriorFeatures的实测中心语义；保留旧eta字段与默认调用兼容。

验收：交集75/液滴100/电极400得到eta=.75和rho=.1875；反向进展为负；目标位置不满足不能确认；退化地图拒绝；模板几何不能自动升级实测。真实标定误差容限应在审核测试图前按实验精度需求冻结，并与每张地图的独立检查点误差比较。

## 7. 阶段B4：先使评测分母可信

- [x] 写T16–T18失败回归：Unknown预测、缺预测行、完全无事件、重复事件、时间区间、未到达及右删失。
- [x] 修改state metrics：人工确定五类GT全部入分母，Unknown作为预测列；GT不确定单独统计。
- [x] 修改evaluation主表为审核参考清单；合法空Mask对阳性GT计分割漏检，缺失文件直接错误；不得静默跳过。
- [x] 在event_evaluation实现提前区间、确认延迟区间、漏事件和路线识别完成率，输出绝对样本数及条件分母。
- [x] 明确frame_results的px字段与experiment frames的mm边界，拒绝未适配实验CSV；真正单位/时钟adapter尚未实现。

新增测试的必要数值：两帧GT均Arrived，预测一Arrived一Unknown时支持数=2、召回=.5、abstention=.5；人工到达[1.0,1.1]且确认1.3时延迟区间[.2,.3]。没有可判读到达且全程观察完整时的Update计错误事件；片段终止/遮挡则列删失。

验收：T16–T18全部通过，任何预测缺行/Unknown/失败运行均不能让总分母减少；5类条件矩阵与完整矩阵清楚分开。

## 8. 阶段C：真实材料、模型与独立人工参考

不开展高压实验。本阶段处理已有合法素材、训练/验证材料及离线审核。

- [ ] 获取并校验真实模型导出、预处理、模型hash和训练数据批次；真实训练网络与微型接口测试模型分开。
- [ ] 对正式ONNX/TorchScript选定后端做输出shape/概率/原尺寸、真实片段分割误差和推理耗时检查；模型缺失明确阻断“真实U-Net完成”验收。
- [ ] 将真实地图与对应原图、ROI、镜头/相机姿态版本绑定；外围使用实测polygon，未涉及外围的核心任务明确有效范围。
- [ ] 在Pilot工具增加事件参考表与双人独立意见；算法预测不对标注者显示。
- [ ] 原视频补连续事件帧，人工确认原定目标；未知目标、未知时间、缺Deviation样本分别标记。
- [ ] 按采集日/芯片/原视频组冻结训练/验证/测试划分，记录类别和事件支持数。单日同源ROI片段不随机拆分凑样本。

验收：独立人工Mask与事件参考可追溯，地图有效；测试标签非算法阈值产物；真实模型在未参与调参的批次上可复现。没有真实采集时间的数据只做分割/帧级事件比较，不输出真实速度或毫秒闭环延迟。某类样本不足就报告不可估计，不能用合成Deviation填充。

## 9. 阶段D：实现四组离线基线与研究报告

- [ ] 创建不含GT的任务manifest与共同mask缓存，写入模型、地图、图像、配置hash；S1–S4读取同一缓存。
- [ ] 实现明确的信息开关：S1当前质心；S2当前覆盖；S3覆盖+位置/任务空间；S4再加因果连续窗和时序信息。
- [ ] 采用teacher-forced任务时间段用于主比较；自由运行假设策略回放另表输出，不能伪称实物恢复/控制结果。
- [ ] 阈值只由训练/验证集选定，冻结文件后才评测试验集；四组都可看目标中心/任务定义，但不能偷看人工到达事件。
- [ ] 输出四组逐帧判定、候选/确认事件、早更新/漏事件/延迟区间、人工支持数、缺失/Unknown数量及失败清单。
- [ ] S4另输出完整五类GT×含Unknown预测的混淆矩阵；单帧S1/S2不输出伪造运动分类。
- [ ] 写T20与缓存一致性测试：GT变化不改变预测、测试批次不参与阈值拟合、同原视频不得跨split。

建议CLI契约（实施后才存在）：

```powershell
python scripts/evaluate_chapter2_baselines.py build-cache --config configs/chapter2_benchmark.yaml
python scripts/evaluate_chapter2_baselines.py run --config configs/chapter2_benchmark.yaml --variants S1 S2 S3 S4
python scripts/evaluate_chapter2_baselines.py evaluate --config configs/chapter2_benchmark.yaml
```

验收：四组输入hash完全一致，只有声明的证据开关不同；所有失败/漏检均入分母；真实事件由人工独立标注；结果含按trial/采集批次配对比较和不确定性。是否优于基线由实际结果决定，不把“S4一定最好”作为测试断言或结果筛选条件。

## 10. 阶段E：无AM输出dry_run与收尾验证

- [ ] 以已审核地图和真实模型做dry_run，transport factory设置为一旦调用就失败的监测对象。
- [ ] 模拟ACK延迟、图像写盘慢、队列覆盖、SDK短时timeout，检查稳定窗和无进展保护；仅在模拟运输接口内测ACK，不连接高压。
- [ ] 完善LiveSource的关闭完成信号/有限等待；停止预览、录像封装、实验启动的owner交接必须等close完成，不仅设置flag。
- [ ] 验证退出保留AM release/日志flush路径；统计真实接收→推理→decision时间，模拟ACK段明确标mock。
- [ ] 更新研究报告中的完成状态、真实材料清单、未验证设备行为，不沿用历史文档的过时“SDK占位”描述。

验收：T19/T21/T22通过；无串口输出；设备owner不重叠；掉帧和处理耗时可审计。物理电气应用时间、真实路径成功率、真实Recovery效果仍属于后续另行确定的实验。

## 11. 回归命令、交付与阶段选择

每次运行代码变更先执行相应局部回归；完成一阶段后按仓库要求执行：

```powershell
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

收尾检查仅包含预定改动、schema兼容、原子ACK/五帧门/局部恢复边界。合成用例只证明软件逻辑，真实准确率和物理时延必须来自对应独立材料。

2026-10-21：已按用户授权先后实施B1+B4及B2+B3，补齐软件连续性/评测分母/任务因果/几何接口，不依赖新模型与高压实验。C可整理已有素材，数据就绪后才做D；simulation需先对独立C组和本批算法补一致性adapter，E以dry_run收尾。软件回归不代表真实模型、真实标注、标定或物理闭环完成；没有创建实现提交。
