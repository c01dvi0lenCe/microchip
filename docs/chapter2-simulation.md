# 第二章：单液滴视觉状态识别与事件驱动闭环算法仿真

## 交付边界

这是独立、自动运行的 **simulation**，不是实物闭环、真实视频实验或U-Net训练结果。新增CLI及`dmf/chapter2_sim/`，不接入串口/相机SDK，不修改第一章AM刷新接口、既有实验控制器或第三章多液滴调度。当前界面没有新增按钮；通过命令运行。

以本地实际基线`fe9699d7e6867ee8897056b122c8248153cadd3e`为准；历史`e1987775fb4b9ce6de8798d818545761aac7e8b3`仅用于了解第二章实验模式起点。后者与当前代码已有大量差异，未回退旧实现。此次代码均为新增文件，原有已跟踪运行文件无diff。未经用户确认，不commit/push。

## 模型、地图与接口

| 文件 | 职责 |
|---|---|
| `run_chapter2_simulation.py` | 独立CLI，冒烟/配对批量/扫描/绘图 |
| `configs/chapter2_simulation.yaml` | 显式`mode: simulation`及可重复参数 |
| `dmf/chapter2_sim/config.py` | 冻结配置、类型和范围校验 |
| `dmf/chapter2_sim/geometry.py` | 只读适配既有420电极地图、掩模栅格及快照 |
| `dmf/chapter2_sim/world.py` | 有限速度、动作延迟、扰动、停滞/偏离/失败及隐藏物理参考 |
| `dmf/chapter2_sim/vision.py` | 合成相机、曝光/处理时间、掩模及空间时序特征 |
| `dmf/chapter2_sim/control.py` | 五状态+独立Unknown、连续窗口、A/B/C及有界恢复 |
| `dmf/chapter2_sim/runner.py` | 虚拟时钟、因果事件队列、闭环执行、原始记录和评价 |
| `dmf/chapter2_sim/batch.py` | 配对seed、汇总/95%CI、配对差、配置/源码溯源 |
| `dmf/chapter2_sim/plotting.py` | 四类PNG/PDF/SVG、对齐检查及图表溯源 |
| `tests/test_chapter2_sim.py` | 物理/观测/控制、旧帧/丢帧、外部地图及边界回归 |
| `tests/test_chapter2_sim_batch.py` | 分母、缺失/删失、配对、统计和溯源回归 |
| `tests/test_chapter2_sim_plotting.py` | 实际图表导出和输出哈希回归 |

公共入口：`run_trial(config, scenario, seed, method) -> TrialResult`。结果包含`metrics`、逐帧`frames`、逐积分步`truth`和控制`events`。控制模块只读观测，不读取隐藏位置或真值。

默认使用仓库既有420-ID模板，包含非规则外围/L形结构，但**不是已独立确认的实测几何地图**。坐标均为归一化电极节距`pitch`，不把旧模板中的毫米参数当作本次实测尺寸。全部420多边形进入快照；当前路线只支持手工给出的核心区相邻ID，不模拟外围储液池出液。

可在YAML中设置`map_path`，相对路径相对配置文件目录解析。沿用既有地图的`core_corners_px`和`pixel_overrides`格式；实际像素多边形通过配准变换映射为pitch，不使用可能仍为模板的`polygon_mm`。外部地图也不自动认证为实测，记录校准覆盖数和来源。测试用外部多边形只是构造样例，不是新增标定成果。

二维运动受控制目标真实反作用：模拟APPLIED延迟后切换吸引目标，再经响应延迟，以有限速度运动。Retry重新激活可解除所设定的首次可恢复钉扎；Recovery返回当前任务源区；Hold不撤销目标。永久失败不因重试变为成功。没有调用A*、全局重规划或多液滴模块。

相机按帧索引预生成扰动、丢帧与处理延迟；使用圆形合成分割掩模代理。曝光起止、可用时间、控制处理时间分别记录。位置取曝光结束附近积分网格值，量化误差上界`dt_s`，不声称模拟真实曝光积分/运动模糊。

## 特征、状态与因果控制

令液滴掩模为D，电极区域为E：

- `eta_target/source = |D∩E|/|D|`：分母为液滴面积；`eta_source`也是源区残留比例。
- `rho_target/source = |D∩E|/|E|`：分母为电极面积。交集像素、液滴面积也保留。
- 保存质心、目标中心距离、源→目标方向投影进展（pitch及归一化比例）、有符号横向偏差。
- 速度由相邻有效曝光时间差计算，保存速度模长和沿任务方向速度；时间倒退无效，过大间隔不伪造固定帧率速度。

Stationary/Moving由有效速度判别；Partial识别目标部分覆盖且源区仍残留；Arrived由目标覆盖、源区释放、目标距离和连续窗口共同确认；Deviation要求连续有效观测离开任务走廊。无掩模、曝光不合法、孤立空间冲突和速度证据不足使用独立`Unknown`，不作为真实Deviation。没有强制五状态顺序，允许合法跳转。

