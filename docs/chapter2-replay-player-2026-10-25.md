# 第二章二维只读仿真播放器交付

用户批准浏览器方案后，新增独立`dmf/chapter2_replay/`，未修改既有v2/replay.py或plotting.py。

交付目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-25_交互式回放播放器_交付`。打开HTML或启动cmd，具体说明见目录内README。

## 实现接口

- `data.build_bundle(path)`：复用PersistedReplay，封存truth/frames/Mask/gates/events/references，附来源hash。
- `data.tick_index(bundle,t)`：向下定位原始tick、拒绝外推。
- `data.audit_bundle(bundle,path)`：逐项比对原始记录、地图、配置、关键帧与Mask/帧号关联，不重跑算法。
- `player.html`：全内嵌Canvas播放器，播放/暂停/前后单步/下一相机帧/拖动/数值定位/速度切换。
- `export.load_verified_bundle(root)`：拒绝修改过的封存包。
- `export.render_snapshot(bundle,index)`：逐tick1600×900图，始终保留内部位置，拒绝旧Mask叠加。
- `run_chapter2_replay_player.py`：构建入口，仅创建新目录。
- `scripts/verify_chapter2_replay_player.py`：字段级事件比对、视频索引和保护输入检查。
- `tests/test_chapter2_replay_player.py`：13项回归，按缺接口/错地图/错Mask关联/编码参数/CSV空值等反例RED→GREEN。

## 实际检查

412原始tick、79实际PNG、12日志事件（432字段）和3参考区间（27字段）一致。初始未知world.active保留None；CSV空值按None核验，不填造为0。6关键帧来自同trial。

交互实测：前后一步、相机帧跳转、滑条实际拖动、数值定位1.925→1.92、0.25×和2×选择、播放到终点自动停止、暂停后时间不变。1.46为Unknown/Hold及独立参考；1.92为Arrived/Update；1.93为Arrived/Hold；1.96为Applied/TASK_EPOCH_MISMATCH，不叠加旧Mask。浏览器控制台无error/warn。

浏览器工具禁止file://自动导航，因此实际UI检查在127.0.0.1本地HTTP完成；不伪称已代用户双击cmd。HTML自包含，实际文件启动仍可由用户验收。窄侧栏下文字较小，建议最大化普通浏览器。

MP4使用已有FFmpeg的h264_mf：软件libx264不可用时没有静默替换，先验证编码器并记录参数及二进制SHA256。412帧全部解码通过，1600×900/25FPS/16.48s，约4倍慢放。Pillow导出最初存在地图未裁切覆盖页眉，修正后重新导出；旧中间稿保留，最终入口为“_交付”。

## 复现

```powershell
python run_chapter2_replay_player.py --output '<新的空输出目录>'
python -m dmf.chapter2_replay.export --player-root '<上一步目录>' --ffmpeg 'E:/Apps/Jianying/JianyingPro/11.6.0.14552/ffmpeg.exe' --encoder h264_mf
python -m unittest tests.test_chapter2_replay_player -v
python -m unittest discover -s tests -q
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
git diff --check
```

封存包、HTML、MP4均不覆盖旧文件。保护源码/冻结结果核对见交付检查JSON。全部研究数据为simulation，没有新研究trial或实物实验，没有commit/push。

最终验证：13项新增、35项局部全部通过；全量726项725通过/1可选跳过（108.398s）。245保护hash与41343份v1尺寸/mtime不变；432事件字段/27参考字段一致；7软件链、编译与diff检查通过。最终验收报告在交付目录“检查结果/验收报告.md”。
