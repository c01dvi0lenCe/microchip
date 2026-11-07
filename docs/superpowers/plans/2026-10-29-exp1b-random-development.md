# 实验一B随机接口与两个开发seed Implementation Plan

> For agentic workers: use subagent-driven-development or executing-plans task by task. No Commit/Push; user explicitly forbids them.

**Goal:** 实现独立随机缓存入口，修订TF及截止分类，只运行268000/268001开发实例，完成审计/回归/Chat报告。

**Architecture:** 只读继承拟议配置并核验hash → 独立raw随机数组 → 8基础World/24共同Mask缓存 → 原六到达门 → 参数化独立参考及明确H分类 → 独立审计。原SDF/门/控制/S1-S3不改。

**Tech Stack:** Python、NumPy PCG64、Shapely、OpenCV、原SavedOutlineReplay及RawAssessor/GateRunner，ReportLab/PyMuPDF仅用于报告。

## 范围与先决条件

现有分支codex/local-cloud-update-20261020，含大量已有未提交研究文件。本轮保留当前工作区及hash保护，新增独立命名空间；不创建会丢失这些依赖的空白基线。正式240批次及实验二性能入口不实现/不开启。

## Task 1: 协议与测试先行

Files: configs/chapter2_geometry_exp1b_random_dev_v1.json、tests/test_geometry_exp1b_random.py。

- [x] 配置继承原草案且核验93d0de69...hash，保留所有门与分布，覆盖TF为卡滞后0.20 s，开发slots为0/10。
- [x] 写先失败测试：

```python
ref = build_reference(rows, (0.,0.), spec={'radius_mm':.288,'max_speed_mm_s':.192,'dwell_s':.15}, horizon=.2)
self.assertEqual(score({'decision_s':.2}, ref, .2)['primary_outcome'], 'reference_supported')
```

- [x] 验证新接口尚不存在导致RED；实现前不删减边界断言。

## Task 2: 独立运行单元（一个完整实现任务）

Create: dmf/chapter2_geometry_sim/exp1b_random/{__init__,spec,draws,world,cache,reference,evaluation,statistics,runner,audit}.py，run_chapter2_geometry_exp1b_random.py。

- [x] spec读取wrapper及base，校验门限/方法/单位，正式seed无论开关均拒绝，最多2开发seed；不修改原proposal。
- [x] draws按配置固定流ID和raw数组形状；保存前后PCG64状态、NumPy版本、所有数组及参数，算法执行之前全部生成。重现仅重抽数组，不重跑物理/算法。
- [x] world：dt.01/H10，最小跃度、响应、暂停/卡滞；原430有效轮廓最近进度平移。记录卡滞首次静止tick，Applied/响应前无位移、实际active交叠为正、面积/中心误差检查。
- [x] cache：实际生成4800Mask，所有6门共用context/raw历史；12条件按草案，TF首曝光≥卡滞tick+.20，整段连续7-12帧均在卡滞后，无重抽。
- [x] reference：7定义参数化，只读World；区间真实离开右开、终点仍有效包含H；区分completed/dwell incomplete/approaching/permanent stall。
- [x] evaluation：一次主类别；确认但参考在H尚未完成单列pending，不算已证实错误；已完成参考未确认即使有待递交也保留漏确认。保存固定H指标及参考/观测删失标志。
- [x] statistics：精确CP手算边界、配对不一致格Bonferroni区间，2seed开发不输出性能CI；不把方法/帧当独立n。正式分层汇总不在本开发入口实现。
- [x] runner拒绝覆盖、拒绝正式及重复seed，保存配置/源码hash、raw数组、逐帧/事件/7参考/主类别。失败逐方法保计划分母且不换seed；缓存失败保留已知World参考。
- [x] audit从持久化输入独立复算参考、端点、覆盖、窗口和事件，不能只调用原识别/评分器重新给自己打分；核对实际扰动/TF重叠/随机数组复现/共享raw历史/原始资产hash。

## Task 3: 两阶段代码审查与开发执行

- [x] 实现者先自审，独立规格审查通过后再做质量审查；不忽略Important问题。三项问题均完成RED→GREEN并获复审批准。
- [x] 运行：

```powershell
python -m unittest tests.test_geometry_exp1b_random tests.test_geometry_exp1b tests.test_geometry_exp1b_closeout -v
python run_chapter2_geometry_exp1b_random.py --config configs/chapter2_geometry_exp1b_random_dev_v1.json --output "独立新开发目录"
```

期望只出现2seed、8World、24缓存、144方法记录；无正式seed。若某case失败，保留失败而非标全通过。

## Task 4: 验证、冻结候选及交付

- [x] 局部、新旧全量、compileall、软件链、git diff --check及旧资产保护；记录实际结果，不提前声称通过。
- [x] 对TF列出卡滞/伪开始/伪结束与实际帧数；列出所有24×6结果和H截止类别，不做开发性能优势推断。
- [x] 另存实施状态及独立配置/代码hash索引，状态为development-validated/freeze-candidate，正式仍blocked pending approval；旧协议原件不改。
- [x] 生成独立Chat审查PDF并逐页渲染检查，不改旧报告，不启动实验二。

## 实际完成记录

批准的两个开发seed各运行一次：8 World、24缓存、144主记录、1008参考评分、4800模拟Mask，失败0。独立审计28422条方法逐帧记录通过。

最终局部191项通过；全量980项中979通过、1项可选FFmpeg环境依赖跳过。编译、软件闭环链、diff及两级旧资产保护通过。完整最终日志在`.planning/geometry_exp1b_random_development_20261029/verification_final`，先前验证尝试保留。

正式240缓存未运行；两个TF中六方法均发生无参考确认，M2/M3在24缓存的R0主类别完全相同。开发结果不用于调阈值或筛选seed。

最终报告保存在`D:/Learn/ZJU/第二章 单液滴视觉闭环/审查材料/2026-10-29_实验一B随机接口双seed开发_Chat审查包_v2`，7页均完成视觉检查。旧排版草稿v1保留。
