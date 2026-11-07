# 粗范围辅助重复点选（2026-10-23）

用户明确要求“在差不多电极范围给标识，由用户点精确位置”。在原盲法记录外新增辅助协议，不重写/覆盖原点位、H、地图或结果。新包：`D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_粗范围辅助点选_v1`。

## 实际修改

- 新增`dmf/vision/registration_guidance.py`：`build_regions`使用实际420设计邻域与冻结H预计算范围，不读取原人工observed_px；核心约3×3、边缘向内选3×3、外围扩大一设计pitch，像素向外32px量化。`prepare_assisted`生成新目录/空两轮/复制原图地图/hash/CRLF启动文件，不复制精确H或旧点给UI。`validate_guidance`校验完整范围、ID、hash和图像界限。
- `registration_repeatability.py`接受独立assisted schema，禁止在原blind schema中混入guidance；辅助点击记录method=coarse_region_assisted_no_snap。汇总保留review_mode、blinding、guidance hash、display_blind/strict_blind信息，原数值公式不变。
- `registration_repeatability_gui.py`对assisted模式显示单个橙色虚线粗框、范围文字和“回到当前粗范围”，自动滚动到粗范围100%视图；不显示预测十字、旧点击或残差。已有人工草稿必须明确确认后保存，旧blind模式仍无粗框。
- `run_registration_audit.py`增加`prepare-assisted --workspace --output`；review/repeat-report复用现有界面和新版本报告。无自动串口/相机或运行配置入口。
- 新增`tests/test_registration_guidance.py`9项，含不依赖旧人工坐标、3×3几何覆盖、非法/篡改范围、模式误标拒绝、真实点击原值、隔离UI没有预测十字、源文件不变/空轮次/不覆盖。

## 实际验证与边界

首批7项在模块缺失时RED，实施后GREEN。新增隔离UI测试首轮有一个断言误放入该用例，追查后移回原越界篡改测试，未删除断言/放宽验证。最终新增9项和原回归共81项通过，14.057s、exit0；编译及diff检查通过。本批离线辅助小改未再次运行完整工程套件，不沿用旧完整644项冒称本批结果。

真实原尺寸照片隔离隐藏Tk冒烟：shape3648×5472×3，1个粗框、0个预测十字，人工轮次0/0。原两个工作包177文件hash不变。未commit/push，不改AM、STM32、U-Net、五状态/控制、正式仿真或第三章。

本版为受粗导航辅助的技术重复性，不是严格盲法，不是新的独立芯片实验。原RMSE1.968/P953.058/max3.132px及H不变。未收集真人重复点选，所有重复性指标仍null，不能预测辅助将改善多少。辅助有降低查找/对应失误的潜在价值，也存在由导航引起偏差的风险；重复性与真实准确度分开解释，不能拿更小轮间差异证明更准。

## 命令

```powershell
python run_registration_audit.py prepare-assisted --workspace '<原封存workspace.json>' --output '<新的辅助版本目录>'
python run_registration_audit.py review 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_粗范围辅助点选_v1/repeatability.json'
python run_registration_audit.py repeat-report 'D:/Learn/ZJU/第二章 单液滴视觉闭环/图像—电极配准/2026-10-23_粗范围辅助点选_v1/repeatability.json'
python -m unittest discover -s tests -p '*registration*.py' -v
```
