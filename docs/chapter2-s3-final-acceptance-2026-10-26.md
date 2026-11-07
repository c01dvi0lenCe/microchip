# 第二章S3正式仿真与最终验收

2026-10-26 | SIMULATION | chapter2_s3_confirmatory_v1 | G3冻结、G4固定批次、G5独立审计。

## 1. 完成范围与停止条件

已完成800个预声明正式trial：560主组、80桥接补充、160受控运输诊断，共2400计划运输步；seed265000-265019全部按顺序使用，无替换、无调参、无新增场景。独立审计800记录、1778推进完成事件、99,291张实际模拟Mask及全部800份外生数组通过，科研评分差异为0。

S1与S2原成果保留。当前S1/S2/S3可构成机制、同输入到达比较、反作用闭环策略比较及失效边界证据链；停止扩大算法级正式批次。S4只给必要缺口与最小可选方案，不自动执行。后续优先真实分割、真实配准、真实视频到达与实物闭环验证。

51,733个受保护旧文件内容不变；局部72项通过，全量852项通过（1项可选FFmpeg跳过），编译和7类独立软件控制链通过。无Commit/Push；未改旧World、相机模型、生产控制、AM、STM32、U-Net或第三章。

## 2. G3定义勘误及研究边界

B_single实际为G+C0，运输到达Q/W/S/K全部关闭，原G0-G2报告“G+Q”是文字错误。27条开发记录的目标门trace以及封存源码一致，无算法协议偏差，无需重跑开发批次。公共保护仍独立使用raw Q，但它不是B的隐含到达硬门；Arrived分支优先于非到达质量/进展保护。G3五份协议及封存JSON附后。

主组为A_fixed/P_B、B_single/P_B、BTQ/P_B及F_arrival/P_F（代码名F_full）。桥接固定到达门或固定保护分支进行归因。旧21共同缓存BTQ/F到达一致、开发12桥接配对控制一致的事实保留。正式结果不与旧版本或开发seed合池。

模型使用420电极示例模板和pitch单位，不是实际Gerber毫米动力学。SyntheticCamera生成圆形合成Mask；内部真值只用于独立评分。此处不是CFD、真实U-Net精度、真实五状态混淆矩阵或实物运输成功率。

## 3. 主组完成、安全与源阶段分母

每行20 planned trials、60 planned steps。S/W/P为源准备/运输流程完成/独立参考支持路径完成；U为至少一次无支持推进请求的trial数。P与U区间为Wilson95%逐点区间，不是实物试验置信区间，也不构成多重显著性检验。

| 条件 | 方法 | S/W/P | P比例[95%] | U/20 | U比例[95%] |
| --- | --- | --- | --- | --- | --- |
| normal | A_fixed | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| normal | B_single | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| normal | BTQ | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| normal | F_full | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| delayed | A_fixed | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| delayed | B_single | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| delayed | BTQ | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| delayed | F_full | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| partial_stall | A_fixed | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| partial_stall | B_single | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| partial_stall | BTQ | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| partial_stall | F_full | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| jitter | A_fixed | 0/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |
| jitter | B_single | 0/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |
| jitter | BTQ | 0/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |
| jitter | F_full | 0/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |
| dropout | A_fixed | 14/14/14 | 0.700 [0.481,0.855] | 0 | 0.000 [0.000,0.161] |
| dropout | B_single | 14/14/0 | 0.000 [0.000,0.161] | 14 | 0.700 [0.481,0.855] |
| dropout | BTQ | 14/12/12 | 0.600 [0.387,0.781] | 0 | 0.000 [0.000,0.161] |
| dropout | F_full | 14/12/12 | 0.600 [0.387,0.781] | 0 | 0.000 [0.000,0.161] |
| deviation | A_fixed | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| deviation | B_single | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| deviation | BTQ | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| deviation | F_full | 20/20/20 | 1.000 [0.839,1.000] | 0 | 0.000 [0.000,0.161] |
| failure | A_fixed | 20/20/0 | 0.000 [0.000,0.161] | 20 | 1.000 [0.839,1.000] |
| failure | B_single | 20/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |
| failure | BTQ | 20/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |
| failure | F_full | 20/0/0 | 0.000 [0.000,0.161] | 0 | 0.000 [0.000,0.161] |

