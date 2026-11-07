# 第二章单液滴视觉闭环：研究目标差距审查

审查日期：2026-10-20（Asia/Shanghai）。实际基线：`fe9699d7e6867ee8897056b122c8248153cadd3e`，本地分支 `codex/local-cloud-update-20261020`。历史参考：`e198777`。审查前工作区干净。本报告依据当前代码、配置、测试和本机最小复现；文档中的历史数据与本轮可检查的材料分开标记。

研究目标：建立基于 U-Net 分割、真实 420 电极地图配准、任务约束和连续时序信息的单液滴运动状态识别与事件驱动闭环控制。

## 1. 核心结论与范围

当前具备可运行的第二章实验软件链：采集 → 分割适配器 → 几何特征/因果预测 → 规则状态 → 四动作策略 → 原子事务 → 日志。它已超出接口草图阶段，但尚不足以支撑“真实 U-Net 五状态识别与实物事件闭环已经完成”的研究结论。

主要缺口是：真实模型与独立标注证据不足；地图仍可使用示例/模板几何；目标电极面积分母的覆盖率、定向进展和横向偏差缺失；稳定确认窗口可以跨越长时间无观测；Partial 停滞没有有界退出；时间先验不满足直接被解释为真实 Deviation；评测漏计 Unknown；缺少统一的事件级参考真值与延迟评测。

本轮仅新增本报告和[最小侵入修改方案](superpowers/plans/2026-10-20-chapter2-research-gap-remediation.md)。没有改运行代码、阈值、AM 刷新时序或固件，没有连接相机/串口，没有开展高压实验，也没有训练模型。S1–S4 在本文中完成可执行实现前的定义与验收设计，尚未新增可运行的四组算法实现。

第二章继续使用人工给定相邻路线、有限 Retry 和返回最近确认源的局部 Recovery。旧 GUI 的 8+4 秒全局重规划、第三章 A*/多液滴调度不移入第二章。

## 2. 实现与证据矩阵

标记含义：**已实现**表示存在可执行代码；**合成/模拟验证**不表示真实设备或真实液滴有效；**接口占位**表示入口存在但不能完成目标功能；**待完成/待实证**表示缺功能或缺真实材料。

