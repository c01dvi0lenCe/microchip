# 第二章清晰照片配准预实验工作包（2026-10-23）

## 批准与边界

用户已确认`照片样本/2026-10-22`两张PNG为工业相机来源，可用于配准；由于最终实验尚需调整芯片高度，本轮明确“先作为预实验”。沿用已有独立配准方案，只补真实照片输入，不重写拟合/状态/控制功能，不commit/push。

当前真实完成的是**预实验材料和人工点位核对入口**，不是已完成的定量精度实验或最终标定。两张新workspace均24点pending，observed_px全null，fit未冻结，RMSE/P95/max全null。没有将初始化四角或投影导航点当作GT。

## 实际来源与输出

原照片均5472×3648、RGB PNG，未提供相机/镜头/曝光内嵌元数据，工业相机来源依据用户确认。两图是同场景材料，不视为两个独立芯片或批次；不生成跨批CI或显著性。

- `camera_20261022_160200_288979.png`：SHA256 `c08cb49f72163a2602444d63e5f3037c6b4f938ab42468ba9a13e90a9d382890`。
- `camera_20261022_160204_057654.png`：SHA256 `650824622f58c268cacea32d021ea83c60239041e751d0559e0cae64712ccbab`。
- 地图继续只读已确认FBC6-3 JSON，SHA256 `04ebb54420037d05849d5e4af04c18bce2bd54d9b3090e07b7e1a89dda25c437`，420多边形和非规则外围保持不变。

新包：`D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_清晰照片_配准预实验_v1`。
包含2张原尺寸复制PNG、确认设计地图副本、资源manifest、配置、各自workspace、Windows CRLF双击入口、CSV/JSON、SVG/PDF/600dpi PNG与QA记录。默认先核对第一张8fit+16check，第二张可稍后重复。

四角`[[1200,580],[3570,620],[3540,2980],[1170,2950]]`仅为助手依据原图作出的导航提议；不是人工校准、不用于正式误差。每张照片都创建新的H初始化与新点位，不继承旧视频H、旧点位或未完成C10。所有原视频点位保留。

## 修改文件与接口

- 新增`dmf/vision/registration_photos.py`：`prepare_photo_workspace(design_directory, inputs_path, output)`。原生PNG/hash/尺寸与确认来源预检，拒绝错误hash、重复ID、非法/越界初始化、覆盖已有输出、非预实验用途；复制后验证hash；复用`point_catalog`、`seal_catalog`及CRLF启动文件。
- 新增`configs/chapter2_registration_photo_preexperiment.json`：两张照片来源/hash、原尺寸和明确未确认的初始化四角，输入配置冻结。
- `run_design_registration.py`新增`prepare-photos`，原prepare/review/build保持兼容。
- `dmf/vision/registration_workspace.py`仅扩展真实图像错误措辞及报告中的预实验用途标记；拟合与评价算法未改。
- `dmf/vision/registration_plotting.py`区分photo与video frame、注明导航初始化来源，增加PRE-EXPERIMENT及非最终标定标记；明亮照片背景上的核心角标改深色。照片不生成假视频帧号或曝光时间戳。
- `dmf/vision/registration_gui.py`仅增加预实验标题/提示；继续复用原点选画布、人工确认、拟合冻结、检查点评价封存和并发保存保护。
- 新增`tests/test_registration_photos.py`12项软件回归；新spec/plan及当前记录，更新实现状态。软件fixture均为合成文件，未作为实测成果。

所有新workspace与报告明确`use_scope=pre_experiment_only`、`final_experiment_calibration_approved=false`、`transfer_to_old_videos_verified=false`、`final_relative_height_fixed=false`；即便日后预实验人工点位全部通过，也不自动授权最终标定。

## 运行命令

```powershell
python run_design_registration.py prepare-photos --design-dir 'D:/Learn/ZJU/第二章 单液滴视觉闭环/电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1' --inputs configs/chapter2_registration_photo_preexperiment.json --output '<新的不存在的输出目录>'
python run_design_registration.py review 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_清晰照片_配准预实验_v1/camera_20261022_160200_288979/workspace.json'
python run_design_registration.py build 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_清晰照片_配准预实验_v1/camera_20261022_160200_288979/workspace.json'
python -m unittest discover -s tests -p '*registration*.py' -v
python -m compileall -q main.py app_controller.py controllers dmf simulation validation run_design_registration.py
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

本机实际Python为`E:/Dev/Python/Python314/python.exe`。已存在目录会拒绝重建；build另存新报告而不是覆盖。

## 实际验证

- 照片适配器缺失时12项测试RED，之后12项全部GREEN（13.453s）。与既有回归合并48项通过（12.466s）。
- 全量622项，621通过、1项可选DMF_FFMPEG集成测试跳过，189.215s、exit0；仍有已有PyTorch/Python3.14弃用提示，不隐藏为实物问题。
- 编译、diff检查通过；move/mix/split/loop/CSE/ZJU/CSC七条独立软件链通过，未运行高压/硬件实验。
- 实际第一张5472×3648照片在隔离Tk窗口成功载入，标题含“预实验”，24点均pending；无假照片对应帧号。
- 进入本轮前111份基线中仅3个预定配准显示/报告模块hash变化；其余108份不变，包括103份原代码/配置、2张原照片及3个旧视频workspace。原控制/推理/地图和仿真均未改。
- 4张最新PDF逐张字号/碰撞审计通过：最小7pt、0 FAIL/0 WARN。纸宽183mm、高142mm，PNG4322×3354/600dpi；单图alignment不适用。静态图源19 PASS/2 WARN/0 FAIL，WARN为无TIFF和变量尺寸，实际按本轮SVG/PDF/PNG核对稿要求交付，PDF尺寸已核实。
- 最新第一张report为`20261023T052502_918069_29b0dc`，第二张为`20261023T052510_806845_abac37`；较早稿保留为过程记录，深色角标新版为交付预览。

## 仍需完成

1. 人工重新点选第一张8fit/16check；导航位置不是GT，不能据初始叠加计算精度。
2. 完成后输出该照片条件下的检查点描述性RMSE/P95/max；缺失与排除保留总分母，不能升级为整个420电极或跨芯片泛化证明。
3. 必要时重复点选/第二审核人评估点位不确定性，检查残差空间模式；不使用检查点反复调模型并仍称独立验证。
4. 最终高度、盖板、装夹和镜头条件固定后另建参考与配准，不直接迁移本包H到旧视频/最终实验。毫米是设计坐标一致性，不是独立物理长度计量。

没有训练U-Net、添加液滴GT、修改五状态/闭环算法、GUI主程序、串口/STM32/AM、第三章或Fig.2-4。所有结果都保留为本地未提交成果。
