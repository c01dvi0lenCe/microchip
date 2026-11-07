# 第二章S2到达事件比较 Implementation Plan（待审，不执行）

> **For agentic workers:** 设计获批后使用`executing-plans`按关执行；不自动委派、不自动提交。以下勾选框仅表示未来实施进度。

**Goal:** 在相同模拟Mask、地图、任务和simulation时钟下比较五种到达门，区分公共W/Q效应与S/K增量。仅输出事件、证据和独立参考评分，不运行闭环策略。

**Architecture:** 新增薄层`dmf/chapter2_sim/s2/`，直接复用v2纯到达门与观测流水线；输入、预测、评分物理分目录。独立S2注册表和评分版本，不修改v1/v2入口、human评分或生产代码。

**Tech Stack:** 现有Python、unittest、NumPy、CSV/JSON、现有Mask缓存及Matplotlib绘图依赖。不新增运动平台、不训练模型。

日期：2026-10-25。**本文件是未来执行规格，不是本轮实施授权。下面的新文件、CLI和测试尚未实现；本轮不运行。** 先审查[研究方案](../../chapter2-s2-arrival-study-design-2026-10-25.md)，再按G0–G5逐关执行。禁止Commit/Push。

- [ ] G0：研究定义审查与保护快照。
- [ ] G1：先写评分失败测试，确认失败，再完成最小独立评分适配并回归。
- [ ] G2：先写五方法契约/隔离测试，确认失败，再实现薄包装并回归。
- [ ] G3：先写像素/时序手算机制测试，再生成小夹具验证可行性。
- [ ] G4：开发seed冒烟，核对完整账本；不自动进入确认运行。
- [ ] G5：另获授权后运行确认seed、只读绘图及全量回归。

## G0：设计确认与保护快照

- 确认五方法、13候选条件、单任务190→191、H=1.00 s与参考区间上界规则；H是到达确认评价预算，不是控制超时。
- S1正式定稿不变；源准备、路径完成、Retry/Recovery不进入S2主评价。旧21三步缓存只作兼容/开发证据，不与新单任务正式样本合池。
- 保存当前Git状态、代码版本及dirty diff/hash、新文件清单；不能只用HEAD代表含未提交修改的实际方法版本。
- 分别保存S1内容hash、原v1/v2文件清单/大小/时间与本研究实际读取的源文件内容hash。检测异常即停，不自动恢复或覆盖用户文件。
- 输出目录使用独立研究ID，已存在且非空则拒绝；resume只接受相同冻结manifest，不静默覆盖。

**验收：** 用户认可设计；所有新运行均有独立目录；没有生产、S1或旧结果写入路径。此关之前不创建可运行S2配置或运行场景。

## G1：先用手算反例固定参考与评分

### 拟新增文件/接口

| 文件 | 接口与职责 | 明确不做 |
|---|---|---|
| `dmf/chapter2_sim/s2/spec.py` | 不可变研究契约、五方法注册表、输入/参考/评分版本；导出公共契约hash和effective_flags | 不放宽v2的旧注册表或开发seed检查 |
| `dmf/chapter2_sim/s2/evaluation.py` | `build_reference(truth_rows, tasks, geometry, reference_spec)`；`score_step(plan, reference_status, first_event, followup, scoring_spec)`；只读评分 | 不读Mask生成参考；不改旧CSV/human评价器 |
| `tests/test_chapter2_s2_evaluation.py` | 独立手算时间与分母用例 | 不调用被测算法反推期望真值 |

参考沿用既有位置/速度/驻留逻辑，适配固定输入truth的step_id、任务目标、模拟Applied和连续tick。参考时刻是**满足驻留后的确认时刻区间**，不是首次进入半径的时刻；同时保留dwell_begin_s。新适配必须与原函数在同一完整truth上的输出逐项对照，不能凭字段重命名宣布等价。

完整性账本每个计划step必须区分：truth完整/参考未知、捕获或显式missing记录完整、task_entered、观察截止、预测首次事件及违规附加事件。参考和确认各有删失，不用“是否预测”推导随访是否完整。

### 手算测试矩阵

通用参考[l,u]=[1.00,1.01] s，H=1.00 s，任务[0,4) s，主截止D=2.01 s；除注明外随访完整。

