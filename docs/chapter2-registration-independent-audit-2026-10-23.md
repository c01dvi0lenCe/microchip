# 第二章配准独立复核与最终装置准备记录（2026-10-23）

## 实施边界

用户批准在原冻结预实验之外创建独立审查包及盲法两轮点选入口。不重新生成420地图，不修改AM、STM32、U-Net、五状态、控制、正式仿真或第三章，不commit/push。

结果目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_配准独立复核与最终标定准备_v1`。原工作包及全部原坐标保持不变。

## 数值与统计复核

读取第一张5472×3648照片已封存的8fit、16check及H。独立NumPy齐次乘除不调用原project/evaluate/fit计算误差；原loader只做来源、顶点和冻结一致性校验。像素残差为inverse(H)投影设计点减人工像素；设计mm残差为H投影人工像素减Gerber设计点。两者单独报告，均不构成独立物理计量精度。

RMSE=1.9680808571533852px、P95=3.058459119862969px、max=3.132176474543148px；检查点16/16、缺失0、排除0。逐点和汇总与原报告最大差约8.31e-13px，满足1e-9计算一致性容差，不是相机精度门限。

预声明分区为核心实际包围盒中央50%矩形/其余核心/外围，点数2/10/4，RMSE分别0.908457/2.275169/1.462785px。中心仅2点，不做区域优劣泛化。图像v与dv的描述性Pearson r=-0.7012；半径与误差模长r=-0.0118。半径起点是图像几何中心，不是已标定光心；16点不能区分或排除畸变、平面/制造误差及人工偏差，没有新畸变系数、CI或p值。

## 实际文件与接口

新增代码：

- `dmf/vision/registration_audit.py`：`homogeneous`/`recompute`独立算术；`audit_workspace`读取冻结来源并与旧结果逐点比较；`audit_dataset`检查现有视频/Mask；`final_manifest_template`/`validate_final_binding`提供最终装置离线拒绝校验。
- `dmf/vision/registration_repeatability.py`：新盲法数据结构、两轮原始坐标及动作记录、逐轮封存、保存冲突保护、缺失分母、两轮完成后才汇总；复制原图/地图但不复制原H/观测/导航点。
- `dmf/vision/registration_repeatability_gui.py`：复用ImageCanvas和设计顶点参考绘制，只显示当前草稿，不显示叠加、预测或原/其他轮坐标。第一轮封存前不能进入第二轮。
- `dmf/vision/registration_audit_plotting.py`：16点向量和三幅位置/半径诊断单图，SVG/PDF/600dpi PNG，箭头显式放大80倍。标签按最终渲染框避让，不改数据。
- `run_registration_audit.py`：prepare/review/repeat-report独立CLI，无硬件依赖；输出新目录、重复性报告自动时间戳，不覆盖已有结果。
- `tests/test_registration_audit.py`：22项软件测试，手算向量、单位/方向、旧报告比较、缺失保分母、盲法内容隔离、原始点击、轮次顺序、封存/篡改/冲突、真实来源复制和隔离Tk/导出测试。fixture全部为软件合成材料，不进入真实审查结果。

新增设计与执行计划在`docs/superpowers/specs/2026-10-23-registration-independent-audit.md`、`docs/superpowers/plans/2026-10-23-registration-independent-audit.md`。文档状态更新仅叠加本轮事实，原记录保留。

结果包包含：数值复核报告、逐点/分区CSV和JSON、原始fit记录/H、视频与Mask来源表、人工重复性待采集报告、畸变风险、最终装置SOP、无效manifest模板、采集分组说明、Fig.2-8面板和图注建议，以及独立两轮点选工作包。最终图在`final_figures_v3`；根目录初稿及v2过程稿保留，不用于交付。

## 数据衔接的实际审查

10段原视频当前SHA256均与既有来源记录一致。沿用原资源元数据，不冒充本轮全帧解码；没有可信逐帧曝光sidecar。18张审核Mask均可读取、0/255、尺寸匹配，来自152806/154518/112318三个原视频各6张。18图均Unknown、unassigned，用户确认同芯片/同次加液/同轮，独立采集组n=1。

Unknown不影响分割Pilot，但Mask只有绑定相应视频/ROI/坐标域的有效配准才可做空间映射；本照片H未绑定旧视频。没有新模型、训练、推理或性能结果。建议下一批先补60–90张分层代表图和独立加液/装夹材料，而非大量相邻帧；数量只是开发计划，不保证泛化或统计效力。

## 实际验证

- 首批缺模块测试RED，新增功能后GREEN；模板误接受/盲法H注入两条行为测试RED→GREEN；默认新目录报告测试RED→GREEN。
- 本轮22项新增测试通过；配准局部共70项通过，22.941s。
- 全量644项：643通过、1项可选FFmpeg跳过，205.523s、exit0。已有PyTorch/Python3.14弃用警告保留，没有为了通过而更改既有阈值或控制模块。
- compileall、git diff --check通过；move/mix/split/loop/CSE/ZJU/CSC七条独立软件链均通过，不是实物闭环。
- 真实原尺寸照片在隔离、隐藏Tk核对窗口加载成功：shape=(3648,5472,3)，两轮0/0，无H，无草稿/历史标记。软件fixtureUI同样隔离测试，未假造实际人工操作。
- 进入本轮前290份保护基线文件hash全部不变，含既有代码/配置、原视频、原审核资料及旧照片预实验工作包；HEAD仍为fe9699d7e6867ee8897056b122c8248153cadd3e。未commit/push。
- 四张v3最终PDF逐张字号/碰撞检查：最小7pt，0 FAIL/0 WARN。原图标注向量图183×145mm，其余单图130×100mm；600dpi PNG与可编辑SVG/PDF齐全。静态图源19 PASS/2 WARN/0 FAIL：无TIFF（本轮要求PNG）及尺寸表达式误判；实际PDF尺寸已核验。单图对齐NOT APPLICABLE。四张PNG均逐图查看。

## 尚未完成，不能冒称

1. 两轮人工重复点选目前0/16、0/16，所有重复性数值null；用户需点选、封存后导出。不计为新独立实验。显示盲法不能消除用户已见过旧结果的记忆影响。
2. 最终相机/镜头/高度/盖板等元数据尚缺，manifest模板不含有效H；最终标定、畸变板验证及物理毫米精度未完成。
3. `validate_final_binding`只作离线准备，未接入现有在线加载或控制流程，不能宣称已有在线防误用保护。SOP明确几何改变/不合格时停止复用并重标定。
4. Fig.2-8交付为单图素材和面板建议，不是假装正式最终装置论文定稿；重复性面板待真实数据。

## 运行命令

```powershell
python run_registration_audit.py prepare --help
python run_registration_audit.py review 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_配准独立复核与最终标定准备_v1/盲法重复点选/repeatability.json'
python run_registration_audit.py repeat-report 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_配准独立复核与最终标定准备_v1/盲法重复点选/repeatability.json'
python -m unittest discover -s tests -p '*registration*.py' -v
python -m compileall -q main.py app_controller.py controllers dmf simulation validation run_registration_audit.py
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

本机Python为E:/Dev/Python/Python314/python.exe。用户优先使用CRLF双击入口。prepare参数来源和所有输入hash记录在独立审查包manifest/JSON；需重跑时使用新输出目录。