在所设独立参考下，正常条件A、BTQ与F均为20/20支持路径，B为0/20；延迟和部分停滞条件BTQ与F均为20/20，而A/B为0/20。这支持共同稳定到达反馈策略包在这些条件下的作用，不将B→BTQ的Q/W联合差异单独归于W。

不利结果同样保留：jitter四组源准备均0/20，不能用无错误请求称其成功；dropout中A支持路径14/20，BTQ/F各12/20，完整方法并非最好。deviation中BTQ/F均20/20，F的全计划平均时间11.792s，高于BTQ的10.891s。持续故障下所有方法严格路径均0/20，A流程走完不等于完成运输。

## 4. 运行时间、保护与未尝试步骤

成功时间只统计严格支持路径，n并列；NA表示无支持成功而非0秒。全计划代价为严格成功实际时间，否则24s的工程惩罚，不是RMST。T/R/Z为常规目标Retry、Recovery和返回目标resend实际Applied，全部失败的零值也保留。

| 条件/方法 | 成功n/时间s | 全计划代价s | T/R/Z | 未尝试步 | 停止原因 |
| --- | --- | --- | --- | --- | --- |
| normal/A_fixed | 20/4.133 | 4.133 | 0/0/0 | 0 | {'fixed elapsed interval; no visual arrival event': 20} |
| normal/B_single | 0/NA | 24.000 | 0/0/0 | 0 | {'final target confirmed': 20} |
| normal/BTQ | 20/4.060 | 4.060 | 0/0/0 | 0 | {'final target confirmed': 20} |
| normal/F_full | 20/4.060 | 4.060 | 0/0/0 | 0 | {'final target confirmed': 20} |
| delayed/A_fixed | 0/NA | 24.000 | 0/0/0 | 0 | {'fixed elapsed interval; no visual arrival event': 20} |
| delayed/B_single | 0/NA | 24.000 | 0/0/0 | 0 | {'final target confirmed': 20} |
| delayed/BTQ | 20/6.969 | 6.969 | 0/0/0 | 0 | {'final target confirmed': 20} |
| delayed/F_full | 20/6.969 | 6.969 | 0/0/0 | 0 | {'final target confirmed': 20} |
| partial_stall/A_fixed | 0/NA | 24.000 | 0/0/0 | 0 | {'fixed elapsed interval; no visual arrival event': 20} |
| partial_stall/B_single | 0/NA | 24.000 | 60/0/0 | 0 | {'final target confirmed': 20} |
| partial_stall/BTQ | 20/9.788 | 9.788 | 60/0/0 | 0 | {'final target confirmed': 20} |
| partial_stall/F_full | 20/9.788 | 9.788 | 60/0/0 | 0 | {'final target confirmed': 20} |
| jitter/A_fixed | 0/NA | 24.000 | 0/0/0 | 60 | {'source confirmation timeout': 20} |
| jitter/B_single | 0/NA | 24.000 | 0/0/0 | 60 | {'source confirmation timeout': 20} |
| jitter/BTQ | 0/NA | 24.000 | 0/0/0 | 60 | {'source confirmation timeout': 20} |
| jitter/F_full | 0/NA | 24.000 | 0/0/0 | 60 | {'source confirmation timeout': 20} |
| dropout/A_fixed | 14/5.276 | 10.893 | 0/0/0 | 18 | {'fixed elapsed interval; no visual arrival event': 14, 'source confirmation timeout': 6} |
| dropout/B_single | 0/NA | 24.000 | 0/0/0 | 18 | {'final target confirmed': 14, 'source confirmation timeout': 6} |
| dropout/BTQ | 12/9.502 | 15.301 | 27/3/2 | 19 | {'final target confirmed': 12, 'source confirmation timeout': 6, 'local recovery timeout': 1, 'local recovery limit reached': 1} |
| dropout/F_full | 12/9.502 | 15.301 | 27/3/2 | 19 | {'final target confirmed': 12, 'source confirmation timeout': 6, 'local recovery timeout': 1, 'local recovery limit reached': 1} |
| deviation/A_fixed | 0/NA | 24.000 | 0/0/0 | 0 | {'fixed elapsed interval; no visual arrival event': 20} |
| deviation/B_single | 0/NA | 24.000 | 60/0/0 | 0 | {'final target confirmed': 20} |
| deviation/BTQ | 20/10.891 | 10.891 | 60/0/0 | 0 | {'final target confirmed': 20} |
| deviation/F_full | 20/11.792 | 11.792 | 0/60/60 | 0 | {'final target confirmed': 20} |
| failure/A_fixed | 0/NA | 24.000 | 0/0/0 | 0 | {'fixed elapsed interval; no visual arrival event': 20} |
| failure/B_single | 0/NA | 24.000 | 80/20/20 | 40 | {'local recovery limit reached': 20} |
| failure/BTQ | 0/NA | 24.000 | 80/20/20 | 40 | {'local recovery limit reached': 20} |
| failure/F_full | 0/NA | 24.000 | 80/20/20 | 40 | {'local recovery limit reached': 20} |

