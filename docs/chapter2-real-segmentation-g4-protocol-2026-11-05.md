# 第二章真实液滴分割：G4匹配训练协议与数据检查

## 1. 研究范围

本轮在180张人工语义Mask、Ignore与144/36内部划分冻结不变的条件下，开展U-Net和DeepLabv3+的首轮匹配开发训练。数据来自同日采集，没有正式独立测试。网络参数选择仍使用36张验证数据，所得指标是选型阶段内部成绩，不是无偏测试或跨批次泛化精度。

Otsu及背景差分沿用既有预测及配置；未根据深度模型成绩重调传统基线。背景差分合格子集只有6张验证图，其NA不能填0，也不能将6图成绩和其他方法36图成绩直接排名。

## 2. 冻结训练设置

| 条目 | 两模型共同约定 |
|---|---|
| 编码器 | ResNet34，官方ImageNet1K V1权重；逐tensor摘要核对 |
| 模型实现 | segmentation-models-pytorch 0.5.0；U-Net / DeepLabV3+ |
| 输入 | RGB/NCHW，512×512，ImageNet归一化 |
| 缩放 | 与G3相同等比例letterbox；原生GT/Ignore不改 |
| GT与Ignore | GT最近邻；Ignore保守面积汇聚，padding无效；原生域评价 |
| 增强 | 同步水平/竖直翻转、90°整数旋转；亮度±0.05、对比度0.9–1.1 |
| 配对机制 | 每epoch/sample_id的独立增强seed，及每epoch共同数据顺序 |
| 损失 | 0.5 masked BCE logits + 0.5 masked soft Dice，Dice smooth=1；逐图后平均 |
| 优化 | AdamW，lr=1e-4，wd=1e-4，全部层微调，无scheduler |
| 预算 | batch4，seed269000，最多60轮，patience12 |
| 选择 | 原生36图macro Dice严格提升>1e-8才更新；同分保留更早轮 |
| 推理 | sigmoid≥0.5，最近邻还原原生ROI，无后处理/最大域过滤 |
| 实现差异 | DeepLab输出stride16/ASPP及其默认解码器不同于U-Net；完整repr保存 |

此设置匹配数据、优化与停止规则，不代表两种不同架构的参数量和计算量相等。单个开发seed不支持训练随机稳定性或最终模型排名结论。

## 3. 定向复筛与数据检查

原有人工作业审核记录保持不变。本轮另作36图助手视觉筛查：空GT145/167/178的电极纹理不作为液滴；157中小液滴保留为前景，不误归为空背景；149/150及161–164液桥、触边和细碎前景不按最大连通域删去；163/164仅排除固定储液/出液电极，多余液体在有效域仍按原人工GT评价。

没有识别出必须改写冻结GT的明确错配；无版本化GT更正。细小碎片身份、反光穿过边界、亚像素连通性不能仅凭预览得到新的独立人工真值，本轮筛查不升级为新的人工双评审。149/150底部触边液滴中的窄缝应保留为未来人工边界细节复核项，暂不自动填洞或更改原标注。

180份图/GT/Ignore的摘要、尺寸、二值编码、原生坐标及集合结构已逐项检查；没有正样本在512缩放后整体消失。GT/Ignore同步缩放、同步几何增强及Ignore梯度屏蔽均有单元测试。历史manifest中的deep_training_released=False不回写；本轮用户授权单独保存在新运行manifest。

## 4. 准入与评价

两模型须先分别完成batch4真实数据前反向、有限梯度及显存检查，通过后销毁试运行模型并重新初始化。试运行权重不进入正式开发训练。OOM/非有限失败单独记录，不单边缩小batch或减少预算。

评价逐图及逐视频报告Dice/IoU/Precision/Recall、空GT误检图数、FP像素及有效域FP比例。实例尚未形成审核真值，实例质心误差/身份漏检不可由合并质心冒充。若给出目标覆盖误差，使用原候选地图且限定完整有效电极子集，不称最终实物测量精度。

GPU推理使用warmup5、每图10次计时，分别保存CUDA forward与含预处理/传输/原生还原的pipeline时间；均不含解码、GT评分和写盘。传统CPU耗时与GPU耗时须明确硬件和口径，不作无条件实时性排名。

## 5. 复现与来源

新运行保存全部原输入文件保护摘要、配置/源码hash、环境与依赖、官方编码器权重来源、GPU试运行、每轮日志、best/last权重（优化器/scaler/RNG一并保存）及原生预测。原G2/G3目录不写入。

实现依据：[SMP模型定义](https://smp.readthedocs.io/en/latest/_modules/segmentation_models_pytorch/decoders/deeplabv3/model.html)、[PyTorch可复现性说明](https://github.com/pytorch/pytorch/blob/main/docs/source/notes/randomness.md)。固定seed及确定性设置不保证跨库版本和硬件逐bit一致。
