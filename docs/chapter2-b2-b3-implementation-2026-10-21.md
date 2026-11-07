# 第二章 B2+B3 改造记录

日期：2026-10-21。基线 HEAD：`fe9699d7e6867ee8897056b122c8248153cadd3e`，历史参考 `e198777`。
以当前实际工作区的 B1+B4 与独立 simulation 未提交成果为基线，不还原、不覆盖、不 commit/push。

## 1. 完成范围与边界

B2已实现软件任务因果、SDK身份/时钟保留、精确APPLIED软件接收stamp、一次性到达事件和分段日志。
B3已实现双分母面积、有向进展/横偏/方向速度、统一实测中心、目标位置门和地图/ROI质量验证。
五状态、合法跨状态跳转、有限Retry/局部Recovery与正式5帧/0.25s门保留；没有新增全局规划。

未改GUI/controllers、U-Net segmenter、MVS硬件适配器、STM32协议/AM刷新/固件、第三章规划；
独立 `dmf/chapter2_sim`、配置、CLI和测试未改。本轮开始记录的39份保护文件SHA256核对无变化。
共享几何模块按B3修改，所以simulation对共享模块的兼容性另由已有33项仿真测试回归，而非假定不受影响。

基线检查发现12个已修改的tracked文件及一批B1+B4/simulation未跟踪文件，全部保留。
开始前114项B1+B4/runner/录像/仿真相关测试全部通过。本轮没有重建独立仿真或启动批量参数扫描。

## 2. 实际修改文件与接口

| 文件 | 本轮增量 |
| --- | --- |
| `dmf/vision/contracts.py` | 可选FrameTiming；capture_identity、timestamp_clock_domain；DropletFeatures尾部追加新几何字段 |
| `dmf/experiment/evidence.py`（B1已有未跟踪文件上叠加） | StepContext、ArrivalEvent、ArrivalEventLedger、FrameAssessment、FrameCausalityGuard；窗口保存证据帧ID |
| `dmf/experiment/sources.py` | 实时SDK/raw/host元数据透传、最新队列覆盖数；录像绝对接收戳与相对锚点保留 |
| `dmf/experiment/actuator.py` | observer旁路捕获APPLIED接收stamp/request ID；CommandResult追加真实ACK、通信重试和simulated字段 |
| `dmf/experiment/runner.py` | 显式run/step/attempt/epoch、旧帧守卫、到达消费、新旧任务命令关联、分段耗时与质量快照 |
| `dmf/experiment/logging.py` | 保留旧列，schema v2追加字段；新增arrivals/latencies表与schema说明 |
| `dmf/vision/features.py` | RegionOverlap、region_overlap、TransportProjection、transport_projection；按源/目标缓存mask |
| `dmf/experiment/perception.py` | 输出rho/投影/横偏/方向速度、目标位置门；SDK/视频/时钟历史隔离 |
| `dmf/experiment/policy.py` | B1进展保护优先用有向progress_mm，保留旧距离兼容路径 |
| `dmf/vision/calibration.py` | 四角/单应矩阵校验，严格ROI边界与for_roi平移 |
| `dmf/vision/electrode_map.py` | 实测override的mm几何/中心统一，polygon验证、帧尺寸检查、quality_manifest |
| `dmf/vision/config.py` | 地图/ROI/尺寸与独立审核点加载、hash/version/误差分组、保存时保留审核参考 |
| `configs/chapter2_experiment.yaml` | 仅更新progress_epsilon注释，不改阈值 |
| `tests/test_chapter2_causality.py`（新增） | 28项B2软件回归 |
| `tests/test_chapter2_geometry.py`（新增） | 21项B3手算/几何/质量回归 |
| 文档 | 本记录、experiment说明、implementation-status、原整改方案进度、B1+B4历史记录链接、本轮执行计划 |

旧FramePacket的5个位置参数、旧Observation位置参数和CommandResult原字段继续有效。
正式PriorFeatures总输出目标位置布尔值；旧手工Observation未给新字段时兼容旧行为，不能据此声称新位置门已检查。
原 `coverage_for_region`、FrameRecord/通用baseline CSV未换分母或偷换单位。

## 3. B2因果和时间语义

