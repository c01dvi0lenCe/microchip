# 第二章S3至实物控制算法一致性测试方案

日期：2026-10-27；版本：v1；状态：**已完成源码差异审查与反例设计，以下新增反例尚未执行**。不是新的S3批次、算法性能评价或实物验证。

## 1. 目的与测试层级

同一Mask序列不能自动保证同一算法行为。需要固定Mask、帧身份、时间、任务、几何及配置，比较原始G/C0/Q/W/S/K、历史更新、保护输入与事件消费。明确四层：

- L0：帧/Mask/坐标与数值特征。可独立手算，评价共同几何定义。
- L1：原始历史与各gate。允许且记录已知差异，不以强制输出相同为目标。
- L2：到达/状态/保护/ArrivalEvent。区分S3研究到达门与实物五状态接口。
- L3：离线mock事务日志。仅内存/文件日志，不创建SerialTransport、相机、GUI控制或真实输出。

测试fixture可使用标记为synthetic software fixture的可手算几何与Mask；不能将其列为真实液滴数据或正式研究seed。旧S3实现和参数只读，实物PriorFeatures也不在本轮修改。

## 2. 实际源码差异

| 项目 | S3 ObservationPipeline/ArrivalGate | 实物PriorFeatures/StateRecognizer | 一致性含义 |
|---|---|---|---|
| 历史采样 | 所有C0有效、语法可解析的观测进入maxlen=2历史，含低Q/空间/时序冲突 | Q失败提前返回；仅temporal_prior开启且spatial/temporal通过时append | 原始K不等价，恢复后可能有不同拒绝/接受 |
| Q与K耦合 | raw Q/K独立计算，Q开关仅组合目标gate | quality_checks=False还使temporal判断直接通过 | 不能用quality_checks=False直接模拟S3的Q消融 |
| 断档/漏帧 | 任务变化、gap、missing_id重建pipeline历史 | 主要按history_max_gap/显式reset处理；帧号缺口不等同自动清历史 | 需要分别测试特征层与runner证据层 |
| 空间 | 源/目标区域与目标位置分量，raw后再组合开关 | candidates可包含其他电极；位置与空间validity进入状态规则 | 同输入测试必须固定候选集，不能把不同输入当算法效果 |
| 时间/单位 | simulation曝光区间和pitch；内部*_mm为兼容数值别名 | video_relative或host时间及真实H/mm | 必须显式映射测试坐标/时钟，不伪造实物曝光 |
| 到达窗口 | ArrivalGate统一管理Q/W/S/K；五状态内部Arrived先抑制再由目标gate确认 | StateRecognizer自己管理连续证据与状态 | 相同W数值不保证整条识别链同义 |
| 保护 | S3开关不改raw Observation，P_B/P_F分开 | 真实配置与历史筛选及runner保护共同作用 | 保存公共保护输入，不只保存最终动作 |
| 默认阈值 | G为0.85/0.08、pitch容差、2.6 s尝试等 | YAML仍为0.75/0.10、mm容差、8/16 s等占位 | 先做同配置语义测试，再做默认配置差异测试；不反写冻结参数 |

源码来源：dmf/chapter2_sim/v2/observation.py、arrival.py、adapter.py；s3/adapter.py；dmf/experiment/perception.py、evidence.py、policy.py、runner.py；dmf/vision/contracts.py、features.py。既有tests中的gate、causality、evidence、geometry和S3机制测试可复用，但不代表已完成新增跨管线测试。

## 3. 共同输入及配置合同

先冻结每个case的Mask PNG/NPY哈希、source/target/candidates、帧号、stream、run/step/attempt/epoch、phase、时间源/域、曝光/可用/接收时间及参数。

L0/L1采用显式fixture坐标，两个实现得到相同数字几何，不将任何fixture值标成真实mm。S3的simulation时钟仍保留；实物离线包装使用video_relative，跨域关系由case中的抽象时间轴描述，禁止将simulation数值冒写为host实际曝光。C0分别在各自合法域执行，再比较“旧帧/重复/无因果证据”等语义。

同配置层仅在测试对象中创建参数副本，映射单位并断言数值一致；不修改配置文件或类默认值。默认配置层另列差异，不据输出不同宣布bug。真实视频层在缺有效地图/任务/时间时只能做Mask/质心核对，不能强行生成到达性能。

## 4. 可手算K反例

使用测试单位pitch（非实测）、相邻源目标中心(0.5,0.5)/(1.5,0.5)，相邻正常帧间隔0.05 s，v_max=6、位置容差0.18、预测容差0.18，则单间隔位移与预测残差界为6×0.05+0.18=0.48 pitch。这些数值来自S3的state_config映射，用于**计划中的确定性软件测试**。

依次输入p0=(0.5,0.5),t0=0.10；p1=(0.5,0.5),t1=0.15；p2=(1.5,0.5),t2=0.20,confidence=0.1；p3=(0.5,0.5),t3=0.25,confidence=1。

预期源码语义：p2的Q不通过；S3仍写入p2，实物提前返回不写入。p3时S3位移1.0>0.48，预测x=2.5，残差2.0>0.48，K失败；实物仍由p0/p1预测x=0.5，位移/残差均0，K通过。不能在实物p2提前返回时虚构其raw K=False，应记not_computed及原因。该例只证明两种历史策略可能不同，不证明哪种真实液滴效果更好。

上述为手算预期，不是本轮运行结果；后续需在Mask栅格化后核对实际质心，必要时用对称可精确表示的像素形状，不能为满足预期篡改输出。

