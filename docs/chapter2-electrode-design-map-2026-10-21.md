# FBC6-3电极设计地图导出

用户已确认本Gerber仅采用形状、控制编号沿用上位机，并确认正面左上1/右上20/左下381/右下400。新独立离线导出器基于这一明确人工证据，不要求不存在的Gerber电极网络，不把文件记录顺序当ID。

新增：`scripts/build_electrode_design_map.py`、`configs/electrode_design_fbc6_3.json`、`tests/test_electrode_design_map.py`，另有本批spec/plan。没有修改既有运行源文件和`configs/electrode_map.yaml`，不接入相机/驱动/状态/控制/仿真。

结果目录：`D:/Learn/ZJU/第二章 单液滴视觉闭环/电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1`。
已实际生成完整420项JSON、420行中心CSV、15287行完整顶点CSV、420行模板差异、编号SVG/PNG和来源manifest。全部轮廓与ID一一对应，原顺序反转测试不改变绑定；无重叠或重复轮廓。PNG完整查看已检查400核心及20外围，四角方向与用户确认一致。

坐标转换x_map=x_gerber+46.159、y_map=169.962-y_gerber，均为mm；保留全部原顶点及面积质心，不创建虚构相机标定。核心节距3.2mm，核心铜面约9.931856mm²；外围实际形状、面积及中心与旧模板差异逐ID记录。

编号状态是user_confirmed_pc_layout_and_orientation；netlist/electrical/as-manufactured/camera均未验证。阻焊缺开窗的12外围源观察保留，但本批仅用形状，不据此否定用户的实际电极映射。

新增8项合成软件测试已观察RED（缺模块）→GREEN；不是实物验证。编译、diff、七条独立控制链通过。完整回归结果与174个原代码/配置保护核对在结果包验收记录中记载，不能沿用此前566项当成本批新全量。

复现：

```powershell
python scripts/build_electrode_design_map.py --source "D:\Learn\ZJU\有源矩阵\微流控PCB\Gerber_20×20FBC6-3_2026-06-25.zip" --output "D:\Learn\ZJU\第二章 单液滴视觉闭环\电极数字地图\FBC6-3_新导出"
python -m unittest tests.test_electrode_design_map -v
python -m compileall -q main.py app_controller.py controllers dmf simulation validation scripts/build_electrode_design_map.py
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

这是独立设计数据，不是现有ElectrodeMap像素格式的直接替换；后续需相机时另行设计配准接口。本批没有分割训练、五状态、闭环仿真、高压实验、AM/STM32/协议/第三章/论文Fig.2-4修改；未commit/push。