- `StepContext(run_id, step_index, attempt_index, epoch, source_id, target_id, ...)`：每个被接受的Start/Update/Retry/Recovery产生新epoch；运输Retry增加attempt，Update重置下一step的attempt。Recovery累计上限不清除。
- `ArrivalEvent.from_window(...)`：只可由已确认且归属于同context的窗口构造，ID由run/step/attempt/epoch/证据帧确定。ledger拒绝旧epoch、重复event或同step的第二次消费。相同源目标对在不同step不混淆。
- `SerialTransport._observe_transaction`：复用既有事务observer匹配request和sequence，采用ACK进入PC时的monotonic/perf_counter stamp，不用execute返回代替。仍发送原BEGIN/SET/COMMIT，仍同sequence最多两次通信重试。
- `applied_receive_ns`只存真实ACK；`software_barrier_ns`和`applied_time_quality`区分真实接收、旧transport返回估计和非硬件模拟接受。offline/dry_run不创建transport，也不填真实ACK。
- 主机接收晚于ACK只是软件屏障。缺曝光映射标`causality_unknown`；已知曝光早于屏障拒绝。显式同域映射可标`exposure_order_verified`，但并不证明设备映射校准或高压应用时刻正确。
- 当前MVS无经过验证的曝光映射；`physical_timing_validated`始终false。SDK/device raw ticks不猜频率，UTC不做控制差值，simulation时间不冒充host clock。
- 离线视频/录像相对域独立于本次主机计时。不同视频即使都叫video_relative也没有共同原点：运行中源切换立即Stop，不改变原任务运输时长；速度历史同时按video/domain隔离。

新增 `arrivals.csv` 保存证据首尾帧/时间、确认主机时刻、context、消费状态与三类重试计数；
`commands.csv`同时保留因果帧context和拟请求的下一context，ACK失败不激活该拟请求epoch。
下一步ACK失败时保留本步视觉成功，并单列下一步命令失败；不会抹去成功或重复推进。

`latencies.csv`区分接收→ingest（含转换/队列等待）、ingest准备、分割、特征、决策、事务、请求→APPLIED接收、写图和含写图总耗时。
缺戳留空，同域才相减；离线文件旧接收时间不减本次处理时间。`pipeline_ms`旧含义仍是不含图像写盘。
日志同步flush、callback及操作系统调度不是物理控制延迟；正式P50/P95/P99汇总/单位时钟adapter尚未实现。

## 4. B3几何定义与验证

同一交集I、液滴面积Ad、电极栅格面积Ae计算eta=I/Ad、rho=I/Ae。
手算I=75、Ad=100、Ae=400，得到eta=.75、rho=.1875。空液滴/空电极/裁剪电极显式质量错误；
完整Ae未知时rho留空，不填0。仍保留原OpenCV包含边界的栅格化，因此相邻区域边界像素可能共享，eta之和不保证严格等于1。

方向单位向量u=(target-source)/|target-source|，progress=(point-source)·u，fraction=progress/步长；
lateral为二维叉积的带符号垂距，parallel velocity为可信前后位置投影差/同域时间差。反向为负，横移不能重置有向进展保护。
实测center_mm由实际polygon的像素中心映射得到，polygon_mm也由实际polygon映射；通用extractor与实验Prior不再混用模板中心。

Arrived位置门采用实际目标polygon及已有position_tolerance_mm；没有未经真实数据标定的新rho或额外中心距离硬阈值。
正常方向/总速度仍基于声明的采样时钟：host receive是接收间隔估计，FPS fallback是未验证播放时间，不能报告真实曝光速度。

校验有限/有序/凸/非退化四角、正pitch、可逆/有限homography、projective horizon、合法简单override polygon；
拒绝分数grid维度/布尔pitch，保留非规则外围模板和420编号。
可选image_size_px声明后运行帧必须匹配；ROI须有参考图大小与坐标声明，整图坐标会同时平移corners/overrides/审核点。
旧地图无尺寸仍兼容，但质量记录明确未绑定图像尺度，不能自动当成有效标定。

`map_quality.json`记录map hash/version、观察/声明图尺寸、ROI、pitch来源、有效范围、template/calibrated来源。
外部validation_points可按center/edge给独立检查点及reference_mm，输出count/RMSE/max和预先声明容差比较；
没有点/容差则留空。没有创建审核点、没有改变真实Pilot审核状态，也没有凭这些字段自动标物理标定已验证。

## 5. 反例：修复前 → 修复后

首批B2 15项全部RED；首批B3 15项产生24个失败断言（含参数subtest）。补查的边界也先实际RED，再GREEN。
全部为人工可核算的软件fixture，不是正式真实液滴真值。

