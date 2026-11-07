# 第二章四组仿真研究实验：现有证据与论文图稿对应表

日期：2026-10-25。性质：基于当前仓库及持久化结果的只读整理，不是新实验结果。

章节基线：[第二章章节与研究证据安排](chapter2-chapter-evidence-baseline-2026-10-25.md)。方法写在2.3.3及2.4，验证结果集中在2.5.3–2.5.4；不在每个方法小节重复设置一组仿真。

## 1. 固定框架、命名与证据等级

固定为四组：**实验S1空间特征与状态变化、实验S2到达事件算法、实验S3完整闭环控制、实验S4消融与异常边界**。S2/S3为核心，S1解释机制，S4检验适用条件与局限。

避免命名冲突：本文“实验S1–S4”是研究组织；既有代码中的`S1_mask_cache_v1`至`S4_mask_cache_v1`是实验S2内的四种到达算法，简称“算法S1–S4”。不改代码枚举、不重命名冻结文件。空间模块S、窗口W、历史K、质量Q也不是四组实验的编号。

全部属于**简化二维单液滴视觉闭环算法仿真**：点位置运动、有限速度/响应延迟、简化圆形Mask和观测扰动、控制动作反作用；单位pitch与simulation时间。当前冻结地图是420示例模板，`map_path=null`，不是已生成的FBC6-3真实毫米设计地图。几何辅助数值实验只检验计算及参数机制；不是实物配准精度、CFD或真实电润湿动力学。

| 证据等级 | 已有材料 | 允许支持的结论 | 不支持的结论 |
|---|---|---|---|
| M：机制/示例 | 单trial过程图、手算几何测试、定向夹具、兼容回归 | 给定输入下某个特征、门、事件与动作确实按契约执行 | 随机平均收益、真实五状态准确率、实物可靠性 |
| D：开发描述 | v2三个开发seed、21份共同缓存、84端到端及24阶段诊断 | 当前开发条件中观察到的相同/不同、失败与触发频次 | 正式v2总体性能、显著优势；不能并入未来确认seed |
| V1：冻结正式仿真 | v1每场景20配对seed、冻结参数、原始数据和统计 | 指定二维代理、路线、扰动与独立模拟参考下的条件性对比 | 真实U-Net、真实液滴准确率或F对等窗BTQ的独立优势 |
| 待补 | v2预声明的辨别性对照、目标/参考敏感性、正式策略比较 | 取得材料并验收后再决定可支持的主张 | 不能因章节已有位置或图框已有标题就标为已完成 |

## 2. 仿真实验—科学问题—现有证据—待补内容—论文图稿

