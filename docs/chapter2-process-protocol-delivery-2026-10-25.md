# 第二章过程图与双层协议交付记录

2026-10-25。用户确认版式后完成图稿与前瞻协议，没有修改dmf/生产控制源码或既有正式PPT。

## 交付

新目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-25_过程图优化与双层协议_v1`。

最终入口为README_先看这里.md。包含16页审查PDF、4页独立PPT与PowerPoint导出PDF、5幅SVG/PDF/600dpi PNG、同trial原CSV与配置/地图/参考、268输入hash及复现源文件。

架构原生可编辑；数据图在PPT内为600dpi图像，可编辑SVG与绘图源独立保留，不宣称全部为原生PPT图元。架构/六帧/两页PPT时间线由PowerPoint实际导出并独立视觉检查。论文完整版不强塞入单页PPT。

## 新增文件

- `scripts/chapter2_process_figures_revision.py`：只读重绘及既有cache/夹具诊断。
- `scripts/chapter2_process_preview.mjs`：独立4页预览。
- `scripts/render_chapter2_process_preview.ps1`：PowerPoint保存/导出，仅操作本轮新文件。
- `scripts/package_chapter2_process_revision.py`：协议与图稿审查PDF。
- `scripts/verify_chapter2_process_revision.py`：保护与来源核查、PDF渲染。
- `tests/test_chapter2_process_figures_revision.py`：6个契约回归。
- `docs/chapter2-btq-f-two-layer-protocol-2026-10-25.md`：科学问题、S/W/K/Q可辨识性、E4/E5协议。
- 本记录、spec/plan和独立planning文件。

## 科学审查结论

21/21共同缓存BTQ/F事件及时间相同，未证明F随机到达性能优势。jitter中的K独立候选拒绝53次，但公共W也阻止确认；不能把gate触发次数当成事件获益。空间/质量夹具尚无真实误差分布验证。

A层采用同输入BTQ、BTQ+S、BTQ+K、F-arrival，仅比较到达门增量。B层允许五状态和Recovery改变运动，只比较完整策略包。E4固定源准备、诊断目标门参数可行性；E5固定预测和运动，仅改变独立参考评分。未启动正式扫描。

## 实际验证

- 局部58项通过，包括新6项只读图稿契约；最初缺入口失败，再实现通过。
- 全量713项，712通过/1可选跳过，128.486s。已有PyTorch3.14弃用提示保留。
- compileall、git diff --check通过；7条独立软件链通过，输出另存本轮manifests/software_chain。
- 5图最终碰撞0 FAIL/0 WARN，最低字体论文6.2pt/PPT图10.5pt，600dpi导出。
- 最终PPT4页、16:9，结构/尺寸/标题检查0问题；PowerPoint重新保存修复生成器冗余content-type引用，没有修改图或数据。
- 245份保护文件SHA256、268份图源SHA256不变；41343份v1文件尺寸/mtime_ns不变（不是全量重新hash）；HEAD不变。
- Artifact Tool依赖缺失`#standard-fonts/Helvetica`，未改运行时，使用已有PptxGenJS与PowerPoint导出作为替代。

## 复现命令

```powershell
python -m unittest tests.test_chapter2_process_figures_revision tests.test_chapter2_sim_v2_benchmark tests.test_chapter2_sim_v2_dev tests.test_chapter2_sim_v2_gates tests.test_chapter2_sim_v2_reference tests.test_chapter2_sim_v2_runner tests.test_chapter2_sim_v2_stage_audit tests.test_chapter2_sim_v2_visualization -q
python -m unittest discover -s tests -q
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
git diff --check
```

绘图使用新空输出目录：

```powershell
python -X utf8 scripts/chapter2_process_figures_revision.py --trial 'D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1/development_smoke_r2/trials/end_to_end__normal__262000__F' --study 'D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-24_chapter2_sim_v2_E0-E3_v1/development_smoke_r2' --output '<新的空输出目录>'
```

## 边界

本轮0个新增研究trial，E4–E7扫描0。测试中的临时合成夹具不计研究结果。真实AM、STM32、U-Net、五状态生产逻辑及第三章未改。无commit/push。最终装置、真实权重/标注和实物闭环仍未验证。
