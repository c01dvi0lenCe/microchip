# 第二章仿真v2阶段验收：科学含义与图稿（2026-10-24）

## 结论：软件计数可验收，暂不整体进入E4–E7正式扫描

本次独立读取development_smoke_r2的原始CSV，不调用原评价函数，重新计算位置/真实速度/驻留参考、事件支持和阶段计数。108条记录、324个计划步骤均保留，原参考区间及核心评价字段未发现数值不一致；14520份trial文件哈希通过。没有新增研究trial，没有修改模型、控制器或冻结结果。

研究证据仍不足：21份共同Mask缓存中BTQ/F的事件和确认时间全部一致；deviation中控制动作不同，但包含五状态保护路径差异，不能单独归因于S/K到达门。下一步应先固定比较含义，不是直接扩大运行次数。

## 1. 评价定义与完整分母

- planned trials：每个场景/方法3条开发seed（262000–262002），端到端共84条；另24条阶段诊断不混池。
- source_prepared：实际视觉源确认。transport_only只记录controlled_initial，不能算视觉源确认。
- transport_complete：控制器发出最终Complete，**不等于路径成功**。
- path_complete：全部3步有独立参考支持、确认不提前/不确定，无错误目标及重复事件，且运输执行完成。
- reference arrivals与supported confirmations分别报告。无参考支持和确定早于区间下界的premature分别列出；不把尚未发生的反事实到达时间补造出来。
- missed confirmation：已有独立参考到达，但缺少有效支持确认。没有独立到达时recall为NA，不是100%；计划失败/未尝试步骤仍保留。
- Retry分为运输重施与Recovery确认后的重发。表中的R表示运输Retry；RR表示恢复后重发，不与R合并。二者均不是串口通信重试。
- Unknown是预测输出而非失败真值。BT/BTQ非到达时按设计输出Unknown，不能用它们的Unknown多来证明感知比F差。

28个场景/方法组合的逐项计数见随附`v2_scene_method_counts.csv`；逐seed见`v2_independent_trials.csv`。本报告附表同样列全28组，不删除失败或零事件。

### 主结果（下列公共计数对四方法分别成立）

| 场景 | 每方法计划/源确认 | 执行完成/正确路径 | 参考到达/支持确认 | 无支持/提前/漏确认 | 每方法未尝试步骤 |
| --- | --- | --- | --- | --- | --- |
| normal | 3/3 | 3/3 | 9/9 | 0/0/0 | 0 |
| delayed | 3/3 | 3/3 | 9/9 | 0/0/0 | 0 |
| partial_stall | 3/3 | 3/3 | 9/9 | 0/0/0 | 0 |
| jitter | 3/0 | 0/0 | 0/0；recall=NA | 0/0/0 | 9 |
| dropout | 3/3 | 3/3 | 9/9 | 0/0/0 | 0 |
| deviation | 3/3 | 3/3 | 9/9 | 0/0/0 | 0 |
| failure | 3/3 | 0/0 | 0/0；recall=NA | 0/0/0 | 6 |

这里“3/3”在执行完成/正确路径列表示两个计数各为3，不是把前者除以后者。每个方法端到端正确路径15/21；这只是3个开发seed的描述，不报告优越性检验或总体性能结论。

保护行为：partial_stall各方法R=9；dropout各R=1。deviation中C_v1_compat/F为R=0、Recovery=9、RR=9；BT/BTQ为R=9、Recovery=0、RR=0。failure中四方法均R=12、Recovery=3、RR=3。normal/delayed无重试恢复。

停止原因：端到端jitter每方法3次source confirmation timeout；failure每方法3次local recovery limit reached。failure每方法仅3个首步被尝试，另6步未尝试，不可把这些零到达样本从路径分母剔除。

### 源准备与运输诊断