| 仿真实验及章节归属 | 科学问题 | 现有代码、原始证据及实际完成状态 | 待补内容与对照 | 论文主图及子图安排 |
|---|---|---|---|---|
| **实验S1：空间特征及运动状态变化**；2.3.3、2.4.1–2.4.2，结果归2.5.3 | 一次迁移中空间特征如何变化，哪些观测和连续证据导致状态/控制事件？ | `world.py`/`vision.py`/`geometry.py`；正式特征接口及`v2/observation.py`；已有v1单trial轨迹/状态图，v2 normal:262000:F:end_to_end:full完整truth、实际Mask、特征、证据窗和事件；Process图、播放器/MP4。属于M机制演示，不是五状态准确率测试。 | 不必新建运动模型。先复用同trial全部持久化量；几何计算需另以手算/数值用例核验。normal演示未出现Stationary、Deviation、Retry、Recovery，不补画；如需异常示例只能另列已有异常trial，不能拼成同次迁移。没有形变动力学或真实状态GT。 | **Fig.Sim-1**方法架构（公共说明图）；**Fig.Sim-2**：(a)190→191六个实际时刻的局部网格、内部位置与实际Mask；(b)eta_source/eta_target及rho_target、距离/方向进展；(c)预测状态与窗口；(d)独立参考、确认和模拟Applied。可由现有Process-2/3组合，不覆盖原图。 |
| **实验S2：不同到达事件识别算法对比**；方法2.4.2，结果2.5.3 | 同一观测下，单帧/连续窗差异是什么？等窗等质量后S/K还有什么增量与代价？ | `dmf/experiment/benchmark.py`、`mask_cache.py`、`fixed_inputs.py`、`study.py`；v1 140共同缓存×7方法=980离线运行，其中算法S1–S4为560、三消融420。v2 `benchmark.py`/`arrival.py`共享EvidenceWindow和C0；21缓存BTQ/F输入hash相同、事件和时间完全一致（本轮直接核对原预测清单）。V1可作条件性仿真结论；v2是D，不支持F独立优势。 | 保留算法S1–S4作历史梯度，不以弱单帧对照代替BTQ。未来A层用BTQ、BTQ+S、BTQ+K、F-arrival共输入比较；必要的S/K辨别条件须先验证正常负对照、候选通过率与事件改变率。需按预声明随访区分漏确认/右删失；E4目标门和E5参考敏感性尚未执行。 | **Fig.Sim-3**：(a)共同Mask与参考区间、各方法首次确认的事件栅格；(b)正确支持/确定提前/无支持/漏确认和删失支持数；(c)确认延迟区间与配对差；(d)BTQ/F一致性及候选拒绝诊断。v1、v2分面分版本，不混成同一批方法排名。 |
| **实验S3：事件驱动闭环控制算法对比**；方法2.4.3，结果2.5.4 | 到达判定与有界保护组成的完整策略能否改善运输可靠性、效率及停止行为？ | `formal_adapter.py`/`formal_runner.py`/`formal_batch.py`；v1正式A/B/C各7×20=420 trial，另420闭环消融；真值/帧/事件/逐trial/配对差已保存。v2 `adapter.py`/`runner.py`/`evaluation.py`，84端到端+24阶段诊断；三步路线相同，动作改变世界目标/响应。v1为V1，v2仅D。 | 拟议A固定时间、BTQ完整策略、F完整策略尚不是已完成的同批正式比较；v2现有方法不含历史A/B。须冻结共同源准备、预算、独立随机流和终点，并核验A的桥接。F五状态Deviation与BTQ Unknown导致保护通道不同，收益只能归完整策略包；若要归S/K须另设共同保护桥接。E6未启动。 | **Fig.Sim-4**：(a)源准备/运输中止/无支持流程完成/正确路径完成的阶段结局；(b)路径完成率及CI；(c)全体执行时间与成功条件完成时间分开；(d)错误更新、Retry、Recovery及恢复后重发；(e)主要停止原因。v1先复用A/B/C，v2开发另表，未来正式A/BTQ/F另批。 |
| **实验S4：时空先验消融及异常工况**；2.4整体，结果2.5.3–2.5.4 | 哪个模块在什么可观察条件下有独立作用？收益、延迟、失败及不可辨识边界是什么？ | v1离线和闭环三项消融各420运行，jitter共享门敏感性180 trial；v2 `FactorFlags`/`ArrivalGate`/`ObservationPipeline`及8夹具×16组合=128机制组合，另21共同缓存gate诊断。已有no_temporal同时去窗口/历史，不能冒称v1已完成W/K独立消融。现有S/Q随机候选拒绝为0，K-only拒绝53但共同W也阻断，BTQ/F无事件差异。 | 正交S/W/K/Q需沿用v2规则，C0始终开启；目标门消融与控制保护消融分开。为S/K/Q补经过可行性论证的压力观测及正常负对照，不按F获益选seed。分开jitter源准备和目标运输；保留dropout不利结果。E4固定源门扫描目标，E5固定运动/预测仅重评分；不得据全部失败声称鲁棒。 | **Fig.Sim-5**：(a)异常场景—模块可检验性/触发频次；(b)配对消融的错误、漏确认与延迟；(c)jitter源区与受控运输分层；(d)deviation/丢帧的真实日志事件线及失败原因；(e)目标参数和独立参考敏感性（取得新结果后才填）。128机制组合与随机性能不能用同一统计柱合并。 |

Fig.Sim为新框架的临时图号，不修改原始Fig.2-1–Fig.2-6。已有名为“Process-3/Sim-3”的联合时间线素材归实验S1的新Fig.Sim-2，不因此重命名旧文件或将其当成到达算法比较图。最终论文编号待2.5排版时统一。

## 3. 各组输入、输出、控制变量及评价口径

