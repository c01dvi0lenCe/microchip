# 第二章：单液滴视觉闭环实验模式

本入口使用已有电极地图、标定、特征提取和原子串口协议，新增五状态规则及局部四动作策略。
统一运行 `main.py`，在“第二章单液滴实验”页使用；`run_experiment.py` 保留命令行兼容。
原有离线 baseline CLI、第三章多液滴规划保留；第一章硬件测试页及专属代码已删除。
状态判断全部在 PC 上完成，STM32 只执行电极命令，无需为本模式增加固件状态机。

## 独立正式算法仿真与离线benchmark（2026-10-21）

新入口`run_chapter2_formal_simulation.py`不接管GUI、相机或真实串口，旧`run_chapter2_simulation.py`不变。
C_formal直接复用本模式B1–B4特征/状态/证据/策略，时间/长度明确是simulation秒与pitch，模拟APPLIED不填造真实ACK。
S1–S4与三项消融通过`dmf/experiment/mask_cache.py`共用冻结输入，由独立参考评价；单帧组不伪造五状态。
已运行正式1020次闭环/敏感性和980次离线判定，保存原始CSV/Mask/参数/源码摘要与16张SIMULATION图。
完整命令、版本、回归、失败样本和真实材料缺失见`docs/chapter2-formal-simulation-implementation-2026-10-21.md`。
这些仅是二维合成代理验证，不等于U-Net真实精度、实物到达真值或严格物理因果时序验证。

## 1. 先跑软件示例（无需相机或 AM）

GUI：`python main.py` → “第二章单液滴实验” → “运行离线合成示例（无需硬件）”。
也可选择已有 YAML 配置，再选择模式并开始。右侧显示液滴轮廓/源目标/状态动作，
左侧显示帧号和控制决策。停止按钮以及关闭窗口都会请求停止并等待输出释放、日志保存。
GUI 为每次运行建立独立时间戳目录，可通过“打开结果目录”查看。

原有“仿真/实物”开关只用于手动电极和路径页；实验页用自己的三种模式，并隐藏该旧开关。
开始实验前需关闭手动串口连接。运行期间手动/路径页和相机预览入口锁定，避免争用设备。

在仓库根目录运行：

```powershell
python scripts/create_chapter2_demo.py --output results/chapter2-demo
python run_experiment.py --config results/chapter2-demo/transport.yaml
python run_experiment.py --config results/chapter2-demo/recovery.yaml
```

第一段视频演示连续两步运输；第二段演示超时重试、偏离和局部恢复，最后可因恢复上限而保护停止（退出码 1）。
示例采用明确标注 `synthetic_test_only: true` 的阈值分割，以确定性图像检验规则、动作和日志。
它不是 U-Net 实验，也不能据此报告真实五状态准确率。正式三种模式都采用已训练 U-Net；
threshold 仅在上述离线合成测试标志开启时允许使用。
输出目录已有日志时拒绝覆盖；重复运行应在 YAML 中指定新目录。

## 2. 正式配置与运行

复制 `configs/chapter2_experiment.yaml`，所有相对路径相对于配置文件目录解析。
替换 `electrode_map.yaml` 中的真实四角坐标和电极间距；图像必须与标定坐标一致。
ROI输入须显式声明参考图像、偏移及局部坐标，不能将整图地图直接用于裁剪帧（见B3说明）。
`route` 为人工给定的相邻核心电极 ID 序列，如 `[190,191,192]`，本模块不进行路径规划。
初始源电极须经过视觉确认才能首次激活目标；最后一个目标确认到达后结束任务。

| 模式 | 输入 | AM 串口行为 |
|---|---|---|
| offline | `source.video` | 不创建串口对象；按视频 PTS/FPS 推进时间 |
| dry_run | OpenCV 相机或 SDK 插件 | 生成相同目标命令并记录，绝不创建 AM 串口 |
| experiment | 同一实时相机接口 | 明确启用后发送事务，等待 `APPLIED` |

```powershell
python run_experiment.py --config configs/chapter2_experiment.yaml --mode offline
python run_experiment.py --config configs/chapter2_experiment.yaml --mode dry_run
python run_experiment.py --config configs/chapter2_experiment.yaml --mode experiment
```

每次运行使用独立 `experiment_id` 和 `output_dir`。启动明确打印 MODE 和 AM 是否启用。
experiment 另需 `enable_am_output: true`、`calibration_confirmed: true`、有效 `serial.port`。
默认均不启用；当前代码没有实际相机或高压实验通过的证据。

### U-Net 模型

