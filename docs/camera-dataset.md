# 工业相机数据整理

目前Pilot包位于`D:\I\ZJU\有源矩阵\视觉-工业相机\单液滴数据集_20261014`。
拍摄日期为2026-10-13，9段原录像保留在相邻`视频\2026-10-13`目录。
21段固定ROI移动/拉伸短片及63张待标注关键帧可用于初步离线分析，不能称为已经标注或训练完成的数据集。

`scripts/prepare_camera_dataset.py`只做离线素材筛查和剪辑，不连接相机、串口，不修改第二章规则和规划算法。
scan筛查的黑色连通区及轨迹不是U-Net输出或GT，必须显式接受候选后才能export。
输出拒绝覆盖，原视频在每个处理阶段核对SHA256；原帧率与ROI偏移写入manifest。

```powershell
python scripts/prepare_camera_dataset.py scan --media "D:\I\ZJU\有源矩阵\视觉-工业相机" --output "新的复核目录" --ffmpeg "ffmpeg.exe的完整路径"
python scripts/prepare_camera_dataset.py export --output "复核目录" --selection "复核目录\selection.json" --ffmpeg "ffmpeg.exe的完整路径"
python scripts/prepare_camera_dataset.py preview --output "复核目录" --ffmpeg "ffmpeg.exe的完整路径"
```

当前筛查ROI/阈值只适配本批Pilot的构图和暗色目标，不作为普遍默认视觉参数。
先确认实际画面，再为新拍摄批次调整筛查范围；正式状态阈值仍由实验YAML管理。

分析用MKV是无损FFV1/BGR0，观看用MP4为有损H.264。两者用途分开，原长视频始终保留。
Mask、源/目标电极和五状态必须独立标注；所有split初始unassigned。
训练/验证/测试按原视频或批次分组，不按短片随机划分，避免相邻帧泄漏。

现有视频没有逐帧设备/采集时间戳，而且文件记录时间跨度与容器播放时长不一致，
所以不能将容器fps当作真实运动时钟。允许初步像素轨迹与形态检查，真实速度与控制延迟需要补充时间数据。

上位机新拍摄输出按日期保存；停止实验/录像并重启后生效。

## 新录像的时间与电极记录（2026-10-14）

重启上位机后，在实物模式开启预览和录像，再进行手动电极操作；停止录像后，
同一个`视频\YYYY-MM-DD`目录自动保留AVI及以下同名文件：

- `.timestamps.csv`：从0开始的视频帧索引、SDK帧号、原始设备/SDK主机计数、
  电脑收到缓冲区的monotonic及高精度perf_counter纳秒、UTC纳秒、可读UTC/本地日期时间、相对接收秒数。
- `.electrodes.csv`：录像起始已确认状态、事务请求、BEGIN/SET/COMMIT发送请求与返回、
  ACK/ERR接收、APPLIED确认、通信失败和ALL_OFF。`changes`使用实际1–420电极ID。
- `.frame_electrodes.csv`：按同一电脑高精度perf_counter（单调时钟）对齐的每帧状态。
  `confirmed_active_ids`是上次已确认的完整开启集合，不是待发送目标；
  `state_status=pending`表示事务尚未确认，`unknown`表示完整硬件状态未知。
- `.recording.json`：记录行数、AVI帧数核对、标称播放fps、实际接收间隔统计、完整性及错误。

未连接串口时，不能把界面0/420当成硬件全关；从未知状态开始的日志不会伪造完整状态。
连接时既有ALL_OFF同步确认可建立已知全关状态。串口断开、外部SYNC或事务失败会使状态未知。
每次重试保持原序列，只有匹配的APPLIED才更新已确认状态；ALL_OFF确认后清空开启集合。
事务请求至ACK之间保守标为pending，不能从日志推断这个区间内精确的片上翻转时刻。

录像逐帧写入SDK成功后才写时间行，SDK帧号可用于检查采集跳帧。日志后台写入，
队列溢出、磁盘失败、时间倒退、AVI帧数不符都会使记录无效或报错；关闭窗口会等待相机封装和日志落盘，
不会直接退出丢掉尾部。检查`recording.json`的`status=complete`后再用于时间分析。

相机原始计数的单位尚未确认，所以只保留原值，不将其虚构为曝光秒数。
本机Python 3.12的monotonic使用GetTickCount64，分辨率约15.625 ms；高精度计时使用
QueryPerformanceCounter，系统报告分辨率100 ns。这个分辨率不是曝光或串口延迟的精度保证。
原monotonic保留给现有实时控制器计时，不改变超时阈值；录像分析/电极对齐使用perf_counter，
禁止直接相减不同计时器的绝对值。实际时钟实现和分辨率同时写入recording JSON。
当前对齐时钟是**电脑收到缓冲区的时间**，含USB/SDK传输延迟；并非曝光时刻。
APPLIED的时间是电脑收到匹配ACK的时间，仅确认电气提交，不代表液滴到达。
这些时间可用于接收时间轴下的运动/命令关联；精确曝光延迟还需要设备时钟标定。

第二章VideoSource、baseline和extract-frames自动优先读取完整录像的时间表。
非法或缺失的配套记录会拒绝分析，不静默回退到固定fps。老视频没有配套表时仍按PTS/FPS处理，
不会补造过去的采集时间。另存/剪辑视频时不能直接复制完整原时间表：需按实际保留的帧
裁出时间行、重新编号并保存原视频/帧索引对应关系，再通过`timestamps_csv`显式指定。
不能用观看MP4转码后的帧率代替原录像接收时间。

第二章experiment另外输出`electrode_events.csv`保存实际串口时刻；原`commands.csv`
中的时间仍是触发决策的帧时间，不应混同为ACK时刻。offline/dry_run不创建串口，
电极事件表只有表头，不伪造真实硬件应用记录。

## 真实Pilot标注入口

独立离线工具为`scripts/annotate_camera_pilot.py`，工作包位于
`D:\I\ZJU\有源矩阵\视觉-工业相机\第二章标注准备_20261014`；双击其中`启动标注.cmd`。
已准备63帧Mask草稿及6个原视频的完整标定参考图，原数据不覆盖。
用户确认间距3.2 mm、编号与上位机一致，但四角配准、Mask及状态审核仍待人工完成。
详见`docs/chapter2-pilot-annotation.md`。草稿不自动计为GT，缺失真实Deviation不强行制造。
