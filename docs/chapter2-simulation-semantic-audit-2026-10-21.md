# 第二章正式算法仿真：语义审查

日期：2026-10-21；HEAD：`fe9699d7e6867ee8897056b122c8248153cadd3e`。
依据当前工作区及B2+B3改造记录。本文件是实施前审查，不表示适配器、benchmark或新批次实验已经完成。

## 基线保护与实际检查

- 当前有19个tracked修改及22个untracked状态项（目录项不等于文件数量）；没有恢复、覆盖、提交或推送。
- 已在本会话记录74份既有GUI/规划/仿真/正式视觉算法等源码的SHA256，后续只允许在明确方案范围内叠加。
- 实际运行179项B1–B4、视觉框架、录像时序及独立仿真相关测试：全部通过，10.009s、exit0。
- 本轮至此新运行的研究批次/闭环对照实验为0；上述是软件回归，不是实验样本。

## 语义对照表

| 项目 | 旧chapter2_sim实际实现 | 正式dmf.experiment实际实现 | 适配要求 |
| --- | --- | --- | --- |
| 重复/逆序帧 | StableWindow返回False，但不清已有samples | EvidenceWindow清窗并保留身份/时间高水位 | 新正式适配版复用后者，不改旧版历史语义 |
| 长gap/捕获号缺口 | 清StableWindow，偏离计数另行清除 | 源/到达/Recovery共享gap、身份及稳定窗规则 | 全部确认门与相同配置一致 |
| 位置稳定 | 位置跨度门，未检查覆盖率跨度 | 同时支持位置和eta跨度 | 映射两种稳定阈值，记录实际使用参数 |
| 到达位置门 | 到目标中心距离<=position_tolerance | 实际目标polygon加position_tolerance_mm | 不能将二者视为同一门；新版本用正式门 |
| 空间先验 | progress范围[-.45,1.45]及横偏走廊 | 实际源/目标/候选polygon的允许区域 | 使用地图来源与候选集合明确的正式几何先验 |
| 观测有效性 | mask缺失/面积<10失效；无置信度/显著连通区域校验 | mask契约、置信度、面积、单显著连通区域、单调时序 | 同一掩膜输入需走正式质量检查，不重复写一套近似规则 |
| 时序冲突 | 总/方向速度供状态输出，没有正式运动预测一致性门 | 只用既往已接受位置外推；冲突Unknown且不污染历史 | 新适配版复用该行为，异常观测不直接Recovery |
| Partial | 固定.12<eta_target<arrival_coverage且源残留 | eta_target>=eta_enter且源残留 | 版本/参数表记录差异；不静默替换旧结论 |
| Deviation | 走廊外持续若干帧；该valid会刷新策略last_valid | 区分invalid/conflict，可信持续空间偏离才Deviation | 质量标志、偏离计数及计时独立一致性测试 |
| 初始源确认 | runner直接Start，默认已在源 | EventController先confirm_source | 三组采用同一初始源设置/确认程序，比较运输阶段；不能只给C增加准备时间 |
| Retry计数 | decide时已增加，尚未等待模拟APPLIED | accept后才增加；失败不推进 | 请求与模拟APPLIED分离，ACK失败/重复ACK回归 |
| 无进展 | 分数progress、超时从command_started计 | 有向长度历史最佳、独立质量/尝试超时 | 显式pitch单位映射，采用正式ProgressMonitor |
| Recovery | recovering阶段用反向特征，Arrived后Resume；不计为retry | 源连续确认后Retry，retry_total包含恢复后的重发，retry_count=0 | 保留正式含义，分开运输超时Retry、恢复重发、通信重试 |
| 任务身份 | step/epoch及consumed step集合 | run/step/attempt/epoch/phase、ArrivalEvent及ledger | 新事件可追溯且一次消费；重访相同源目标对不得混淆 |
| 时钟 | 曝光起止/available_s均模拟秒 | FrameTiming区分SDK/raw/host；现有guard不接受simulation实时域 | 新增显式simulation分支/适配，禁止借host_monotonic冒充真实时间 |
| 旧帧 | runner拒绝模拟APPLIED前曝光，通常不改变新窗 | guard/识别窗拒绝旧/重复帧并有确定重建规则 | 新正式版遵守正式窗；日志保留拒绝原因与context |
| 长度 | pitch归一化，默认非真实mm | 旧接口字段含mm，运行时来自标定地图 | 适配器必须声明pitch；不把内部兼容字段导出成实测mm |
| 真值 | 世界位置盆地+真实速度+独立驻留；评价器可见，控制器不可见 | 正式事件评价要求独立人工审核区间 | 分开simulation参考入口与human入口，禁止伪造annotation_source=human |
| 指标 | 已有路径率、提前率、条件延迟、执行总时间、Retry/Recovery及CI | B4强调完整manifest、Unknown/失败/漏事件/删失 | 补到达召回、条件完成时间、完整分母/参考支持数和方法版本 |

## 已实际复现的最小反例

以下只构造软件逻辑输入，不是实际液滴GT。

1. 四帧证据后输入重复帧：旧窗count仍为4，正式窗count=0；下一新帧旧窗确认True，正式窗False。
2. 目标polygon内、距中心0.4、容差0.18、连续稳定高覆盖输入：旧识别器Stationary，正式识别器Arrived。
   该差异证明门不同，不证明哪种算法更准确。独立世界真值仍可判它提前，不能由状态输出反造真值。
3. 无进展Retry决定发出但尚未接受：旧策略retry=1，正式策略retry_total=0。

## 统计与数据边界

- 独立单位是配对环境seed，不是帧、运输步、重复画图或bootstrap重采样次数。
- 旧batch的METHODS仅A/B/C；新正式版/消融不能只改显示名后继续写成相同方法。必须使用method_version与配置hash。
- 提前率同时报告全部计划步及已发确认事件两种分母；路径成功率分母为全部试验，失败不剔除。
- 旧total_time包含保护停止时间；需另列成功条件下completion_time，禁止把提前停止的短时间写成完成更快。
- 到达召回只在独立参考存在时定义，并同时报告全部计划步、已出现真值事件、未到达、未尝试和删失数。
- 不预设C/S4必优，也不根据正式扫描结果挑阈值、seed或删异常。观测有效性消融若无效应，照实输出，不添加有利扰动。

## 当前真实材料缺失

配置仍指向`models/unet.onnx`，本次Test-Path为False；配置calibration_confirmed=false。
当前仓库可发现文件中未找到正式benchmark/到达人工参考输入。此结论限当前配置与仓库，
不等于断言用户其他目录没有模型或标注。

真实S1–S4评测需输入资源manifest、训练模型/预处理或共同分割缓存、相机/地图绑定、
固定任务段、独立已审核人工到达区间及批次划分。缺少时只运行明确的simulation/合成接口测试。

## 推荐结论

新增版本化正式算法适配入口，保留旧chapter2_sim默认入口和历史结果。先证明适配语义与正式算法一致，
再做共同缓存S1–S4与三项消融，最后跑配对闭环与敏感性分析。具体设计见
[正式仿真设计](superpowers/specs/2026-10-21-chapter2-formal-simulation-design.md)。
