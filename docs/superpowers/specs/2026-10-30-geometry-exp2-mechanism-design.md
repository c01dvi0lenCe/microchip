# 实验二：单活动目标因果闭环机制版

用户已确认单活动目标原子替换。此轮只交付独立接口、确定性测试与四组正常机制演示，不运行正式seed或性能扫描。旧World、实验一B、S1/S2/S3、真实控制及第三章只读；不Commit/Push。

## 开发模型及边界

路径190→191→192→172，真实420 Gerber地图、4 mm面积等效轮廓、0.8 mm高度仅记录。每次模拟Applied原子替换active单ID。request/pending/Applied/响应分开，任意切换时位置和速度状态不重置。

单步预生成最小跃度不能从任意位置/速度因果重定向。本机制版独立采用有界速度松弛模型：期望速度为(goal-position)/settle_time，经1.4 mm/s限幅；加速度为(desired-velocity)/velocity_tau，经4 mm/s²限幅；dt=0.01 s半隐式积分。settle_time=0.75 s、velocity_tau=0.25 s均为新增开发假设，不是视频标定值或正式冻结参数。响应前desired=0（已有速度可衰减），初始静止不动；无实际轮廓—active正交叠则停止并明确记录blocked_no_overlap，属于非惯性模型门，不称流体动力学。

轮廓只用430个已保存有效多边形，按进展选择、平移和旋转，不做新SDF插值或修复。真实active切换时保留当前形态/方向状态；之后phase向实际源目标进展以最大1/0.15每秒变化，方向最大2π rad/s转向当前任务轴。该时间参数及转弯形态未由独立视频验证，完整记录。每次选择轮廓仍保面积及质心；不优化动画、不作形变真实性结论。

## 算法与控制

复用现有RawAssessor、GateRunner、METHODS、StepContext、EvidenceWindow和ArrivalEvent语义及全部门限。不得改旧代码。M1/M2/M3只读取Mask特征、时间、上下文；不读truth或评分。A_fixed在本步Applied后4.65 s推进，明确为开发候选，不生成视觉ArrivalEvent。

共同P0：已激活190后，用source的rho≥0.90、单连通不触ROI及源中心距离≤0.576 mm连续5帧/0.25 s确认；独立于目标G的源残留定义，P0超时2 s。源准备失败进入互斥终止类。

全部方法共用基础保护：每运输尝试10 s，最多2次Retry、1次局部源Recovery；Recovery有10 s源准备限时，确认后Resend目标，再无进展到期保护停止。每计划步Applied最多7次（含首次、Retry、Recovery、resend）；同目标Retry仍建立新软件epoch，但不打断独立物理驻留。开发全局控制预算40 s，不能作为正式预算；全过程固定观察到40 s，控制器Complete/Stop后保持最后激励，不继续推进。每trial固定3计划步，未尝试仍保留。

事务pending不消费旧任务确认或发新事务；captured context在曝光时绑定，Applied后建立新context。队列中旧epoch、倒序/重复、曝光在Applied前的帧不能推进当前门。A共享P0与安全计时，但运输不用视觉ArrivalEvent。完整五状态/Deviation保护不在本轮新增，不能把M3门冒称五状态控制器。

## 独立参考与评分

truth只进入持久化和评分。参考仍用半径0.288 mm、速度0.192 mm/s、驻留0.15 s，按实际active改变分段，不按attempt/epoch分段。同目标Retry物理连续；Recovery真正换激励后重建。切换瞬间保存旧激励左极限，分开评分request/Applied，不能未来追认request。

分列工作流transport_complete、最终目标参考完成、逐步参考支持路径、request/Applied无支持事件及实际无交叠阻断。参考前不是实物危险。互斥终止类：source_preparation_failed、transport_aborted、time_budget_exhausted、workflow_complete_without_supported_path、reference_supported_path_complete。每3步计划表含attempted、终止/删失和缺失字段。

## 本轮验收与停止

确定性测试覆盖连续位置/速度、延迟、pending、无交叠、三步邻接/转弯、面积/质心、旧/重复/断档帧、一次性事件、P0一致、预算、Retry/Recovery参考、request/Applied分评分、终止和未尝试分母。四方法各一次normal机制演示，另两个预声明定时切换反例（非常早与等待后），全部random_draws=0，不使用任何正式seed。输出真实Mask、World、事件、原始门、预测及评分；独立保存并审计。

报告必须明确这是新开发World，不能沿用实验一B确认时刻/性能，也未冻结正式固定等待、预算或动力学参数。机制通过后停止，不自动开展随机对比。