| 环节 | 当前实际实现 | 判定与证据边界 | 主要代码/测试定位 |
| --- | --- | --- | --- |
| 离线视频 | OpenCV 解码；优先完整录像逐帧时间表，否则 PTS/FPS 回退 | 已实现；视频时间来源有标记，FPS 回退不能视为真实采集时间 | `dmf/experiment/sources.py:14`；`dmf/vision/timebase.py:9` |
| 实时采集 | OpenCV、插件工厂、单帧最新值队列、超时、MVS 独占与 LatestImagesOnly | 已实现，不再只是 SDK 插件占位；本轮仅检查源码和模拟测试，未验证实机 | `sources.py:42,60`；`dmf/experiment/mvs_camera.py:116,145`；`tests/test_mvs_camera.py` |
| U-Net 推理 | ONNX Runtime CPU/TorchScript；RGB/NCHW/归一化、二值输出、恢复原尺寸、模型 SHA256 | 推理适配器已实现；本机仓库未发现 `.onnx/.pt/.pth` 权重；测试是人工微型网络，不是训练 U-Net 的效果证据；ONNX 真实导出端到端未验证 | `dmf/experiment/segmenter.py:10`；`tests/test_chapter2_adapters.py:123` |
| 统一离线算法注册 | Threshold、Background 可用；注册器中的 unet 为 RESERVED | 统一 baseline CLI 的 U-Net 仍占位；不能因实验入口支持 U-Net 就认定 CLI 已支持 | `dmf/vision/algorithms/registry.py:19`；`pipeline.py:162` |
| 420 地图 | 四角单应变换、1–420 多边形、外围形状模板、pixel_overrides、ROI 地图平移 | 软件实现完整；真实配准/误差验收未完成。核心默认是整格矩形，外围默认模板，不能自动代表实测电极有效面积 | `dmf/vision/calibration.py:53`；`electrode_map.py:51`；`configs/electrode_map.yaml` |
| 地图审核工具 | 原图叠加、人工四角、版本、审核失效传播、Mask/状态审核 | 已实现并由合成文件验证；文档引用的真实标注目录在本机不存在，不能核验其当前审核进度 | `dmf/vision/pilot_annotation.py:169,229,285`；`docs/chapter2-pilot-annotation.md` |
| 五状态 | Stationary/Moving/Partial/Arrived/Deviation，加 Unknown | 规则已实现；阈值明确标为初值，缺真实五状态混淆矩阵 | `dmf/experiment/perception.py:73`；`configs/chapter2_experiment.yaml:1,29` |
| Hold/Update | Hold 无目标因此无串口输出；Arrived 更新路线，末步 Complete；接受后才推进 | 已实现；合成流程/模拟 ACK 验证。Update 后清确认门，通常能阻止同一确认结果重复推进 | `policy.py:26,50`；`actuator.py:98`；`runner.py:98` |
| Retry | Stationary 超时后重新声明同一目标；接受后递增；与通信重试分开 | 已实现，有限次数；不是电极 ALL_OFF 脉冲 | `policy.py:40,54`；`tests/test_chapter2_policy.py:64` |
| Recovery | 重新激活最近确认源；视觉确认源后再尝试；次数/恢复时限有界 | 已实现；观测拒绝立即触发可能造成误恢复；离线回放不证明液滴受该动作控制 | `policy.py:34,40,46`；`tests/test_chapter2_runner.py:67,131` |
| 原子指令/ACK | BEGIN/逐 SET ACK/COMMIT/APPLIED；同序列最多两次重试；失败不更新本地 active | 已实现，模拟串口有覆盖；本轮未做实机串口或示波器验证 | `controllers/electrode_transaction.py:95,138`；`dmf/experiment/actuator.py:8,28` |
| 时间与日志 | frames/steps/commands、配置/地图/模型快照；实际发送/ACK 事件；录像 SDK 帧号、原始计数、主机双时钟与 UTC | 已实现；实验 FramePacket/frames.csv 丢失部分 SDK/高精度元数据；主机接收时刻不是曝光时刻 | `dmf/experiment/logging.py:12`；`dmf/recording.py:12`；`sources.py:106` |
| GUI 生命周期 | 实验后台线程、最新帧槽、限制设备争用、退出尝试释放和日志 flush | 已实现，GUI/线程测试存在；LiveSource.close 仅置 stop，不等待采集线程完成；切换设备所有权仍需收尾确认 | `controllers/experiment_session.py`；`experiment_controller.py:116`；`sources.py:150` |
| 研究评测 | IoU/Dice/边界/质心、覆盖误差、归属、五类混淆计算函数 | 部分已实现；实验 CSV 与 CLI schema 未贯通，事件到达/路径/端到端延迟评测未完成 | `dmf/vision/evaluation.py:23`；`metrics.py:96` |

相对 `e198777`：增加 GUI、MVS、录像/事务时间线、Pilot 审核工具等；`perception.py` 和 `policy.py` 没有差异，以下核心判别与策略差距仍存在。旧文档中“相机 SDK 尚未实现”的表述已落后于现代码，应与“已实现但未实机验证”区分。

## 3. 特征逐项核查与推荐定义

令 D 为液滴前景，E_t/E_s 为同一图像坐标中的目标/源电极有效多边形，c 为液滴质心，c_s/c_t 为实测地图对应中心。面积默认采用同一栅格像素计数；透视显著时，应说明其为图像面积比，或统一整流后计算，不能称为物理 mm² 面积比。

