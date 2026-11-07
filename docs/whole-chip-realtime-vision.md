# 整芯片U-Net检测：运行与异机部署

## 当前功能边界

本功能只负责图像感知：完整相机图像→分块U-Net→原尺寸二值Mask→全部连通域、轮廓与质心。它不向电极事务发送请求，不提供M3闭环输入，不根据检测结果推进开环任务。停止检测不停止相机、录像或定时任务。STM32无需因本功能重新烧录。

界面中的“实时”指持续接收最新图像并后台检测，不承诺每个相机帧均被处理。5472×3648原图需150块；检测吞吐量、接收帧率、输入年龄须分别观察。当前本机完整图像处理为秒级，不能据此启用短窗口闭环控制。

## 另一台电脑安装

1. 使用64位Windows及Python 3.14，检出`codex/whole-chip-realtime-vision`分支。
2. 双击仓库根目录`setup_vision_env.cmd`。此入口建立独立`.venv-vision`并安装`requirements-vision.txt`中的G4匹配依赖；不改变普通上位机的Python环境。CUDA不可用时采用CPU，速度需要实测。
3. 单独复制推理模型文件夹到`models/g4_unet`，其中必须有`manifest.json`与`unet_state.pt`。也可启动后通过“模型包／选择”指定外部文件夹。权重、训练状态、SDK、视频和人工GT均不随Git分发。
4. 在相机电脑安装厂商MVS及其Python绑定。复制`configs/camera_mvs.local.example.yaml`为`configs/camera_mvs.local.yaml`，按实际安装填写SDK的`MvImport`文件夹与相机序列号；共享模板中的两个字段为空。
5. 双击`start_vision_gui.cmd`。预检会报告依赖、模型校验、CUDA及SDK绑定路径，但不会连接相机或串口。缺少模型或SDK时仍可进入普通上位机；缺少基础GUI依赖时明确报错。
6. 人工开启相机预览，等待真实图像后点击“启动检测”。按需切换“原图／叠加／Mask”。自动视觉控制仍保持禁用；本阶段不要求连接串口。

```powershell
git clone --branch codex/whole-chip-realtime-vision https://github.com/c01dvi0lenCe/microchip.git
cd microchip
.\setup_vision_env.cmd
.\start_vision_gui.cmd
```

若使用已有兼容环境，可运行`python scripts/vision_preflight.py --model-package <模型包目录>`再运行`python main.py`。不要将未经检查的任意训练checkpoint当作推理包加载。

## 本次模型迁移清单

模型来源：2026-11-05 G4匹配训练U-Net，最佳epoch 16。推理包不含优化器与训练随机状态，仍使用原始权重及预处理，不重新训练。

|文件／内容|校验信息|
|---|---|
|`unet_state.pt`|SHA256 `7f66da9108fcadb1b32c577a8a3142b7295e00a4b7705bcca94871bd77cd5578`|
|来源`best.pt`|SHA256 `06a26187ab6ab3c0fe3924fb8d24201fb2ad547f5fbe7113414a1bcd680aa0ef`|
|训练协议|SHA256 `b89b997e4478ef470b9dbb119f7b956a0a62f53428d4cc8ae5b9f76b9489675f`|
|包中manifest|包含来源、权重摘要、架构和完整预处理契约；加载前检查|

本机模型包保存在章节资料目录`真实分割研究/2026-11-07_整芯片检测_G4推理模型_v1`。此路径仅供本机取件，不是异机运行依赖。

## 检测与显示规则

- 默认处理完整原图；“整芯片范围”仅可排除芯片外背景，应包含核心及外围电极，不是只选单个液滴。检测运行期间不能修改范围。
- 512×512原生块、384像素中心有效区、64像素上下文；原图外白色补齐。只回写每块中心有效区，不用重叠Mask并集，不将整图缩为512。
- G4规则为BGR→RGB、ImageNet归一化、512输入、logits经sigmoid后阈值0.5，无新增形态学处理。批量输出与单块有任意二值像素差异即退batch=1；本次120张审计已发现差异，交付配置因此固定默认batch=1，重启仍保持单块设置。不要仅依据启动时少量块相同就重新启用batch4。内存失败不发布半张Mask。
- 所有连通域均保留，包括微小碎片。帧内连通域编号不是持续液滴身份，也不是电极ID；气泡、暗纹理等可能误检，仍需独立GT验证。
- “原图”保持最新预览；“叠加／Mask”显示已完成检测的对应源帧，不能把旧Mask画到新图像上。结果较慢时其输入年龄会持续增加。
- 输入与结果各一个槽位，允许主动跳过旧帧，不积压播放。相机取流、录像、推理与Tk显示分别执行。
- 严重暗图、近全前景、空Mask仅报告诊断，不等于已建立可靠Q门，也不自动更改模型阈值。

## 保存与时间含义

每次检测建立独立`results/realtime_vision/<会话>`，持续保存`frames.csv`、`events.csv`、`components.csv`，停止后生成`manifest.json`。原图、Mask和叠加图仅在点击“保存结果”时写入同一源帧快照，避免默认大量写盘。

设备计数、主机接收时间、当前推理起止时间分别记录。历史录像的原始接收时间不是本次处理时刻，主机接收不是已确认曝光时间。该功能不证明图像发生在真实高压输出之后。

计数分别包括LiveSource覆盖、UI预览覆盖、推理输入覆盖及结果覆盖；`delivered_sdk_number_gaps`是已交付帧号的复合缺口，可能包含上游队列替换，不能当作独立SDK采集丢帧。未独立测得的`sdk_capture_skips`保留未知，而非填0。

## 本机验证与回放入口

```powershell
python -m unittest tests.test_whole_chip_geometry tests.test_g4_model_package tests.test_whole_chip_worker tests.test_realtime_vision_controller tests.test_vision_preflight tests.test_whole_chip_acceptance_cli -v
python scripts/export_g4_model.py --help
python scripts/verify_whole_chip_replay.py --help
```

`verify_whole_chip_replay.py`核对120张原生ROI的G4单块逐像素一致性，随后读取登记视频各前30帧及3个低照度来源帧，保存完整Mask、逐帧日志、配置与来源摘要。无GT的新帧不计算Dice或到达准确率；输出目录须全新，失败记录也保留，不覆盖前次验收。

## 目标电脑10分钟验收清单（尚待实测）

- [ ] 模型SHA、依赖版本、后端与SDK路径检查通过；启动未自动连接串口或相机。
- [ ] 人工开启相机后连续至少10分钟，接收与检测持续运行，原始录像独立。
- [ ] 记录完整图像分辨率、ROI、块数、实际接收FPS、整帧检测FPS、均值/P50/P95耗时和结果年龄。
- [ ] 记录各类队列覆盖、复合SDK帧号缺口、错误、CPU/GPU与显存占用。
- [ ] 叠加与源帧对应；停止检测不影响预览及开环；关闭相机清空检测旧结果。
- [ ] 模型异常／SDK断开可见，无半帧Mask、无界面长时间阻塞，无任何检测触发的电极动作。

以上通过仍只完成阶段A相机感知验收。实际配准、目标身份、真实到达参考、dry_run时序和独立高压安全检查属于后续闭环准入，不能用本机视频回放替代。
