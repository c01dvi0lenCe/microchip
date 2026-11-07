# G4 匹配深度分割开发训练协议

## 授权、范围与数据

用户2026-11-05确认：seed269000、batch4、最多60epoch、patience12，AdamW lr1e-4/weight_decay1e-4，按原生验证平均Dice选权重，同分保留较早轮。仅同日内部开发；不是独立测试或四算法最终排名。不Commit/Push。

只读G2/G3冻结目录 `2026-11-05_G2内部冻结_G3传统基线_v1`。144train/36val/0test，原视频、SHA、操作/视频内轨迹组不跨集合；跨文件物理谱系和独立装夹未确认。旧manifest中deep_training_released=False是历史记录；本次授权另存新manifest，不回写历史。无GT更正时沿用180份人工GT及Ignore的原字节。

## 模型和共同输入

使用同一固定版本segmentation-models-pytorch的Unet与DeepLabV3Plus，encoder=resnet34，encoder_depth5，imagenet初始化，3通道、1logit、无输出activation。DeepLabV3Plus output_stride16，其余解码器采用该固定版本默认值并保存构造参数。两模型编码器初始state_dict逐tensor hash相同，不要求解码器相同。无模型自动替代或无预训练降级。

复用G3 prepare_image的512×512等比例白色letterbox，BGR转RGB、/255，ImageNet mean/std。GT最近邻变换；Ignore用保守面积汇聚：任何被缩入输入像素的Ignore均使该像素不参与训练/验证损失，padding无效。几何增强同步变换image/GT/valid，不在验证集增强。所有正式指标在原生尺寸、原生GT/Ignore上计算；sigmoid>=0.5形成512二值Mask，按G3最近邻还原。不后处理、不保留最大域。

## 增强与损失

每(epoch,sample_id)确定性独立生成增强，模型间相同：水平/竖直翻转各p0.5，0/90/180/270°均匀旋转；brightness offset U[-0.05,0.05]、contrast U[0.9,1.1]，无裁剪/弹性/随机缩放/合成液滴。验证无增强。每epoch随机顺序按共同seed+epoch生成，不受模型随机数消耗影响。

loss=0.5*masked_BCE_logits+0.5*masked_soft_Dice；先每图有效像素BCE均值，Dice=(2Σpy+1)/(Σp+Σy+1)，再图均值。全Ignore图明确拒绝，不能当作空GT。无类别权重/负样本重采样；空GT参与损失。

## 训练与停止

AdamW固定lr1e-4、wd1e-4，所有层微调，无scheduler；batch4，144整除；60epoch上限，每epoch36optimizer steps；AMP fp16+GradScaler，共同配置。单开发seed269000；early-stop连续12epoch无严格Dice提升（>1e-8）；最早轮tie。保存best/last（model、optimizer、scaler、epoch、RNG、protocol/source hashes）及每epoch训练/验证损失、原生Dice/IoU及时间。

CPU线程4、OpenCV1、DataLoader workers0。固定Python/NumPy/Torch seed，cudnn benchmark=False/deterministic=True，记录warn_only确定性设置；不宣称跨版本/平台bitwise一致。两模型先分别batch4前反向、有限梯度、显存检查；任一OOM/非有限则两者都不启动正式开发训练，先记录阻断，不单边降batch。试运行后的模型/优化器全部重建，不能带入更新权重。

## 评价与计时

同36val逐图Dice/IoU/Precision/Recall；同时按positive/emptyGT与视频汇总。FP像素、FP/有效域、空GT有任意FP图数、全Mask漏检数完整保留。实例ID未审核，质心/实例漏检不冒充可计算。候选地图覆盖诊断沿G3适用子集，标明非最终标定。

Otsu复用冻结预测/指标不重调。背景差分109/180、6/36可用率保留；4方法仅在合格背景共同6val配对。无NA赋0；不给不等样本总体排名。仅描述统计，不将36张当独立批次，不做帧独立CI/p值。

最佳权重eval后CUDA同步计时：batch1，warmup5，每val图10次；分别记录GPU forward(含sigmoid/threshold)、处理端到端(letterbox/RGB/normalize/H2D/forward/D2H/nearest restore)，不含读盘/GT/保存。CPU Otsu与GPU深度方法硬件不同须明示，不做不带条件的速度排名。

## 高风险复核与保护

本轮助手对冻结36图进行定向视觉检查并保留逐例记录，不升级为新的人工GT。经CSV核对，空GT为145/167/178；157是含389px有效小液滴的正样本，不是空GT。重点检查网格误检、液桥161–164、小碎片/触边、Ignore163/164。任何明确错误或重大歧义先列出并阻断相关授权，不自动改GT。用户原有人工审核记录与本轮助手筛查分开。

运行前后检查G2/G3全目录文件hash，及原有受保护代码/配置；新运行和环境独立目录。两模型无成功结果时不制造表格数值；异常、OOM、NaN、未完成均保存。无新的S1/S2/S3运行，不接相机/串口。
