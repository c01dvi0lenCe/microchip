# 实验一B机制核查 Implementation Plan

> 使用executing-plans在当前会话逐项执行；用户已批准固定机制核查。保留现有分支和未提交成果，只新增独立文件。不创建提交/推送，不使用子代理。

**Goal:** 在固定16共同缓存中核验六到达门的语义、异常注入与独立评分，不开展随机批次。

**实际阶段状态（2026-10-29）：** 新增接口、测试、15个缓存、审计、图稿及报告已完成；4World/16缓存的完整生成未通过，B1慢速保留6条未执行。下方为原始计划，实际验收以文末记录为准。

**Architecture:** 冻结输入校验 → 独立4基础运动World/16缓存 → 共享原始观测评估 → 六正交到达门 → 独立参考匹配 → 只读审计/图稿/Chat报告。

**Tech Stack:** Python、NumPy、OpenCV、Shapely、既有EvidenceWindow/ArrivalEvent、Matplotlib、ReportLab/PyMuPDF。

## 1. 新增接口与测试

新增`dmf/chapter2_geometry_sim/exp1b/{__init__,spec,gates,evaluate,generate,audit}.py`及`tests/test_geometry_exp1b.py`。不改旧shadow/shape_sequence/reference/控制器。

- [ ] 先写期望接口测试：`METHODS`六组合、`RawAssessor(context).observe(frame,features)`一次原始历史、`GateRunner(spec,context).observe(frame,raw)`独立窗口/ledger、`score_event(event,reference,H)`独立评分。
- [ ] `python -m unittest tests.test_geometry_exp1b -v`观察未实现功能失败。
- [ ] 最小实现后重跑；重复/倒序/跨任务/曝光前、非法时间、无Mask均不能推进；不允许通过消融关闭C0；同一任务只消费一次。

手算例：6个曝光0.60—0.85 s、处理+0.05 s，M1=0.65，M2=0.90；重复第三帧重建后不足0.25 s，不确认。原始K从(0,0)到(1.2,0)/0.05=24 mm/s，K拒绝首跳；后续固定位置K适应不得隐去。

## 2. 生成与持久化

- [ ] `load_baseline()`逐项核对已登记manifest/hash；A0前120Mask/事件与冻结例一致。
- [ ] `make_worlds()`生成normal延长尾段、0.7慢速、q≈0.55暂停1s与永久停滞4基础World。每步检查非空/面积/中心/激活交叠；不偷偷修改运动满足覆盖门。
- [ ] `alter_mask()`只改视觉；`delivery_plan()`只改递交，保持曝光和身份；case明细由spec固定，禁止新增seed。
- [ ] `run_development(output)`拒绝覆盖已有目录；保存source snapshot、每World内部记录/参考、每cache实际Mask/递交表、每method逐帧和事件、96计划记录及错误记录。

## 3. 评分与可归因审计

- [ ] 测试无参考时错误确认为unsupported，未来参考前事件为premature，离开后旧参考不支持，缺事件保持分母；驻留建立中单独标签。
- [ ] 每方法原始历史摘要必须相同；记录raw gate失败数、GQ上S/K额外拒绝、拒绝交叉与事件影响。
- [ ] `audit_development()`独立从保存Mask/时间/位置重算特征、参考区间、事件及全部分母，不调用识别器生成答案。

## 4. 执行与交付

- [ ] 仅运行一次`python run_chapter2_geometry_exp1b.py --output <独立新目录>`，16缓存×6=96方法记录，不当作96独立trial。
- [ ] 局部回归、compileall、diff、旧资产保护；全量是否运行如实报告。
- [ ] 从保存CSV制作事件矩阵、可靠性/时差、门重叠三类图；图内不放说明性小字。
- [ ] 输出Chat审查PDF（原始结果/失败/边界/追溯/图），逐页渲染检查；当前只做机制检查，不输出虚假的性能置信区间。
- [ ] 停止扩展，等待审查后再决定随机分布及20配对seed探索。

偏差处理：生成失败或Q/S/K无差异都保留；不为展示M3收益调整幅度或门限。真实误差分布未标定，所有观测注入为synthetic stress。

## 实际执行清单

- [x] 测试先行完成16项新增接口/评分/错误处理测试；共享原始历史、六组合与一次性事件实现。
- [x] 基线hash核验，正常前120Mask字节摘要及4.40/4.65/4.65 s事件兼容。
- [x] 首轮在慢速形态生成中止，r2字节复用已完成正常World续跑；全部96计划记录保留，90执行、6未执行，不当两批独立重复。
- [ ] 完整4World/16缓存生成：B1在7.97 s、q=0.9713094425380367产生自交轮廓，未修补。
- [x] 3000Mask、17970条方法逐帧、独立参考/事件/分母核查一致；G2整体闸门HOLD_generation_failure。
- [x] 局部152项通过；全量941项（940通过、1可选跳过）；编译、diff、7软件链及旧资产保护通过。
- [x] 三类图SVG/PDF/600dpi PNG、完整CSV、7页Chat审查报告及逐页视觉QA完成。
- [x] 本轮停止；不启动20seed、实验二或新的形态修补。

结果目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-29_实验一B_固定机制核查_r2`。原中止目录`2026-10-29_实验一B_固定机制核查_v1`保留。

报告：`D:/Learn/ZJU/第二章 单液滴视觉闭环/审查材料/2026-10-29_实验一B固定机制_Chat审查包_v1/实验一B_异常到达判定与消融机制核查_Chat审查报告.pdf`。