## 5. 配对效应与科学归因

正式预声明比较为BTQ−A、BTQ−B和F−BTQ。下表列F−BTQ核心效应，全部126项配对指标在paired_contrasts.csv。区间为场景内seed级2000次bootstrap百分位95%逐点区间；不按是否跨0制造显著性结论。

| 条件 | 指标 | 配对n | 差值[95%逐点区间] |
| --- | --- | --- | --- |
| delayed | path_rate | 20 | 0.000 [0.000,0.000] |
| delayed | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| delayed | budgetized_completion_s | 20 | 0.000 [0.000,0.000] |
| deviation | path_rate | 20 | 0.000 [0.000,0.000] |
| deviation | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| deviation | budgetized_completion_s | 20 | 0.900 [0.712,1.077] |
| dropout | path_rate | 20 | 0.000 [0.000,0.000] |
| dropout | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| dropout | budgetized_completion_s | 20 | 0.000 [0.000,0.000] |
| failure | path_rate | 20 | 0.000 [0.000,0.000] |
| failure | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| failure | budgetized_completion_s | 20 | 0.000 [0.000,0.000] |
| jitter | path_rate | 20 | 0.000 [0.000,0.000] |
| jitter | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| jitter | budgetized_completion_s | 20 | 0.000 [0.000,0.000] |
| normal | path_rate | 20 | 0.000 [0.000,0.000] |
| normal | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| normal | budgetized_completion_s | 20 | 0.000 [0.000,0.000] |
| partial_stall | path_rate | 20 | 0.000 [0.000,0.000] |
| partial_stall | unsafe_trial_rate | 20 | 0.000 [0.000,0.000] |
| partial_stall | budgetized_completion_s | 20 | 0.000 [0.000,0.000] |

正式桥接同保护条件下，BTQ与F_arrival控制事件及时间完全一致的配对为80/80。该结果限定于本批模型和参数，不证明两个算法数学等价，也不支持S/K在随机闭环中有独立优势。保护差异必须由P_F−P_B桥接衡量，不能从四主组F−BTQ直接归因S/K。

