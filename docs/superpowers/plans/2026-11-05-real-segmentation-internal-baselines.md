# G2/G3 real segmentation implementation plan

> For agentic workers: use subagent-driven-development and staged spec/quality review. User prohibits commit/push. Preserve all current tracked/untracked work.

**Goal:** Freeze the approved180-mask internal split and run reproducible all-foreground traditional baselines without deep training.

**Architecture:** Add one pure offline semantic baseline/metrics module, a separate freeze/run script and tests. Reuse existing image IO and provenance. No existing control, old segmentation baseline or frozen data edits.

**Tech Stack:** Python/OpenCV/NumPy, native PNG and past reference frames, JSON/CSV.

## 执行结果（2026-11-05）

本轮G2/G3已实际执行：内部train144/val36/test0，180份GT/Ignore原生快照；75份严格过去的首帧ROI参考经助手逐图资格筛查，47可用对应109样本，其他71样本完整保留为不可用。360计划方法/样本行、289实际原生预测，独立复算像素计数/Dice/IoU一致。验证只共同6张，不混用36与6的分母排名。首计时输出评分问题在运行前通过RED/GREEN修正；正式运行无异常或重复输出不确定性。

独立规格与质量审查通过。全量1170项，0失败/0错误/1跳过；编译和7软件控制链通过。保留已有Tk after回收警告，不修改GUI隐藏。583份原始工作区/标注/录像与索引、628运行输入、301输出台账及运行源码hash核验一致。没有深度训练、新正式仿真、硬件输出或Commit/Push。

## Task1 — Pure semantic methods (test first)

- [ ] Create tests/test_semantic_segmentation_baselines.py for multiple blobs/border preservation; negative gray differences; ignore excludes all errors inside it; empty GT and missing-background accounting; causal background identity/time rejection;512 restore and complete-target geometry.
- [ ] Observe failing tests before creating dmf/segmentation_research/semantic_baselines.py.
- [ ] Implement pure methods otsu_mask/background_mask, common512 preprocessing/restore, score_mask, causal reference guard and optional candidate-map coverage diagnostic. No GT input to predictions.
- [ ] Run focused tests and existing segmentation regressions; independent spec then quality review.

## Task2 — Freeze180 approved inputs and inspect backgrounds

- [ ] Recheck current human review flags and hashes; freeze original bytes to a new G2/G3 directory. Validate proposed video/operation/qualified-track split and create actual internal144/36 manifest with explicit nonindependent-batch limitation.
- [ ] Extract same-native-ROI frame0 reference candidates for75 unique video/ROI keys from already byte-verified first-frame PNGs; save original frame/time/hash. Review all75 candidates against current fixed Ignore, without using target GT or future images.
- [ ] Record usable/unavailable/uncertain reference status. No background invented for permanently occupied areas.

## Task3 — Run initial baselines and package

- [ ] Add scripts/run_real_segmentation_internal_baselines.py and run tests for frozen dataset invariants before real run. Save config first with fixed blur5/close3×1/difference20/common512.
- [ ] Save180 Otsu outputs and background outputs only where eligible; all360 planned method/sample rows remain. Score first timed output, warmup5/repeats10, save per-image/per-video/per-split with explicit denominators and no batch-level CI.
- [ ] Export candidate-map target coverage only if complete target is withinROI and outsideIgnore; mark mapping provisional. Instance centroid remainsNA, not union-centroid substitution.
- [ ] Generate review previews and concise report; verify input hashes, predict/score audit, local regression and no old data modifications. Do not start networks.
