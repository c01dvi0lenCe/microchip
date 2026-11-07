# 第二章真实分割：审核后Pilot基线记录（2026-10-21）

## 范围与事实

用户已审核18张Mask并授权下一步。仅新增离线分割研究入口，不改五状态、闭环控制、GUI、U-Net适配器、串口协议、AM、STM32、第三章和原正式仿真结果，不commit/push。

实际运行包：`D:/Learn/ZJU/第二章 单液滴视觉闭环/真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认`。
v1是用户补充采集关系前的首次Pilot，保留历史。两版参数/预测指标完全相同；v2新增用户确认的来源分组，并重新计时。新增分组信息不是新增独立实验。

用户确认10段视频均同芯片、同一次加液、同轮采集，独立采集组只有1。所有开发样本split保持unassigned。状态Unknown不影响Mask分割研究。主素材虽有两个文件日期，不能据日期虚构两次独立采集。

## 新增文件与接口

- `dmf/segmentation_research/data.py`：`load_reviewed(path, formal=False, groups=None)`只读审核Mask；拒绝空路径/错尺寸/非二值/重复来源帧；检查parent/source hash/已知chip/session跨集合泄漏。可读取独立人工来源分组manifest。`freeze_samples`复制原始字节并核对hash，不伪造状态或电极字段。
- `baselines.py`：`ThresholdBaseline('otsu'|'adaptive', parameters)`，只收FramePacket；复用既有clean_mask/result_from_mask和VisionResult，不读GT。
- `evaluation.py`：`score_prediction`、`summarize_rows`和`run_pilot`；复用现有Dice/IoU/Precision/Recall/质心指标。失败、缺失、空Mask保持分母；条件质心分母明确；原视频宏平均只是描述。拒绝覆盖已有输出。
- `review.py`：`write_review(results)`，先核对核心产物hash，再生成全部样本的本地HTML核对页和来源sidecar，不伪装正式论文图。
- `run_segmentation_pilot.py`：`--reviewed`、`--groups`、`--config`、`--output`，无硬件依赖。
- `configs/chapter2_segmentation_pilot.json`：冻结CPU参数及方法共同后处理。
- `tests/test_segmentation_research.py`：20项合成软件fixture测试；不是实际液滴精度结果。

原审核工具、image_io、公共结果契约/后处理/指标直接复用，未重新开发审核GUI或修改UNetSegmenter。

## 测试先行与实际结果

初始17项测试在新模块不存在时RED（ModuleNotFoundError），实现后GREEN。HTML核对页测试RED→GREEN。用户补充单采集组后，新增外部分组跨集合拒绝、完整来源覆盖2项测试RED（缺groups参数）→GREEN。最终新增20项通过。

v2真实审核数据：18图、3个原视频、1个独立采集组。Otsu：Dice 0.9128593985，IoU 0.8840637994，Precision 0.8871104557，Recall 0.9411562322，空Mask1/18；质心误差1.4461207963px，条件分母17。Adaptive：Dice 0.9742294984，IoU 0.9500369974，Precision 0.9897489138，Recall 0.9601010868，空Mask0/18；质心误差0.7511587540px，分母18。

Intel Core Ultra9 275HX、OpenCV4.13.0 CPU单线程；每图每方法5次预热/10次计时，各180次。Otsu mean/P50/P95=1.731934/1.766600/2.624390ms，Adaptive=2.447771/2.412900/3.360455ms。包含预处理/推理/后处理及结果格式校验，不含读写和指标。不是物理相机或控制端到端时延。

参数在得分前冻结，无扫描、未看结果修改。Otsu source帧153空预测的连通区域诊断如实保存，没有删除失败。所有18帧及两种预测展示在review.html。

n=1不给跨采集CI/p值，不作最终最优算法结论。尚无U-Net训练/权重、背景差分匹配参考、真实测试集、跨批次/跨芯片精度或毫米误差。人工审核来自用户，未编造双人一致性或审核人员身份。

## 运行与回归入口

```powershell
python -m unittest tests.test_segmentation_research -v
python -m unittest tests.test_segmentation_research tests.test_camera_dataset tests.test_pilot_annotation tests.test_pilot_annotation_gui tests.test_chapter2_adapters tests.test_chapter2_runner tests.test_vision_framework tests.test_chapter2_evaluation_regressions -v
python -m compileall -q main.py app_controller.py run_segmentation_pilot.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

实际数据运行命令、逐图/视频/计时CSV、参数和hash均见结果包README和manifest。最终完整回归与保护核验见本轮交付验证记录，不沿用历史546项作为新测试结论。

## 下一步

先扩充形态/成像覆盖并尽可能加入独立采集材料，形成可冻结的分组协议；不能把同轮18图随机拆成train/val/test。开发当前仅有Pilot与基线评测，不声称完整训练导出流程已完成。U-Net网络/同步增强/验证选择/导出在数据和评测目标就绪后继续，保持现有RGB/NCHW、归一化、logits/probabilities、阈值与原尺寸恢复契约。正式Fig.A–D后置，不用当前开发指标代替独立测试。