- source_only：normal的BTQ/F各3/3视觉源确认，jitter各0/3。
- transport_only：normal的BTQ/F各3/3正确路径；jitter各0/3正确路径，但各有3个独立参考到达、0个支持确认、3个漏确认，另6个计划步骤未尝试，均以local recovery timeout停止。
- 所以jitter既有P0源准备瓶颈，也有运输确认/恢复瓶颈，不能只说“没启动，所以目标算法没有问题”。

## 2. 为何v2多组3/3，而历史A/B低

主要原因是**方法不是同一组**，其次是指标语义及seed条件不同；不是环境被偷偷调容易。

| 场景 | v1 A正确路径/20 | v1 B正确路径/20 | v1 C正确路径/20 |
| --- | --- | --- | --- |
| normal | 20 | 0 | 20 |
| delayed | 0 | 0 | 20 |
| partial_stall | 0 | 0 | 20 |
| jitter | 1 | 0 | 0 |
| dropout | 15 | 0 | 14 |
| deviation | 0 | 0 | 20 |
| failure | 0 | 0 | 0 |

1. 历史A是运输阶段固定1.2s推进（仍有共同视觉源准备/保护），并非整条系统完全无视觉。历史B是单帧eta_target≥0.85及源释放判据，不等待相同稳定窗口。
2. 当前四方法为C_v1_compat、BT、BTQ、F，**没有历史A/B**。BT/BTQ已加入至少5帧/0.25s、最大间隔及质心/覆盖跨度限制，因此不能把它们当作旧单帧B的“同方法复测”。
3. v1 B在normal、delayed、partial_stall、deviation各20/20执行到末尾，但每场景60次无支持提前更新，路径均0/20。v1 A在delayed、partial_stall、deviation、failure也均20/20执行到末尾而路径0/20。若只看transport_complete，会把这些失败误说为100%成功。
4. v1的A在normal本来就20/20正确路径，并非所有场景都差。旧C和新C_v1_compat/F在大部分场景同样成功；不应将已有C的能力冒称v2新贡献。
5. 两批环境配置快照逐字段完全相同；World/Camera保持同一模型。v1使用261000–261019，当前使用262000–262002。dropout旧C为14/20，当前3/3是不同seed的小样本，不能解释为算法提升。既有E0仅证明所核历史条件兼容，不证明不同seed结果相同。
6. v2参考显式要求同epoch/目标的连续transport tick，不跨Recovery/断档拼接；v1参考是世界位置/速度/驻留的在线记录。两者半径/速度/驻留阈值相同，但参考作用时间段并非完全同一实现。本批legacy无支持数与独立重算数一致，未发现它解释当前成功差别；以后参考敏感性只用独立重评分，不能混用legacy字段。

## 3. BTQ/F冻结契约与可归因性

共享到达门通过审查：eta_target≥0.85、eta_source≤0.08，N≥5、T≥0.25s、max_gap=0.18s、质心跨度≤0.11pitch、覆盖跨度≤0.15；Q置信度/面积/连通域相同，C0常开。BTQ是“等稳定窗口覆盖率强基线”。rho_target仅记录，没有新增强制电极覆盖门。

S为源/目标多边形允许区和目标多边形外扩0.18pitch的位置门，不是“距目标中心≤0.18pitch”。corridor_width没有进入当前正式适配，不能声称其走廊贡献已验证。K取所有C0可解析帧的共同历史，任务切换/丢号/断档重建；判据是位移及常速度预测残差上界（6pitch/s与0.18pitch容差）。方向速度已记录，但未另设“必须正向运动”的门，不能扩大称为完整动力学预测。

| 输入条件 | 实际支持及科学含义 |
| --- | --- |
| normal/delayed/dropout | 共享缓存BTQ/F事件及时间相同；未见S/K额外到达收益 |
| partial_stall/deviation/failure共享缓存 | 两者均无到达事件，覆盖门已拒绝；不能据此证明S改善到达判定 |
| jitter共享缓存 | 有53个覆盖/Q/S通过但K拒绝的候选帧，然而共同W已让两者均零事件；gate激活不等于事件性能改善 |
| 全部21共同缓存 | BTQ/F到达事件和时间21/21完全一致；S单独否决覆盖候选=0，Q拒绝可解析Mask=0 |
| 定向机制夹具 | spatial_tail可区分S，motion_jump可区分K，质量夹具可触发Q；它们只证明软件机制可触发，不代表随机统计优势 |

