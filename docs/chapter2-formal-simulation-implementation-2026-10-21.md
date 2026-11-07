# 第二章正式算法适配、S1–S4与配对仿真实施记录

日期：2026-10-21。仓库基线 HEAD：`fe9699d7e6867ee8897056b122c8248153cadd3e`。
这是 simulation 软件研究记录，不是实物闭环、真实视频评测或 U-Net 精度结果。

## 1. 边界与成果保护

- 按用户确认的“新增版本、不覆盖旧版”方案实施；未 commit/push。
- 74份既有源码的基线摘要保存在 `chapter2-formal-simulation-baseline-2026-10-21.json`。
- 本轮仅允许其中3份共享源码变化：`evidence.py`、`perception.py`、`event_evaluation.py`。其余71份不变，包括旧独立仿真、GUI、串口事务和第三章规划/调度。
- 未改STM32固件、AM扫描/刷新、既有协议或U-Net适配器；未打开真实串口、工业相机或高压输出。
- 旧入口 `run_chapter2_simulation.py` 与旧C保持原样；新版本不复用旧结果冒充正式算法结果。

## 2. 新增接口与实际修改文件

| 文件 | 作用 |
| --- | --- |
| `dmf/chapter2_sim/formal_adapter.py` | NormalizedMap、SimulationFrameTiming、FormalDecision、FormalAdapter；直接复用正式特征/状态/策略/证据/事件 |
| `dmf/chapter2_sim/formal_runner.py` | 共用World/Camera，准备确认、请求/模拟APPLIED分离、动作反作用、独立物理参考、完整捕获/待处理帧记录 |
| `dmf/chapter2_sim/formal_batch.py` | 六种方法、seed统计/配对差、流式原始CSV、显式缺失支持、配置/源码/输出摘要 |
| `dmf/chapter2_sim/fixed_inputs.py` | 固定教师控制任务段，Mask输入与独立物理参考分别落盘 |
| `dmf/chapter2_sim/study.py` | 冒烟→正式/敏感性门槛、冻结参数/地图/源码、离线批量预测与独立评价 |
| `dmf/chapter2_sim/formal_plotting.py` | 从持久化CSV生成带SIMULATION标识的图，不生成新样本 |
| `dmf/experiment/mask_cache.py` | 一次写入、摘要校验的统一输入；任务/单位/单流/缺失Mask校验，禁止GT字段 |
| `dmf/experiment/benchmark.py` | GT隔离的S1–S4和三项消融；单帧组仅输出到达事件，不虚构完整状态 |
| `dmf/experiment/evidence.py` | 新增显式simulation时钟分支；既有offline/dry_run/experiment语义保留 |
| `dmf/experiment/perception.py` | 三个显式消融开关，默认全部开启，正常正式路径不变 |
| `dmf/vision/event_evaluation.py` | 严格human入口保留，另增simulation_physics入口，共用计数核心，不伪造人工来源 |
| `configs/chapter2_formal_simulation.yaml` | 冻结七场景、种子、方法、扫描网格与统计次数 |
| `run_chapter2_formal_simulation.py` | 新CLI：smoke/formal/sensitivity/cache/run/evaluate/materials-check |
| `scripts/evaluate_chapter2_baselines.py` | 离线预测/评价入口 |
| `scripts/package_chapter2_formal_results.py` | 交付前核验全部原始摘要/身份/评价/图，保存源码快照与完整结果清单 |
| 七个 `test_chapter2_{formal_adapter,benchmark,fixed_inputs,formal_cli,formal_statistics,formal_plotting,formal_packaging}.py` | 新增回归与接口测试 |

配套：语义审查、正式设计、执行清单、图契约与本记录。既有实施状态文档只追加真实状态。

主要API：`FormalAdapter.observe/tick/accept`；`write_cache/load_cache`；`run_variant`；`evaluate_simulation_events`；`run_formal_batch`。
算法预测入口不接收reference参数。输入缓存只含Mask、图像坐标变换、任务段、时间与冻结判据；参考在兄弟目录evaluation中。

## 3. 算法语义与方法版本

