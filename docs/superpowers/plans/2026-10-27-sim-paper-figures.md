# 第二章仿真论文图清晰版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户已要求当前会话直接制作；无提交/推送步骤。

**Goal:** 从冻结数据导出5张可检查的160mm论文版候选图，保留S1原图作为参照。

**Architecture:** 独立read-only数据/绘图脚本，S2使用既有source_manifest和统计CSV，S3使用正式trial日志与既有区间表。所有新结果落入新候选目录，源文件前后哈希核对。图内无长脚注，图注单独保存。

**Tech Stack:** Python，matplotlib，numpy，PyMuPDF；现有alignment/font/collision审计器。

## Task 1 数据映射先测

- [ ] 新增tests/test_chapter2_paper_figure_closeout.py，覆盖NA/计数、配对区间、日志断线、七场景完整分母和单一seed选择。
- [ ] 运行`python -m unittest tests.test_chapter2_paper_figure_closeout -v`，观察新增模块缺失的失败。
- [ ] 新增scripts/chapter2_paper_figure_closeout.py，只读实现数据检查与series函数，再运行测试。

## Task 2 导出候选

- [ ] S2-A四层时间线保留全部4s观测和五方法事件。
- [ ] S2-B四面板使用冻结条件/配对CSV，不计算新统计；完整13条件表复制到新目录。
- [ ] S3-A拆成8面板运动覆盖和4面板状态控制，均从同一四策略deviation/265000读取。
- [ ] S3-B保留七条件及固定保护桥接。全部图宽160mm，文字≥8.5pt，无长脚注。
- [ ] 源数据、图注、S1原样参照和合并预览PDF均另存，不覆盖。

## Task 3 验收

- [ ] 对新脚本运行validate_figure；逐图alignment、font(min8pt)、collision审计。
- [ ] 原CSV数值/区间与导出审计数据逐项核对，来源哈希前后相同。
- [ ] 查看全部五图与整体预览，修复真实碰撞而不掩盖曲线。
- [ ] 保存QA、manifest和运行命令。交付候选，不标为用户已定稿。
