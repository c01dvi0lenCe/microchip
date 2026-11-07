# 第二章图像—电极配准第一批：真实视频帧核对工作包

## 结论与真实完成状态

已完成独立离线配准工具、人工点位核对界面、真实视频来源验证、3组初始轮廓叠加与点位导航。**尚未完成人工拟合点/独立检查点核对，不存在可报告的真实配准精度。** 当前3份结果状态均为pending_fit，RMSE/P95/max为null；不将旧四角拟合残差当作配准误差，不将软件合成测试当作实物成果。

用户2026-10-22明确：清晰无液滴照片不是工业相机拍摄，工业相机目前只有视频。本轮排除该照片、设计截图、示意图和带CN编号的裸接触板视频；仅采用既有真实工业相机AVI的原尺寸帧。

## 实际材料

设计地图：`D:/Learn/ZJU/第二章 单液滴视觉闭环/电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1/electrode_design_map.json`。
SHA256为`04ebb54420037d05849d5e4af04c18bce2bd54d9b3090e07b7e1a89dda25c437`，版本`2026-10-21_fbc6_3_user_confirmed_v1`。源manifest全部7项hash通过，420编号、实际轮廓与毫米设计坐标保留；没有重新生成地图。

| 原视频 | 帧号（0-based） | 原尺寸 | 重新解码与PNG逐像素比较 | 新点位 |
|---|---:|---|---|---|
| camera_20261013_152806_975638 | 10 | 5472×3648 | 一致 | 8fit/16check均pending |
| camera_20261013_154518_384889 | 636 | 5472×3648 | 一致 | 同上 |
| camera_20261014_112318_257662 | 665 | 5472×3648 | 一致 | 同上 |

原视频SHA256与既有resource_manifest一致；参考PNG复制前后hash一致。没有裁切、缩放原图、颜色增强或修改原视频。新图稿的纸面采样不改变保留的原尺寸PNG。

工作包：`D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-22_工业相机视频帧_点位核对_v1`。
默认`启动配准核对.cmd`打开第一张图；其他两张单独入口。包内README说明逐点操作、最新报告版本与限制。

## 新增代码/接口

- `dmf/vision/design_registration.py`：设计地图hash/420编号/单位/轮廓校验；`project`复用既有投影检查；`fit_transform`只读已确认fit点；`freeze_fit`冻结矩阵与拟合记录；`record_observation`要求实际点选与审核来源；`evaluate_registration`保留缺失/排除分母；`seal_evaluation`在首次完整误差暴露前锁定检查点。
- `dmf/vision/registration_workspace.py`：`prepare_workspace`输入只读预检后创建新目录；预声明8fit/16check且都绑定实际轮廓顶点；导航/观测列严格分离；`load_workspace`检查原图/地图/实际顶点；`save_workspace`拒绝外部并发覆盖；`build_report`创建新版本快照、CSV、JSON、图稿和代码/资源hash。
- `dmf/vision/registration_gui.py`：复用原`ImageCanvas`原图缩放/滚动，提供具体设计顶点参考、人工重新点击、确认、冻结、排除原因、另版报告；审核过程中不显示检查残差。
- `dmf/vision/registration_plotting.py`：单幅真实图像核对板，完整420多边形；SVG/PDF/600dpi PNG，183mm宽，7pt以上可编辑文字，无未经验证的mm比例尺。
- `run_design_registration.py`：独立prepare/review/build命令，不打开相机、串口或实时控制入口。
- `tests/test_design_registration.py`：22项纯几何与审核保护测试。
- `tests/test_registration_workspace.py`：12项文件、来源、图稿、CLI和隔离Tk进程测试。
- 新设计说明与执行计划，当前记录和实现状态说明；没有修改既有控制或推理实现。

## 统计语义

图像坐标为原尺寸像素(u,v)，左上原点，u向右、v向下；设计坐标为已确认地图的毫米(x,y)，核心理想网格左上原点，x向右、y向下。H为图像→设计，逆H投影全部实际轮廓。单应拟合使用全部已确认fit点，method=0，不用检查点做RANSAC/inlier筛选或模型选择。

拟合点和检查点的身份/实际设计顶点先于新像素观测冻结；重复设计点、共享特征、退化点集、非法H、非有限值及越界观测拒绝。旧四角仅生成navigation初始化，不能填入observed_px。检查点只能在fit冻结后点选；修改冻结fit或已曝光评价的check会报错。

全部检查审核完成后，对确认点计算欧氏像素重投影误差和设计毫米残差；RMSE=sqrt(mean(e²))、P95=linear分位数、max为最大值。保留check_total/confirmed/missing/excluded和每个排除原因；缺失时不悄悄缩分母或输出“正式精度”。不足12确认点/存在排除/拟合不足8点时仅描述性结果。记录设计点是否位于拟合凸包外。

当前每张图实际是0/8新fit、0/16新check，所有独立精度均空。3张图同芯片/同次加液/同轮采集，独立采集组n=1，不制造跨批CI或显著性。

## 运行命令

