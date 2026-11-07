"""Freeze approved S3 protocol after the independent G3 checks pass."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from audit_chapter2_s3_g3 import OUT,OLD,DATA,ROOT,js,sha,write_json,FLAGS,planned_formal_identities,verify_protected

def build():
    audit=js(OUT/'QA/g3_audit.json')
    if not audit['passed'] or not verify_protected()['passed']:raise ValueError('G3 checks not passed')
    oldconfig=js(DATA/'config_manifest.json')['spec']
    plan=[dict(r,seed=265000+r['seed_index']) for r in planned_formal_identities()]
    contract=dict(schema='chapter2_s3_confirmatory_v1',version='chapter2_s3_confirmatory_v1',
        common=oldconfig['common'],arrival_flags=FLAGS,methods=['A_fixed','B_single','BTQ','F_full'],
        F_full_definition='F_arrival + P_F; alias is a controller package, not a new arrival gate',
        source_hashes=audit['source_hashes'],reference_version='s3_activation_position_speed_contiguous_dwell_v1',
        statistical_unit='paired seed within scenario; no pooling scenarios or cohorts',
        planned_trials=800,cohorts=dict(main=560,bridge=80,diagnostic=160),plan=plan,
        main_contrasts=[['BTQ','A_fixed'],['BTQ','B_single'],['F_full','BTQ']],
        bootstrap=dict(repetitions=2000,seed_sequence=[20261026,303],level=.95,interval='percentile; pointwise, not simultaneous'),
        primary=['reference_supported_path_complete / planned trials','any unsupported request / planned trials'],
        formal_seed_min=265000,formal_seed_max=265019,
        authorization='Latest user request explicitly permits G4 after G3 passes; no preselection or tuning',
        algorithm_change=False,data_overwrite=False,required_random_storage=['world_noise','camera_errors','camera_uniform','speed_factor'],
        invalid_policy='Keep planned denominators; report conservative yield, unknown fraction and unknown-all-success upper bound; no seed replacement')
    write_json(OUT/'S3_正式冻结协议.json',contract)
    docs={
    'S3 G3协议一致性与冻结审查报告.md':'''# S3 G3协议一致性与冻结审查报告

2026-10-26。状态：技术核查通过，按最新用户条件授权可进入G4；本文件生成时正式研究trial为0。仿真模型为二维点运动、合成Mask、pitch单位。

## B_single结论

原方案是G+C0、单帧，目标到达Q/W/S/K全关闭。s3/spec.contract选择s2.flags_for('B_single_frame')，返回S/W/K/Q四项false；ArrivalGate将关闭的Q视为不限制资格。原adapter未将B_single改成BQ。120条运行记录中27条为B_single（21主组、6受控诊断），全部目标门trace.enabled和eligible重算通过。源准备及Recovery阶段的enabled四项true不属于B的运输到达门，不能据此误读目标Q已开。

G0-G2报告第3节将B写成G+Q，是文书错误。本次另存勘误，不改原PDF、算法、参数、seed、CSV或manifest。开发批次实际符合原方案，无需重跑开发版本。

## 共同保护Q的准确含义

ObservationPipeline始终计算raw Q，ResearchAdapter将raw Q写入原始Observation.valid与error，所有方法保护输入一致。P_B/P_F在非到达分支根据可靠观测与进展执行保护。EventController的Arrived分支先于无进展/质量超时分支，因此公共raw Q监控并不是关闭的B到达Q门的隐式替代，也不是每帧硬否决。C0始终开启。该优先级按原源码冻结，不做补丁。

## 公平性、评分与复现

四主组及2×2与原方案一致。原77份核心源码在120个封存副本及当前工作区内容一致。共同P0、外生流、3步与每步7 Applied限制沿用独立审计。BTQ/F同保护12个桥接配对控制事件与时间一致，不能宣称S/K闭环独立收益。

从各trial封存的config/world/vision源码构造开发外生数组，不调用advance/expose/controller。研究环境Python3.14.3、NumPy2.4.4、OpenCV4.13.0与manifest一致；3个开发seed的world_noise、camera_errors、camera_uniform、speed_factor及外生组合摘要在120记录逐项相同。重建数组另存在reconstructed_development_rng，明确是新审计产物。原数组未被回填至旧目录。

## 准入结论

G3算法、共同条件、独立评分、统计单位与随机源复现检查通过。依据用户最新“G3通过后执行G4”的条件授权，允许按已冻结800身份执行，不再筛选正式seed。旧开发入口仍只接受264000-264002；新正式包装层必须验证本冻结协议及G3摘要，存足随机数组，并经机制测试后运行。G4不得启动任何未计划方法/场景。

冻结文档哈希与授权在S3_G4准入凭证.json中，未来任一核心源码或参数变化均使凭证失效。本结论不代表G4已经完成，也不代表真实闭环有效。
''',
    'S3四主组及2×2桥接最终算法定义表.md':'''# S3四主组及2×2桥接最终算法定义表

| 单元 | 到达C0/G/Q/W/S/K | 保护 | 解释 |
|---|---|---|---|
| A_fixed/P_B | C0公共完整性；Applied后1.2s定时，无视觉ArrivalEvent | P_B | 共同P0和安全底线，不是历史纯开环A |
| B_single/P_B | C0+G；Q/W/S/K关闭 | P_B | 单帧覆盖门，不是BQ |
| BTQ/P_B | C0+G+Q+W；S/K关闭 | P_B | 等稳定窗口反馈 |
| F_arrival/P_F（代码名F_full） | C0+G+Q+W+S+K | P_F | 完整到达门与五状态保护策略包 |
| BTQ/P_F | C0+G+Q+W | P_F | 桥接补充，只partial_stall/deviation |
| F_arrival/P_B（代码名F_full/P_B） | C0+G+Q+W+S+K | P_B | 桥接补充，只partial_stall/deviation |

G：eta_target≥0.85且eta_source≤0.08。Q：confidence≥0.2、10≤面积≤100000像素且显著连通域1个。W：至少5连续帧、跨度≥0.25s、最大间隔0.18s、质心跨度≤0.11 pitch、覆盖跨度≤0.15。S与K原样复用冻结S2/v2空间与历史门，不新增corridor_width或正向速度门。

公共P0与Recovery源区确认独立于运输到达开关：源覆盖0.85、位置容差0.18 pitch、共同稳定窗、超时2.6s，并复用可靠性约束。P_B与P_F共用raw Q、C0、原始历史、无观测/无进展/最长尝试、有限动作和停止；P_F额外使用完整五状态和持续Deviation。开关不删除异常观测历史。

所有组共享420示例模板、190→191→192→172、24s预算、0.01s积分、20fps、0.04s模拟Applied延迟及同seed外生数组。动作分叉后位置和Mask允许不同。四组完整轨迹差异不能单独归因于S/K；固定保护的桥接才用于到达门增量。
''',
    'S3正式统计与独立评分协议.md':'''# S3正式统计与独立评分协议

## 物理参考与事件

每trial固定3计划步190→191→192→172。评分只读内部位置、速度、实际激活及任务Applied。参考半径0.09 pitch、速度≤0.06 pitch/s、连续驻留0.15s；严格支持采用离散完成区间上界。评分真值不传给算法。

同目标Retry只改软件epoch且实际激活/驻留连续时，独立驻留不清除；算法证据窗仍重建。Recovery真实切回源或active改变时参考分段，不能拼接。目标离开后旧支持失效。切换瞬间保留旧目标支持左极限仅用于该时刻，不能延伸未来。无有效任务Applied不得补造支持。

Request与新事务Applied分别评价此前当前目标。Applied才到达不能追认Request安全。最终Complete独立评分，但无电极事务时Applied为NA。主动切换截断未来轨迹时，未出现参考只能称unsupported；不得用反事实将其都叫premature。

## 分母与终止

按优先级互斥：infrastructure_invalid、source_preparation_failed、transport_aborted、workflow_complete_without_supported_path、reference_supported_path_complete。源失败后3步均未尝试，仍计3计划步。Retry/Recovery不增计划步。Unknown、错误、动作和删失为独立标签。

每trial总预算24s，包含源准备与事务/响应/成像延迟；每计划步实际Start/Update激活加常规Retry/Recovery/返回目标累计上限7。可用预算相同而非强制动作相同。没有原始数据支持的缺失参考记Unknown，不计已知算法错误/漏确认，不删除计划分母，不补seed。

## 主指标

1. 所有计划端到端trial中独立参考支持路径完成的保守产出；并给invalid比例与全部invalid均完成的上界。
2. 至少一次unsupported_at_request的trial比例；另给每计划步及每实际推进/Complete事件的无支持频率，分母并列。

辅助指标：source_prepared、transport_started、transport_complete分别对全部计划trial；三步账本中的参考到达、支持确认、无支持/提前/不确定、漏确认、未尝试和删失；Request/Applied单独计数。严格成功条件完成时间及n，实际执行时间和终止类别；全计划工程时间代价为严格成功实际完成时间，否则24s（非RMST）。常规Retry、Recovery、返回目标resend分别统计；Unknown/缺Mask/C0拒绝及停止原因完整输出。

确认延迟只对已有同任务参考的支持确认，保留区间[c-u,c-l]与样本数；失败不填0。时延和条件完成时间有选择效应，不作为总体效率的唯一证据。

## 统计单位与区间

每场景20个外生seed为配对区组；三步、尝试、帧、四策略不是独立n。七场景分开；同一seed跨场景复用，不能将140组合当140独立抽样构造总体置信区间。主、桥接、受控运输三层不合池。

二元比例给Wilson95%区间。主预声明比较BTQ−A、BTQ−B、F−BTQ；每场景按同seed差值计算效应及配对seed bootstrap百分位95%区间（2000重抽，分析RNG SeedSequence[20261026,303]，与世界流分离）。所有为逐点描述区间，不宣称同时覆盖或以是否含0断言多重显著性；不进行结果驱动筛选或新增p检验。

成功完成时间配对差仅用双方都严格成功的seed并列n；全计划预算化代价在全部seed比较。错误数据的保守计数上下界单列，不冒充明确算法失败。

桥接固定保护比较F_arrival−BTQ，固定到达门比较P_F−P_B，再给差中之差；交互必须直接计算，不用“一组有差另一组没差”推断。先逐seed得到效应，再重抽seed。开发n=3不合入正式20seed，不预设F胜出。
''',
    'S3 G4运行准入清单.md':'''# S3 G4运行准入清单

| 准入项 | 状态/证据 |
|---|---|
| B_single协议 | 通过；实际Q/W/S/K关闭，旧报告文书勘误 |
| 共同P0/原始历史/保护/预算/时钟 | 通过；既有机制测试和120记录审计 |
| 独立评分 | 通过；3步、物理连续参考、Request/Applied、互斥终止、完整分母 |
| 外生随机复现 | 通过；冻结源码+原环境重建3开发seed，120份摘要/速度因子一致 |
| 用户授权 | 最新任务明确“G3通过后执行G4”，条件授权已满足；不是提前筛选授权 |
| 正式实现测试 | 启动前必须通过正式包装层门禁/计划/统计测试；旧算法不变 |
| 源码/协议封存 | 启动时逐项验证77核心摘要和冻结协议hash；不符立即拒绝 |
| 正式规模 | 主560（1680计划步）、桥接80（240步）、诊断160（480步），共800，不合池 |
| seed | 固定265000-265019全用；审查前不构造，启动后不替换 |
| 失败处理 | 保留所有计划身份，基础设施异常保3步与Unknown，不自动重抽 |
| 可复现材料 | 每trial保存实际Mask/日志/源码，独立存三类外生数组、速度因子及raw hash/shape/dtype/字节序 |
| G5 | 独立逐步/逐事件/Mask/预算/分母复算；全部七场景、配对区间、S3-A/B和全表 |

桥接必要性：partial_stall与deviation用于区分到达门和保护因子；两个主组单元复用，不额外计独立重复。受控运输仅jitter/dropout分解共同P0失败与运输失败。保留原定范围，不根据开发结果符号增减。

G4不是自动允许后续大型S4。只有明确误拒代价/参数敏感性缺口可提出最小补充方案；先分析S2/S3已有证据，不另开有利场景。
''',
    'S3协议差异与开发重验说明.md':'''# S3协议差异与开发重验说明

本轮唯一确认偏差为报告文字：旧G0-G2报告“B_single=单帧G+Q，无W/S/K”应读作“B_single=G+C0，目标Q/W/S/K关闭；raw Q在共同保护通道独立计算”。

证据链：原研究方案第3节 → 封存s3/spec.py选择B_single_frame → 封存s2/spec.py返回四项false → 封存ArrivalGate按开关组合 → 27条B_single运行的target gate_trace.enabled/eligible逐项复核。P0/source与Recovery行四项true不是运输门配置。

原算法未改变，无需恢复算法或生成重跑开发版本。旧报告、旧CSV与源快照保留原样；本说明为可检索勘误，不回写历史记录。S3最终正式版本仅增加正式计划/门禁/材料封存及统计输出包装，不改变动力学、到达判据、保护顺序或阈值。

共同raw Q是监控输入，不意味着B到达门暗中启用Q：到达分支按原EventController优先处理，非到达时质量超时/无进展约束生效。这是算法定义的限制，正式解释不得把B→BTQ差异单独归因W，因为BTQ同时加Q与W。
'''}
    for name,body in docs.items():(OUT/name).write_text(body,encoding='utf-8')
    gate=dict(schema='s3_g4_admission_v1',technical_g3_passed=True,user_conditional_authorization=True,
        formal_allowed_after_implementation_tests=True,contract_sha256=sha(OUT/'S3_正式冻结协议.json'),
        audit_sha256=sha(OUT/'QA/g3_audit.json'),documents={name:sha(OUT/name) for name in docs},
        source_hashes=audit['source_hashes'],no_trial_run_in_G3=True,requires_no_parameter_changes=True)
    write_json(OUT/'S3_G4准入凭证.json',gate)
    print(json.dumps(dict(G3_passed=True,formal_trials_run=0,documents=list(docs)),ensure_ascii=False))

if __name__=='__main__':build()