| 特征 | 定义 | 当前可计算性/使用情况 |
| --- | --- | --- |
| 液滴目标覆盖率 | eta_t = area(D∩E_t)/area(D) | 已计算并用于 Arrived；`coverage_for_region` 的分母确为液滴面积 |
| 目标电极覆盖率 | rho_t = area(D∩E_t)/area(E_t) | 未计算；不能把 eta_t 重命名为 rho_t。小滴完全位于大电极内时 eta_t=1 而 rho_t 可很小 |
| 源区残留 | eta_s = area(D∩E_s)/area(D)；另记残留绝对像素数/源电极覆盖率 | eta_s 已有，绝对残留和电极面积分母版本未输出。多显著连通区域被拒绝，因此断开的真实残留当前会变成 Unknown，不能直接证明无残留 |
| 质心目标距离 | d_t = norm(c-c_t)，mm | 已计算/记录，实验 PriorFeatures 对实测中心有处理；Arrived 不使用该量。通用 feature extractor 对 calibrated override 仍取模板 center_mm，存在两条路径不一致 |
| 沿方向进展 | u=(c_t-c_s)/norm(c_t-c_s)；p_mm=(c-c_s)·u；p_norm=p_mm/norm(c_t-c_s) | 未实现；不能用总速度替代，不应裁剪 p_norm，否则会隐藏反向和越界 |
| 横向偏差 | e_perp=叉积(u,c-c_s)，mm，可同时输出绝对值 | 未实现；当前 spatial_ok 只是候选多边形并集内外，不等于源目标走廊约束 |
| 真实时间速度 | v=norm(c_i-c_j)/(t_i-t_j)，另记 v_parallel=(p_i-p_j)/dt | 速度公式已实现；PriorFeatures 仅用此前接受的位置、长间隔清历史。没有方向速度；真实精度受时间来源、地图误差、采样率约束 |
| 连续窗口稳定性 | 同一步/尝试、有效且新鲜观测、最少帧数、最短时间、最大间隔、位置/覆盖波动 | 仅“连续候选次数+首尾时长”已实现；无最大间隔、窗口位置离散度/覆盖波动、采集帧重复/掉帧审计 |

完整 420 个 ID 不等于真实 420 多边形已配准。默认核心矩形覆盖整个 pitch 单元，未表达真实间隙；rho_t 的分母必须使用实测有效电极边界。外围 401–420 默认几何应保留 template 标记，涉及其正式标签/分析时要求实测覆盖；第二章路线仍限定核心相邻电极，不为满足地图数量扩展运输控制范围。

## 4. 五状态、停滞和时序审查

### 4.1 观测有效性与 Deviation

已有正确区分：无 mask、置信不足、面积不合适、多显著连通域 → Observation.valid=False → Unknown；不直接判 Deviation。空间/时间被拒绝的位置不进入预测历史，预测只用之前接受的至多两个位置，不读未来帧。

剩余问题：在单显著 mask 被视为有效后，只要候选区域或运动预测不符，`StateRecognizer` 立即输出 Deviation，跳过 consistency_frames。该冲突既可能来自真实偏离，也可能来自错误分割、短时反光、相机/芯片移动、误标定、低帧率或模型漂移。当前没有独立的“观测冲突待确认”维度，一次异常即可触发 Recovery。

建议分离 observation_quality、motion_state、deviation_evidence；保留原五种运动状态及 Unknown，对矛盾观测先保持/重新观测，真实 Deviation 必须有可信几何和持续证据。缺失/过时/时间异常不生成真实偏离标签。

### 4.2 合法跨状态跳转

当前逐帧由特征决定候选，允许 Stationary 直接 Arrived、Moving 直接 Arrived，不强迫经过 Partial；候选切换重置计数。这适合低帧率可能跳过短暂状态的情况。后续不得引入 Stationary→Moving→Partial→Arrived 的强制顺序。

问题在确认能力而非跳转本身：低帧率下五帧至少需要约 4/fps 秒，无法用“0.25 s”保证固定确认延迟。应报告实际采样间隔和检测延迟；采样过稀时输出证据不足，不降低正式闭环的五帧/0.25 s 下限。

### 4.3 中途停滞与长时间 Hold

`EventController.decide` 只对 Stationary 检查 wait_s。判别顺序先 Partial 后速度，因此静止的桥接/拉伸形态即使速度为零也可能一直 Partial→Hold。有效 mask 但状态不断切换时可长期 Unknown；位置抖动可长期 Moving。`runner` 在 obs.valid 时刷新 last_valid，因而这些情况不受无检测超时限制。

建议在独立时间窗上判断“朝目标无有效进展”，不由标签 Stationary 单独决定超时；引入每尝试/每步最长等待界限。有效但无进展进入既有有限 Retry/局部 Recovery；观测质量长期不足进入明确保护停止，不能假装真实 Deviation。所有判断只看当前及过去数据。

### 4.4 丢帧、间隔与旧图像

显式无效帧会清状态计数，丢失持续过久有停止条件；LiveSource 有最新帧槽、读取超时、处理后 stale 检查。SDK 暂时 Timeout 可在采集线程内继续，但消费者等不到帧仍会终止实验，不能等同“任意掉帧都可无缝恢复”。

