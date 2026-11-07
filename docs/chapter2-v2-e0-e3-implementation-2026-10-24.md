# 第二章仿真v2 E0–E3阶段交付（2026-10-24）

本批是独立研究接口、机制测试及开发seed冒烟，不是正式v2性能实验，不是真实液滴或流体动力学结果。未启动E4–E7、未修改PPT及冻结论文统计图。

结果目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1`。

## 1. 实施范围与兼容边界

- 新增`dmf/chapter2_sim/v2/`，沿用未改动的DropletWorld、SyntheticCamera、SimulationMap，以及生产EvidenceWindow、StateRecognizer、EventController、ProgressMonitor、StepContext和ArrivalEventLedger。
- `C_v1_compat`直接委托原FormalAdapter。normal、jitter、partial_stall的历史seed261000与旧runner及冻结CSV的truth/frames/events/metrics均一致；这是有限样本的兼容证据，不是全参数等价证明。
- 原PriorFeatures中Q/K及历史采样相互耦合，不能直接声称其消融正交。新ObservationPipeline对每个C0可解析输入先计算raw S/K/Q，运动历史不受开关影响，再组合eligible。生产实现未改。
- K历史在context、长断档、丢号或无效输入处重建。W只控制目标确认，不改变源准备/Recovery的P0或预算。C0不是可关闭模块。
- 源准备和Recovery各有独立配置；本批保留P0，不实现P1。`transport_only`标为受控初始条件，不能计为源区视觉确认。

## 2. BTQ与F判据对照

| 判据 | BT | BTQ（等稳定窗口覆盖率强基线） | F |
| --- | --- | --- | --- |
| C0：格式、非空、身份、时钟、任务因果、帧时序 | 常开 | 常开 | 常开 |
| eta_target≥0.85且eta_source≤0.08 | 相同 | 相同 | 相同 |
| W：≥5帧且≥0.25s，间隔≤0.18s | 相同 | 相同 | 相同 |
| W：质心跨度≤0.11pitch、覆盖跨度≤0.15 | 相同 | 相同 | 相同 |
| Q：置信度、面积、显著连通域 | 关闭 | 开启 | 开启 |
| S：源目标允许区及目标位置门 | 关闭 | 关闭 | 开启 |
| K：方向/位移预测一致性 | 关闭 | 关闭 | 开启 |
| 输出五状态 | 不伪造，仅Arrived/Unknown | 不伪造，仅Arrived/Unknown | 复用正式识别器 |
| 事件一次消费、有限Retry/局部Recovery | 保留 | 保留 | 保留 |

W包括质心和覆盖波动稳定性，绝不把BTQ解释为仅“累计帧数”的弱基线。F额外贡献是S/K，不是更宽松的窗口。公共时间全部为simulation域；代码字段中的历史`*_mm`别名在适配层实际使用pitch，并在manifest/图中明确，不能报告毫米精度或实测ACK。

## 3. E0–E3实际运行

开发seed固定为262000、262001、262002，未因结果调参或替换seed。

- 84条端到端：7场景×3seed×4方法。
- 24条阶段诊断：normal/jitter×3seed×BTQ/F×source_only/transport_only。
- 共108计划trial和108记录，324计划步骤和324步骤账本，基础设施错误0。
- 8个手工机制序列×16个S/W/K/Q组合，共128次。raw特征序列在全部组合中一致。
- 21个共享Mask缓存：历史S1–S4共84次预测，BT/BTQ/F共63次预测。另有8个机制缓存×3方法，共24次预测。这些是接口/共享输入验证，不是正式统计图。
- 最终dev2批次真实SyntheticCamera输出共13224张非丢帧Mask PNG。丢帧、待处理帧和Unknown另有日志，不用插值补成有效帧。

### 端到端终态（每个方法每场景n=3）

| 场景 | 四种方法的执行终态 | 独立行为标签 |
| --- | --- | --- |
| normal | 各3次transport_complete | 无Retry/Recovery |
| delayed | 各3次transport_complete | 无Retry/Recovery |
| partial_stall | 各3次transport_complete | 各9次Retry（合计3条trial） |
| jitter | 各3次source_not_prepared | 所有计划运输步骤保留为unattempted |
| dropout | 各3次transport_complete | 各1次Retry（合计3条trial） |
| deviation | 各3次transport_complete | C_v1_compat/F各9次Recovery；BT/BTQ各9次Retry |
| failure | 各3次transport_stopped | 各12次Retry、3次Recovery |

源诊断：normal的BTQ/F各3/3源确认，jitter各0/3。受控运输诊断：normal各3次完成，jitter各3次保护停止。这些视图不混池，运输受控初值不是源准备成功率。

108条的互斥终态为transport_complete66、source_not_prepared18、transport_stopped18、source_prepared6。此跨视图总数只用于账本守恒，不作为混合性能率。`path_complete`还要求逐步独立参考支持且无错误/提前/不确定/重复事件，不能只看transport_complete。

### 开关机制证据与边界

| 夹具 | 检验对象 | 实际结果 |
| --- | --- | --- |
| stable | 正常负对照 | 所有配置均可确认 |
| transient | W | F不确认，关闭W可单帧确认 |
| spatial_tail | S | F不确认，关闭S可确认；Q/K保持相同 |
| motion_jump | K | F不确认，关闭K可确认；不足窗口与跳变作用分别可见 |
| low_confidence / small_area / two_components | Q | F不确认，关闭Q可确认 |
| high_confidence_indistinguishable | 可观测性盲区 | 全开仍确认，表明完全同观测伪像无法仅靠这些特征识别 |

夹具只是已知构造的合成机制单元测试，不是正式人工GT、真实误检率或Q真实有效性的证明。本批真实相机模型仍主要是圆Mask位移/半径噪声及丢帧，不能覆盖真实U-Net伪像分布。

## 4. 统计定义

- 互斥trial终态：source_not_prepared、source_prepared、transport_complete、transport_stopped、time_limit、infrastructure_error。
- 步骤执行终态互斥：unattempted、attempted_unconfirmed、confirmed。独立参考支持另列，不把confirmed自动称正确。
- 提前、无参考支持、错误目标、重复事件、参考区间不确定、漏确认、确认时间右删失为独立标签。零预测保留全部计划步骤；无有效延迟时为null，不填0。基础设施异常仍保留计划trial/step，参考状态为unknown。
- 参考到达由循环结束后的内部位置、真实速度和独立dwell定义，算法模块不读truth/参考/场景/seed。控制日志保留旧参考字段仅供历史兼容，不传入算法。
- E4前仍需冻结正式事件率、按试验配对不确定性及参考敏感性协议。本阶段不计算n=3优越性或正式CI。

## 5. 可视化与来源

v1冻结日志没有Mask像素，不能完整复原SyntheticCamera Mask；上轮v1严格日志回放保持不动。本次明确新增开发trial：

`normal:262000:F:end_to_end:full`

`visualization_r2/`仅从`development_smoke_r2/`该trial已持久化日志生成，绘图不重跑世界/相机/控制，不插值位置或补造事件。

- `V2-Process-1_仿真架构`：数据流、控制流、评分真值隔离。
- `V2-Process-2_关键帧`：源确认0.50s、观测运动0.81s、Partial1.06s、参考到达1.46s、Arrived/Update1.92s、模拟Applied1.96s。
- `V2-Process-3_联合时间线`：位置、覆盖、证据帧数/时长、五状态/Unknown、参考/确认/请求/应用分行。
- H.264 MP4：1280×720、25fps、412帧，4倍慢放16.48s；模拟原时长4.11s。全部412帧实际解码通过。
- 世界内部点位置为蓝色，算法可见Mask/质心为橙色。仅显示已处理且当前epoch/C0有效的Mask叠加；原始被拒绝Mask仍可在独立观察窗检查。世界active、response_at与软件模拟Applied分开显示。
- 图稿保留SVG、PDF、600dpi PNG和逐帧来源索引、trial/config/map/source hash。

默认几何为完整420示例模板，单位pitch，**不是已验证FBC6-3 Gerber实尺寸地图**。局部视图只放大本路线附近电极。模型是有限速度的二维点运动与圆形视觉Mask，不是COMSOL、CFD、电润湿或真实液滴形变计算。

## 6. 修改文件及入口

新增v2模块：`spec.py`、`observation.py`、`arrival.py`、`adapter.py`、`reference.py`、`evaluation.py`、`runner.py`、`persistence.py`、`benchmark.py`、`probes.py`、`development.py`、`replay.py`、`plotting.py`、`__init__.py`。

新增配置/入口：`configs/chapter2_simulation_v2.yaml`、`run_chapter2_simulation_v2.py`。

新增测试：`tests/test_chapter2_sim_v2_{gates,runner,benchmark,dev,visualization,reference}.py`。

新增验收及打包脚本：`scripts/verify_chapter2_v2_delivery.py`、`scripts/package_chapter2_v2_delivery.py`。规格/计划位于`docs/superpowers/{specs,plans}/2026-10-24-chapter2-v2-e0-e3.md`；原三份规划记录只追加本阶段内容。

```powershell
python run_chapter2_simulation_v2.py validate
python run_chapter2_simulation_v2.py compatibility --frozen-dir "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\2026-10-21_B1-B4正式算法_v1\formal\closed_loop"
python -m unittest tests.test_chapter2_sim_v2_gates tests.test_chapter2_sim_v2_runner tests.test_chapter2_sim_v2_benchmark tests.test_chapter2_sim_v2_dev tests.test_chapter2_sim_v2_visualization tests.test_chapter2_sim_v2_reference -v
python run_chapter2_simulation_v2.py smoke --output "新的开发输出目录" --frozen-dir "上述v1 closed_loop目录"
python run_chapter2_simulation_v2.py visualize --trial "已保存的trial目录" --output "新的可视化目录" --ffmpeg "可用H.264编码器路径"
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