重要归因限制：F运输中运行五状态识别器，Deviation能触发Recovery；BT/BTQ非到达时输出Unknown，不产生同样的Deviation状态。虽然EventController与预算相同，实际保护触发信息不同。故deviation中的Recovery/Retry差别目前只能称**完整管线的安全响应差异**，不能仅归因于到达门S或K。若E6要研究纯到达判据增量，需要先冻结共同保护状态通道/桥接对照；若保留现状，就必须明确比较的是整个策略而不是单模块。当前不改算法以免追改冻结实验。

## 4. 同一trial图稿验收

已从最终visualization_r2字节一致提取三张图（SVG/PDF/600dpi PNG）、六张关键帧PNG、H.264 MP4、frame_index、事件CSV、配置/地图/trial manifest与该trial实际模拟Mask。所有来源绑定normal:262000:F:end_to_end:full，未拼接其他seed，未重新运行模型画图。

该trial有83条帧记录：Unknown53、Moving19、Partial8、Arrived3；**没有Stationary/Deviation预测，没有Retry/Recovery事件**。Hold、Start、2次Update、最终Complete实际存在。架构图中的Retry/Recovery是功能示意，不是该trial已经发生；不能为了列齐五状态/四动作而补画。

| 面板/事件 | simulation时间 | 核对解释 |
| --- | --- | --- |
| 源区确认/Start | 0.50s | 源确认事件，不等于预测Stationary；当帧算法输出Moving |
| 观测运动 | 0.81s | 内部点位置与实际模拟Mask不同色，均来自同trial |
| Partial | 1.06s | 预测Partial，不是独立五状态GT |
| 独立参考到达 | [1.45,1.46]s | 位置/真实速度/驻留；此刻算法为Unknown/Hold |
| Arrived/Update请求 | 1.92s | 连续证据确认后请求下一目标，不是即时液滴移动 |
| 下一步模拟Applied | 1.96s | 软件应用日志；该tick world.active仍191，下tick才更新，不能等同真实硬件ACK |

完整三步参考区间为[1.45,1.46]、[2.88,2.89]、[3.97,3.98]s；确认时刻为1.92、3.01、4.11s。动画412帧、1280×720、25fps，4倍慢放；原simulation时长4.11s。

图稿修正文案（不改原图）：V2-Process-2/3均应加“预测状态而非五状态真值；本trial未出现Stationary、Deviation、Retry、Recovery”。三图能解释正常运输与证据时序，不能单凭本图证明异常恢复有效。长度为pitch，420示例模板，二维点＋圆Mask，不是FBC6-3实尺寸、COMSOL/CFD、真实U-Net或实物实验。

## 5. 下一阶段闸门

- E0–E3软件与计数：通过本轮独立复算，没有发现需要改写原评价器的数值错误。已用规范字段与独立表修正解释，保留所有失败/Unknown/未尝试。
- E4目标参数、E5参考敏感性：可继续准备冻结协议，但本轮不运行。先写清参考支持/未到达/删失和共同W的可行性，不以所有失败或全部相同作为优势。
- E6闭环：暂缓正式扫描，先决定“完整策略对比”还是“共同保护下的到达门对比”，避免把五状态保护差异错归S/K。需要新桥接时另立版本，不覆写当前结果。
- E7真实几何迁移：仍未实施，当前模板不能替代Gerber配准/物理验证。
- 正式结论门：需要预设有辨别力且物理/观测合理的条件与负对照，再锁定确认seed及主要终点。不能看F是否领先来选择场景；不以机制夹具当随机或实物性能证据。

新增的只是独立审查脚本、手算回归、报告和原图提取。生产AM/五状态/U-Net/第三章、v1/v2原始算法及冻结结果均不修改，不commit/push。
