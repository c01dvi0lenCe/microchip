# 实验一B固定机制核查：实际交付与边界

2026-10-29。用户批准先机制核查、不跑每类20seed。旧S1/S2/S3和当前SDF工作模型不改；没有真实相机/AM输出、Commit/Push。

## 新增接口

| 文件 | 作用 |
|---|---|
| dmf/chapter2_geometry_sim/exp1b/spec.py | 六正交方法、16固定工况与完整数值配置 |
| exp1b/gates.py | 共享原始历史RawAssessor，独立GateRunner窗口/事件消费 |
| exp1b/generate.py | 运动变体、Mask/递交异常、失败保分母、持久化 |
| exp1b/evaluate.py | 独立区间支持、提前/无支持、漏参考、删失和延迟 |
| exp1b/audit.py | 不调用识别器/评分器的保存数据复算 |
| run_chapter2_geometry_exp1b.py | 固定开发集入口，拒绝覆盖 |
| scripts/check_geometry_exp1b.py | 独立审计及gate计数 |
| scripts/plot_geometry_exp1b.py | 三类机制图SVG/PDF/600dpi PNG，仅读CSV |
| scripts/verify_geometry_exp1b.py | 保存局部/全量/编译/软件链/保护日志 |
| scripts/package_geometry_exp1b_review.py | Chat审查包与完整来源hash索引 |
| tests/test_geometry_exp1b.py | 16项新增机制、评分、失败处理测试 |

## 实际运行

- 计划16缓存×6方法=96记录；完成15缓存、90方法记录；B1慢速6方法未执行。
- 4个基础World计划：正常、慢速、暂停恢复、卡滞；3完整，慢速部分生成失败。观测变体共享基础World，不当独立运动重复。
- 3000张生成Mask、2995次处理递交、17970条方法逐帧记录独立核对一致。
- 正常前120Mask与已封存SDF例字节摘要相同；M1=4.40，M2/M3=4.65，独立参考4.72 s。
- 固定开发身份264900，随机抽样0；无任何正式批次seed。初次中止和r2续跑不当独立重复合池。

## 科学发现，仅限本机制集

1. S在GQ候选上新增拒绝0；没有S增量性能证据。
2. K在C5/C6/D6各新增拒绝1帧，但不改变最终事件类别。
3. C5一帧伪目标被W挡住；C6七帧伪目标使M2于2.30 s、M3于2.35 s提前消费。K适应持续错误观测，未消除错误。
4. C4破碎Mask有7帧Q失败；M1=4.40、GQ=4.60、M2/M3=4.85 s，显示Q与W等待分别作用。
5. C3后部局部缺失使源残留低估，M1=4.25、M2/M3=4.50 s，比正常更早；现有Q不能排除单连通错误Mask。
6. D6返回时K额外重建，使M3较M2增加0.05 s等待；没有对应正确性提升。
7. B3卡滞无参考、无确认，不算漏到达；B1生成失败参考NA，不强填成无到达或识别失败。

所有已完成方法中严格支持28、提前56、无事件6；另6未执行。这些跨工况/方法相关计数不是准确率。每方法14个可评价参考，M1/GQ支持0，四个连续门支持各7；正常例早于参考是G连续窗口与低速驻留参考定义不一致的已知边界，不代表实际控制已失败。

## 未关闭问题

慢速在t=7.97 s、q=0.9713094425380367、SDF最后两节点权重0.315146904228856处得到自交零水平轮廓。8输入均有效；错误发生在面积归一化前。原模型未修，未自动buffer/补桥/吸附相位。

下一步可审查“慢速时间轴复用已保存有效轮廓”的最小适配，并明确相位量化误差；当前不自行采用，不扩大形态研究。G2整体闸门HOLD_generation_failure，20seed与实验二均未启动。

## 验证

- 新增16项RED→GREEN；相关局部152项通过。
- 全量941项：940通过、1可选FFmpeg跳过，230.099 s，exit0。
- compileall、git diff --check、7条独立软件控制链通过。
- 460旧源码内容hash和352135旧资产大小/mtime记录，changed=[]；元数据检查不冒称全部资产内容hash。
- 三图原始数据索引完整；字号/碰撞自动检查通过，双面板对齐通过；7页报告逐页渲染检查。

## 复核命令（不生成新研究trial）

```powershell
python -m unittest tests.test_geometry_exp1b -v
python scripts/check_geometry_exp1b.py "D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-29_实验一B_固定机制核查_r2"
```

原生成命令及续跑关系见该结果目录的config、reused_normal_source、failures、manifest与上级v1中止记录。不得用同一输出目录重新运行或把开发夹具当正式研究统计。