| 输入 | 必须得到的结果 |
|---|---|
| c=0.99 | premature；由于一次性消费且无主窗口支持，参考完整H时同时计missed_supported_confirmation |
| c=1.00、1.005 | timing_uncertain，不算supported；不可强制归入提前或正确 |
| c=1.01 | supported，延迟区间[0,0.01]；不混用human评价器的上界规则 |
| c=2.01 | 主截止上界包含，supported；浮点容差仅作数值比较，不增加物理不确定区间 |
| c=2.10 | 任务内late_supported；主终点仍为miss，不用迟到事件掩盖确认预算失败 |
| 无事件，记录至3.00 | missed_supported_confirmation且no_prediction_reference |
| 无事件，记录至1.50 | confirmation_right_censored，不冒称完整H漏确认；已知参考仍留在R |
| truth在是否驻留成立前截断 | reference_right_censored，不补造“无到达” |
| 无参考但完整truth，c=1.20 | unsupported_no_reference；R=0，召回NA |
| truth不完整、事件存在 | unassessable，不按完整无参考评分 |
| 首次c=0.99、后来c=1.30 | 首次premature；后者duplicate违规，不修复首次事件或miss |
| c=4.00 | 在半开任务窗外，不能移回前一step支持；记身份/时序完整性问题 |
| 观测丢帧但显式记录覆盖完整H | 不是删失；按实际事件计支持/漏确认 |
| 计划step未生成或未进入 | planned保留，unattempted/infrastructure_unknown单列，不变成算法漏确认 |

数值比较容差拟1e-9 s，写入评分版本；边界测试同时含±2e-9用例。延迟缺失不填0。测试各事件类型互斥；错误事件与参考漏确认是两套维度，不能总和等于planned。

**验收：** 上表及分母重建全部通过；新评分版本标明H/区间规则；旧评价器和旧输出字节不改。

## G2：五方法薄适配与公平性回归

### 拟新增文件/接口

- `dmf/chapter2_sim/s2/benchmark.py`：`predict_arrivals(cache_root, method_spec, output_root)`；只接算法输入，不能接truth/reference目录、场景类别或评分状态。调用现有`run_arrival_variant`/`ObservationPipeline`/`ArrivalGate`，不调用`ResearchAdapter`、EventController或闭环runner。
- `tests/test_chapter2_s2_contract.py`：共享契约、原始特征、历史和事件身份。
- `tests/test_chapter2_s2_isolation.py`：输入/GT隔离和参考置换不变性。

| 注册名 | S | W | K | Q |
|---|---:|---:|---:|---:|
| B_single_frame | 0 | 0 | 0 | 0 |
| BTQ | 0 | 1 | 0 | 1 |
| BTQ+S | 1 | 1 | 0 | 1 |
| BTQ+K | 0 | 1 | 1 | 1 |
| F_arrival | 1 | 1 | 1 | 1 |

公共G/C0始终开启。四强方法W/Q/G/C0参数摘要必须完全相同；B必须另记effective_window为N=1/T=0、无跨度约束，不能只写同一declared W误导读者。S/K原始计算和前史均不随开关改变。共同参数及单位以研究方案第2节为准。

**必须先写回归：**

1. 同cache的五预测manifest记录相同input hash/map/tasks/timebase；正常输入BTQ与F可完全一致，不将一致判为失败。
2. 重复帧、逆序、旧任务、曝光早于模拟Applied、跨epoch、长断档、missing ID、无效/空Mask和事件重复：公共拒绝/重建一致；不能拿C0作用冒充S/K贡献。
3. 关闭S只改变S参与eligibility，关闭K只改变K参与eligibility；raw S/K/Q、历史取样和原始时序逐帧一致。W变化导致的后续确认差异允许存在。
4. reference文件替换、移走或修改后，**同一算法输入的预测内容hash不变**；预测阶段不得打开评分目录。预测算法不读取scenario/seed标签选择分支。
5. 原21缓存上原BTQ/F回归签名仍与旧事件逐项一致；输入hash一致。新B/+S/+K首次运行另存，不能声称旧版已存在这些方法。
6. 参考重评分版本不改变原事件时间。浮点/CSV序列化只比较约定字段，忽略新manifest生成时间等非语义字段。

**验收：** 契约/隔离/正交开关通过；生产与v2源代码无需改动。如果必须修改公共源代码，停止并另报原因，不自行扩大本轮授权。

## G3：输入机制可行性，先于开发统计

拟新增`dmf/chapter2_sim/s2/inputs.py`及`tests/test_chapter2_s2_inputs.py`。

接口：`derive_first_task(parent_cache, selection_spec, output_root)`显式保存父hash/选择规则；`build_observation_variant(base_observations, task_map, intervention_spec, rng_stream, output_root)`只操作观测，不能接独立reference或期望算法结果。算法输入不携带内部truth；truth由研究编排层单独保存。

对研究方案13条件逐项生成确定性小夹具，先验核算：目标/源覆盖像素、质心、显著连通域、S距离、K历史残差、W候选跨度、Q及C0。记录其他公共门是否已经拒绝，不只看最终事件。

- B两条件：raw S/K/Q可通过且质心/覆盖跨度合格，只变化持续长度；若做不到，报告W无法独立归因。
- C两条件：合法新帧、有效时钟；短暂与持久条件同时保留，不能只截在K增加的延迟之前。
- D两条件：在原完整地图/ROI核算90+15起始构造；失败则保留不可行记录，不改共享门限强行通过。分别绑定无参考与有参考的world，揭示拒绝收益和漏确认代价。
- E三条件：质量值受控、其余观测固定；高置信不可辨识假观测必须保留。小面积/多连通域沿用辅助夹具，不以confidence一个条件外推全部Q。
- F三条件：原jitter/dropout失败保留；F_gap不插值/填Mask；连续完整missing日志不视为随访删失。

