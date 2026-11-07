# 第二章S3仿真最终封存与论文证据索引

日期：2026-10-27；版本：v1；工作性质：既有材料只读归档核查，不重跑实验。

## 1. 封存范围与证据等级

S1、S2正式成果保持冻结。S3现有120条开发记录与800条正式记录分别保留，不合池。正式批次为chapter2_s3_confirmatory_v1：七场景、四主方法、每场景20个配对seed；560主trial、80桥接、160受控运输诊断，共2400个计划步，正式seed265000–265019不新增、不替换。

本轮证据分为三层：①实际文件哈希、索引链和数据清单复核；②已封存G5独立评分与统计审计；③模型范围内的科学解释。本轮不重复运行G5评分器或统计bootstrap，文件一致性不冒充第二次独立性能复现。实物接口仍为PARTIAL，不据此否决已经完成的算法级仿真，也不据仿真完成免除实物验证。

## 2. G3→G4→G5追溯链

以下路径相对章目录`D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果`。

| 层级 | 冻结材料 | 核查内容 | 用途 |
|---|---|---|---|
| G0–G2开发 | 2026-10-26_S3_G0-G2开发验收_v1 | 120条开发身份、三类不合池、机制测试和开发seed | 说明实现与机制验证，不是正式性能n |
| G3定义 | 2026-10-26_S3_G3协议冻结_v1/S3_正式冻结协议.json | 方法、阈值、77份核心源码摘要、800身份计划、随机源与统计规则 | 最终方法/参数来源 |
| G3准入 | 同目录/S3_G4准入凭证.json、QA/g3_audit.json及五份MD协议 | contract/audit/document/source哈希链 | 解释B_single勘误与公平性 |
| G4运行 | 2026-10-26_S3正式仿真_v1/config_manifest.json、planned_trials.json、completion_manifest.json | 800计划=800完成，三类560/80/160，2400步，替换0 | 运行规模与完整分母 |
| G4原始材料 | 同目录/trials/* | 源快照、实际外生数组、Mask、逐帧/事件/内部真值/独立参考及trial_manifest | 逐trial复现，不从图反推数据 |
| G4聚合 | formal_trials.csv、formal_steps.csv、request_applied_evaluation.csv | trial/step/event分母和Request/Applied分开 | 正文及全表源数据 |
| G5统计 | formal_summary.csv、paired_contrasts.csv；正式验收目录/tables | 全场景统计、配对区间、阶段与桥接 | 报告效应、失败与代价 |
| G5独立审计 | 2026-10-26_S3正式验收与论文图_v1/QA/independent_final_audit.json | 历史独立审计800trial、2400步、1778事件、99291张Mask及800份外生数组通过 | 既有独立评分复算证据，不是实物验证 |
| 冻结输入索引 | 同目录/QA/formal_frozen_input_index.json | 聚合输入及800个trial_manifest，再追溯各payload哈希 | 只读完整性校验入口 |
| 论文图索引 | 同目录/figures/figure_sources.json | CSV、表格、示例trial、绘图脚本和逐trial来源摘要 | 连接论文图与正式数据 |
| 交付索引 | 同目录/交付manifest.json | G3协议、原始CSV和验收PDF摘要 | 检查报告与源材料一致性 |

## 3. 算法定义及不可混淆项

四主组为A_fixed/P_B、B_single/P_B、BTQ/P_B、F_arrival/P_F（代码名F_full）。A为模拟Applied后1.2 s定时推进，无视觉ArrivalEvent；B_single为G+C0单帧，目标Q/W/S/K全关闭。BTQ启用G+C0+Q+W；F_arrival再增加S/K。P0源准备相同，目标开关不改变公共原始历史和保护输入。

公共raw Q保护不等于B_single到达门暗中启用Q：原EventController中Arrived分支先于后续质量/进展超时。B→BTQ是Q与W联合差异，不能只归因于W。桥接固定保护比较到达门，固定到达门比较P_B/P_F；完整策略差异不能全部归因于S/K。

模拟request、模拟Applied、真实request、真实ACK及实际高压输出不同。正式S3使用420电极示例模板、pitch单位、二维点运动与SyntheticCamera简化Mask，不是FBC6-3真实Gerber动力学、CFD、真实U-Net或实物实验。

## 4. 已完成科学问题、论文可用结论与负面证据

| 科学问题 | 可用证据与结论 | 保留的限制/负面结果 | 章节位置 |
|---|---|---|---|
| 到达反馈能否改变实际运输结果 | 闭环动作确实改变World后续轨迹；在既定delayed/partial_stall条件下，BTQ/F严格支持路径均20/20，A/B均0/20 | 特定模型和冻结参数，不是普遍最优性；Retry解锁故障是World假设 | 2.4.3、2.5.4 |
| 单帧门能否把流程完成误当运输完成 | normal中B_single流程完成20/20而严格支持路径0/20 | 不能外推真实提前更新率；仍需独立真实视频参考 | 2.5.3与2.5.4衔接 |
| 源准备与运输失败是否可区分 | 各阶段和未尝试步已有独立账本 | jitter四组源准备0/20；不能以0错误请求宣称安全完成；诊断不合池 | 2.5.4 |
| 观测缺失是否构成边界 | dropout严格支持路径A为14/20，BTQ/F各12/20；保留失败及保护停止 | 完整方法不必最好；苛刻窗口可能增加等待或漏确认 | 2.5.4 |
| 五状态保护是否有独立代价 | deviation中BTQ/F均20/20；F使用不同恢复流程 | F全计划平均时间约11.792 s，BTQ约10.891 s，代价必须报告；不是S/K独立优势 | 2.5.4 |
| 持续故障时是否避免虚假成功 | failure四组严格路径均0/20；反馈组保护停止 | A流程走完不等于运输成功；停止本身也不是完成 | 2.5.4 |
| S/K是否已有独立闭环增益 | 同保护正式桥接80/80控制事件与时间一致；旧21共同缓存BTQ/F确认一致 | 未建立独立闭环增益；不能把机制gate可触发写成统计优势 | 2.4.2、2.5.3–2.5.4 |

上述比例均为每条件20个配对seed，不是20次实物实验。正式比例区间、配对效应及完整七场景表继续引用原CSV；不将开发seed、诊断或不同版本合池，不以选择性摘要替代全表。

### 可用于论文的阶段性表述

本文在简化二维运动与合成视觉环境中完成了事件驱动单液滴运输策略的比较。通过共同源准备、外生随机条件、有限动作预算及独立运动参考，区分了流程完成与参考支持路径完成。在所设延迟和部分停滞条件下，等稳定窗口反馈策略能够避免部分无支持推进；抖动、丢帧与持续故障仍构成明显失效边界。完整五状态保护在偏离工况改变恢复过程并产生执行时间代价，同保护桥接未显示S/K到达门的额外闭环收益。结果反映所设算法模型及参数的适用范围，实际液滴识别精度与实物控制有效性仍需独立验证。

## 5. 论文图、表与原始来源

| 图/表 | 冻结文件（正式验收目录内） | 数据与图意 | 使用边界 |
|---|---|---|---|
| S3-A | figures/S3-A_formal_process.svg/.pdf/.png | 预声明deviation、seed265000，四主策略各1trial的运动/状态/控制 | 每策略n=1机制示例，不代表平均性能，不拼接不同seed |
| S3-A正常补充 | figures/S3-A_supplement_normal.* | normal、seed265000四主策略 | 补充正常流程，不替换负面例 |
| S3-B | figures/S3-B_formal_performance.* | 七主场景与预声明桥接，20配对seed | 保留jitter/dropout和所有失败 |
| 完整阶段分母 | tables/complete_stage_denominators.csv | source、transport、strict path、未尝试与终止 | transport_complete不是路径成功 |
| 事件时序 | tables/request_vs_applied.csv、原始request_applied_evaluation.csv | 请求和模拟Applied各自的参考支持 | 后到达不追认早请求安全 |
| 代价与延迟 | tables/time_and_action_intervals.csv、conditional_confirmation_latency.csv | 条件成功时间、全计划代价、重试恢复与延迟 | 无成功时NA，不填0；24 s惩罚不是RMST |
| 桥接 | tables/bridge_control_identity.csv、bridge_paired_contrasts.csv | 固定保护/到达门的归因 | 不把策略包差异直接归于S/K |

图稿不重新生成。本轮给出新图稿文件摘要索引，但已有图稿来源哈希由figure_sources建立；新生成的输出哈希本身不是历史图稿未变的独立证明。原始trial图像与CSV另由冻结manifest保护。

既有图稿审查记录指出S3-A原宽约243.8 mm、S3-B约182.9 mm，部分注释最低5 pt。正文应按合适整页/横向幅面使用，不能未经版式检查直接缩成窄栏并声称仍清晰；本轮不改定稿图。

历史兼容字段`formal_seed_runs=0`曾继承在legacy视图中，不作为正式批次数量依据。正式身份以chapter2_s3_confirmatory_v1、purpose、预声明计划、completion_manifest和实际seed为准；已有勘误保持原样，不追改旧数据。

## 6. 封存核查的交付与边界

本轮新目录为章目录`审查材料/2026-10-27_真实视觉离线验证准备与S3封存_v1`。其中`sources/S3_G3-G5索引链核查.csv`记录每条引用链及期望/实际哈希，`S3已有图稿导出摘要.csv`登记图稿；`QA/本轮只读核查.json`保存核查结果与本轮源文件快照。

既有保护索引、实际源码和原始视频/Mask均只读核验；核查失败时先停止相关结论引用并说明差异，不回填或修补旧文件。未执行新seed、训练、正式算法评价或高压；未Commit/Push。算法级正式仿真不继续扩张，重心转向真实视觉材料与独立参考准备。
