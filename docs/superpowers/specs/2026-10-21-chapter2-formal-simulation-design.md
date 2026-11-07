# 第二章正式算法适配、离线基线与配对仿真设计

日期：2026-10-21。状态：用户已确认方案，进入实现；实际进度以执行记录为准。
不commit/push，不覆盖既有tracked/untracked成果或历史结果。

## 1. 目标与方案选择

目标是在同一可追溯输入上检验B1–B4的到达事件识别与闭环控制，不把旧C直接改名为正式算法。
前置语义与已复现反例见[语义审查](../../chapter2-simulation-semantic-audit-2026-10-21.md)。

采用方案A：新增显式适配、版本化方法、独立benchmark与实验入口，保留旧runner/control/配置/CLI行为。
方案B（直接替换旧C）会改变历史方法语义与复现，拒绝。
方案C（再复制一套近似规则）代码少耦合却继续产生两套算法漂移，拒绝。

## 2. 模块与边界

| 新增/有限修改位置 | 职责 |
| --- | --- |
| `dmf/chapter2_sim/formal_adapter.py` | simulation FrameTiming/StepContext、显式单位映射、正式观测/状态/事件/控制适配 |
| `dmf/chapter2_sim/formal_runner.py` | 复用原World/Camera/Map，模拟命令请求→APPLIED分离、动作反作用与独立truth记录 |
| `dmf/chapter2_sim/formal_batch.py` | 方法版本/消融/敏感性、配对seed、统计与manifest，不改旧batch.METHODS |
| `dmf/experiment/benchmark.py` | 无GT预测入口，S1–S4及消融，共同缓存/固定任务段 |
| `dmf/experiment/mask_cache.py` | 只读统一掩膜输入与hash/时钟/任务资源校验，不含参考GT |
| `dmf/vision/event_evaluation.py` | 保留严格human入口；如需共用计数核心，另加显式simulation参考入口，不能弱化human审核要求 |
| `dmf/experiment/evidence.py`等共享算法 | 仅为显式simulation域/必要单位接口作兼容扩展；offline/dry_run/experiment路径必须保持回归 |
| `scripts/evaluate_chapter2_baselines.py` | build-cache/run/evaluate/materials-check离线入口，不创建串口或控制世界 |
| `run_chapter2_formal_simulation.py` | 新版本闭环/固定输入/消融/扫描入口，旧CLI继续可复现 |
| `configs/chapter2_formal_simulation.yaml` | 冻结参数、单位、场景、种子、方法版本、真值、输出位置 |
| 新测试与文档/绘图模块 | 先RED→GREEN、一致性、数据隔离、统计分母、图源数据与材料缺失报告 |

所有新增结果使用新输出目录，已有目录拒绝覆盖。GUI、MVS/U-Net硬件适配器、串口协议、AM/STM32、第三章不修改。

## 3. 单位与时钟契约

- 仿真长度单位是pitch，时间域是simulation。FrameTiming保留模拟曝光/可用时刻，但真实host/UTC/device字段为空。
- StepContext的真实APPLIED接收字段为空；模拟应用时刻单独声明为simulation_applied。ArrivalEvent的真实主机确认戳为空，事件表另存模拟decision_time_s。
- 不将pitch=1伪称1mm。适配器输出只能用progress_pitch、lateral_pitch、velocity_pitch_s等列；内部旧数值接口的长度单位须被包装器/配置显式标明。
- 正式算法参数的同名legacy mm字段如参与归一化适配，必须记录其仅为内部兼容别名及数值单位映射，不能导出成物理标定参数；若无法保证该契约，应增加最小通用长度单位接口而不是猜真实pitch。
- 共享FrameCausalityGuard对simulation必须有独立分支：上下文/时钟/捕获ID一致，曝光起始不早于当前模拟APPLIED；不通过伪造host_monotonic绕过检查。

## 4. 正式适配与一致性

优先直接调用RegionOverlap、TransportProjection、EvidenceWindow、ProgressMonitor、StateRecognizer、EventController及ArrivalEventLedger。
观测有效性/空间/时序预测需复用正式PriorFeatures行为；不能在adapter重写一套近似置信度、连通区域或预测规则。
纯几何和单位包装可新增，但不改变正式实物模式默认单位和控制语义。