| 条件 | 指标 | 固定因子对照 | 差值[95%] |
| --- | --- | --- | --- |
| partial_stall | path_rate | gate_at_P_B | 0.000 [0.000,0.000] |
| partial_stall | path_rate | protection_at_BTQ | 0.000 [0.000,0.000] |
| partial_stall | path_rate | interaction_difference_in_differences | 0.000 [0.000,0.000] |
| partial_stall | budgetized_completion_s | gate_at_P_B | 0.000 [0.000,0.000] |
| partial_stall | budgetized_completion_s | protection_at_BTQ | 0.000 [0.000,0.000] |
| partial_stall | budgetized_completion_s | interaction_difference_in_differences | 0.000 [0.000,0.000] |
| partial_stall | recoveries | gate_at_P_B | 0.000 [0.000,0.000] |
| partial_stall | recoveries | protection_at_BTQ | 0.000 [0.000,0.000] |
| partial_stall | recoveries | interaction_difference_in_differences | 0.000 [0.000,0.000] |
| deviation | path_rate | gate_at_P_B | 0.000 [0.000,0.000] |
| deviation | path_rate | protection_at_BTQ | 0.000 [0.000,0.000] |
| deviation | path_rate | interaction_difference_in_differences | 0.000 [0.000,0.000] |
| deviation | budgetized_completion_s | gate_at_P_B | 0.000 [0.000,0.000] |
| deviation | budgetized_completion_s | protection_at_BTQ | 0.900 [0.712,1.077] |
| deviation | budgetized_completion_s | interaction_difference_in_differences | 0.000 [0.000,0.000] |
| deviation | recoveries | gate_at_P_B | 0.000 [0.000,0.000] |
| deviation | recoveries | protection_at_BTQ | 3.000 [3.000,3.000] |
| deviation | recoveries | interaction_difference_in_differences | 0.000 [0.000,0.000] |

## 6. 桥接与受控运输诊断独立列示

以下不并入560主组总体率。桥接20seed/单元；主组两格复用构成2×2，不新增独立重复。受控运输绕过P0，只用于区分源准备瓶颈和目标确认瓶颈；其source_prepared工程标记不是视觉源确认的证据。

| 层/条件 | 方法/保护 | S/W/P | 支持确认/60 | 无支持请求 | 未尝试/60 |
| --- | --- | --- | --- | --- | --- |
| bridge/partial_stall | F_full/P_B | 20/20/20 | 60 | 0 | 0 |
| bridge/partial_stall | BTQ/P_F | 20/20/20 | 60 | 0 | 0 |
| bridge/deviation | F_full/P_B | 20/20/20 | 60 | 0 | 0 |
| bridge/deviation | BTQ/P_F | 20/20/20 | 60 | 0 | 0 |
| diagnostic/jitter | A_fixed/P_B | 20/20/20 | 60 | 0 | 0 |
| diagnostic/jitter | B_single/P_B | 20/20/0 | 0 | 60 | 0 |
| diagnostic/jitter | BTQ/P_B | 20/0/0 | 1 | 0 | 39 |
| diagnostic/jitter | F_full/P_F | 20/0/0 | 1 | 0 | 39 |
| diagnostic/dropout | A_fixed/P_B | 20/20/20 | 60 | 0 | 0 |
| diagnostic/dropout | B_single/P_B | 20/20/0 | 2 | 58 | 0 |
| diagnostic/dropout | BTQ/P_B | 20/17/17 | 57 | 0 | 0 |
| diagnostic/dropout | F_full/P_F | 20/17/17 | 57 | 0 | 0 |

## 7. 参考、时序、Unknown与删失

三计划步不因Retry/Recovery变成新样本。同目标实际驻留连续不按软件epoch清参考；Recovery实际切换后分段；离开目标旧参考失效。请求与Applied分开，Complete无真实电极事务时不伪造Applied。未发生独立参考的提前切换称unsupported，不通过反事实强称premature。

以下仅为全包核查计数，不是三层合池的准确率：核查1778个推进完成事件，其中请求支持1140；模拟Applied支持768，Applied分母不含无事务Complete。科研指标仍按cohort/场景/方法分别统计。逐事件上下界、提前/不确定/无支持标签见request_vs_applied.csv和独立逐事件表。确认延迟按trial内支持事件先汇总，再按seed给区间；事件数不是独立n。

Unknown不作为第六物理状态；其中既包含无效/旧帧/证据不足，也包含P_B研究分支不输出非到达五状态。全部帧级Unknown和缺Mask保存，不能用其计数声称五状态分类准确率。完整阶段表保留60步分母、参考到达、漏确认、未尝试、Unknown参考及删失。

