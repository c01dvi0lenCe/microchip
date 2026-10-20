# 第二章：单液滴视觉闭环实验模式

本入口使用已有电极地图、标定、特征提取和原子串口协议，新增五状态规则及局部四动作策略。
统一运行 `main.py`，在“第二章单液滴实验”页使用；`run_experiment.py` 保留命令行兼容。
原有离线 baseline CLI、第三章多液滴规划保留；第一章硬件测试页及专属代码已删除。
状态判断全部在 PC 上完成，STM32 只执行电极命令，无需为本模式增加固件状态机。

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
替换 `electrode_map.yaml` 中的真实四角坐标和电极间距；图像必须为与标定一致的完整画面。
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
| `wait_s / max_retries` | 单次尝试等待时长及允许的运输重试次数 |
| `source_frames / source_duration_s` | 初始/恢复源位置确认门限 |
| `recovery_timeout_s / max_recoveries` | 局部恢复等待时限及每步最大恢复次数 |
| `no_detection_timeout_s` | 无可靠 mask 的最大等待时间 |

无可靠 mask→Unknown；候选邻域或时间连续性不满足→Deviation；随后依次检查 Arrived、
Partial、Stationary/Moving。判据刚切换且尚未满足连续帧数时输出 Unknown/Hold，避免沿用旧 Arrived。
单个 mask 若有多个显著连通区域则拒绝，不把它解释为多液滴任务。
空间/时间不一致的观测保留作 Deviation 证据，但不写入预测历史。
当前预测只用之前已接受的至多两个位置按真实时间间隔外推，不读取未来帧。

## 4. 动作与计数器

- Moving/Partial→Hold：保持当前驱动。
- Arrived→Update：将视觉确认目标记为下一步源位置，并切换下一目标；最终目标返回 Complete。
- Deviation→Recovery：激活最近确认源电极，等待源占比和连续帧确认，再重新激活原目标。
- Stationary 超时前→Hold；超时且 `N_r<N_max`→Retry，否则→Recovery。

Retry 命令成功接受后才 `N_r += 1`，同时重启本次尝试计时；通信失败不递增，不推进策略状态。
成功 Update 清零下一步的 `N_r`。Recovery 进入时不清零，视觉确认回到源位置、重新开始尝试后清零。
恢复后的首次重新激活记录为 Retry，`reason=recovery confirmed`，表示新尝试的起点而不是已超时重试，
其 `N_r=0`；累计 `retry_total` 仍记录这次重发。`recovery_total` 跨该步恢复保留，防止反复清零形成无限恢复。
Start、Complete、Stop 为生命周期事件；实际运输动作仍只有 Hold、Update、Retry、Recovery。

## 5. 输出与验收边界

- `frames.csv`：全部要求的逐帧字段，额外包括置信检查结果、阶段、错误、动作原因和耗时。
  centroid/distance/velocity 分别以 mm、mm、mm/s 记录；area 为前景像素数；occupancy 分母为液滴 mask 面积。
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