最大的窗口缺口是没有来帧的长时间区间：PriorFeatures 只清速度历史，StateRecognizer 和源确认门不清累计证据。即使没有显式 invalid 帧，长间隔也必须打断稳定性。队列覆盖丢帧与相机丢帧需区分；消费 frame_id 当前不是 SDK frame_number，无法直接审计。

## 5. Arrived、Update 与 ACK 因果关系

### 5.1 现有 Arrived 的实际逻辑

在 valid、spatial_ok、temporal_ok 后：eta_t≥eta_arr 且 eta_s≤eta_release，候选累计 arrival_frames 帧并持续 arrival_duration_s 后输出 Arrived。默认值为 5 帧、0.25 s。它不要求 d_t、rho_t、低速度、质心窗口离散度或目标覆盖的窗口最小值。

已有来源确认门也使用面积比、帧数和持续时间。`StateConfig` 校验仅要求 arrival_frames≥1、duration≥0，因此正式模式配置可被放宽为单帧；默认值本身不会单帧更新，但约束没有被固化为正式模式下限。

推荐正式到达事件需要：可信观测、当前任务/尝试因果匹配、目标液滴占比、源区释放、目标位置/区域、连续稳定窗口。rho_t 先做辅助特征和分析；不能要求所有大小液滴都填满电极，是否作为硬门应由真实尺寸分层数据决定。位置稳定建议用窗口位移/离散度，不能只靠相邻两帧速度。

### 5.2 已有防重复与旧帧保护

实时 execute 返回后才 `controller.accept`，接受目标命令才更新 last_applied；早于该时刻的接收帧被标为 PRE_ACTUATION_FRAME 并 Hold。Start/Update/Retry/Recovery 后重置 recognizer 和源确认门。旧窗口通常不能直接推进新目标；命令失败后停止，避免继续重复 Update；视觉已成功步骤在下一目标发送失败时保留成功记录。

因此，没有证据支持“当前每次都会单帧提前更新/重复更新”的结论。风险是缺乏完整证明边界：

1. last_applied 是 execute 返回后的主机 monotonic 时刻，较实际 ACK 接收略晚；它是保守的软件屏障，不是精确 ACK 时间，也不是物理上电时刻。
2. 接收时间晚于 ACK 不证明曝光晚于 ACK。SDK 缓存、曝光区间、传输延迟可能带来先拍后收的帧；现代码没有时钟映射或曝光证据。
3. FramePacket 不保留 SDK 帧号，帧/状态/decision 没有 step_id、attempt_id、epoch；现行为依赖单线程顺序和重置，缺显式 exactly-once 事件契约。
4. offline 刻意不应用 ACK 屏障；它是假设动作回放，不能据此证明真实控制因果、Recovery 成功或控制端到端时延。
5. 正式配置可降为 1 帧/0 秒，加上窗口断档缺口，仍有提前确认风险。

建议 ArrivalEvent 使用 `(run_id,step_id,attempt_id,event_id)`，每步只消费一次；命令结果携带实际 APPLIED 接收时间及 clock_domain。保留现有接收屏障并加入帧新鲜度/SDK序号；曝光/接收关系无法证明时标记不确定，不写“曝光后严格因果已验证”。

## 6. 本轮最小复现记录

以下均为内存 Observation/合成 mask 的软件反例，不是实测液滴行为。未修改生产代码。

