# 过程图与双层协议 Implementation Plan

**Goal:** 只从冻结日志重排5图和4页预览，形成科学可归因的A/B层与E4/E5协议。
**Architecture:** 只读snapshot/source table与渲染分离；不导入或调用世界运行函数。图和方案另存日期目录。
**Tech Stack:** Python/Matplotlib、现有PersistedReplay、CSV/JSON、SVG/PDF/PNG、本地presentation API。
**Execution:** 当前会话执行；仅PPT视觉QA按技能要求委托独立审查。用户禁止commit/push，不创建丢失未提交成果的新checkout，不改旧文件。

- [ ] 保护当前v1/v2输入与源码，记录SHA256/HEAD。新增测试先RED：六时间戳确实对应日志，1.96s不能叠加拒绝Mask，缺状态不造，稿件不读GT作为算法输入。
- [ ] 新建`scripts/chapter2_process_figures_revision.py`，只读原trial和共同缓存，导出5图及source_data/figure_manifest。预览应满足`assert manifest['new_simulation_runs']==0`和原hash不变。
- [ ] 完成图1简化、图2固定局部裁剪、图3完整版和两简版；每次修改重新做对齐/文本/碰撞审计，修正实际渲染问题。
- [ ] 建立研究写作基础事实/证据/论证/节契约，在`docs/chapter2-btq-f-two-layer-protocol-2026-10-25.md`写A/B层、机制适用性、E4/E5及归因结论，禁止把计划写成结果。
- [ ] 独立4页PPT预览：原生可编辑架构和标题，数据图以可追溯SVG/PNG嵌入，保留图源脚本；不修改现有第二章PPT。导出、渲染、独立视觉QA，修复后再验。
- [ ] 运行新局部回归、源/图hash检查及现有必要回归；生成合并审查PDF、协议MD、来源清单和使用说明。确认无新研究trial或正式扫描。
