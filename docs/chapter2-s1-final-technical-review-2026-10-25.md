# S1最终定稿候选：单位与可观测性核查

用户已通过S1-A/B结构，本轮禁止重新设计。只读核查当前代码、对应冻结源码快照、原Mask、65条运输观测及绘图字段，不运行世界/相机/识别器，不修改数据或图像文件。

## 结论

1. `transport_projection`中progress为`dot(c-s,t-s)/norm(t-s)`，是有符号投影距离；另有`progress_fraction=progress/norm(t-s)`。S1-B(c)绘制`progress_pitch`，不是`progress_fraction`。仿真适配层坐标为pitch，历史`*_mm`仅为兼容别名，现有“任务空间量 / pitch”正确，保留。
2. `ObservationPipeline.extract`从frame.mask的二值矩计算像素质心，经冻结栅格变换得到观测坐标；`DropletFeatureExtractor`使用此质心及源目标地图中心计算距离/进展；runner记录到frames.csv，绘图读取原值。两量是算法可观测特征，不是DropletWorld内部位置计算的评分特征。S1-B(a)内部x/y仅为单独绘图对照。

## 数值和版本核验

- 65条运输观测由原持久化Mask质心、冻结地图中心及像素/pitch变换独立复算：质心和进展最大差0，目标距离最大差1.1102230246251565e-16 pitch。
- 三段源目标中心距均为1 pitch，投影距离和归一化进展数值相同不能用于判别单位；以公式、字段和变换契约判别。
- 当前features.py与v1源码快照一致；v2 observation.py及formal_adapter.py与v2源码快照一致。
- 仅更新交付图注和QA状态，另存技术核查。S1-A/B六份SVG/PDF/PNG内容hash未变化，原trial、时间戳、CSV、Mask、SIMULATION/n=1说明保持不变。

交付位置沿用章节仿真结果`2026-10-25_S1两张核心图_定稿候选_v1`，状态更新为最终定稿候选。未修改绘图/仿真/控制代码或冻结结果，不新增S1实验，不Commit/Push。