命令发出后等待模拟APPLIED到达才调用accept、切换epoch/attempt并清证据。失败不推进，重复应用不重复接受。
三组共用初始源设置/确认程序；运输阶段A按固定时间、B按简单单帧eta、C按完整正式状态/事件策略。
source/Recovery确认都采用正式连续窗，统计中将准备时间与运输时间分开。

方法标识至少含：`A_fixed_v1`、`B_single_eta_v1`、`C_formal_b1b4_v1`，同时保存base_method和代码/config hash。
旧`C`只标`C_legacy`用于历史复现/语义对照，不并入新C结果。

一致性验收：相同掩膜/地图/参数/context输入，适配器与正式算法的观测质量、五状态、窗口首尾、动作和计数逐帧一致。
专测重复/逆序、长gap、无效帧、SDK身份变化、Partial停滞、孤立异常、目标polygon门、旧epoch、ACK失败、ArrivalEvent一次消费。

## 5. S1–S4共同缓存与GT隔离

共同缓存保存mask路径/hash、检测元数据、捕获号、曝光/可用时间、时钟域、地图hash、冻结参数及外部任务时间段。
不存隐藏位置、真实速度、真到达时间或人工参考。预测模块不得接受GT对象/参考路径。
评价阶段单独读取reference manifest，测试更换GT不改变预测文件/hash；四组输入manifest/hash完全一致。

| 组别 | 使用信息 | 事件输出 |
| --- | --- | --- |
| S1 | 当前mask质心、任务目标中心与冻结单帧位置门 | 首次合格到达事件；不伪造五状态 |
| S2 | 当前eta_target及eta_source释放门 | 同上 |
| S3 | S2+任务候选区域/目标polygon位置门 | 同上，无连续证据 |
| S4 | S3+正式有效性、因果context、连续窗、已接受历史 | 完整识别器状态及一次性确认事件 |

所有组至少要求输入可计算（非空可解析mask），缺失不猜位置、不沿用上帧填补成功。单帧组不强行补Moving/Partial等标签。
离线主比较采用teacher-forced固定任务时间段，不让各组预测改变输入分段。
simulation共同缓存由预先固定的外部控制程序生成，所有组读取同一缓存；世界truth只写评价侧独立文件。

真实视频输入另需模型/预处理或共同分割缓存、人工给定任务段、已审核参考与划分。缺材料输出missing_materials，不报告真实准确率。

## 6. 消融定义

以S4/C_formal为完整方法，增加三个预先定义版本：

1. no_spatial：禁用任务区域/目标polygon先验，其余因果、可计算性、连续窗与保护不变。
2. no_temporal：禁用连续证据及历史运动预测，使用同空间/质量下的当前帧事件，事件仍不可重复消费。
3. no_validity：去掉非必要置信度/显著连通区域/运动冲突筛查，保留输入可解析性、任务身份和控制安全屏障；缺mask仍Unknown，不能伪造观测。

逐项开关、参数与实际输入扰动必须记录。不得为了得到预期提升而临时添加异常、挑选场景或改变truth。
若现有圆形mask场景无法识别某项有效性收益，允许平坦/无差异结果并写入局限；一致性单元测试另外覆盖异常mask。

## 7. 环境、独立参考与公平性

复用原DropletWorld、SyntheticCamera和420地图及非规则外围；保留按tick/frame索引的外部随机流。
动作经模拟APPLIED与响应延迟后真正改变世界目标；Retry/Recovery作用于世界，不是只改标签。
真到达继续由世界位置盆地、真实速度及独立驻留定义，参数不随方法、阈值扫描或算法判定变化。
重复访问同一电极时按当前step/有效时间段重建参考，不复用该电极在整条路径上的第一次到达时间。

主场景固定为normal、delayed、partial_stall、jitter、dropout、deviation、failure。
同scene/seed使用相同环境参数；允许控制差异导致轨迹分叉，不要求位置逐tick相同。

## 8. 分阶段运行与计划规模（尚未执行）

