# 实验二：独立异常机制工作包（已批准范围）

用户批准10条确定性开发案例、五类机制及单元边界测试。只扩展独立开发命名空间，不修改首版exp2、实验一B或S1/S2/S3冻结数据/算法/阈值，不执行随机seed或性能扫描，不Commit/Push。

## 原样复用

读取真实420地图、430有效轮廓池和首版速度松弛World；复用首版控制器、P0、M1/M2/M3、独立参考和持久化格式。正常动力学参数、4.65 s候选基线、40 s观察/控制预算保持。新代码位于`dmf/chapter2_geometry_sim/exp2_faults/`，新增专用runner而不修改首版runner。控制器仍不接收World/独立评分真值。原始正常四trial只读复算，不重跑。

## 预声明10条案例（每条n=1，随机调用0次）

| ID | 方法 | 唯一预声明干预 |
|---|---|---|
| early_M1 | M1 | 在2.05 s曝光帧用191中心的紧凑池轮廓替换一次观测Mask |
| early_M2 | M2 | 同一干预规则；不强制后续轨迹相同 |
| stall_false_M2 | M2 | 从2.00 s永久固定World位置/速度；2.20–2.75 s的12帧观测替换为191中心紧凑Mask |
| stall_false_M3 | M3 | 同一独立物理/观测干预，允许闭环轨迹分叉 |
| camera_gap_M2 | M2 | 丢弃1.00–1.60 s共13个曝光帧的交付；仍保存实际生成Mask与丢弃记录 |
| late_duplicate_M2 | M2 | 帧68（3.40 s）额外延迟1.00 s；帧69正常交付后额外重复交付一次，available增加0.02 s，保留原身份和曝光上下文 |
| applied_delay_M2 | M2 | 模拟Applied固定延迟改为0.30 s；单独标为事务延迟stress，其他参数不变 |
| stall_timeout_M2 | M2 | 从2.00 s永久固定World位置/速度；没有伪Mask；观察实际Retry/Recovery和40 s预算终止 |
| turn_early_M1 | M1 | 在4.80 s曝光帧用192中心紧凑Mask替换一次，检查后续192→172激励切换 |
| turn_early_M2 | M2 | 同一干预规则；不预设方法一定成功 |

所有假Mask均使用现有有效池的紧凑轮廓、面积不变，位置由预声明电极ID决定，不依据评分真值或算法结果动态挑选。永久卡滞是明确的合成物理压力夹具，不修改正常World方程。模拟层干预可以读取环境状态用于生成观测；控制器接口仍只看到观测。

## 新增评价和日志契约

不修改旧metrics，另存`outcome_separation.json`及`decision_alignment.csv`：

- 三计划步的决策支持（含Complete）与两次实际Update请求支持分别计数。
- 实际Update的Applied支持单独计数；无Applied时NA，不记成失败/成功。
- `completed_task_target`表示当前判定完成的目标；`commanded_active_electrode`为下一指令；`applied_active_electrode`为对应生效目标；Complete后两项NA。
- 分列workflow_complete_s、最终目标首次参考时刻、Complete当时参考支持、H时参考支持；未Complete为NA，不利用未来参考追认过去。
- 保留原互斥终止、三步计划、失败、未尝试、Unknown/无观测、删失和排队情况。
- 每个捕获Mask、实际交付（包括重复）及丢弃/延迟操作都有记录。实际捕获上下文不能重绑为交付时上下文。到期队列按available及稳定序号排序，延迟帧不能阻塞其他已到期帧。
- 保存环境原Mask与算法可见Mask的身份/摘要；至少保存注入帧的原始Mask，不把伪观测当作World真值。

## 单元测试与审计

先红后绿：确定性案例数量/参数；卡滞不移动而事务仍可生效；丢帧、重复、倒序及跨任务帧；实际Update与Complete分类；未来参考不追认；最终参考丢失不被“曾到达”掩盖；延迟事务pending禁止重发新目标；Retry/Recovery预算及终止后Applied禁止；转弯位置/速度/轮廓不在Applied瞬间跳变。

独立审计从持久化World、Mask、事件复算分列指标和参考，不调用原评分器；逐项核查干预确实发生。机制要求是如实解释响应，不要求M3胜出。未触发的分支报告为未覆盖，不重抽/调时刻以制造结果。

## 交付与停止

10条开发记录＋旧4条正常只读分析，原始CSV/Mask/事件/manifest、新增测试、两张过程诊断图（只含必要图例/坐标/时间/SIMULATION）及Chat审查PDF。新World参数敏感性只列正式准入需求，不在本批增设扫描。完成后停止。
