# 实验一B正式统计、冻结与一次配对批次 Implementation Plan

> For agentic workers: use subagent-driven-development, test-driven-development and two-stage review. No Commit/Push. User has approved the already-reviewed design and conditional execution after statistical/freeze gates pass.

**Goal:** 验收正式分层统计及输入/源码冻结，然后一次运行266000–266019，交付240缓存/1440预测/10080评分、三张论文图和Chat审查报告。

**Architecture:** 新增`exp1b_formal`命名空间，原`exp1b_random`、旧到达门、轮廓库及旧研究数据全部只读。正式层复用已验收World、Camera、Gate及Reference/Score，不改变任何模型或门限。正式特有工作仅为20seed执行锁、分层统计、冻结/来源与独立批次审计。

**Tech Stack:** Python 3.14、NumPy PCG64、Shapely、OpenCV；统计沿用原精确CP/配对不一致格原语；Matplotlib三图，ReportLab/PyMuPDF报告。

## 工作区与既有设计

当前普通checkout的codex分支含大量必要未提交依赖，保持原目录，不建立丢失这些文件的新worktree。以新增文件和内容hash保护隔离；原开发入口继续只允许268000/268001。正式授权来自本轮用户“统计模块、正式配置冻结和最终审计，通过后运行240组”的明确要求。

既有研究协议已完成审阅，不重开形态/阈值/场景设计。仅将先前拟议统计规则落实成可验收接口；不增加开发seed，不初始化正式随机流作筛选。

## Task 1：正式层接口及手算验收

Files: `dmf/chapter2_geometry_sim/exp1b_formal/{spec,draws,runner,freeze,audit,statistics,summary}.py`、`run_chapter2_geometry_exp1b_formal.py`、`configs/chapter2_geometry_exp1b_formal_v1.json`、`tests/test_geometry_exp1b_formal.py`。

- [ ] 测试先行：新接口RED；精确二项0/5、5/5手算边界；两层各10不可当各20；配对不一致格及完全一致仍有非零区间；缺失上下识别界而非删除；未执行仍保已知参考；已完成参考即使队列待处理仍计漏确认；n_joint<5不给bootstrap区间。
- [ ] base/单强度用CP95%；压力总体仅同一家族两层各97.5%CP限按0.5权重组合；不合池跨工况。输出k/N及已知/未知数，任何未知暂停普通CI并给[k/N,(k+u)/N]。
- [ ] 配对比较M2-M1、M3-M2；另预声明GQ-M1、M2-GQ、M2_S-M2、M2_K-M2用于消融。逐层p_plus/p_minus各以alpha=.05/(2*层数)构造CP边界，按权重组合差界，保留discordance和相同seed。
- [ ] 条件支持延迟仅同时受参考支持的配对子集，报告n_joint、原始差、中位差；n_joint≥5给10000次配对百分位bootstrap（分析seed930100），否则区间NA；同一预测七参考敏感性完整保留，不将其当新重复。
- [ ] 输出固定截止支持/参考前/无参考确认/支持外确认、未执行、参考pending、漏确认、丢帧与晚帧诊断；每条一个主分类。所有帧和方法行均不作为独立n。
- [ ] 正式spec绑定proposal SHA与开发wrapper完整hash，固定20seed/12家族/6方法/7参考、原TF修订、全部模型及门限。既有模块不改；纯draw公式逐字段与开发流对照，不调用开发seed白名单。
- [ ] runner拒绝已有目录、拒绝子集/替换seed；全部80运动抽样及240观测流先保存后运行方法；失败不重抽、不补seed，1440/10080完整分母。已知World参考在缓存失败时保留。

## Task 2：正式前闸门

- [ ] 规格审查通过后质量审查；关闭所有Critical/Important问题，父代理新测试及相关局部回归实际通过。
- [ ] 只读审计已有记录，确认266000–266019未作开发使用（检查真实run记录字段，不把文档中的保留号码误作已执行）。保存扫描范围/文件hash/发现，无法覆盖范围明确说明。
- [ ] freeze保存运行/统计源码及依赖、配置、地图/430轮廓来源、Python/NumPy/OpenCV/Shapely环境、随机流规则、计划完整身份；冻结操作不调用正式draw。
- [ ] 正式执行必须校验freeze全部摘要、环境、seed/计划和前测通过证据；篡改任一必要源码/配置必须拒绝。仅当前正式入口可执行，旧开发入口不解锁。

## Task 3：一次正式运行与独立审计

```powershell
python run_chapter2_geometry_exp1b_formal.py freeze --output "独立冻结目录"
python run_chapter2_geometry_exp1b_formal.py run --freeze "冻结文件" --output "全新正式目录"
python -m dmf.chapter2_geometry_sim.exp1b_formal.audit "正式目录"
```

- [ ] 只运行一次80World/240cache/1440方法/10080参考；无新开发seed、无额外压力、不运行实验二。
- [ ] 独立从World/实际Mask/逐帧历史复算全部参考、到达门、窗口、事件及评分；核对随机数组、身份、主表与R0、统计分母与手算原语。不得只调用原scorer重新给自己打分。
- [ ] 正式源文件冻结后不根据结果更改运动/判据/参考规则。若真实代码问题阻断，保留失败记录，说明而非静默重跑。

## Task 4：三张核心图与审查包

- [ ] Fig1：参考前、无参考确认及参考支持产出，完整12家族和压力低/高层；主方法保持同色/异形，0/100%完整区间。
- [ ] Fig2：可靠性与时间代价：逐工况参考支持率及支持子集延迟，同seed确认差；无事件不赋0，n_joint与限制写图注。
- [ ] Fig3：Q/W/S/K消融配对变化与7参考敏感性；不将拒绝帧数等同性能收益，不预设M3优势。
- [ ] 图面仅必要坐标/单位/方法/条件/子图标签/SIMULATION，不放参数段落、路径、seed或结论小字；183mm矢量PDF/SVG及600dpi PNG，附完整来源CSV和caption。
- [ ] 使用Python独占绘图；对齐≤1.5pt、文字/碰撞审计及逐面板/整图视觉检查。
- [ ] 新旧局部/全量、compileall、软件链、diff及旧数据hash保护；生成独立Chat PDF（含统计/冻结/原始数据/三图/局限）并逐页渲染检查。
- [ ] 正式结果与旧S1/S2/S3及开发数据不合池。完成后收住实验一B，不自动增加仿真，实验二只保留后续入口。