- 冒烟：每场景3个seed（260600–260602），三组+三个闭环消融共126 trials；21份固定输入缓存对应147次离线方法运行。
- 正式：每场景20个独立配对seed（261000–261019），三组420 trials，三个闭环消融420 trials；140份固定输入缓存对应980次离线方法运行。
- 敏感性：jitter场景、20个相同正式seed，eta_arr=[.75,.85,.95] × duration=[.25,.4,.6]，只跑C_formal共180 trials，truth不变。
- 计划正式闭环总数1020；冒烟与正式分开存放，不合并充大n。上述是计划数，不是已完成结果。

门槛：先一致性/分母/GT隔离测试，再完成冒烟检查；源确认失败、丢帧、永久失败必须有明确终态且记录。
固定参数及manifest后才运行正式seed；若修复实现缺陷或改参数，升方法/配置版本并保留旧批次，不挑结果。

## 9. 指标与置信区间

独立单位为scene内配对seed；帧和路径步是seed内相关观测。

- 提前更新：确定早于参考的确认事件，报告/全部计划步及/已发确认事件两种分母。
- 到达召回：正确确认的独立参考到达事件/全部可判定参考到达事件；同时列计划步、未到达、未尝试、漏事件、Unknown与删失，不能用缩小支持数掩盖失败。
- 延迟：仅有真实参考且成功确认时给延迟；早确认、漏确认和右删失另列，不用0替代。人工区间输出延迟区间，不强制压成单时刻。
- 路径成功率：全部计划步真实到达且无提前/错误更新的trial/全部试验；离线结果称路线识别完成率，不称物理控制成功率。
- 时间：全部trial的execution_time与成功条件下completion_time分开；失败完成时间缺失，不能把保护停止解释为更快完成。
- 计数：运输超时Retry、Recovery后重发、Recovery、通信重试分别列出；simulation没有真实通信重试就留0并标模拟。

路径率用trial级Wilson95%区间；提前率/召回/连续量采用scene内seed整簇bootstrap（2000次），配对差按同seed重新采样。
缺失配对和条件样本数显式输出。不默认开展显著性检验，不以CI重叠与否代替方法比较结论。

## 10. 原始输出、图与验收

保存逐tick世界truth、逐帧输入/特征/质量/动作、逐事件、逐trial、汇总与配对差CSV；
manifest记录seed、参数、单位/时钟、truth定义、方法版本、HEAD及dirty源码hash、依赖版本、输入/输出hash。
真实人工参考与simulation物理参考入口分开，原严格human接口不能接受simulation标签冒充人工。

图使用现有Python绘图技术路线，全部标题/图注标SIMULATION，保留原始源数据：
1. 单个预先指定scene/seed的轨迹与状态/动作，解释因果过程，不选择最有利例子；
2. A/B/C路径率和提前率及配对差/CI；
3. S1–S4事件识别与空间/时序/有效性消融，显示分母/漏事件；
4. 固定truth的阈值敏感性；失败时间和删失不画成成功完成时间。
导出PNG/PDF及图源数据，按科研绘图规范核对对齐、文字和碰撞；没有渲染/检查不能称图已验收。

最终执行新增局部、B1–B4、旧仿真33项、完整unittest、compileall、七条独立控制链及保护文件差异检查。
材料缺失、失败运行、统计不确定性、圆形掩膜/二维代理/时间量化及未验证物理行为必须保留在最终报告。

## 11. 当前完成状态

用户已确认并完成实施：版本化C_formal适配器、同Mask缓存S1–S4与三项消融、冒烟126次闭环/147次离线、正式840次闭环/980次离线与180次敏感性试验；140份正式共同缓存均已落盘。
16张simulation图已导出SVG/PDF/600dpi PNG，最终文字/碰撞审计通过；全量546项测试中545通过、1跳过，七条独立控制链通过。
74份既有源码中仅3份经设计允许的共享接口变化，旧仿真、GUI、协议与第三章不变。未commit/push、未执行高压或实物实验。
人工参考、真实U-Net权重/精度、独立验证地图与物理因果时序仍未完成；失败结果及条件样本支持保留。实际数值、局限、运行命令与最终打包状态见`docs/chapter2-formal-simulation-implementation-2026-10-21.md`。