支持导出的 ONNX（`backend: onnx`）或 TorchScript（`backend: torchscript`）。
按所选后端安装 `onnxruntime` 或 `torch`，不要求同时安装；既有依赖见 `requirements.txt`。
输入为 RGB、NCHW float32，默认除 255 后按 `mean/std` 归一化并调整为 `input_size`。
输出须为 `[1,1,H,W]` 二值分割 logits 或 probabilities；多分类输出需先导出为二值模型。
配置 `output` 决定是否执行 sigmoid；输出插值回原图后按 `threshold` 二值化。
模型和训练预处理必须匹配。缺少模型文件即报错，不静默回退到阈值算法。
本改造不训练 U-Net，不增加分类网络，也不创建虚假的训练权重。

### 相机

OpenCV 可识别的工业相机用 `source.backend: opencv` 和 `device`。
厂商专用 SDK 使用 `backend: plugin` 与 `factory: module_name:open_camera`；工厂接收
`source.parameters` 字典，返回含 `read(timeout_s)` 和 `close()` 的对象。
`read` 必须返回新的 H×W×3 uint8 BGR 帧；SDK 应启用其自身超时和丢弃旧缓存能力。
采集工作线程使用单帧最新值队列，主循环具有 `frame_timeout_s` 超时；不接受积压旧帧。
`timestamp` 是主机接收时间的 monotonic 秒，不宣称是相机曝光时间。
MVS取流保存GetImageBuffer成功返回时的接收时间（在颜色转换前）；其他插件未提供该元数据时，
继续使用read返回时的主机时间。新录像逐帧时间表可用于offline回放；详见`docs/camera-dataset.md`。
SDK 插件须保证 read/close 有界；未提供厂商 SDK 时不能声称已连接该相机。

本机 Hikrobot MV-CS200-10UC 的原始取流预览配置位于 `configs/camera_mvs.yaml`。
在旧界面的“实物”模式点击“开启预览”即可验证 USB3/MVS 连接；这只显示原始图像，不运行 U-Net、
不控制电极，也不代表实验已开始。MVS 客户端正在实时取流时，请先停止其取流，再由上位机独占打开相机。
MVS SDK `MvImport` 目录通过配置中的 `sdk_python_path` 指定；若 SDK 安装位置变化，更新该项。
实物预览时可在“视觉反馈”旁使用“开始录像/停止录像”，视频自动保存到
`D:\I\ZJU\有源矩阵\视觉-工业相机\视频`，格式为 MVS SDK AVI；“拍照”将当前全分辨率帧保存到同级`照片`目录，格式为 PNG。
若目标文件已存在，上位机会自动追加 `_001`、`_002` 等编号，不覆盖旧录像或失败残留文件。
录像逐帧送入 SDK、拍照文件写入都在后台线程执行，界面异步轮询完成状态；预览队列仍只保留最新帧。
关闭预览会在后台请求停止录像并封装文件。录制帧率受相机实际输出及主机磁盘/USB3性能限制，
开始实验前建议先短录并检查 AVI 是否能正常播放及帧率是否满足需要。
新录像同目录同时保存`.timestamps.csv`、`.electrodes.csv`、`.frame_electrodes.csv`和
`.recording.json`。AVI标称播放帧率与接收节奏分开保存，不再用播放时间替代真实接收间隔。
停止录像会核对帧数并完成电极状态对齐；队列溢出/写入失败会标记不完整，关闭窗口会等待后台保存。
第二章experiment另保存`electrode_events.csv`，记录串口发送及实际接收ACK时刻；
原`commands.csv`中的时间是触发决策的帧时间。offline/dry_run不会生成真实硬件事件。
后续 Chapter 2 `dry_run` 可将同一 `factory` 和 `parameters` 配置复制到所选实验 YAML 的 `source` 下，
但仍须准备正式 U-Net 模型后才能运行完整视觉实验。

### AM 和停止

复用 `BEGIN/SET/COMMIT` 和 `ACK:<id>:APPLIED`。成功 ACK 仅代表电气应用，不代表液滴到达。
启动先确认 `ALL_OFF`，建立已知释放状态；然后只切换当前源/目标所需的电极。
Retry 使用新事务号重新声明同一目标电极为开启，不通过 ALL_OFF 反复脉冲。
通信重试最多两次、沿用同一事务号；它与液滴运输的 `N_r` 完全不同。
Hold 无串口写入。退出、异常和完成时均尝试 `ALL_OFF`，并记录释放 ACK 是否成功。
Ctrl+C 或创建 `emergency_stop_file` 指定文件可触发软件停止；停止受当前采集/ACK 超时约束。
软件停止不能替代实验台的独立硬件急停。串口断开时不能保证释放命令已被执行，日志会标记失败。