| 反例/审查对应 | 修复前证据 | 修复后行为与测试 |
| --- | --- | --- |
| SDK号/raw元数据丢失，T11/T13 | LiveSource只传消费index | SDK号987、原始ticks和接收双时钟透传；重复SDK号即使消费index新增也不累计 |
| 旧帧/跨任务，T11/T12 | 无显式guard/context | ACK前接收/已知旧曝光拒绝；错误task_epoch不触发下一任务 |
| 接收≠曝光，T12/T21 | 无可表达的不确定性 | 接收在ACK后仍causality_unknown；曝光映射缺失不声称物理顺序 |
| 重复事件，T13 | 无事件/ledger | 同step不同event ID也只能消费一次，旧context窗口不能改贴新context |
| 下一步ACK失败，T14 | 视觉成功保护已有，但缺事件/epoch追踪 | 保留前步成功及唯一事件，下一步失败，拟epoch不激活（原行为继续回归） |
| 实际ACK时刻，T21 | execute返回替代接收 | observer延迟5ms后，返回的ACK戳仍等于原received事件；失败命令清除旧stamp |
| 无真实ACK字段 | 模拟accept与真实ACK未明确区分 | offline/dry_run真实ACK空，旧transport估计只作软件barrier |
| 时钟/视频原点 | 跨视频1→1.1s算出1mm/s；切换t=1000抬高运输时长 | 不跨域/跨视频算速度；源切换Stop且原任务时长不被抬高 |
| SDK可用性变化 | SDK1→消费2可拼接旧窗提前Complete | 清窗后至少重新积累完整窗口；各identity来源保留高水位 |
| 不可能曝光/初始源 | 无APPLIED时未来曝光仍可过守卫 | 初始源确认前也拒绝曝光晚于接收 |
| 双分母，T01 | 无rho字段 | 75/100=.75，75/400=.1875；小滴大滴区分 |
| 源残留，T02 | 缺显式交集分析输出 | 独立源25/目标75像素保留eta=.25/.75；显著双连通区域在Prior为Unknown/AMBIGUOUS_MASK，非虚假零残留 |
| 方向/速度，T03/T04 | 只有总速度/目标距离 | 正反/斜向手算一致；不等间隔速度正确；纯横向距离改善不能掩盖停滞 |
| 实测中心，T15 | override目标x=240px仍用模板10.5mm中心 | 实际12mm中心、polygon_mm和两路距离一致 |
| 覆盖高但位置不满足，P1 | 单靠eta可Arrived | 目标位置门false时不Arrived；不增加rho阈值 |
| 地图/ROI，T15 | 全重合/交叉四角可加载，ROI静默改范围 | 明确ValueError；尺寸不匹配拒绝；ROI同移审核点且保存不丢参考 |
| 延迟日志，T21 | 只有pipeline_ms/零散事务表 | 分段表关联run/step/attempt/epoch，不同时间域不减，写图另列 |

调试中两个夹具问题已单独纠正：模拟串口必须按原协议回复SET ACK；重复帧测试的0.3s等待触发了正常B1 Retry，
只延长该夹具等待以测试重建窗，没有放宽生产超时/帧数/性能门限。

## 6. 实际验证与只读复查

- 基线114项：全部通过。
- 最终局部主回归146项：全部通过（含B1+B4、两组新测试、视觉框架/录像时间线）。本批新增49项=因果28+几何21。
- 编译与git diff --check：exit0。
- move/mix/split/loop/CSE/ZJU/CSC独立链路：7/7 PASS，串口协议与扫描模块未改。
- 中间隔离全量474项：473通过、1项DMF_FFMPEG条件跳过，113.333s、exit0。
- 中间同进程全量479项：478通过、1跳过，85.002s、exit0；此前首轮-v曾因Tk后台回收/Tcl_AsyncDelete提前退出，不隐去该失败。
- 最终补查后同进程全量：484项，483通过、1项DMF_FFMPEG条件跳过，88.131s、exit0。随后再次运行新增49项，全部通过（1.740s）。
- 只读复查首先运行因果24/几何17通过；补查发现跨视频原点P2，已由主任务RED→GREEN修复，审查方重新运行两项针对性回归确认修复。

GUI单独5项通过；已有PyTorch3.14弃用提示和Tk after/销毁清理问题不在本轮修复，不能说其已消失。
保护文件与全量状态在收尾再次核对；没有修改固件、连接真实串口、相机或高压。

复现命令（仓库根目录）：

```powershell
python -m unittest tests.test_chapter2_causality tests.test_chapter2_geometry tests.test_chapter2_evidence tests.test_chapter2_policy tests.test_chapter2_runner tests.test_chapter2_evaluation_regressions tests.test_chapter2_event_metrics tests.test_recording_timeline tests.test_vision_framework -v
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -q
python -m validation.closed_loop_chain.run_validation
git diff --check
```