| 组别 | 实际输入 | 输出 | 必须固定/分层的控制变量 | 评价指标与统计单位 |
|---|---|---|---|---|
| 实验S1 | 持久化truth ticks、观测Mask/时间/context、地图、特征/证据/事件日志；内部truth只用于展示或评分 | 同trial关键帧、空间特征、预测状态/动作联合时间线 | 同trial、同step/epoch、同一时间轴；不插值补Mask/状态/动作；缺失明确标记；单位pitch | 几何手算误差、逐点时序一致性、窗口重建/事件消费检查。单trial是示例n=1，无总体准确率或CI |
| 实验S2 | 同字节Mask缓存、地图、外部固定任务片段、帧/曝光/可用时间、模拟Applied与冻结参数；算法不读GT | 每任务至多一次到达事件、确认窗边界、gate轨迹；参考独立评分 | 教师任务不受算法输出影响；BTQ/F共W/Q/C0、覆盖与源释放门；S/K为增量；输入hash及参考版本绑定 | 支持确认、提前、无支持、时间不确定、重复/错误事件、漏确认、延迟区间；计划步/参考步/完整随访步同时给分母。以共同cache/seed配对，不把帧当独立重复 |
| 实验S3 | 初值、相邻路线190→191→192→172、环境/相机/执行延迟配置与配对随机流；算法仅见观测 | 自适应truth/观测/动作轨迹、阶段结局、路径正确性、执行代价、停止原因 | 同场景/seed/外部随机数组、源准备/恢复门/保护预算/上限；允许控制使后续轨迹和观测分叉，不能称同输入 | planned trials/steps、source_prepared、transport_complete、path_complete、支持/错误事件、全体与条件时间、Retry/Recovery/恢复后重发、Unknown/丢帧/未尝试。seed为统计单位 |
| 实验S4 | 与S2相同的共同缓存或与S3相同的闭环配对条件；机制夹具独立标记synthetic stress | 开关组合、原始S/K/Q和有效门、候选计数、窗口重建、事件改变与控制代价 | C0常开；历史从相同C0可解析帧更新，不由开关选择历史；只改预声明因素；源P0/Recovery门不随目标W开关改变 | 候选分母→gate拒绝率→事件改变率→参考支持变化，不能只报触发次数；配对效应与CI、失败类别、敏感性可行性。机制组合数不是独立随机样本数 |

### 共用定义

- eta_source和eta_target：Mask与相应区域交叠面积／液滴Mask面积；rho_target：交叠面积／目标电极面积。rho仅记录，当前不新增强制阈值。
- 源区“残留”在本模型是二维Mask面积比例，不等于实测残留体积。没有真正的液体形变、拉伸、分裂、体积守恒或电场求解；半径扰动不能写成经验证的形变模型。
- 模拟参考用内部位置盆地、真实模拟速度与连续驻留定义，和Mask/算法阈值隔离；v2默认0.09 pitch、0.06 pitch/s、0.15 s，0.01 s网格形成参考区间。它仍是约定的模拟参考，不是实测真值。
- 对参考[l,u]和确认c：c<l是确定提前；l≤c<u为分辨率内不确定；c≥u为支持，延迟区间[c−u,c−l]。没有参考的确认标unsupported，不推测反事实未来到达。
- `transport_complete`表示控制流程完成，`path_complete`还须满足预声明的逐步独立支持、无错误/重复/不确定事件等条件。两者不能互换。
- 计划试验和步骤不删除；源失败、未进入运输、物理未到达、漏确认、随访不足、基础设施问题分别记录。参考为0时recall=NA，不填100%。Unknown是观测/输出标签，不是新物理状态，更不能据BTQ的Unknown较多判其识别准确率低。
- v1的`early_updates`沿用历史字段，包含没有参考支持的更新；与v2区分“确定提前”和“unsupported”的评分不能直接同名合池。冻结结果保留；如需统一口径，只能另存独立重评分及版本。
- 已有v1路径率使用Wilson95%区间，事件比例/延迟以seed整簇bootstrap，配对差同seed重采样。0或1的退化bootstrap区间不表示总体零风险。v2当前三个开发seed只作描述。

## 4. 本轮直接核对的原始事实

### 4.1 数量与重复使用边界