## 3. 配置阈值与判别顺序

示例阈值仅为占位，实验前须以 Pilot 数据标定。

| 配置项 | 含义 |
|---|---|
| `v_th_mm_s` | 静止速度阈值 |
| `eta_enter / eta_arr / eta_release` | 跨入、到达、释放的面积占比阈值 |
| `candidate_electrodes` | 当前源/目标之外额外允许的局部候选电极 |
| `position_tolerance_mm` | 候选区域和一步运动的边界容差 |
| `max_speed_mm_s / prediction_tolerance_mm` | 速度上界及历史位置预测容差 |
| `history_max_gap_s` | 历史过久后重新初始化速度/预测，首帧速度留空 |
| `consistency_frames` | 普通状态连续确认帧数 |
| `arrival_frames / arrival_duration_s` | 到达确认帧数与最短持续时间（默认 5 帧、0.25 s） |
| `evidence_max_gap_s` | 连续证据允许的最大观测间隔；超过后重新累计 |
| `arrival_max_centroid_span_mm / arrival_max_coverage_span` | 到达/源确认窗口的质心和覆盖波动上限 |
| `deviation_frames` | 持续空间偏离所需帧数，至少2帧；时序冲突不直接判Deviation |
| `wait_s / max_retries` | 朝目标无净进展的等待时长及允许的运输重试次数，不再只检查Stationary |
| `attempt_timeout_s / progress_epsilon_mm` | 每次尝试硬时限及目标距离净减少阈值；有进展也不能无限尝试 |
| `source_frames / source_duration_s` | 初始/恢复源位置确认门限 |
| `recovery_timeout_s / max_recoveries` | 局部恢复等待时限及每步最大恢复次数 |
| `no_detection_timeout_s` | 无可靠 mask 的最大等待时间 |

无可靠mask→Unknown/invalid；时间预测不符、重复/逆序观测→Unknown/conflict；
单次空间偏离先Unknown，持续有效空间偏离且时间合理才确认Deviation。
正常几何依次检查Arrived、Partial、Stationary/Moving，允许合法跨状态跳转，不强制经过Partial。
候选变化、无效帧、时间/帧号冲突、长gap、任务/尝试切换均重建证据，避免沿用旧Arrived。
Arrived和初始/恢复源确认共用连续窗口，检查唯一帧、首尾时间、最大间隔与窗口稳定性。
单个 mask 若有多个显著连通区域则拒绝，不把它解释为多液滴任务。
空间/时间不一致的观测保留作 Deviation 证据，但不写入预测历史。
当前预测只用之前已接受的至多两个位置按真实时间间隔外推，不读取未来帧。
接受Start/Update/Retry/Recovery后也会清预测历史。B2优先使用SDK捕获号，缺失时保留旧帧号接口；
身份来源切换会重建窗口。该唯一性检查不等于曝光因果证明，详见B2说明。

正式offline/dry_run/experiment配置不得低于5帧/0.25s的到达/源确认门。
只有显式`synthetic_test_only: true`的非experiment软件fixture允许缩短门限；
即便开启该标记，experiment仍不能降低门限。直接构造的低门限单元测试不是正式控制配置。
最大gap过小时低帧率会持续证据不足，不会自动降门；这些新增值仍为待Pilot验证的软件初值。

## 4. 动作与计数器

- Moving/Partial→Hold：有进展且未超过时限时保持当前驱动。
- Arrived→Update：将视觉确认目标记为下一步源位置，并切换下一目标；最终目标返回 Complete。
- 确认Deviation→Recovery：激活最近确认源电极，等待源占比和连续帧确认，再重新激活原目标。
- Stationary/Moving/Partial及可靠但标签未稳定的Unknown，均受净进展和最长尝试时限约束；达到界限且`N_r<N_max`→Retry，否则→局部Recovery/保护停止。
- 观测质量持续不足→保护停止，而不是自动转成真实Deviation。无可靠mask的原保护也保留。

B3优先使用源→目标方向上的有符号进展（mm），要求超过历史最佳值至少`progress_epsilon_mm`；
来回抖动或纯横向接近不能反复刷新进展计时。旧Observation缺投影时保留负目标距离兼容路径。