- 内部复用正式 `PriorFeatures`、`RegionOverlap`、`TransportProjection`、`EvidenceWindow`、`ProgressMonitor`、`StateRecognizer`、`EventController`、`FrameCausalityGuard`、`StepContext`、`ArrivalEventLedger`。
- 长度是pitch，速度是pitch/s；旧接口内部的`*_mm`只是有文档的数值兼容别名，不代表1pitch=1mm。
- 模拟曝光/可用/APPLIED/决策使用simulation域；真实host/UTC/device/APPLIED接收字段不填造数值。
- 三组共用源区准备与稳定确认。A运输阶段固定时间；B单帧eta与源释放；C调用正式连续状态和有界局部策略。
- 决策携带任务上下文、请求token和发出方；复制/旧epoch/修改后的决定不能重复应用。到达事件在应用成功后才消费；失败可再次请求。
- 停止时仍在处理队列的已捕获帧保留为Unknown/unavailable/censored，不伪造成已处理观测。

正式闭环版本：

- A：`A_fixed_v1__formal_full`；B：`B_single_eta_v1__formal_full`。
- C：`C_formal_b1b4_v1__full`；消融后缀为`__no_spatial`、`__no_temporal`、`__no_validity`。
- 离线：`S1_mask_cache_v1`至`S4_mask_cache_v1`及三个`no_*_mask_cache_v1`。

| 离线组 | 到达事件判据 |
| --- | --- |
| S1 | 当前质心到目标中心的单帧位置门 |
| S2 | 当前eta_target与eta_source释放门 |
| S3 | S2 + 当前任务允许区域/目标polygon门 |
| S4 | 正式有效性、任务因果、历史运动约束和连续稳定窗 |

四组读取相同缓存/hash、地图、外部任务分段、时间源与冻结参数。S1–S3不输出虚构的五状态标签。
no_spatial只去空间先验；no_temporal去连续确认和运动历史但保留身份/因果屏障；no_validity去非必要质量/运动冲突筛查，仍不允许缺失或不可解析Mask充当观测。

## 4. 反例及修复后的回归

以下都是软件合成夹具，不是人工标注实测真值。

| 修复前反例 | 修复后 |
| --- | --- |
| 复制Update可接受两次、跳过运输步 | origin/token/issuer注册校验，一次接受，旧epoch拒绝 |
| 拒绝应用后Arrived事件已耗尽 | 事件pending保留，成功应用才消费，后续新帧可重发 |
| 零延迟初始Prepare无Applied日志 | tick0/亚步长/正常延迟均恰有一次应用记录 |
| 待处理捕获帧在终止时消失 | 显式删失行与capture/pending计数保留 |
| S2漏源释放门 | 高目标覆盖但源残留的手算反例不确认 |
| 去有效性消融连带关闭运动历史 | 只移除质量门，运动速度历史仍计算 |
| 不同video_id的三帧+三帧可拼成稳定窗 | cache v1要求单流，保留原video_id，不跨流拼证据 |
| 配置1帧/0秒仍标成S4正式算法 | 正式参数先校验，只有显式no_temporal允许单帧消融 |
| 更换参考文件或空hash仍可打分 | 真实SHA256绑定，跨缓存参考拒绝；事件时钟/身份不可被静默改写 |
| 冒烟后更换环境/真值/地图仍可正式运行 | 绑定解析后配置、地图字节摘要、源码和冻结研究设计 |
| 部分敏感性目录仍宣称9组/20seed | 渲染前验证九条件、种子、方法、配置和真实样本数 |
| 已到达漏确认与GT本身右删失混用 | delay_censored与right_censored_reference分别保留 |
| 非法负计数/NaN可产生负提前率或recall>1 | 公共统计接口拒绝非法类型、非有限值和不可能计数关系 |
| 打包只信数量，可重新签认改动/缺失原始结果 | 核对旧摘要、父子身份/配置、全部离线行及重算评价/汇总，图QA不通过则不打包 |

另外覆盖重复/逆序帧、长gap、无效帧、跨epoch、目标位置门、Partial/无进展超时、有限Retry/Recovery、时钟/单位及同输入与正式算法逐帧一致性。

## 5. 实验设置与独立参考

现有420地图结构（包含非规则外围）被保留，默认来源仍是`example_420_template_not_measured`；没有已独立验证的实物几何文件，不能称为真实标定地图。
冻结相邻路线为`190→191→192→172`，不新增A*或多液滴调度。
运动、相机、误差与随机流复用既有模块；控制动作经过模拟应用/响应延迟后真正改变世界目标。

独立参考由世界位置盆地0.09pitch、真实速度≤0.06pitch/s和驻留0.15s定义；不读取Mask、eta或识别阈值。
参考时间区间记录积分网格误差，步长0.01s。曝光为端点采样近似，不模拟真实运动模糊。
物理随机流按tick，视觉随机流按frame索引；同scene/seed配对，允许控制差异导致轨迹分叉。