若再次遇到Tk同进程原生回收问题，可逐模块验证同一完整集合（不是删除GUI用例）：

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object {
    python -m unittest discover -s tests -p $_.Name -v
    if ($LASTEXITCODE -ne 0) { throw "Regression failed: $($_.Name)" }
}
```

## 7. 独立simulation结构审查（只读）

| 层 | 实际入口/已存在能力 | 边界 |
| --- | --- | --- |
| 地图 | geometry.SimulationMap复用420地图，保留L形/非规则外围及外部override | 默认归一化pitch模板，不是假定真实mm或独立标定 |
| 运动 | world.DropletWorld.command/advance：模拟APPLIED/响应延迟、有限速度、噪声，Retry可解除首次钉扎，Recovery回源 | 二维点状态代理；无流体/接触角/形变/高压电路物理拟合 |
| 观测 | vision.SyntheticCamera：曝光起止、可配置fps、位置/半径误差、丢帧/突发丢帧、处理延迟/抖动 | 圆形mask代理，不是U-Net、真实相机或运动模糊模拟；曝光采样有dt量化 |
| 闭环 | control.EventPolicy+runner.run_trial：A固定时间、B单帧、C空间+连续窗，旧曝光过滤、有限Retry/Recovery | 与dmf.experiment仍是两份独立实现；不是本批控制器已自动接入simulation |
| 随机 | world SeedSequence([seed,101])按tick，camera [seed,202]按frame；ABC同seed | 相同外部随机环境，不要求不同控制动作下轨迹相同 |
| 真值 | world真实位置盆地+真实速度+独立驻留，runner事件评价读取隐藏真值 | 仅仿真参考，独立于覆盖/识别阈值；不是人工实物标签 |
| 指标 | batch.summarize_trials/paired_differences，Wilson路径率、seed簇bootstrap提前率/连续量/配对差，缺失延迟单列 | 早更新分母含全部计划步，并另列已发Update分母；确认延迟是观测确认条件均值，有删失计数 |
| 测试 | test_chapter2_sim 20、sim_batch 12、sim_plotting 1 | 33项现有软件测试，不是33次实物实验；本轮全量仅测试临时小夹具 |

后续一致性风险：仿真StableWindow对重复帧的“返回False但是否清窗”与B1窗语义有差别，
C组仍使用归一化距离门/走廊，与本批实际目标polygon位置门不完全相同；不能把其历史结果直接改名为B2+B3算法结果。
本轮不为统一接口重写simulation；其共享几何输入在现有回归中兼容，受保护源文件hash不变。

## 8. 下一阶段具体开发入口与门槛

六类场景已存在config.SCENARIOS：normal、delayed、partial_stall、jitter、dropout、deviation；failure为额外失败保护场景。
下一步先围绕`world.py`运动、`vision.py`观测、`control.py/runner.py`闭环建立到本批FrameTiming/StepContext/特征的显式adapter，
simulation clock必须保留独立时间域，归一化pitch到mm须有可信pitch。先做同输入状态/动作一致性和重复/旧帧断窗测试，再重跑预注册配对seed。
正式扫描入口仍为`run_chapter2_simulation.py`/`batch.run_batch`和`run_sensitivity`；本轮未执行批量命令或生成论文图。

S1–S4不要把A/B/C改名：需新建尚不存在的`dmf/experiment/benchmark.py`与离线CLI，复用当前FramePacket、
DropletFeatureExtractor、PriorFeatures、StateRecognizer/EvidenceWindow及event_evaluation。
S1仅当前质心，S2当前eta，S3任务空间/真实地图，S4再加因果连续时序；各组读取冻结的共同mask缓存与人工给定任务段。
先实现GT改变不影响预测、teacher-forced任务段、全分母漏事件、同原视频不得跨split等测试，然后才做正式评测。
正式人工到达参考、真实U-Net、地图审核/同步和像素-mm/时钟评价adapter仍缺，不输出真实准确率或物理控制结论。

## 9. 未验证功能/剩余风险

1. MVS device ticks频率、曝光到host映射、物理电极应用时刻均未验证；当前只有软件ACK/接收链路。
2. 真实模型权重、独立人工Mask/状态/到达区间、真实地图独立中心/边缘误差检查尚未交付，软件初始阈值不能当实测最优值。
3. 旧地图无尺寸/ROI/有效范围时只能兼容加载，不自动证明配准正确；模板外围不升级为实测几何。
4. SDK counter回绕/相机重启保守拒绝，须显式新run；LiveSource异步close/owner交接完整整改仍属原E阶段，本轮不改GUI生命周期。
5. 实验mm日志到通用px/人工事件时钟的正式adapter、S1–S4共同缓存/benchmark和真实延迟分位数报告未实现。
6. Tk同进程回收问题可导致偶发测试原生退出；隔离GUI与其他模块的测试证明各模块可运行，不等于该生命周期问题已经修复。

所有完成状态仅为本地软件功能与回归；不包含真实液滴研究成果。未commit、未push，等待用户审阅。