C组默认至少5个连续捕获ID、持续至少0.25 s、窗口质心跨度不超过0.11 pitch。20 fps下通常需要6帧才能覆盖0.25 s。缺失捕获ID、超时隙或无效观测会断开证据；重复/逆序旧帧不能增加计数。低帧率若超出允许间隔会保护停止，而不是悄悄放宽连续条件。

每次Start/Retry/Recovery/Resume均建立新epoch并清空识别历史。曝光**开始**早于当前模拟APPLIED的帧、逆序/重复帧、过期帧不得触发Update；已消费步骤只更新一次。重试仍保持当前目标，局部Recovery明确切换回源。模拟APPLIED只代表虚拟电极应用，不代表到达；本模块没有真实ACK解析/串口事务重传试验。

| 组别 | 更新条件 | 公共保护 |
|---|---|---|
| A | 每步固定1.2 s，无视觉反馈决策 | 全局仿真时间上限 |
| B | 当前单帧满足位置/覆盖/源区释放即更新 | 与C相同的超时、停滞、Retry和局部Recovery预算 |
| C | 任务空间约束+连续时序稳定后更新 | 默认每步至多2次Retry、1次Recovery，观测超时/恢复失败保护停止 |

Recovery返回源的确认使用稳定窗，是B/C共用的安全保护；B的前进更新仍为单帧。计时/无进展保护使中途停滞不会无限Hold。默认路径3步，统计的总Retry次数可超过2，因为预算按步骤分别计算。

## 独立仿真真值和公平比较

隐藏物理参考到达事件：进入目标中心半径0.09 pitch范围，真实速度≤0.06 pitch/s，并连续驻留0.15 s。三组和阈值扫描共用该定义。物理世界不读取覆盖率、识别状态、`arrival_coverage`或`stable_duration_s`；控制器不读取隐藏参考。它是**预先规定的仿真评价参考**，不是实物人工标注，也不是控制器输出自生成真值。

三组相同场景、参数、路线、配对seed；环境扰动按物理tick和相机帧索引预生成，不因控制器多发一次动作而改换随机数流。因动作不同造成的轨迹分叉是闭环结果，不强迫三组复用同一条不可反作用轨迹。

路径完成率要求所有计划步骤均更新且无提前更新。提前更新分母默认是**所有计划运输步骤**，同时另存以已发出Update为分母的比例，避免停止策略通过隐藏未尝试步骤得到虚高成功率。确认延迟是Update时间减独立参考到达事件，仅对已实际观察到的确认计算；保留未确认到达（删失）、尚未到达、未尝试和缺失数量，不填0。均值先在seed内计算，再在seed间汇总，因此是有条件的seed均值，不是所有步混池均值。

路径完成率使用Wilson 95%CI；提前率按seed整簇bootstrap后重新计算分子/分母；时间、Retry、Recovery、条件确认延迟及配对差使用seed级bootstrap（2000次）。零事件的bootstrap区间可能退化为[0,0]，不能解释为真实风险上界为零。`paired_differences.csv`保存B−A/C−A/C−B，同seed缺失延迟对不填补。

## 运行方法

在仓库根目录、安装仓库依赖并可用NumPy/OpenCV/PyYAML/Matplotlib的Python环境中运行：

```powershell
# 先测试最小闭环
python -m unittest tests.test_chapter2_sim tests.test_chapter2_sim_batch tests.test_chapter2_sim_plotting -v

# 快速冒烟（新输出目录；拒绝覆盖既有结果）
python run_chapter2_simulation.py --output results/chapter2_smoke_new --seeds 1 --scenarios normal partial_stall dropout --no-plots

# 七场景×20配对seed×A/B/C；另加C组3×3×20阈值扫描
python run_chapter2_simulation.py --output results/chapter2_run_new --seeds 20 --sensitivity
```

参数扫描仅在核心单元测试和实际闭环冒烟通过后开展。可用`--config`、`--seed-start`、`--scenarios`、`--no-plots`控制运行，详见`--help`。没有硬件输出选项。

## 本次实际运行结果（2026-10-20）

正式结果目录：`results/chapter2_simulation_20261020_final/`。固定路线190→191→192→172，seed 260600—260619。主比较420 trial；阈值扫描180 trial。`illustration/`是同seed的可复现示例副本，不计为额外独立样本。之前的smoke和初版输出保留，不混入正式统计。

下表为严格路径完成数/20；每条路径3步：

| 场景 | A固定时间 | B单帧 | C事件驱动 | C提前更新/计划60步 |
|---|---:|---:|---:|---:|
| normal | 19 | 0 | 20 | 0/60 |
| delayed | 0 | 0 | 20 | 0/60 |
| partial_stall | 0 | 0 | 20 | 0/60 |
| jitter | 19 | 0 | 0 | 0/60 |
| dropout | 19 | 0 | 17 | 0/60 |
| deviation | 0 | 0 | 20 | 0/60 |
| failure | 0 | 0 | 0 | 0/60 |