| ID | 输入/操作 | 当前观察输出 | 意义 |
| --- | --- | --- | --- |
| P1 | valid/spatial/temporal 均真，eta_t=.9，eta_s=0，distance=99，velocity=1000，默认门，t=0,.1,.2,.3,.4 | 第五次 Arrived | 单独验证状态层未使用 distance/velocity；此抽象输入不声称是可发生的真实图像 |
| P2 | 同一合格目标观测，t=0,.1,.2,.3,10 | 第五次 Arrived | 9.7 s 无观测仍累计稳定窗口 |
| P3 | Confirmation(5,.25)，上述时刻全部 True | 最后 True | 源/恢复确认门也跨断档 |
| P4–P6 | 已 Start 的策略在 t=1000，分别输入 Partial/Moving/Unknown | 均 Hold | 状态依赖超时不覆盖无进展/不确定 |
| P7 | 单次 temporal_ok=False，其他有效 | Deviation | 一次运动不一致即可进入真实偏离分支 |
| P8 | 单帧配置下 Stationary 后直接目标覆盖成立 | Stationary→Arrived | 允许跳转；这一能力应保留 |
| P9 | GT=[Arrived,Arrived]，预测=[Arrived,Unknown]，state_classification_metrics | 只计1帧，Arrived recall=1.0 | Unknown 预测被排除，完整分母的召回应为0.5 |
| P10 | 400×400合成图，真实调用 PriorFeatures+StateRecognizer，目标内圆mask，时刻同P2 | t=10 时 velocity=None 但 Arrived | 确认断档问题贯穿特征与状态链，不是只构造 Observation 的假象 |
| P11 | ArrayGridCalibration 四角均(0,0)，构造 ElectrodeMap | 没有拒绝，仍返回420个区域 | 420完整性检查不等同标定有效性检查；Pilot GUI的检查未覆盖直接加载路径 |
| P12 | typed_config(StateConfig,{arrival_frames:1,arrival_duration_s:0}) | 配置被接受 | 正式模式的最低时序约束未强制 |

关键复现可直接运行（合成、无硬件）：

```python
from dataclasses import replace
from dmf.experiment.config import StateConfig, ControlConfig
from dmf.experiment.perception import Observation, StateRecognizer
from dmf.experiment.policy import EventController
from dmf.vision.contracts import DropletState as S
from dmf.vision.metrics import state_classification_metrics

f = Observation(valid=True, centroid=(1., 1.), area=100., eta_source=0.,
                eta_target=.9, distance=0., velocity=0., spatial_ok=True, temporal_ok=True)
r = StateRecognizer(StateConfig())
print([r.recognize(f, t).value for t in (0., .1, .2, .3, 10.)])
c = EventController((1, 2), ControlConfig())
c.accept(c.decide(S.STATIONARY, 0., source_confirmed=True), 0.)
print(c.decide(S.PARTIAL, 1000.).action)
print(state_classification_metrics(['Arrived', 'Unknown'], ['Arrived', 'Arrived'])['per_class']['Arrived'])
```

## 7. S1–S4 离线基线定义

四组共用同一冻结 U-Net、相同预处理/后处理、420 地图、帧集合、任务清单和时间源，只改变判定证据。原始图像与模型输出 hash 固定；Ground Truth 不进入特征、空间候选、时间预测或阈值选择。任务源/目标来自操作者记录，不从 GT 到达位置反推。

| 组别 | 使用的信息 | 到达候选/事件定义 | 明确排除 |
| --- | --- | --- | --- |
| S1 单帧质心 | 当前预测 mask 质心、目标中心 | 质心距离/目标接受区域满足验证集固定条件即发候选；不等稳定窗 | 覆盖率、过去帧、速度、预测 |
| S2 覆盖率 | 当前 eta_t、eta_s；rho_t 记录为诊断 | 目标液滴覆盖达到条件且源残留低即发候选；无稳定窗 | 位置走廊、速度、过去帧 |
| S3 空间先验 | S2 + 当前目标位置、人工任务候选区、定向进展/横向边界 | 通过任务空间一致性及位置门后发候选；仍单帧 | 连续窗口、历史预测、稳定持续时间 |
| S4 空间+连续时序 | S3 + 因果接受历史、速度/进展、连续有效窗口 | 五帧且至少0.25s、最大间隔、稳定性、任务epoch均满足才发一次确认事件 | 未来帧、GT阈值反推、跨步骤窗口复用 |

S1/S2是故意简化的离线到达消融，不直接接硬件；不能把它们的单帧设定移入正式控制。共用的基本 mask 格式/置信质量、输入时间合法性和因果任务归属应一致，避免把预处理差异误当连续时序收益。S3空间拒绝属于本组算法证据，不能暗中作为S1/S2的公共门。

主要比较任务是到达事件识别，不为单帧 S1/S2 虚构 Moving/Stationary 的五类输出：单帧位置无法可靠识别运动。四组统一输出 ArrivedCandidate/Confirmed、NotArrived、Unknown 和证据。完整五状态混淆矩阵单独评测 S4；若要比较五状态消融，应另预注册共同的运动估计支路，不能继续称 S1 为纯单帧基线。