## 5. 最小反例测试矩阵

所有下列case状态均为PLANNED_NOT_RUN，不新增正式seed。

| ID | 固定输入/操作 | 应检查的不变量或已知差异 | 层级 |
|---|---|---|---|
| C01 | 稳定、无噪声、合法相邻运输 | 原始质心/eta/rho/距离/进展单位一致；六个0.05 s间隔采样跨0.25 s，不把5帧=0.25 s | L0–L2 |
| C02 | 低Q跳变后回到原位置 | 第4节手算差异；raw history、Q提前返回和not_computed完整 | L1 |
| C03 | Q有效但空间越界后返回 | S3保留异常历史，PriorFeatures不append；不得静默“清洗成一致” | L1 |
| C04 | Q/S有效的超速或预测冲突后返回 | 两种K失败后的历史更新不同；比较重建时间与观测来源 | L1 |
| C05 | 逐项切换S/K/Q | S3 raw值和公共保护输入不随目标开关改变；实物quality_checks与K耦合单独标出 | L1–L2 |
| C06 | 完整帧号但时间长断档 | 比较实际gap配置与重建；同配置/默认配置两层分别判读 | L1–L2 |
| C07 | 时间近邻但SDK帧号缺口 | S3历史missing_id重建；实物特征层与证据层分别记录，不能只看最终窗口 | L1–L2 |
| C08 | 重复、倒序帧与倒序时间 | 两条链C0不能推进Arrival证据；全局high-water不随Retry重置 | L0–L2 |
| C09 | 旧epoch、跨stream、跨step帧 | 拒绝或明确重建/停止；旧帧不能确认新任务 | L0–L2 |
| C10 | 只有receive晚于ACK，曝光未知；另设可靠映射负对照 | 前者causality_unknown；不能伪造exposure_order_verified或实际HV | L0–L3 |
| C11 | G满足但质心不在任务目标容差；另设合法中心 | 分开记录G、S_area、S_position和W，不将rho替代eta | L0–L2 |
| C12 | 空Mask、缺失、尺寸错、非二值、多个显著连通域 | invalid/Unknown与Deviation分离；语法失败不拼历史，缺失状态保留 | L0–L2 |
| C13 | 同一到达事件重复消费与过期context | 同步一次消费、任务身份不变，不能重复Update | L2–L3 |
| C14 | Mock pending、ACK失败/超时、通信同seq重发 | 不发并行新电极事务；通信retry与液滴Retry不同；不生成假Applied/HV | L3 |
| C15 | Partial/Moving但无进展，源准备失败和attempt超时 | 公共保护预算有界；终止与计划分母完整，Unknown不沿用为当前已确认状态 | L2–L3 |
| C16 | 同目标Retry和Recovery两种context变化 | 软件窗口重建与独立物理/人工驻留分段分开；不跨Recovery拼参考 | L2–L3 |
| C17 | 像素ROI偏移/缩放及另一图像域 | 全图/ROI特征等价仅在显式变换后；旧照片H/模板输入应被标绑定不足 | L0 |
| C18 | 高置信持续伪Mask与正常可见Mask负对照 | 记录算法可能无法区分的失效边界，不强制F拒绝；预测不读取GT | L1–L2 |

## 6. 必须分别持久化的日志

每帧一行：case/layer/implementation/config/source_sha、frame/stream/context、各时间与quality、Mask哈希、坐标域/单位、历史before/after、append/reset/reason。

gate独立列：G_target、G_release、C0/reason、raw_Q、raw_S_area、raw_S_position、raw_K、各gate是否computed、enabled开关、effective gate、W_count/duration/gap/span/rebuild/confirmed。无法计算用null+reason，不把null等同False。

公共保护另存：Observation.valid/error/spatial_ok/temporal_ok/target_position_ok、progress及其单位、last_reliable_time、attempt_start、no_progress/no_observation状态、预算余额、P_B/P_F收到的state、最终action及reason。ArrivalEvent另存事件ID、上下文、证据起止与是否消费；mock事务另存request/pending/ACK结果，HV恒为空。

分层输出建议为input_manifest.json、raw_features.csv、gate_trace.csv、protection_inputs.csv、arrival_events.csv、mock_transactions.csv、differences.csv。输入不含评分真值；若需要人工参考，仅测试后离线评分器读取。

## 7. 判定与实施计划

1. 冻结源码/输入/测试profile与本方案版本；确认安全隔离：所有相机/串口工厂被拒绝，任何硬件实例化立即失败。
2. 先运行C01几何和C0共同不变量，再运行C02–C07已知差异，最后做L2/L3；不运行World、SyntheticCamera或新seed，只读固定Mask。
3. 每个case分类为shared_invariant_pass、documented_semantic_difference、unexpected_difference、blocked_input，而不是把“差异存在”一概计为失败。
4. 不变量偏差才要求独立诊断；已知策略差异先报告科研含义，不自动修改冻结S3。真实研究版本若改变历史规则，另建新profile及回归后批准。
5. 进入真实视频事件验证前，必须完成相应视频绑定、任务、时间质量和双评审参考；没有这些输入的case标blocked_input，不能补造性能。

本轮仅完成方案与空日志模板，不声称18个case已通过。后续实施应新增独立tests/test_chapter2_sim_real_consistency.py及只读测试包装入口，复用现有契约，不复制重写算法。是否修改实物历史策略须在差异报告审查后另行决定。
