# Real segmentation ROI Pilot implementation plan

> For agentic workers: use subagent-driven-development for isolated implementation and staged review. Do not commit or push. Preserve the dirty worktree and all existing files.

**Goal:** Deliver 180 native ROI candidates with provenance, human annotation workflow and provisional group split, without training or evaluation.

**Architecture:** Add one offline preparation module and one data extraction script. Reuse PilotWorkspace and its UI; do not modify existing data loaders, adapters or controls. Actual split remains unassigned until human and group gates pass.

**Tech Stack:** Python, OpenCV, NumPy, existing Tk annotation canvas, JSON/CSV/PNG.

## 实际执行记录

2026-11-04：任务1–4已按本轮准备范围完成。180候选、180次独立原生重解码核验、39来源hash一致；旧18图/Mask共36文件符合旧索引。建议train144/val36但实际split全部unassigned，新GT=0、模型训练=0。新增27及既有32局部测试合计59通过，实际180样本GUI无保存smoke通过；没有执行全仓库套件。规格与质量分阶段独立复核通过。工作树全部旧修改保留，未创建/切换分支、未Commit/Push。训练环境安装、背景人工参考、实例GT和真正划分放行留待下一阶段，不冒充已经完成。

## Task 1 — Guarded preparation primitives

- [ ] Add `tests/test_segmentation_roi_pilot.py` before implementation. Assert multi-component draft preservation, binary/same-size masks, native crop clamping, candidate metadata, unchanged review flags, distinct task/instance identities, group leakage rejection and no training eligibility for unreviewed rows.
- [ ] Run `python -m unittest discover -s tests -p test_segmentation_roi_pilot.py -v`; observe failure from the missing new interface.
- [ ] Implement `dmf/segmentation_research/roi_pilot.py` only; reuse existing PilotWorkspace persistence and image IO. No existing module edit.
- [ ] Rerun the focused tests; independently review spec compliance then quality.

## Task 2 — Native data selection and extraction

- [ ] Inspect structured source manifests and choose deterministic, temporally distributed candidates, with per-video provenance and coverage categories, without using future GT or calling candidates confirmed labels.
- [ ] Add `scripts/prepare_real_segmentation_roi_pilot.py`, selecting 120 migration, 40 complex and 20 negative/background candidates; fail rather than duplicate frames or silently fall short. Extract native AVI crops, save actual receive time and proposed group split.
- [ ] Create new external output directory `真实分割研究/2026-11-04_ROI_Pilot180_v1`; generate drafts only, task/source indices, exclusion candidates and instance/lineage review templates.
- [ ] Re-decode all selected crops and compare exact pixels. Rehash all source files and old 18 images/Masks. Record failures rather than replacing source data.

## Task 3 — Human workflow and configurations

- [ ] Write foreground/exclusion/bridge/split/merge/instance rules, two-stage review and uncertainty handling. Save internal proposed train/val list and block formal test.
- [ ] Save matched U-Net/DeepLabv3+ draft configs and Otsu/causal-background config, explicitly non-executable until review gates pass. Do not download weights or train in this task.
- [ ] Reuse the existing annotation GUI with a dedicated launcher and explicit limitation that binary review alone does not approve instances, exclusion or training.
- [ ] Inspect candidate overview sheets and historical18-mask comparisons, preserve all old bytes and log compatibility findings.

## Task 4 — Verification and delivery

- [ ] Run focused preparation and existing segmentation/Pilot tests, compile new files, verify output counts/PNG hashes/source hashes/empty GT/no split leakage and launch GUI smoke without hardware access.
- [ ] Save readiness report, audit JSON, grouped manifests, source hash index and reproducible commands. Report actual candidate coverage and remaining manual work; no accuracy/training claims.