| 数据集 | 直接读取结果 | 研究归属及避免重复计数 |
|---|---|---|
| v1 formal/closed_loop/trials.csv | 840行＝7场景×20seed×6方法；其中原A/B/C 420，三消融420 | 实验S3和S4引用同批不同方法，不再相加为两套840次 |
| v1 formal/offline_trials.csv及cache_trials | 980行、140份共同缓存；算法S1–S4 560行，三消融420行 | 实验S2/S4的共输入研究，不是980个独立视频或独立seed |
| v1 sensitivity | 9条件×20seed＝180；全部路径失败 | 属于共享源/目标证据门的jitter历史扫描，不是独立目标门敏感性 |
| v2 development_smoke_r2/trials.csv及step_ledger.csv | 108条、324计划步骤；84端到端＋12 source_only＋12 transport_only | 实验S3/S4开发诊断；三种phase_mode不合池，不把旧development_smoke再计作新重复 |
| v2 research_predictions | 21共同缓存、BTQ/F预测各21份；逐step/target/timestamp及输入hash均相同 | 实验S2的一致性事实；事件总数两方法各26，不是21份均有到达 |
| v2 module_mechanism_matrix.csv | 128行＝8夹具×16开关组合 | 实验S4机制证据，不是128个独立随机trial |
| normal:262000:F:end_to_end:full | 412 truth tick、83 capture/帧记录、79实际Mask、78 gate记录、12事件、3参考区间 | 实验S1单trial演示；绘图、动画和播放器不是新增trial |

上述只读计数未调用模型或重新运行识别器，不能算新仿真实验。v1“正式”仅指此前冻结研究批次，不能升级为真实实验或未开展的v2正式批次。

### 4.2 必须进入正文/图注或失败分析的不利结果

| 条件 | 已有结果 | 必须采用的解释 |
|---|---|---|
| v1 jitter | A路径1/20、B0/20、C_formal0/20；C有19/20源准备失败，实际参考2、支持确认1、未尝试58/60步 | 低更新数并不等于安全/准确，条件召回只有极小支持；源失败不能删除 |
| v1 dropout | A路径15/20、B0/20、C_formal14/20；C支持44/45参考，计划60步，未尝试15步 | 不能写C所有条件优于A；报告完成率CI和漏确认，不只展示成功样例 |
| v1共享门敏感性 | 9条件均0/20路径完成；0.25 s仅1/20通过源准备，0.40/0.60 s均无通过 | 主要暴露源窗抖动瓶颈；不是目标阈值鲁棒或完整参数最优性的证据 |
| v2共同输入 | 21/21 BTQ/F事件/时刻一致；S-only拒绝0、Q拒绝0；K-only拒绝53但共同W也无事件 | S/K额外随机到达收益未被当前输入辨识。不能以多跑相同分布替代解释 |
| v2 jitter端到端 | BTQ/F各0/3源确认、0/3路径，9/9计划步未尝试，无参考 | 到达召回NA；不能据目标阶段没有错误说明目标门可靠 |
| v2 jitter受控运输 | BTQ/F各0/3路径；各3参考、0支持、3漏确认、6未尝试；均恢复超时 | 目标确认/恢复也有瓶颈，不只是源准备。controlled_initial不是视觉源确认 |
| v2 dropout | BTQ/F各3/3路径、9/9支持；各1次运输Retry | 不同seed的小样本，不能与v1 14/20对比为算法改进 |
| v2 deviation | BTQ/F各3/3路径；BTQ运输Retry9/Recovery0，F运输Retry0/Recovery9/恢复后重发9 | 完整保护策略差异；不能说F到达门S/K因此更准确，也不以恢复数更高直接证明更优 |
| v2 failure | BTQ/F各0/3路径、6未尝试、无参考；Retry12/Recovery3/恢复后重发3 | 有界停止机制，不是成功率；无实际到达的recall为NA |

### 4.3 运动及观测模型的可归因边界

`DropletWorld._apply`在partial_stall首次作用时把目标改到路线58%处，重施后再指向真正目标；deviation首次目标横偏0.8 pitch，后续作用可恢复原目标；failure的非Recovery动作不产生迁移。因此Retry/Recovery具有收益是该响应规则下的结果，不能推广为真实芯片重施一定能克服停滞、污染或故障。固定路线仅三步，不能宣称覆盖全部420电极及外围运输。

SyntheticCamera以内部位置加噪后绘制圆Mask，包含位置/半径噪声、随机丢帧及dropout时段；不是从真实图像运行U-Net。当前随机输入confidence通常为1，显著多连通区域和空间碎片主要来自人工机制夹具；现有随机场景不足以验证Q/S的完整统计收益。曝光为带时间戳的端点采样近似，不模拟真实曝光积分/运动模糊。

## 5. 复用、只读派生与必须新运行的界线