离线按人工/日志给定的任务时间段进行 teacher-forced 评测，不能由各组自己的 Update 改写下一任务起点后再相互比较；否则早更新会改变后续输入任务，指标失去可比性。可另报告自由运行的假设策略回放，但标为 replay，保留错误传播和不可反作用限制。无可靠命令日志的旧视频不用于 ACK 条件评测。

每组输出 frame_decisions.csv、arrival_events.csv、run_manifest.json；共同记录 video/frame、run/step/attempt、算法版本、模型/地图/配置hash、时间来源、有效性、特征、候选和事件。阈值只在训练/验证批次选定后冻结；测试批次按采集日/芯片/视频隔离，同原录像裁剪片段不能跨分组。

## 8. 真实人工参考到达事件方案

现有 Pilot 工具是合适基础：草稿不自动成为 GT，Mask 审核与状态审核分开，地图改动使状态审核失效。缺少的是覆盖连续过程的事件级标注、独立双人判读和事件时间不确定性。

1. 为每条人工指定路线建立 trial_id、step_id、源/目标、原始视频hash、地图版本、时间来源；只有原定目标明确的片段才可做任务状态 GT。旧视频未知目标保持缺失。
2. 两名标注者独立看原始连续视频及经核对地图，隐藏算法状态、数值阈值、候选事件和模型Mask。根据可见液滴主体完成进入目标、源区不再保留连通桥/显著残留、随后稳定驻留，给出“最后明确未到达帧”和“首次明确到达帧”，并标注后续是否反弹/离开。
3. “视觉稳定驻留”的人工判读手册用正反例和可见行为描述预先定稿；不得把 eta_arr、rho、距离或算法五帧门直接转成参考标签。手工Mask用于分割/几何参考，不运行当前分类器生成状态 GT。
4. 记录 arrival_frame_interval=[f_L,f_R] 以及对应时间区间；低帧率导致事件时间不确定就保留区间。没有真实采集时钟的旧视频只报告帧级事件和定性时序，不输出伪精确毫秒延迟/速度。
5. 分别标注 observable/occluded、partial/stalled/deviated、原定目标是否可知、是否完整看见事件；未到达、片段结束前无法确认、被遮挡是不同结果。Deviation需可信的任务方向和持续偏离证据，失检不能充当偏离样本。
6. 双人冲突由第三人/共同复核裁定，保存原意见、裁定、标注者、版本、修改理由和一致性统计；评测集冻结后修改需升版本并重跑全部组别。
7. 63张关键帧不足以提供连续到达窗口；围绕源、过渡、接触、拉伸、停滞、到达/反弹加密连续帧。资料整理可以现在完成；实机高压采集不在本轮内。

建议新增独立 arrival_reference.csv：`trial_id,video_id,step_id,source_electrode,target_electrode,last_not_arrived_frame,first_arrived_frame,arrival_lower_s,arrival_upper_s,outcome,visibility,timestamp_quality,annotator_id,review_status,map_hash,video_hash,notes`。不要把两名标注者记录覆盖为一行后丢失分歧。

## 9. 指标是否能输出、正确分母与时间口径

| 指标 | 现状 | 补齐方式与统计边界 |
| --- | --- | --- |
| 路径成功率 | steps.success 和 summary.status 有原料，缺统一批次汇总/独立GT | 人工确认完成全部计划步骤的 trial 数/全部符合入组条件且尝试的 trial 数；停止/通信错误/失败不静默剔除，分层列出原因。回放只报路线识别完成率，不叫物理控制成功率 |
| 提前更新率 | 缺参考事件/事件级评测 | 已发送或拟发送Update早于参考到达下界t_L为确定提前；处于[t_L,t_R]为不确定；没有到达且观察完整的Update另记错误事件。分母同时报告全部运输步骤和全部Update，禁止只选成功步骤 |
| 到达确认延迟 | 有帧时刻但缺人工参考、实际决策时刻 | 报签名差值区间[t_confirm-t_R,t_confirm-t_L]；到达未确认单列漏检/删失，不能只报被成功确认样本的均值。算法确认帧延迟与在线决策时间延迟分开 |
| 状态混淆矩阵 | 已有函数，但Unknown预测被排除；CLI默认state_pred=Unknown | 对人工确定五类GT保留Unknown预测列并作为漏识别；未知GT另列不确定数量。报告每类支持数、召回/F1、abstention、有效预测覆盖率；5类条件矩阵只能作附录 |
| 控制端到端延迟 | 有pipeline_ms及事务事件，不足以直接得到完整链路 | 记录接收→推理起止→特征/决策→事务请求/写出→APPLIED接收。可得主机接收至ACK总延迟及各段P50/P95/P99；曝光→物理电气应用延迟需同步/测量，当前不能声称已测 |
| 重试次数 | step retry_total/recovery_total、frame retry_count、事务attempt已有 | 区分运输超时Retry、恢复后重新激活、通信同序列重试。当前retry_total含recovery confirmed的Retry，不应直接称为超时重试数 |

