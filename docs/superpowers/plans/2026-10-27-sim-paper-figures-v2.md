# 图稿v2实施计划

用户已给定并要求执行设计，当前会话内实施。仅新增脚本/测试/候选目录；不创建工作树、不提交。

1. 新建tests/test_chapter2_paper_figure_revision.py，先验证普通Retry与resend分类、Wilson端点、n=20/组内变化和时间惩罚规则；缺实现先失败。
2. 新建scripts/chapter2_paper_figure_revision_v2.py，复用上一只读数据读取及导出，不改旧文件；实现三个S3绘图入口、S1/S2原样复制、图注与来源索引。
3. 仅从CSV核验比例/均值及动作次数，保存绘制数据并由独立脚本复查；使用冻结的bootstrap区间而非新建区间。
4. 导出三个新S3图和7页汇编，执行字号/对齐/碰撞及600dpi检查，逐图检查。保存差异与独立检查报告，交用户审阅。

运行：bundled Python -m unittest tests.test_chapter2_paper_figure_revision tests.test_chapter2_paper_figure_closeout -v；bundled Python scripts/chapter2_paper_figure_revision_v2.py。正式seed不会用于调用模型。
