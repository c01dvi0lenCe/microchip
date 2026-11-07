# 第二章 B2+B3 执行计划（2026-10-21）

基线：`fe9699d`，在用户已有 B1+B4 和独立 simulation 未提交成果之上叠加。用户已授权本批实施；不 commit/push，不新建工作区以免丢失未提交基线。

## 边界与基线

- B1+B4、runner、录像时间表及 simulation 相关基线：114 tests，OK（本日实际运行）。
- 保留 GUI/controllers、AM/串口协议、U-Net segmenter、第三章规划、独立 `dmf/chapter2_sim`、仿真配置/CLI/测试；已在会话内记录这些文件 SHA256，收尾逐一核对。
- 使用既有整改方案，先 RED 后 GREEN；不把合成回归计作真实研究结果。已有代码变更保留，不恢复或覆盖。

## 执行清单

- [x] B2 反例：SDK 元数据透传、重复/跨 epoch/旧帧、时钟域不匹配、重复事件、ACK 失败。
- [x] 追加可选 FrameTiming；保留旧 FramePacket 构造、录像原始时间表 anchor；记录最新帧队列覆盖。
- [x] StepContext、ArrivalEvent、一次性 ledger 和 FrameCausalityGuard；同域接收屏障与曝光因果分开。
- [x] 包装既有事务 observer，返回精确 APPLIED 软件接收时间、request/sequence/通信重试数，不改发包。
- [x] runner 接入显式 epoch/attempt、事件消费、分段延迟及 schema；offline/dry_run 不造真实 ACK。
- [x] B3 手算反例：eta/rho、正反/斜向投影、方向速度、实测中心、位置门、退化地图/ROI。
- [x] 同一交集提取双覆盖，源/目标 mask 缓存；统一标定几何，增加投影/横向误差/方向速度。
- [x] 几何校验、可选图像尺度/ROI 坐标声明、质量 manifest；无真实审核点不报告标定完成。
- [x] 独立 simulation 结构审查（只读），记录六类场景与 S1–S4 后续入口。
- [x] 局部146项、新增49项、最终全量484项（1条件跳过）通过，compileall/diff检查和七条控制链通过。
- [x] 保护39份文件 SHA256 无变化；完成状态/未验证清单见 docs/chapter2-b2-b3-implementation-2026-10-21.md。

## 接口决策

1. FramePacket 的 `timestamp_s` 原语义不变，附加 FrameTiming 保存 SDK/raw/host 信息。设备 ticks 不猜频率。旧无 metadata 调用可用，但标为 legacy/unknown。
2. StepContext 使用 run/step/attempt/epoch/source/target/phase，APPLIED 接收时刻只在同一 host clock domain 比较。曝光映射缺失标 `causality_unknown`；接收晚于 ACK 不能证明曝光晚于 ACK。
3. ArrivalEvent 由当前连续窗生成；ledger 校验当前 context 且每 run/step 只消费一次。Retry/Recovery/Update 均重建 epoch；失败 ACK 不创建下一有效 epoch。
4. eta 仍为交集/液滴；rho 为交集/完整电极。裁剪电极未知分母不填 0。rho 仅输出，不加硬阈值。
5. Arrived 需目标位置成立，优先复用目标多边形及现有位置容差，不凭空增加未标定距离阈值。
6. 正式 benchmark/cache/人工标注审核 UI 与相机 owner 关闭生命周期不在本批扩建；明确保留下一阶段风险。

## 验收

每个反例记录修复前/后结果；B1+B4 与已有控制链无回归；所有新增时延包含 clock domain/quality，软件 ACK 不冒充物理电极应用时刻。只进行本地软件测试，不连接硬件或开展批量仿真。