C正常场景平均终止时间3.628 s（95%CI 3.504—3.756），条件确认延迟0.155 s（0.135—0.178），平均Retry=0。正常/延迟/停滞/偏离的路径成功率为100%，但20个seed的Wilson区间仅83.9%—100%；丢帧85%（64.0%—94.8%）；强抖动和永久失败0%（0—16.1%）。所有组完整数值与置信区间见`summary.csv`，不只看成功样本。

不能据此写“C普遍最优”：C强抖动场景0/20，而A为19/20；C以较长等待/重试换取避免提前推进，在丢帧场景也有3条路径未完成。C强抖动的4.12 s条件延迟仅来自1个seed中的1个已确认步骤，不是20条路径的平均延迟。B的大量提前更新源于本模型中单帧几何满足早于独立速度/驻留参考，不能外推为所有单帧算法实物成功率为0。

阈值扫描固定强抖动场景，覆盖门0.65/0.85/0.95、稳定时长0.25/0.4/0.6 s。九格路径完成率与提前率均为0，图上显式标0%。这不是“阈值鲁棒”证据：默认圆形掩模下距离门/源区释放门使覆盖门高度冗余，强抖动又主要破坏稳定跨度。需要后续独立设计跨度/定位噪声/时间窗扫描；本次不在看到结果后调参制造优势。

## 结果文件与图表

- `trials.csv`：逐seed逐方法全部指标和终止状态。
- `frames.csv`：曝光/可用/处理/APPLIED、epoch、validity、状态、特征和动作。
- `truth.csv`、`events.csv`：隐藏轨迹/速度/参考到达、动作及未确认删失事件。
- `summary.csv/json`、`paired_differences.csv`：汇总、95%CI、缺失分母和配对差。
- `config_snapshot.json`、`electrode_map_snapshot.json`、`manifest.json`：完整参数、420多边形、seed、源码SHA256、共享地图源码、依赖版本及运行命令。
- `sensitivity/`：180次扫描指标、九格汇总、参数和溯源。
- `figures/01_trajectory_simulation.*`：预先选择partial_stall、首个seed的A/B/C轨迹，不挑最好seed。
- `figures/02_state_timeline_simulation.*`：同一C试验的状态/特征/动作；横轴为处理决策时间。
- `figures/03_control_comparison_simulation.*`：六面板性能和95%CI，包含失败，耗时是**终止时间**而非成功运输速度。
- `figures/04_threshold_sensitivity_simulation.*`：九格真实统计，保留全零结果。
- `figures/figure_notes.md`、`figure_manifest.json`和QA文件：图注边界、输入/绘图源与输出哈希、对齐/文字/碰撞核查。

按科研绘图工作流保留逐panel证据与不确定性，输出可编辑PDF/SVG及300-dpi PNG预览。PNG非600-dpi投稿TIFF；硕士论文线图优先用矢量PDF/SVG。字体最低8 pt；最终四图须通过对齐、PDF文字和碰撞检查并人工审视。所有图题明确SIMULATION。

## 验证与局限

新增测试覆盖整数预算校验、外部多边形、动作反作用、独立真值、双面积分母、曝光速度、旧帧/逆序/重复、连续捕获ID、无效观测不判Deviation、停滞重试/局部恢复、永久失败预算、延迟删失、配对统计、依赖/源码溯源和真实图表导出。另按AGENTS.md运行全量编译、unittest和七项独立链路验证；最终运行数量见交付回复。

最终验证：新增33项全部通过；全量`python -m unittest discover -s tests -q`运行385项，384通过、1项因未设置`DMF_FFMPEG`跳过（65.411 s，exit0）；compileall通过；独立链路move/mix/split/loop/CSE/ZJU/CSC共7/7通过。四图PDF最小字体8 pt、碰撞0 FAIL/0 WARN；三张多panel图对齐PASS，单panel轨迹图不适用。源码和主输出/图表哈希均匹配，重复运行的全部主原始CSV完全相同。

回归异常透明记录：此前一次全量测试出现Tk `Variable.__del__`非主线程清理异常及`Tcl_AsyncDelete`，未正常结束；相关9项GUI测试独立通过，最终全量复跑通过，但仍打印旧GUI `after`回调销毁后的非致命警告。未在本次修改原有GUI/AM/第三章代码，不能声称此GUI清理问题已修复。

当前局限：简化质点吸引模型，无EWOD多物理场/接触线/液滴形变和体积守恒；圆掩模误差不覆盖真实U-Net漏分/反光/粘连等误差；参数未经实测辨识；仅3步核心区路线；未估计实际相机/串口端到端延迟；没有真实人工到达标注或完整五状态混淆矩阵；未验证电压、安全释放与AM时序。初始液滴假定已位于源中心，没有独立的初始实物检测阶段。

下一阶段应使用独立人工复核的真实连续视频/曝光日志和命令ACK，固定人工到达区间及标注规则后再评测；将U-Net预测掩模接入相同观测接口，并单独报告分割与控制误差。不得把这里的synthetic mask性能当作U-Net精度或实测闭环成果。