附加评测风险：`evaluate_results` 只遍历有预测且匹配GT的行，缺预测帧可消失；需按GT评测清单建立完整分母。缺失预测Mask（None）当前返回None分数并被mean_available跳过；合法的全零Mask则可正常计为分割漏检，两者不能混称。应对缺结果显式报错或按预注册规则计入失败，不能静默减少分母。评价器不校验Pilot审核标记，必须由入组验证器强制使用已审核清单。

当前两种CSV schema不同：实验是 timestamp/recognized_state/centroid_x(mm)，CLI评测期待 timestamp_s/state_pred/centroid_u_px。直接把frames.csv塞给evaluate_results会缺video_id、mask_path等字段，不能视为现成贯通。应增加显式适配层，不能猜坐标单位或重命名后混用。

## 10. 按优先级排序的差距

P0表示在据此开展可信算法比较前需要处理，不表示本轮立即改运行逻辑。

| 优先级/ID | 差距及后果 | 最小修改落点 | 验收条件 |
| --- | --- | --- | --- |
| P0 G01 | 长间隔不清到达/源确认，假稳定 | perception.py、runner.py、config.py | P2/P3/P10反例不确认；缺帧/长间隔重建窗口 |
| P0 G02 | Partial/Moving/有效Unknown无进展可无限Hold | policy.py、perception.py、config.py | 各标签下无进展均有有界结果；维持局部Retry/Recovery |
| P0 G03 | 一次运动不一致直接Deviation/Recovery | perception.py、runner.py | 无效/冲突观测与确认偏离分离；孤立误分割不Recovery |
| P0 G04 | 无显式任务epoch/事件幂等；ACK时间未贯通；接收≠曝光 | contracts.py、sources.py、actuator.py、runner.py、logging.py | 同步任务/尝试、旧帧拒绝、每步一次事件；不能证明曝光因果时明确标记 |
| P0 G05 | Unknown/缺预测被排除，评测偏乐观 | metrics.py、evaluation.py及新事件评测 | P9完整分母召回=.5；漏帧、漏事件和失败步骤进入分母 |
| P1 G06 | eta/rho混淆风险，进展/横向误差缺失，距离未参与到达 | features.py、perception.py、config.py | 手算几何一致；位置不满足不确认；rho按液滴尺寸验证后决定是否硬门 |
| P1 G07 | 退化/模板地图可进入分析；实测中心路径不一致 | calibration.py、config.py、features.py | 退化/翻转/非有限/越界地图拒绝；实测地图版本与误差可追溯 |
| P1 G08 | 正式模式可降到单帧零时长 | experiment/config.py | 正式配置不得低于5帧/0.25s；S1–S3仅独立离线评测 |
| P1 G09 | 真U-Net模型、真实标注和标定证据缺失 | 资源清单/模型manifest/Pilot标注，不伪造模型 | 模型hash/预处理/独立批次分割结果可复现；缺材料时明确未完成 |
| P1 G10 | S1–S4及事件GT/评测未贯通 | 新offline benchmark与event evaluation | 四组同输入、参数冻结、人工独立GT、完整事件指标 |
| P1 G11 | frames日志缺任务ID/阶段时间；pipeline_ms不含后续图像写盘 | logging.py、runner.py、contracts.py | 全链路可关联、时钟不混用，延迟有明确定义 |
| P2 G12 | 资源close异步返回、标定/模型文档有过时描述、CPU全图推理成本未实测 | sources.py、GUI收尾、文档 | 停止后相机释放完成才可换owner；真实尺寸推理另测，不用合成速度替代 |

## 11. 测试与验收样例