| 任务 | 可直接复用 | 可只读派生、不新增世界trial | 需要另行实施/运行 |
|---|---|---|---|
| S1解释图 | v2已保存的79Mask、truth、frames、gate、events、参考；现有过程图和播放器 | 特征曲线、同trial版式、关键帧放大；缺失量从同一Mask和冻结几何确定性计算时注明derived与版本 | 若要求当前模型没有的真实形变/新观测，须另立研究设计；本轮不增加 |
| S2历史算法比较 | v1共同缓存、逐事件、参考、逐trial与汇总；v2 BTQ/F一致结果 | 重新组织主图、逐事件差分审查；E5在truth/预测/控制hash冻结且参考器验收后可仅独立重评分 | BTQ+S/+K尚需新预测运行；E4目标参数需重新运行判据但不必重跑世界；新辨别输入先机制验证，再预声明正式研究 |
| S3完整控制 | v1A/B/C及全部失败；v2开发与阶段诊断原始日志 | 阶段计数、支持数、版本化图稿与失败分解 | 正式同批A/BTQ/F必须新的闭环运行，因为策略改变后续世界；不能从旧trial反事实拼出。共享保护桥接如需实施另获授权 |
| S4消融/敏感性 | v1旧消融及全失败敏感性；v2 128夹具和21cache gate轨迹 | 触发率/事件改变率、既有异常时间线、源/运输分层；旧参考重新评分只另存版本 | W/K拆分对照需新判据运行；控制级消融需新闭环trial；E4与E5先可行性/评分语义，E6仍不启动 |

v1闭环未持久化每帧原Mask时，不能用质心重新画圆并称“原始SyntheticCamera Mask”。其独立cache中的Mask属于固定教师输入，不得套到自适应C闭环轨迹。需要精确过程展示优先选完整持久化的v2 trial。

所有新评分/新预测也是新分析版本，即使不重跑世界，也不能说是旧冻结试验的原始输出。图中注明数据批次、方法版本、source manifest与支持数；禁止把v1与v2不同参考/seed拼为扩大n。

## 6. 五张主图的取舍和验收条件

1. **Fig.Sim-1 仿真模型与运行机制**：复用V2-Process-1，五主模块＋独立评分支路；虚线分隔算法可见观测和内部真值。它是方法图，没有统计n。
2. **Fig.Sim-2 单trial运动—特征—证据—动作**：复用优化Process-2及Process-3。1.46 s为[1.45,1.46]参考上界，1.92 s为算法确认/Update，1.96 s为模拟Applied；该tick任务目标192而world_active仍191，必须沿原日志说明，不画成瞬时已搬运。未发生的状态/动作不补齐。
3. **Fig.Sim-3 到达算法比较**：v1与v2分面；当前可展示v1事件结果和BTQ/F等同事实，但不能制作尚未执行的正式增量优势柱。只比较到达事件，算法S1/S2不输出伪造五状态。
4. **Fig.Sim-4 闭环性能与运行代价**：v1正式结果可直接用；v2开发分表，不与v1三方法拼同一排名。所有七场景和失败分母保留，完成时间明确条件样本量。
5. **Fig.Sim-5 模块作用及失败边界**：现有机制表、jitter/dropout负结果可用。未来正交随机消融与E4/E5取得后更新独立版本；不把空面板写成已完成。细节诊断、全部逐seed图放附录/源数据，不在正文堆满程序图。

共用验收：标SIMULATION、pitch和simulation时间；实际source/trial一致；内部truth不进入算法；无事件插值或GT阈值泄漏；源/运输/路径分母可核算；主图同时表达收益和边界；原Fig.2-1–Fig.2-6与冻结图源不改。

## 7. 下一步最小必要顺序（仅安排，不授权执行）

1. 先整理S1及现有S2/S3/S4证据图，无需增加平台功能或扩大样本数。
2. 正式新分析前处理评价语义：当前`v2/evaluation.py`的`right_censored`按“有参考、无预测”赋值，未检查随访长度；需独立区分完整随访漏确认与真正右删失。保留原指标，另存修正版及手算回归；本轮仅登记。
3. 对目标门S/K/Q确定“可通过公共门、能改变事件、又有正常负对照”的最小条件；若仍无事件区别，应如实报告冗余/不可辨识，不预设F必须胜出。
4. 预声明后分别开展E4目标参数与E5参考重评分；保持源P0固定。先检查连续窗可达性、候选拒绝和随访，不用全失败曲线推断鲁棒性。
5. 只有在完整策略比较的归因、评分和接口冻结后，再决定E6的必要范围和确认seed。既有开发seed262000–262002不混入未来正式推断；263000–263019仍只是拟议，不是已运行数据。

