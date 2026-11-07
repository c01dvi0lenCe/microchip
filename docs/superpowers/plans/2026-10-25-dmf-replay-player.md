# DMF Replay Player Implementation Plan

**Goal:** 自包含本地HTML严格回放既有单液滴日志，随后导出同源MP4和6帧。

**Architecture:** 数据包为唯一快照接口，HTML和Pillow导出均消费它。复用PersistedReplay，禁止模型/控制执行入口。自包含Mask PNG保留实际像素。

**Tech Stack:** Python、HTML Canvas/JavaScript、Pillow、现有FFmpeg。

## Task 1 数据契约（TDD）

- [x] 新增tests/test_chapter2_replay_player.py：缺模块时断言失败。
- [x] 新建dmf/chapter2_replay/data.py：build_bundle(path)、tick_index(bundle,time)、audit_bundle(bundle,path)。
- [x] 测试412tick、原始Mask解码相等、1.96旧帧不叠加、无插值/无外推、事件逐项对应、输入hash、状态/事件不补造。
- [x] 运行`python -m unittest tests.test_chapter2_replay_player -v`，先RED再GREEN。

## Task 2 自包含交互播放器

- [x] 新增player.html，内嵌JSON与Mask data URL，不fetch、不引用CDN。
- [x] 新增run_chapter2_replay_player.py build入口，只向新目录输出，拒绝覆盖。
- [x] 浏览器检查播放/暂停/单步/拖动/速度与相机帧导航；检查0、1.46、1.92、1.96、4.11s。

## Task 3 同源导出

- [x] 新增export.py，消费已封存bundle而非重新调用模拟器，逐tick导出1600×900 PNG及H.264 MP4。
- [x] 6帧选用既有keyframes，事件来源保留CSV行号。
- [x] 解码412帧/25FPS，写frame_index.csv、source_manifest和检查报告。

## Task 4 交付核对

- [x] 本地与既有v2回归、全量测试、编译、diff检查。13新增、35局部通过；726全量含1可选跳过。
- [x] 保存保护输入/结果清单，确认245保护hash与41343份v1尺寸/mtime不变。
- [x] 写启动说明、模型边界与实际交互/数据审查结果。不commit/push。