| 用例 | 构造 | 期待行为 |
| --- | --- | --- |
| T01 面积分母 | 液滴100px，目标电极400px，交集75px | eta=.75，rho=.1875，禁止混名 |
| T02 源残留 | 主体目标内+独立源残留 | 保留残留证据或Unknown，不虚假零残留Arrived |
| T03 方向 | 相同总速度，分别朝目标/背离/横向 | p递增/递减、e_perp增长可区分；无进展时限可触发 |
| T04 不等间隔 | 位置0→1mm，dt=.1/.5s | 10/2mm/s；首帧/超长gap速度缺失 |
| T05 断档 | 四帧合格后长gap，再一帧 | 到达和源确认均不累计到第五帧 |
| T06 显式失检 | 合格→失检→合格 | 重建窗，Unknown不变真实Deviation |
| T07 合法跳跃 | Stationary后直接稳定目标，未见Partial | 满足新窗口后可Arrived，禁止强制经过所有状态 |
| T08 途中停滞 | Partial且p长期不变；Moving抖动但p不增 | 有限Hold后Retry/Recovery或明确保护停止 |
| T09 冲突观测 | 一帧错误mask位置，随后正常 | 不立即Recovery，不污染接受历史 |
| T10 真实偏离证据 | 连续可信单滴越过任务走廊 | 确认Deviation，只激活最近确认源 |
| T11 旧帧 | 在ACK前采集/接收，ACK后处理 | Hold，不计源/到达窗口 |
| T12 先拍后收 | SDK曝光序号/时间表明旧，接收在ACK后 | 拒绝或标因果不确定；不声称严格因果 |
| T13 重复事件 | 重复帧号、重入回调、相同arrival_event | 每步最多一次Update/Complete |
| T14 下一步失败 | 本步到达，下一目标ACK失败 | 本步成功保留，下一步失败，停止并释放 |
| T15 配置/地图 | 单帧正式门、退化四角、错ROI/地图尺寸 | 启动前拒绝，清晰错误；离线消融不接AM |
| T16 评测分母 | 两个Arrived GT，一正确一Unknown/缺预测 | 支持数2、召回.5、abstention/漏预测显式 |
| T17 人工时间区间 | GT到达[1.0,1.1]，确认.9/1.05/1.3 | 确定提前/不确定/延迟[.2,.3]，不伪造单一真值 |
| T18 无到达/删失 | 完整看见不达、片段结束看不清 | 错误更新与删失分开，不能挑成功片段 |
| T19 模式隔离 | offline/dry_run+mock transport | transport从未构造；通信重试契约保持 |
| T20 数据隔离 | 同原视频两个ROI短片分入训练/测试 | 入组验证失败；GT审核/版本不完整不得入测试 |
| T21 延迟时钟 | mono/perf/UTC/相机ticks混合输入 | 未有映射拒绝相减；分段延迟与ACK关联准确 |
| T22 资源收尾 | 相机close阻塞可控、正在封装/写日志 | 完成释放/flush后再解锁owner，异常不冒充完成 |

以上样例为拟新增回归/验收，不是已经实现的新测试。

## 12. 本轮验证与阶段门

本轮实际执行83项第二章策略/引擎/适配器、MVS、录像时间线、Pilot、视觉框架/CLI测试，全部通过。命令：

```powershell
python -m unittest tests.test_chapter2_policy tests.test_chapter2_runner tests.test_chapter2_adapters tests.test_mvs_camera tests.test_recording_timeline tests.test_pilot_annotation tests.test_vision_framework tests.test_vision_cli -v
```

本会话在更新至同一 `fe9699d` 后还执行过完整352项测试（351通过、1项FFmpeg条件跳过），compileall及7个独立闭环场景通过。本轮没有修改生产代码，因此不重复消耗全量回归；该结果证明软件既定测试通过，不证明上述缺口不存在。83项日志中显示的“1帧review_status”来自临时合成fixture，绝不是实际Pilot审核进度。

建议阶段门：A=冻结审查/指标/人工标注口径；B=离线回归修复P0及几何、因果契约；C=真实模型/地图/独立人工参考数据就绪；D=四组离线预注册评测；E=无AM输出dry_run与主机链路延迟验证。每阶段完整文件、接口、测试和验收见配套方案。高压/真实控制试验为之后单独决定的工作，本方案不授权启动。
