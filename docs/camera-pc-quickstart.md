# 相机电脑：安装上位机并验证 U-Net

适用于 64 位 Windows、64 位 Python 3.14。这个版本支持你开环操作、相机录像、U-Net 检测和同帧结果记录。以下安装和自检不打开相机或串口，不需要重刷 STM32。**不要为了试检测而打开高压。**

只想照着按钮完成本次任务：见[两段视频操作卡、交回文件清单与 Chat 接手任务](camera-pc-two-recordings.md)。本文保留安装、自检命令供相机电脑 Chat 使用。

## 1. 取正确的代码

新电脑用 PowerShell：

```powershell
git clone --single-branch --branch codex/whole-chip-realtime-vision https://github.com/c01dvi0lenCe/microchip.git
cd microchip
```

已有项目先用 `git status -sb` 确认当前分支。如果正是上述分支且工作区干净，用 `git pull --ff-only`；若有本地改动，先保留原项目，另找空目录克隆。不要用强制重置覆盖相机电脑的修改。保留本机 SDK 路径、相机序列号和模型目录。

## 2. 装依赖，放入固定版本的权重

Windows x64 / Python 3.14 的[匹配版本清单](../requirements-vision-win-py314.constraints.txt)随项目提供，安装脚本会同时应用，避免另一天装到不同的间接依赖。

1. 双击根目录的 `setup_vision_env.cmd`，等它提示安装成功。它使用独立的 `.venv-vision`，安装 [日常上位机依赖](../requirements.txt) 和 [视觉依赖](../requirements-vision.txt)，包括 PyTorch、torchvision、segmentation-models-pytorch。安装需要能访问 PyPI 和 PyTorch 的 cu128 软件源；仓库不分发驱动、Python 安装程序或虚拟环境。
2. 下载 [G4 U-Net 推理包](https://github.com/c01dvi0lenCe/microchip/releases/download/g4-unet-inference-v1/g4_unet_inference_v1.zip)。与代码分支分开发布；是原始 G4，不是后续材料扩充训练模型。假设下载到“下载”文件夹，在项目根目录运行：

```powershell
$zip = Join-Path $HOME 'Downloads\g4_unet_inference_v1.zip'
if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne 'abee591817d64853ef71f2ab9b8b947f51a29fff1f1d36646da86704bd422a9b') { throw 'G4 ZIP hash mismatch' }
if (Test-Path -LiteralPath '.\models\g4_unet') { Write-Host 'Model directory exists: verify it below; not overwritten.' }
else { Expand-Archive -LiteralPath $zip -DestinationPath '.\models' }
if ((Get-FileHash -LiteralPath '.\models\g4_unet\unet_state.pt' -Algorithm SHA256).Hash -ne '7f66da9108fcadb1b32c577a8a3142b7295e00a4b7705bcca94871bd77cd5578') { throw 'G4 weights hash mismatch' }
```

权重和 `manifest.json` 应在 **同一层** `models\g4_unet\` 下。若已有包校验失败，先保留旧包，确认来源；不要修改 manifest 来绕过校验。

## 3. 不接任何硬件，先验证模型确实能算

```powershell
.\.venv-vision\Scripts\python.exe -m pip check
.\.venv-vision\Scripts\python.exe scripts/vision_preflight.py --require-model
.\.venv-vision\Scripts\python.exe -c "import numpy as np; from dmf.vision.g4_model import G4UNetPredictor; p=G4UNetPredictor('models/g4_unet', batch_size=1); m=p.predict_batch([np.zeros((512,512,3),dtype=np.uint8)])[0]; assert m.shape==(512,512) and m.dtype==np.uint8 and np.isin(m,[0,255]).all(); print('G4 inference OK:', p.device, m.shape)"
```

三条依次通过才算软件就绪。第二条的 `model_ready` 是文件契约和摘要检查；第三条才真正加载权重并输出一张二值 Mask。输入是合成测试图，这不评价液滴识别准确率。若显示 `cpu`，说明用 CPU 计算，不是 GPU 实时性验收。若只看到 `sdk_bindings_present=false`，离线测试可以继续，取流前需安装本机 MVS 驱动和 Python 绑定。

## 4. 再接相机，先不让视觉驱动电极

- 按[相机接入清单](target-computer-camera-integration-checklist.md)从[海康机器人官网下载中心](https://www.hikrobotics.com/en/machinevision/service/download/)安装与相机匹配的 Windows MVS 和 Python 绑定，填写 `configs/camera_mvs.local.yaml`；勿覆盖已有本机配置。双击 `start_vision_gui.cmd` 打开上位机，手动开启预览。
- **第一段：**串口保持断开，关闭检测与“录像联动检测”，不动电极，录约 32 秒。保留 AVI 与同名全部 CSV/JSON，用[连续性核对说明](camera-recording-30s.md)区分 SDK 交付缺号、本机未写、仅预览被替换。
- **第二段：**空载录像通过后，在正常实验条件下由操作者执行一次单滴开环迁移，同时开启联动检测。保留原视频、时间表、检测会话、实际处理的区域 Mask、电极请求与 APPLIED 记录。不能用 APPLIED 当到达，也不能把检测时间当曝光时间。
- **视觉接管仍未放行：**本次装夹配准、同一液滴身份、任务 ROI 的帧龄和连续有效窗口、真实到达区间与无输出旁路判定，均需另行验收。
