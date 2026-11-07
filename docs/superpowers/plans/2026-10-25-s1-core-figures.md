# S1核心图实施计划

**Goal:** 只读冻结trial，交付S1-A六阶段和S1-B空间时序两张定稿候选图。
**Architecture:** 新脚本复用PersistedReplay与既有style/save；数据选取和阶段解析为纯函数。渲染不改变源图、算法和结果。
**Tech Stack:** Python/Matplotlib、CSV/JSON、SVG/PDF/600dpi PNG；沿用当前后端。
**Execution:** 本会话执行，无委派、worktree、Commit/Push；不进入其他研究任务。

- [x] 在`tests/test_chapter2_s1_core_figures.py`先测试缺失模块的失败，再实现只读数据契约。
- [x] 新建`scripts/chapter2_s1_core_figures.py`，提供`phase_intervals`、`spatial_segments`和`s1_panels`。测试阶段时间、原始字段/单位、无效帧/丢号/epoch断线和六帧来源。
- [x] 按设计绘制两图。路线Inset不与六主面板参与相同尺寸比较，单独记录排除理由；六主面板等宽高，B三面板等宽且共享时间轴。
- [x] 对新脚本运行源码预检；对最终两PDF运行字形和碰撞检查，每次改图重做。逐幅查看预览，修正排版。
- [x] 导出两图SVG/PDF/600dpi PNG、简短图注、完整原CSV与来源manifest、独立绘图脚本。输出到新的日期目录；拒绝覆盖已存在目录。
- [x] 执行新旧局部回归、输入/生产源码保护核验，最终仅交付两图和简短说明，不把机制图写成性能结果。