jitter、dropout以及持续故障的结果必须与正常条件并列解释：共同P0源失败不能归于目标到达算法；受控运输诊断不能替代端到端率。失败模型中的Retry解锁/偏离恢复是已披露的简化机制，不能外推实物恢复概率。

## 8. 独立复算与材料完整性

G5只读复核174,491份manifest文件hash、99,291张PNG及解码像素hash、800份实际构造外生数组的raw字节hash/速度因子。独立物理驻留及事件/步骤算术不导入原reference/evaluation函数。共同P0核验140组，配对外生180组，观察到控制后Mask分叉134组。独立统计重算Wilson与配对bootstrap一致。

实际数组在World/Camera原构造后、运动开始前复制保存；没有额外RNG抽样，算法对象和运动方程不变。每trial保存外生npz、形状/dtype/字节序、seed流、速度因子、源码及环境。G3开发数组重建与正式实际数组保存分别标明来源，不回填旧记录。

兼容字段勘误：继承的trials.csv及legacy_view内formal_seed_runs=0仍是旧开发兼容字段；它不用于本研究正式运行计数。正式trial_manifest明确formal schema/purpose、formal_seed_runs=1及正式seed身份，800规模由固定计划与完成manifest核定。本报告公开该元数据差异，不回写原始记录，也不将其隐瞒为0次正式试验。

## 9. S4必要性与仿真停止判断

| 模块/问题 | 可复用证据 | 仍缺什么/处理 |
| --- | --- | --- |
| W连续窗口 | S2单帧/BQ/BTQ瞬态对照；S3等窗闭环结果 | 已有机制与所设条件证据，不加大型批次 |
| Q观测质量 | S2低置信正负对照、高置信伪Mask失败 | 真实错误Mask泛化仍待真实视频；S3无新Q主消融 |
| S空间任务门 | S2远端碎片synthetic stress；S3同保护桥接 | 误拒代价未独立识别，D_tail_true_cost受其他门影响，不能宣称已量化 |
| K历史一致性 | S2短跳变/持续伪Mask及K适应失败；S3桥接 | 保留持续错误适应和缺帧重建边界，不为F胜出新增场景 |
| 五状态保护 | S3固定门P_F−P_B及差中之差 | 行为/成本变化不自动等于安全性提升，更不等于真实五状态精度 |
| 参数代价（可选最小补充） | 已有共同Mask缓存和独立参考可复用 | 若论文必须量化，另审0.15/0.25/0.35s共同窗离线重放；只改同输入BTQ/F共同W、源P0不变，不新抽seed，不本轮执行 |

结论：没有必要再开启大型S4正式批次。S/K误拒成本若要给真实意义，应优先补独立人工真实到达参考；构造更离奇Mask不能代替真实证据。可选小窗敏感性仅回答参数权衡，不提升模型物理可信度。下一步转入真实分割、独立最终装置配准、真实视频事件与实物单液滴闭环，并据已有证据修订论文正文。

## 10. 图稿说明与复现

S3-A采用预声明deviation/265000，各列同一trial的位置、覆盖、预测状态、参考、请求与Applied；normal/265000为完整补充。S3-B用所有七场景及原定deviation桥接，n=20配对seed；图中失败/未尝试仍在分母。全部为SIMULATION，不向S1/S2回写图稿。

python scripts/audit_chapter2_s3_g3.py audit（已执行，不覆盖）

python run_chapter2_s3_formal.py plan

python run_chapter2_s3_formal.py run --output <全新目录>（800条已完成，不建议重跑）

python scripts/audit_chapter2_s3_final.py（只读原始记录，审计输出不覆盖）

python scripts/analyze_chapter2_s3_final.py

python scripts/plot_chapter2_s3_final.py

python scripts/verify_chapter2_s3_final.py full

源码复用关系和最终算法定义见后附G3协议。正式数据在独立目录，逐帧Mask/事件/真值分开；图稿源数据、完整40组汇总、126配对项、桥接及阶段表随包保存。