Retry 命令成功接受后才 `N_r += 1`，同时重启本次尝试计时；通信失败不递增，不推进策略状态。
成功 Update 清零下一步的 `N_r`。Recovery 进入时不清零，视觉确认回到源位置、重新开始尝试后清零。
恢复后的首次重新激活记录为 Retry，`reason=recovery confirmed`，表示新尝试的起点而不是已超时重试，
其 `N_r=0`；累计 `retry_total` 仍记录这次重发。`recovery_total` 跨该步恢复保留，防止反复清零形成无限恢复。
Start、Complete、Stop 为生命周期事件；实际运输动作仍只有 Hold、Update、Retry、Recovery。

## 5. 输出与验收边界

- `frames.csv`：全部要求的逐帧字段，额外包括置信检查结果、阶段、错误、动作原因和耗时。
  centroid/distance/velocity 分别以 mm、mm、mm/s 记录；area 为前景像素数；occupancy 分母为液滴 mask 面积。
  B1仅追加`observation_quality`、`state_reason`、`progress_status`，旧列保留；进展状态记录决策时值，不被accept后的计时重置覆盖。
- `steps.csv`：每步起止时间、运输时间、成功与否、累计重试/恢复次数、最终状态。
- `commands.csv`：命令 ID、目标变更、是否发送、是否被接受及异常；离线和 dry-run 的 accepted 是模拟接受。
- `config_snapshot.yaml`、`electrode_map_snapshot.yaml`、`model_sha256.txt`：本次参数和模型版本。
- `summary.json`：完成/未完成/停止/错误及原因。
- 可选 `raw/`、`mask/`、`overlay/`：原图、二值 mask、轮廓/质心/源目标/状态动作叠加图。

图像落盘在实验线程同步完成。GUI 使用单个最新帧槽、最多约 10 Hz 的预览，
不积压每帧消息，也不在后台线程操作 Tk。实时实验可关闭 raw/overlay 减少存储延迟；
CSV 的 `pipeline_ms` 记录分割、判别及命令过程，不含后续图像写盘耗时。
离线视频是不可反作用的回放，控制命令只是假设输出；不能把回放中的 Recovery 成功视为实际控制因果验证。

## 6. 新增文件与兼容性

`dmf/experiment/` 的 config、perception、policy、segmenter、sources、actuator、logging、runner
各承担一个职责；`run_experiment.py` 是 CLI；`scripts/create_chapter2_demo.py` 生成演示视频；
`tests/test_chapter2_*.py` 验证状态、策略、模式隔离、时序和日志。
GUI 已接入同一引擎；本地规划线程、相机计算和界面性能优化已合并，保留最新手动原子事务及阵列显示。
无需切换到另一个项目目录启动。固件文件未修改。

验收 A/B/C 先由合成视频和接口测试验证软件链路。真实离线视频的五状态准确率、实际 U-Net
效果、厂商 SDK 和 AM 高压实验仍需模型、标注视频、地图标定与硬件提供后验证。

## 7. B4研究评价接口（2026-10-20）

通用`evaluate_results`仍读取px单位frame-results CSV，不接受实验`frames.csv`的mm字段，
包括只有表头的文件也拒绝。它以完整参考CSV为主表：缺预测/空mask/检测失败作为空预测计入
分割分母，非空路径对应文件缺失直接报错；重复video/frame键报错。调用方须提供完整已审核参考清单。

五类确定GT全部计入state指标，Unknown是预测列，另记不确定GT数；
`conditional_five_class`只是去掉Unknown预测后的条件指标，不能替代完整分母结果。

新增纯函数`dmf.vision.event_evaluation.evaluate_events(predictions, references, trial_manifest)`。
完整trial/计划step清单提供主分母；参考要求人工来源、reviewed、provenance、任务和时钟身份。
人工到达区间[L,U]前的确认算提前，区间内算时间不确定，区间后给延迟[t-U,t-L]。
无事件、重复确认、可判读未到达、遮挡、不确定和右删失分别统计；缺参考不会删除失败运行。
此处没有自动CSV单位/时钟适配、正式GT生成器或S1–S4评测CLI。
接口和逐问题回归见`docs/chapter2-b1-b4-implementation-2026-10-20.md`。

## 8. B2任务因果与时间日志（2026-10-21）

FramePacket旧5参数构造保留，尾部可选FrameTiming透传SDK帧号、原始device/SDK host ticks、
主机monotonic/perf_counter/UTC接收戳、录像相对时间锚点、队列覆盖数及时间质量。
设备ticks频率未知时不转换为秒；UTC不用于控制间隔。SDK号回绕/重启目前保守拒绝，须新建run。