输出目录存在即拒绝；重跑须用新目录。没有formal scan入口，也不接受本阶段未批准的确认seed263000。

## 7. 验证与保留

- 最终新增41项回归通过（8.599s）；全量696项，695通过、1项可选FFmpeg集成测试跳过，134.946s。PyTorch/Python3.14的既有TorchScript弃用警告保留，不据此宣称部署兼容性已验证。
- compileall、git diff --check通过，move/mix/split/loop/CSE/ZJU/CSC七个独立软件验证通过；没有硬件运行。
- 212份受保护源码/配置/关键旧成果SHA256不变；41343份v1冻结文件的尺寸/mtime_ns清单不变（不是全量逐字节重哈希）；HEAD保持fe9699d7e6867ee8897056b122c8248153cadd3e。未commit/push。
- 所有旧source_snapshot保留当时版本，不追改旧manifest。首次验收计数脚本曾因Windows路径分隔符把Mask数量显示为0，`acceptance_v2`已修正为13296，针对的是首次开发批次，不混淆为数据缺失。最终交付以`development_smoke_r2`、`visualization_r2`及`acceptance_final`为准。

### 最后复核的反例与dev2修订

1. 原始raw gate正交，但开关曾写回Observation的valid/spatial_ok/temporal_ok，连带改变保护策略输入。新增16组合观测相同及关闭S不取消Recovery的反例，修复前失败、修复后通过。现在开关只作用于目标ArrivalGate，原始状态/保护输入保持不变；到达门不同导致的真实Update后续轨迹变化仍是合法反馈，不要求闭环轨迹人为相同。
2. 独立参考曾跳过非transport行，可能跨Recovery拼接驻留；epoch变化或缺失tick也未清除。新增Recovery、epoch、断档及新epoch自建窗口反例（3项），修复前失败、修复后通过。独立参考现在要求同epoch/目标、连续transport tick；位置/真实速度/驻留阈值仍与控制判据独立。
3. 首次108条开发记录保留于`development_smoke`，不作为最终dev2统计。修订版按相同计划重跑108条并另存`development_smoke_r2`，没有增加独立seed。实际执行两批共216条记录，但重复seed不得当作216次独立研究重复。两批终态完全相同，6条BT/BTQ deviation记录的执行时间、捕获帧数和延迟等发生变化；其余方法对应指标未因本修订改变（方法版本号除外）。
4. 独立审查过程提出了上述两个有效风险；审查服务随后中断，不能称已完成全面独立代码审查。本批已以具体反例、主代理逐项复核及全量回归闭环；扩大正式实验前仍建议再做独立审查。

## 8. 下一阶段闸门

先审核机制图、同trial动画、BTQ/F契约及jitter双阶段诊断，再决定E4–E7。建议先以已冻结共享缓存开展BTQ对F及S/K/Q真实可检验场景；确认时间/覆盖阈值与独立参考分别扫描并报告失败原因，不能用源准备失败掩盖目标识别评价。需要时再批准P1源门，不在本批偷偷放宽。

真实形状、镜头、U-Net置信度/误检分布、物理时序与实物闭环均未验证；当前机制差异不能替代这些证据。
