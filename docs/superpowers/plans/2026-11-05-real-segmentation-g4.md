# G4 matched development training implementation plan

**Goal:** Run the user-approved paired first development training without altering frozen inputs.

**Architecture:** New pure data/loss helpers, separate GPU runner and evaluation. Reuse G3 input verification/native scoring; never import real control entrypoints.

**Tech Stack:** existing Python/PyTorch CUDA, isolated system-site-packages venv with pinned SMP, OpenCV/NumPy.

- [x] Verify all frozen inputs and 36 high-risk previews; save source and review ledgers.
- [x] Write failing tests for conservative Ignore downsampling, joint geometric transforms, masked loss/gradient invariance, per-sample model-independent RNG, early-stop tie and output restore.
- [x] Add minimal `dmf/segmentation_research/deep_training.py` and run focused tests.
- [x] Add `scripts/train_real_segmentation_g4.py`: immutable protocol, common pretrained encoder hash, two GPU dryruns, fresh models, matched epoch budgets, atomic checkpoints and durable logs.
- [x] Freeze exact config/dependencies/source/environment before training, then run both models sequentially using seed269000.
- [x] Score36val on native grid; reuse frozen180 Otsu/109background predictions; save full and common-background subset with planned denominators and NA intact.
- [x] Independently recompute prediction PNG metrics, confirm source hashes, run local and full tests. Produce data-check/protocol/result report with actual limitations and no formal-test claims.

## 实际交付

两模型28轮、best16，编码器hash一致；72新预测/114可用预测独立复算一致，30NA背景行保留。全量1185项0失败/0错误/1跳过，局部47，编译/7软件链通过；既有Tk清理警告保留。原1013份G2/G3及90份控制/视觉/配置hash不变。报告26页，18组验证预览NA布局问题在图形门禁中被发现并修复，不涉及训练结果。初始协议示例中ROI157空GT列表文字错误以新数据检查说明更正，原标签未改。微小液滴157召回偏低；无独立测试/普遍优势结论。

No commit/push/worktree migration: preserve current uncommitted dependencies by adding only new isolated offline files in this existing codex branch. No change to core control, old inference adapters or frozen simulation.