StepContext明确run/step/attempt/epoch/source/target/phase；Start/Update/Retry/Recovery被接受后才
创建新epoch，Retry增加attempt，Update进入下一step并将attempt重置。Recovery后重发仍保留
该step的累计恢复/运输Retry计数。无元数据旧调用保持接口兼容，但标legacy_unverified。

真实SerialTransport旁路包装既有transaction observer，获得匹配APPLIED ACK的软件接收双时钟和
request ID；发送/通信重试协议未改。`applied_receive_ns`只存真实ACK，dry_run/offline保持空。
旧transport缺ACK戳时仅记录`software_barrier_ns`与`command_return_estimate`，不冒充实测。
offline控制时间为声明的视频/录像相对域，跨域帧停止；不能用其绝对原始录像戳与本次主机时钟相减。

旧接收帧、重复SDK号、错误task_epoch、已知APPLIED前曝光不能进入确认窗。接收晚于APPLIED但
曝光未映射时允许既有软件接收屏障流程，明确标`causality_unknown`，不能称严格物理时序验证。
仅显式同域曝光映射可标`exposure_order_verified`；目前MVS未提供该映射，summary始终声明
`physical_timing_validated: false`。模拟时间不直接传入实时host-monotonic控制入口。

ArrivalEvent记录证据首尾帧/时间、确认主机时刻及完整context；ledger仅消费当前epoch且每run/step一次。
下一目标ACK失败保留本步视觉成功，另记下一步命令失败，不激活下一epoch；旧源目标对再次访问按step区分。

新增`arrivals.csv`与`latencies.csv`，旧frames/steps/commands列保留并追加字段，schema见`log_schema.json`。
记录接收→ingest队列等待、分割、特征、决策、事务、请求→APPLIED接收、图像写盘以及含写盘总耗时。
各差值只在同域计算；缺戳留空，不能填0。`pipeline_ms`仍不含图像写盘，CSV同步flush等开销可见于总耗时。
运输Retry、Recovery与同序列通信重试分别关联step/attempt/epoch；commands另区分因果帧context与请求的新context。

## 9. B3几何与地图质量（2026-10-21）

- eta_source/eta_target仍为交集像素数/液滴面积。rho_target为同一交集/完整目标电极像素面积；
  空分母、裁剪电极等质量问题显式记录，rho未知留空。旧coverage_for_region接口含义不变。
- 输出progress_mm、progress_fraction、带符号lateral_error_mm与velocity_parallel_mm_s。
  距离/方向统一使用region.center_mm；实测override中心由实际像素多边形中心映射，polygon_mm也同步实际形状。
- Arrived除原覆盖和连续窗外，必须满足实际目标多边形及现有position_tolerance_mm位置门。
  不新增rho硬门；手工构造的旧Observation未提供新位置字段时保留旧API兼容，正式PriorFeatures总提供布尔结果。
- 电极mask按图像尺寸/ID缓存，仅计算当前源/目标。保留OpenCV既有包含边界的栅格化，邻接边界共享像素
  可能使eta_source+eta_target略大于1；不偷偷更换原定义。rho是栅格面积，不是未经验证的物理润湿面积。
- 速度使用声明时间源的间隔，首帧/冲突/长gap无可靠速度。host_receive只有接收间隔速度估计，
  FPS回退时间不是实测曝光时间；clock domain或视频变化不跨域计算速度。

直接加载现在拒绝退化/翻转/交叉/非有限四角、非法pitch、奇异/非有限单应矩阵、退化/自交override。
地图可选`image_size_px: [width,height]`，声明后运行时必须匹配；旧地图缺尺寸时仍兼容，但不证明标定有效。
ROI地图须声明`roi: [x,y,w,h]`、`reference_image_size_px`及`coordinate_frame`。
`full_frame`会把四角、override和独立审核点一起平移；`roi_local`表示已平移，不重复减偏移。
独立Roi.crop现在拒绝越界，不再静默裁成另一幅图；如确需裁剪策略，应显式调用旧clamp_to_frame。

`map_quality.json`保存map SHA256/version、图像尺寸/ROI、pitch来源/有效范围、每区域template/calibrated来源。
可选validation_points读取外部独立审核点（pixel_px、reference_mm、location=center/edge、independent），
按组报告count/RMSE/max和外部声明容差；缺点留空，不生成审核点或自动宣称物理标定通过。
模板外围形状继续保留；外围作为候选仍要求实测polygon，本模式运输仍限相邻核心电极。

完整反例、回归、simulation结构审查和后续开发入口见
`docs/chapter2-b2-b3-implementation-2026-10-21.md`。未训练模型、未造人工标注、未进行高压实验。