- 冒烟已完成：126闭环、21缓存、147离线运行；seed260600–260602。
- 正式闭环已完成：7×20×6=840次，其中ABC420次、三项消融420次。
- 敏感性已完成：jitter，20同配对seed，3覆盖×3时长=180次。
- 正式离线已完成：140共同缓存、980次方法运行（S1–S4与三项消融）。
- 正式闭环合计1020次；冒烟单独保存，不并入正式n。

统计单位是scene内seed，非帧或运输步。路径率用Wilson95%；提前/召回比率和连续量用2000次seed整簇bootstrap；配对差按同seed重采样。
成功完成时间与全体执行时间分开；延迟是已观测确认的条件均值，漏确认、未到达、未尝试、Unknown与删失均保留支持数。无独立到达事件时recall不定义，不填0或100%。
整簇percentile-bootstrap在全部观测seed为零/一时可能给出退化区间，不能据此证明总体风险为零；路径率另用Wilson区间。20个seed和简化代理不支持真实可靠性或显著性结论。

## 6. 已实际得到的正式闭环结果

每格20个seed，路径成功要求所有步真实到达且无提前更新；不能把发完命令等同成功。

| 场景 | A成功 | B成功 | C_formal成功 | C条件确认延迟均值(s) |
| --- | ---: | ---: | ---: | ---: |
| normal | 20/20 | 0/20 | 20/20 | 0.149 |
| delayed | 0/20 | 0/20 | 20/20 | 0.162 |
| partial_stall | 0/20 | 0/20 | 20/20 | 0.155 |
| jitter | 1/20 | 0/20 | 0/20 | 6.210，仅1个seed有可观测延迟 |
| dropout | 15/20 | 0/20 | 14/20 | 1.654，15个seed有可观测延迟 |
| deviation | 0/20 | 0/20 | 20/20 | 0.158 |
| failure | 0/20 | 0/20 | 0/20 | 不定义 |

20/20的Wilson95%区间为[83.9%,100%]；0/20为[0%,16.1%]。dropout的C为70%[48.1%,85.5%]，A为75%[53.1%,88.8%]；不能由此声称C在所有条件优于A。
C本批次全部420计划步的提前更新为0，但jitter有19/20源确认失败，不能把“没有执行/没有更新”解读为低风险或高识别精度。
dropout的C正确确认44/45个实际出现的到达参考，60个计划步均保留；还有1个已到达漏确认。
jitter的C仅有2个实际到达参考、1个确认，来源于1个进入运输的seed；50%条件recall支持极小，不能作精度结论。

无进展/偏离保护确实生效：partial_stall的C平均每路线3次运输Retry；deviation平均每路线3次局部Recovery（每步最多1次）；永久failure最终保护停止，不伪造成完成。
空间/有效性消融在若干圆形Mask场景与完整方法相同，照实保留，不临时添加有利异常。

敏感性9条件均未完成路径；0.25s条件只有1/20通过源准备，0.4/0.6s无seed通过源准备。
覆盖阈值和持续时间同时用于源准备/Recovery与目标确认，因此这是共享证据门扫描，不是孤立的目标阈值扫描。
该结果主要暴露源确认的抖动瓶颈，不证明参数鲁棒；真值及环境未为改善结果重调。

## 7. 已实际得到的S1–S4离线结果

每场景20个seed、每路线3步；外部固定任务时段与同一Mask缓存供所有方法读取。离线固定控制不执行Retry/Recovery，不能与自适应闭环路径成功率混为一谈。