几何计算验证不等于实物空间精度；软件五状态运行不等于真实识别准确率；模拟控制可靠性不等于实物成功率。真实分割需要人工Mask及独立采集组，真实五状态需要独立人工时序标签，真实配准需要最终装置检查点，真实闭环必须另做芯片/相机/驱动联合实验。

## 8. 代码与数据索引

以下相对路径以本仓库为根，仅作定位，本轮未编辑源码：

- 世界/相机/几何：`dmf/chapter2_sim/{world,vision,geometry,config}.py`。
- v1正式适配/闭环/批量：`dmf/chapter2_sim/{formal_adapter,formal_runner,formal_batch}.py`。
- 共输入：`dmf/chapter2_sim/{fixed_inputs,study}.py`、`dmf/experiment/{mask_cache,benchmark}.py`。
- v2：`dmf/chapter2_sim/v2/{spec,observation,arrival,adapter,benchmark,runner,evaluation,reference,development,probes,persistence,replay,plotting}.py`。
- 图稿/播放器：`scripts/chapter2_process_figures_revision.py`、`dmf/chapter2_replay/`；原配置`configs/chapter2_formal_simulation.yaml`与`configs/chapter2_simulation_v2.yaml`。
- 既有回归：`tests/test_chapter2_geometry.py`、`test_chapter2_formal_adapter.py`、`test_chapter2_benchmark.py`、`test_chapter2_formal_statistics.py`、`test_chapter2_fixed_inputs.py`、`test_chapter2_sim_v2_{gates,benchmark,reference,runner,stage_audit}.py`、`test_chapter2_replay_player.py`。这些是软件测试，不是实物识别证据；本轮未重新执行。

数据根目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/`：

| 工作标识 | 根目录下的实际位置 | 关键来源 |
|---|---|---|
| V1 | `2026-10-21_B1-B4正式算法_v1` | `formal/closed_loop/{truth,frames,events,trials,summary,paired_differences}.csv`、`formal/{offline_trials,offline_summary}.csv`、`formal/cache_trials`、`formal/predictions`、`sensitivity`、`result_manifest.json`、源码ZIP |
| V2 | `2026-10-24_chapter2_sim_v2_E0-E3_v1/development_smoke_r2` | `trials.csv`、`step_ledger.csv`、`planned_trials.json`、`study_manifest.json`、`shared_inputs`、`research_predictions`、`mechanism_predictions`、128行矩阵、各trial的配置/地图/manifest |
| TRACE | V2内`trials/end_to_end__normal__262000__F` | `observations/{captures,frames,gate_trace,events}.csv`与`masks/`；`evaluation/{truth_ticks,reference_intervals,event_evaluation,step_outcomes}.csv` |
| AUDIT | `2026-10-24_v2阶段独立验收_v3` | `v2_independent_trials.csv`、`v2_scene_method_counts.csv`、`v2_phase_diagnostic_counts.csv`、`shared_cache_BTQ_F_events.csv`及原始hash |
| FIG | `2026-10-25_过程图优化与双层协议_v1/图稿_交付` | `figures/V2-Process-*`、`source_data`、`figure_manifest.json`；论文完整版和两页PPT版均保留 |
| PLAYER | `2026-10-25_交互式回放播放器_交付` | HTML、replay_bundle、source_manifest、原始日志副本、视频与关键帧、检查结果；不是新研究样本 |

补充解释见：[v1实施记录](chapter2-formal-simulation-implementation-2026-10-21.md)、[v2阶段验收](chapter2-v2-stage-acceptance-2026-10-24.md)、[BTQ/F双层协议](chapter2-btq-f-two-layer-protocol-2026-10-25.md)、[过程图交付](chapter2-process-protocol-delivery-2026-10-25.md)、[播放器交付](chapter2-replay-player-2026-10-25.md)。

本轮仅整理四组研究实验、读取原CSV/预测并登记证据。不重跑模型、不重跑算法、不启动大规模扫描、不修改正式五状态或生产控制/AM/U-Net/第三章、不覆盖v1/v2、不Commit/Push。