```powershell
python run_design_registration.py prepare --design-dir 'D:/Learn/ZJU/第二章 单液滴视觉闭环/电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1' --pilot-workspace 'D:/Learn/ZJU/第二章 单液滴视觉闭环/真实分割研究/2026-10-21_第一阶段与Pilot_v1/pilot_annotation/workspace.json' --resource-manifest 'D:/Learn/ZJU/第二章 单液滴视觉闭环/真实分割研究/2026-10-21_第一阶段与Pilot_v1/resource_manifest.json' --output '<新的不存在的输出目录>'
python run_design_registration.py review 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-22_工业相机视频帧_点位核对_v1/camera_20261013_152806_975638/workspace.json'
python run_design_registration.py build 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-22_工业相机视频帧_点位核对_v1/camera_20261013_152806_975638/workspace.json'
python -m unittest discover -s tests -p '*registration*.py' -v
python -m compileall -q main.py app_controller.py controllers dmf simulation validation run_design_registration.py
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

本机实际使用`E:/Dev/Python/Python314/python.exe`，包含NumPy/OpenCV/Pillow/Matplotlib/Tk。prepare拒绝覆盖现存版本；build每次生成新目录。

## 实际验证

- RED：新增模块前18项几何测试因功能缺失全部失败；工作包功能前10项失败；图稿/GUI前2项缺功能失败；评价锁定前2项失败。后续全部GREEN。
- 新增局部34项通过，最终6.726s、exit0；包括手工0/5/10/0像素误差的RMSE=sqrt(125/4)、P95=9.25、max=10验证。**这些数值只用于软件单元测试，不是实物结果。**
- 全量608项，607通过、1项DMF_FFMPEG可选集成测试跳过，144.508s、exit0。
- 编译和`git diff --check`通过；独立move/mix/split/loop/CSE/ZJU/CSC七条软件链通过，没有运行真实硬件。
- 进入本轮前102份既有dmf/controllers/simulation/configs代码配置hash与结束时一致。既有19份tracked修改及所有旧untracked成果保留；只新增离线模块、测试和文档。HEAD未变，没有commit/push。
- 六张最终图字号≥7pt，碰撞审计各0 FAIL/0 WARN；单图alignment不适用。两项静态WARN（无TIFF、变量宽度）有明确说明，实际交付为用户所需SVG/PDF/600dpi PNG，PDF宽183mm。逐图QA见工作包`figure_qa.md`。
- 首版图的381/400编号曾压线，已改为外侧引线并重新导出审计；旧过程稿保留但不作为最新交付。

## 后续验收缺口与风险

1. 人工点位未核对：当前不能报告RMSE/P95/max，不能宣称图像—电极配准完成。请先完成默认第一张；不可见拟合点应换帧/重新预声明点集，不可猜测补点。
2. 真实图像核心边界弱、锯齿顶点细小，存在点击不确定性；需要重复点选或第二审核人评估标注一致性，不能只看overlay“差不多”。
3. 平面单应未包含镜头畸变、FPC翘曲和折射；独立残差若有系统空间模式，应另立模型/采集方案与新检查集，不能用原检查点调好模型再报告独立精度。
4. 设计毫米非独立物理长度标定，不能升级为真实毫米计量准确度；Gerber精度也不代表制造精度。
5. 同一采集组n=1，仅能做该组内配准一致性描述；跨芯片/装夹/采集的泛化尚未验证。
6. 当前自动流程支持完整误差表，但正式论文误差图和最终版叠加尚待真实点位确认；没有使用示意图、合成点或自动导航位置冒充实际观测。

原运行配置、GUI主程序、U-Net、五状态/闭环控制、AM/STM32协议和第三章未修改；原Fig.2-4及已有正式仿真结果未改。

## 同日启动入口修复

用户报告双击cmd无法打开。已按真实双击工作目录复现exit2：`'l' is not recognized`、切换目录失败，随后Python在工作包目录找不到`run_design_registration.py`。同一真实5472×3648工作包直接加载及Tk初始化成功，确认问题在启动文件而非图像/点位/配准算法。

根因是手工生成的UTF-8批处理只有LF换行，Windows cmd在代码页切换后误解析后续行。新增`write_review_launcher`明确生成UTF-8/CRLF批处理，并使用主程序绝对路径；prepare现自动生成启动入口，修复现有3个cmd，不改任何workspace点位记录。新增真实Windows cmd解析回归，从带中文/空格且非仓库的目录执行受控诊断CLI，验证argv与退出码；另验证prepare确有双击入口。两项先RED后GREEN，最新局部36项通过（7.831s）、diff检查通过。原全量608项结果为入口修复前记录，未将其冒充新610项全量结果。

真实核对窗口已在诊断期间成功启动（窗口标题“第二章 图像—电极配准：独立点位核对”）。启动修复函数只重写3个cmd，不写workspace；结束核查发现第一张已在界面中保存8个确认点并冻结拟合，因此其hash发生正常进度变更，已保留、不覆盖；另外两份workspace hash不变。当前第一张进入检查点核对阶段，不能沿用初始0点状态描述当前进度。没有改控制/标定算法，没有commit/push。