每条件出一张机制账本：C0/G/Q/S/K计数、最长有效窗、各重建原因、五首次事件、独立参考与跟踪截止、目标门独立可检验标记。帧数不是独立n。

**验收：** 条件可解释、正常负对照完整；无区别也是合法结果。预先写明可行/不可行与保留边界，之后才决定正式范围。不可按F获益符号决定排除。

## G4：开发seed冒烟与协议锁定

拟新增`dmf/chapter2_sim/s2/study.py`、`run_chapter2_s2.py`、`configs/chapter2_s2_arrival.yaml`、`tests/test_chapter2_s2_study.py`。

编排只做：计划ledger→封存共同输入/truth/reference→五方法盲预测→独立评分→审计汇总。禁止每方法重新生成世界。normal/failure base world及随机流在seed层封存，观测干预记录parent hash；保留完整地图/ROI和pitch单位。

开发262000–262002：13候选全保留时最多39单任务输入、195方法预测。正常/jitter/dropout共9个可从原缓存首任务派生，新hash不能冒充父hash；其余30个观测输入需要另生成。新任务严格[0,4) s、Applied=0.04 s，不能丢掉首任务晚到的捕获/处理/缺失记录后仍称完整；不改变旧缓存时钟。

**拟议CLI（未来接口契约，当前不可运行）：**

```powershell
python -m unittest discover -s tests -p "test_chapter2_s2_*.py" -v
python run_chapter2_s2.py validate-design --config configs/chapter2_s2_arrival.yaml
python run_chapter2_s2.py mechanism --config configs/chapter2_s2_arrival.yaml --output "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\S2_arrival_development_v1\mechanism"
python run_chapter2_s2.py development --config configs/chapter2_s2_arrival.yaml --output "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\S2_arrival_development_v1\paired_inputs"
python run_chapter2_s2.py audit --study "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\S2_arrival_development_v1"
```

阶段子目录归同一study manifest；audit只读。`validate-design`核对配置但不能偷偷生成数据；`mechanism`不冒充统计试验。CLI不存在时应明确失败，不用其他入口替代执行。

验收账本须满足planned全可追溯、参考/事件标签可手算、所有失败/Unknown/未尝试/删失保留、同输入五方法和配对seed一致、完整W/Q/G/C0校验通过。对所有失败必须区分“无独立参考”“有参考无确认”“参考未知”和“未进入输入”。开发结论只描述，不输出正式性能优势。

此后封存：主假设、条件纳入/排除原因、参数、H、评分版本、方法与输入hash、正式seed、图示例选择、bootstrap设置与软件环境。方案修改升版本并保留开发旧包。

## G5：用户再次授权后才运行确认seed并出图

拟263000–263019；13条件都准入时上限260输入/1300预测，每方法260 planned steps，只有每条件20个独立seed簇。最多normal/failure各20个base world轨迹，不是1300次独立世界实验。条件数量在打开确认seed之前冻结。

拟新增`dmf/chapter2_sim/s2/plotting.py`及`tests/test_chapter2_s2_plotting.py`。只读封存结果：S2-A主示例固定A_normal/263000；S2-B按model_generated/synthetic_stress分面，主指标与失败分母配套。图中不做事件时间横向抖动、缺失填0或无输入曲线插值。

```powershell
python run_chapter2_s2.py confirm --config configs/chapter2_s2_arrival.yaml --output "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\S2_arrival_confirmatory_v1"
python run_chapter2_s2.py audit --study "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\S2_arrival_confirmatory_v1"
python run_chapter2_s2.py figures --study "D:\Learn\ZJU\第二章 单液滴视觉闭环\仿真结果\S2_arrival_confirmatory_v1"
```

以上仍为未来规格，**本轮不执行**。confirm必须核验冻结状态，不能自动从development跳转。没有批准配置，不得把提出的seed或数量称为正式完成。

## 交付目录与回归

后续实际运行输出：`plan.csv`；独立`inputs/`、`scoring_side/`、`predictions/<method>/`；逐帧gate/window、逐事件、逐step/followup、逐seed计数、配对差/CI；manifest含simulation/timebase/pitch、模型边界、原始和派生hash、设备/软件环境、代码dirty状态、异常账本。输入只读，scoring_side不暴露给预测接口。

未来实施局部回归通过后按仓库规范执行全量回归，并报告实际数量/失败，不推断物理完成：

```powershell
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

本轮仅完成方案和已有数据的只读核对，因此没有执行上述测试或声称新功能通过。没有新增模型、预测、评分、论文曲线或正式结果。