| 场景 | S1/S2/S3路线识别完成 | S4路线识别完成 | S4正确确认/实际到达 | S4提前事件 | S4条件延迟均值(s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| normal | 均0/20 | 20/20 | 60/60 | 0 | 0.153 |
| delayed | 均0/20 | 20/20 | 60/60 | 0 | 0.142 |
| partial_stall | 均0/20 | 0/20 | 无实际到达，recall不定义 | 0 | 不定义 |
| jitter | 均0/20 | 0/20 | 3/60 | 0 | 2.077 |
| dropout | 均0/20 | 13/20 | 51/60 | 0 | 1.182 |
| deviation | 均0/20 | 0/20 | 无实际到达，recall不定义 | 0 | 不定义 |
| failure | 均0/20 | 0/20 | 无实际到达，recall不定义 | 0 | 不定义 |

normal/delayed/jitter中S1–S3各有60/60次提前确认；dropout中S1提前58次、正确2次，S2/S3提前59次、正确1次。不能把首次越过算法阈值当成独立物理到达。
这些结果只说明本二维代理、冻结噪声及独立物理参考下的行为，不证明S4对真实视频更准确。
空间/有效性消融在本批次若干圆形Mask场景无差异；完整原始行和支持数保留，未补造五状态GT或混淆矩阵。

## 8. 输出位置与运行命令

结果目录：`D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\2026-10-21_B1-B4正式算法_v1`。
保留原仓库源码，第三章文件夹不改。各目录拒绝覆盖。

```powershell
python run_chapter2_formal_simulation.py smoke --output <新目录>/smoke
python run_chapter2_formal_simulation.py formal --smoke-manifest <新目录>/smoke/study_manifest.json --output <新目录>/formal
python run_chapter2_formal_simulation.py sensitivity --smoke-manifest <新目录>/smoke/study_manifest.json --output <新目录>/sensitivity
python run_chapter2_formal_simulation.py run --cache <缓存>/inputs --variant S4 --output <新预测目录>
python run_chapter2_formal_simulation.py evaluate --prediction <预测>/prediction.json --references <评价>/references.json --trial-manifest <评价>/trial_manifest.json --simulation --output <新评价文件>.json
python run_chapter2_formal_simulation.py materials-check
python -m dmf.chapter2_sim.formal_plotting <新目录>/formal <新目录>/figures --sensitivity <新目录>/sensitivity --qa-scripts <已安装科研绘图QA脚本目录>
python scripts/package_chapter2_formal_results.py <新目录>
```

原始输出包括逐tick truth、逐帧、逐事件、逐trial和配对差CSV；共同缓存Mask/摘要、独立reference/trial manifest、配置/地图快照、seed与版本/dirty源码摘要、依赖信息。
已生成16张图，每张保存SVG、PDF、600dpi PNG、图注与布局/文字碰撞审计；全部标题标SIMULATION。
轨迹和状态图使用预先指定normal/261000/C_formal单次试验（展示n=1，不代表20次平均）；其余统计图保留全部七场景与配对seed。
16份PDF文字均可审计，最小字号6或7pt，无低于5pt文字；碰撞审计全部0失败/0警告。16张均为单坐标轴，对齐审计为NOT APPLICABLE，不冒称多面板对齐通过。
绘图源码预检20通过、1警告（提供PNG而非TIFF）；本次交付面向论文草图，SVG/PDF为矢量主文件，不宣称满足特定期刊生产格式。
排版修复前的自有草稿保留于figures_draft_1，不作最终论文图使用；最终图仅取figures。
最终交付由打包程序逐一核对原始摘要、全部Mask、预测CSV/JSON、独立评价及汇总、图集合与QA，再生成algorithm_source_snapshot.zip和result_manifest.json。
最终打包已实际成功（exit0）：55份源码快照、41,342份输出文件SHA256；smoke126/147、formal840/980、sensitivity180/0的父子身份/种子/配置与旧摘要核对通过。
源码ZIP为本轮算法及关联模块快照，不是整个上位机仓库备份；原完整仓库和全部未提交成果仍保留原位。结果清单不包含自身摘要，所有后续改动应另立版本，不覆盖本包。

## 9. 回归与材料缺失

最近一次全量：546项测试，545通过、1跳过（211.773s；与正式批次同时运行），包含新增打包回归；编译通过。之后仅调整两张图的标题间距，绘图2项与打包7项再次通过。
七条独立控制链move/mix/split/loop/CSE/ZJU/CSC通过。PyTorch/Python3.14弃用警告与原有FFmpeg跳过不隐藏。

缺失：当前配置的真实U-Net权重、已审核人工到达参考、独立验证的真实地图、真实时序/指令日志与实物闭环证据。
软件夹具与仿真Mask不充当这些材料；不报告真实分割IoU、真实五状态准确率或实际液滴运动精度。

后续真实评测入口：用冻结U-Net/共同Mask缓存、相机/地图绑定与人工给定任务段；两名盲于算法输出的标注者独立给到达区间、遮挡/不确定/右删失状态，保存原始意见与仲裁来源。
人工参考不得由eta/位置/稳定窗阈值自动产生。参考先锁定再运行S1–S4，按视频/批次分组，禁止同一序列泄漏到调参和正式评测两侧。

下一步研发建议：先研究源准备与运输确认分离的接口及抖动容忍规则，另立版本/冻结方案再测试；增加经真实数据支持的非圆形Mask误差、低帧率/长断档与独立标定地图；保留本批次全部失败结果作为基线。不得据本仿真直接开展高压实物实验。
