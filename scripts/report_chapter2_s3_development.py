"""Package G0-G2 evidence. Reads saved CSV/QA only; no research execution."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1')
DATA=OUT/'development_smoke'
TITLE='第二章S3_G0-G2实施与验收报告'

def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def js(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def bridge_check(metrics):
    comparisons=[]
    fields=('event','time_s','step','epoch','attempt','phase','source','target','activated_target','action','activation_step')
    for scenario in ('partial_stall','deviation'):
        for seed in ('264000','264001','264002'):
            for protection in ('P_B','P_F'):
                ms=[next(m for m in metrics if m['scenario']==scenario and m['seed']==seed and m['protection']==protection
                         and m['method']==method and m['phase_mode']=='end_to_end') for method in ('BTQ','F_full')]
                ev=[[{k:r.get(k,'') for k in fields} for r in rows(DATA/m['relative_trial_path']/'observations/events.csv')
                     if r['event']!='ArrivalEvent'] for m in ms]
                comparisons.append(dict(scenario=scenario,seed=int(seed),protection=protection,
                                        control_events_equal=ev[0]==ev[1],event_counts=[len(e) for e in ev]))
    (OUT/'QA/bridge_control_comparison.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2),encoding='utf-8')
    return comparisons

def build():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak
    from pypdf import PdfReader,PdfWriter
    metrics=rows(DATA/'development_trials.csv');summary=rows(DATA/'development_summary.csv')
    audit=js(OUT/'QA/independent_data_audit.json');protection=js(OUT/'QA/protection_check.json')
    checks={k:js(OUT/'QA'/f'{k}_verification.json') for k in ('local','full','compile','chain','diff')}
    assert audit['passed'] and protection['passed'] and all(c['passed'] for c in checks.values())
    assert len(metrics)==120 and len(rows(DATA/'development_steps.csv'))==360
    bridge=bridge_check(metrics)
    pdfmetrics.registerFont(TTFont('CJK','C:/Windows/Fonts/simhei.ttf'))
    styles={
        'body':ParagraphStyle('body',fontName='CJK',fontSize=9,leading=14,spaceAfter=6),
        'small':ParagraphStyle('small',fontName='CJK',fontSize=7,leading=10,spaceAfter=2,wordWrap='CJK'),
        'head':ParagraphStyle('head',fontName='CJK',fontSize=12,leading=18,spaceAfter=8,spaceBefore=10,keepWithNext=True,textColor=colors.HexColor('#174b70')),
        'title':ParagraphStyle('title',fontName='CJK',fontSize=18,leading=25,spaceAfter=14,textColor=colors.HexColor('#174b70'))}
    story=[];md=[]
    def para(s,style='body'):return Paragraph(escape(str(s)),styles[style])
    def text(s):story.append(para(s));md.append(s+'\n')
    def heading(s):story.append(para(s,'head'));md.append('## '+s+'\n')
    def table(headers,data,widths=None):
        widths=widths or [174*mm/len(headers)]*len(headers)
        t=Table([[para(v,'small') for v in headers]]+[[para(v,'small') for v in r] for r in data],colWidths=widths,repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E5EEF4')),('VALIGN',(0,0),(-1,-1),'TOP'),
                              ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#174b70')),('BOTTOMPADDING',(0,0),(-1,-1),5),
                              ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F5F7F9')])]))
        story.extend([t,Spacer(1,7)])
        md.extend(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |'])
        md.extend('| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in data);md.append('')
    story.append(para('第二章S3 G0-G2实施与验收','title'));md.append('# '+TITLE+'\n')
    text('2026-10-26 | SIMULATION | chapter2_s3_g0_g2_dev1 | 仅开发验收，不是正式性能比较。')
    heading('1. 验收结论与边界')
    text('G0接口、公平性契约、G1确定性机制与G2开发冒烟已完成，可进入G3设计冻结审查。G4正式扫描未启动；正式seed 265000-265019在本入口被拒绝。只有在研究问题、比较口径及配置通过G3审查后，才具备启动G4的条件。')
    text(f"实际持久化120条记录：84主组、12桥接补充单元、24受控运输诊断，共360个计划运输步。全部保留，无删seed或补跑替换；独立只读审计0差异。S3局部{checks['local']['tests']}项通过；全量{checks['full']['tests']}项通过（1项跳过）；编译和7类独立软件控制链通过。")
    text(f"保护校验覆盖{protection['files']:,}个此前文件，内容变更0。已有tracked/untracked修改全部保留。只新增独立S3模块、测试、绘图/审计/交付工具与新输出；未改旧World、Camera、生产五状态、AM、STM32、U-Net、第三章或S1/S2数据。无Commit/Push。")
    text('本轮结果只能支持实现机制及开发场景诊断。每条件3个开发seed不形成正式成功率、置信区间或完整算法优越性结论。仿真为pitch单位二维点运动和合成Mask，不是CFD、实物电润湿动力学或真实U-Net结果。')
    heading('2. G0复用与新增接口')
    table(['来源/接口','处理方式','理由及边界'],[
        ['world.py / vision.py / SimulationMap','原样复用','原速度、延迟、扰动与SyntheticCamera输出均不改；使用420电极示例模板，非Gerber实测尺度。'],
        ['v2 ObservationPipeline / ArrivalGate','原样组合复用','C0及原始S/K/Q/历史共同计算；只在到达门开关，不污染保护输入。'],
        ['FrameTiming / StepContext / ArrivalEvent / EvidenceWindow','原样复用','simulation独立时钟，任务epoch屏障、连续窗口、事件一次消费。'],
        ['StateRecognizer / EventController','原样复用','完整五状态与有界控制；P_B屏蔽非到达状态标签，P_F保留；原始观测和无进展保护均共同输入。'],
        ['s3/spec.py / S3Spec / development_plan','新增','锁定4主组、2×2桥接、3计划步、120记录上限、开发seed。'],
        ['s3/adapter.py / S3Adapter / TransactionSlot','新增','1.2s固定策略，无虚假视觉到达事件；pending期间禁止第二事务。'],
        ['s3/runner.py / run_trial / flush_applications','新增','独立协调器；恰到期应用先于adapter通知，原半开积分及_apply逻辑不改。'],
        ['s3/reference.py / physical_segments / support_at','新增','物理连续段而非软件epoch；旧v2参考不能直接满足同目标Retry要求。'],
        ['s3/evaluation.py / evaluate_trial / terminal_class','新增','请求/Applied独立评分、互斥终止、3计划步完整分母。'],
        ['s3/persistence.py / study.py / run_chapter2_s3.py','新增','仅开发入口，追加式数据、77核心源码快照、原始Mask与时序日志。']
    ],[48*mm,28*mm,98*mm])
    heading('3. 四主组与2×2桥接公平性')
    table(['组别','到达门','保护策略','共同约束'],[
        ['A_fixed','模拟Applied后1.2s定时；不发ArrivalEvent','P_B','共同P0、C0、原始质量/进展输入、预算和外生流'],
        ['B_single','单帧G+Q；无W/S/K','P_B','同上；单帧判定仍受任务因果和数据完整性约束'],
        ['BTQ','G+Q+W','P_B','与F同覆盖阈值、W/Q、时钟及任务因果'],
        ['F_full','G+Q+W+S+K','P_F','完整五状态保护；非S/K独立增量对照'],
        ['桥接补充','BTQ/P_F、F_arrival/P_B','形成2×2','partial_stall、deviation；主组另两格复用，不当新独立样本']
    ],[24*mm,51*mm,23*mm,76*mm])
    text('P0与Recovery源区门均采用覆盖≥0.85、目标位置容差0.18 pitch及共同5帧/0.25s窗口，P0超时2.6s。目标G为eta_target≥0.85、eta_source≤0.08；Q为confidence≥0.2、面积10至100000像素且有效连通区域为1。W最大断档0.18s、质心跨度≤0.11 pitch、覆盖跨度≤0.15。')
    text('S为源/目标任务区域约束及目标位置门；K复用既有速度/预测残差一致性。所有C0可解析观测都进入相同原始历史，包括低Q和空间冲突帧，关闭S/K不删除历史。未新增corridor_width或正向速度门。Unknown是观测/判定可靠性标记，不是第六物理状态。P_B图中的Unknown还可能来自研究保护分支不输出非到达五状态标签，不能据此计算真实五状态准确率。')
    text('共同基础保护包含缺观测/无进展/尝试超时及有界动作。每步最多7个实际电极Applied：初始目标1次、常规Retry最多2次、Recovery最多1次、返回目标1次及再次Retry最多2次。Recovery返回目标单独记为resend，不混入常规Retry；Retry/Recovery不会新增计划运输步。')
    text(f"21个端到端场景-seed共同P0前缀一致，27个场景-seed-阶段配对组外生摘要一致；审计找到{audit['equal_frame_control_fork_witness_groups']}组控制分叉后同frame_id的实际Mask不同。共同的是外生随机流，不是强行相同的闭环观测轨迹。外生数组原字节未持久化，只保存摘要与源码/seed/速度因子，审计未重新生成数组。")
    equal=sum(r['control_events_equal'] for r in bridge)
    text(f'只读桥接复核：同一保护策略下BTQ与F_arrival的12个场景-seed-保护配对中，控制事件及时间完全一致者为{equal}/12。deviation的Retry/Recovery差异随P_B/P_F切换，而不是本批S/K到达门收益。现有v2旧21缓存BTQ/F到达确认一致的事实亦不被本轮改写。')
    heading('4. G1独立物理参考与手算验证')
    text('独立评分读取内部位置p(t)、内部速度v(t)和实际激活电极a(t)，不读Mask、预测状态或到达阈值。目标中心c的支持条件为||p-c||≤0.09 pitch、||v||≤0.06 pitch/s且连续驻留≥0.15s。按真实active变化分段；软件epoch变化本身不切断物理段。参考完成时刻用相邻内部tick形成区间，严格支持使用区间上界。')
    table(['机制','确定性输入/手算','核查结果'],[
        ['同目标Retry','0,0.05,0.10,0.15,0.20s均静止在191；0.10s改epoch','参考上界0.15s；0.20s仍支持，软件epoch不清除驻留'],
        ['Recovery切换','191驻留0-0.10s，0.15s激活190，0.20-0.30s再到191','前后不拼接；两段各不足0.15s，无支持'],
        ['离开目标','驻留至0.20s，0.25s偏离0.30 pitch','0.20s支持；0.25s不支持'],
        ['请求/Applied','驻留完成0.15s；请求0.10s、Applied0.20s','请求不支持，Applied支持；不追认请求安全'],
        ['切换左极限','旧目标连续驻留至切换瞬间','仅切换当时允许旧段左极限；切换之后不延长旧支持'],
        ['旧帧/重复/倒序','重复SDK身份、倒序时间或旧epoch','C0拒绝并重建窗口，无新到达/事件消费'],
        ['事务与失败','pending、错误Applied/重复accept、未激活步','不发重叠事务；失败不推进上下文；一次性消费；未激活不能获得路径支持'],
        ['分母与Unknown','源失败/真值缺失/重复推进','固定3计划步；保留未尝试；真值Unknown不硬算已知错误或漏确认']
    ],[28*mm,71*mm,75*mm])
    text('独立规格与质量审查关闭6类问题：未激活步获支持、切换边界旧目标支持丢失、恰到期Applied晚一tick、异常记录缺地图不能封存、参考Unknown误计错误、只记录HEAD而遗漏未提交源码。以上均先加反例，再在新S3层修复；原World和生产控制代码未改。')
    heading('5. G2完整计数：主组84条')
    text('下表每行均为3 planned trials / 9 planned steps。S/W/P分别是源准备、运输流程完成、独立参考支持路径完成；W不是路径成功率。Ref为主评价窗口内参考到达步，Sup为支持确认步，U为无支持推进请求，M为参考到达但漏确认，NA为未尝试计划步。数值直接读取冻结开发CSV。')
    def count_table(cohort):
        group=[r for r in summary if r['cohort']==cohort]
        # reference_arrived_steps is a trial metric, not a stored group-summary field.
        data=[]
        for r in group:
            matched=[m for m in metrics if all(m[k]==r[k] for k in ('cohort','scenario','method','protection','phase_mode'))]
            ref=sum(int(m['reference_arrived_steps']) for m in matched)
            data.append([r['scenario'],r['method']+'/'+r['protection'],'/'.join(r[k] for k in ('source_prepared','transport_complete','path_complete')),
                         ref,*[r[k] for k in ('supported_confirmations','unsupported_requests','missed_confirmations','unattempted_steps')]])
        table(['条件','方法/保护','S/W/P','Ref','Sup','U','M','NA'],data,[29*mm,40*mm,22*mm,16*mm,16*mm,16*mm,17*mm,18*mm])
    count_table('main')
    story.append(PageBreak())
    heading('6. 桥接12条与受控运输24条：独立列示')
    text('桥接仅补充2×2的另外两格，每行3试验/9步；不能与主组重复加权。受控运输从声明的源区初始位置开始，绕过P0，仅诊断运输阶段。其S列为工程初始化标记，不是源视觉确认或源准备的独立证据。')
    count_table('bridge');count_table('diagnostic')
    heading('7. 失败原因、Unknown及预算完整保留')
    text('下表涵盖全部40个条件-方法-保护-阶段组；T/R/Z为常规目标Retry / Recovery / Recovery后返回目标的resend（实际Applied次数）。Unk为处理帧Unknown计数，Drop为缺Mask计数；不是独立试验数。计划分母仍为每行3试验/9步。')
    table(['层/条件','方法/保护','T/R/Z','Unk/Drop','停止原因（记录数）'],[
        [r['cohort']+'/'+r['scenario'],r['method']+'/'+r['protection'],'/'.join(r[k] for k in ('retries','recoveries','recovery_resends')),
         r['unknown_frames']+'/'+r['missing_mask_frames'],str(json.loads(r['stop_reasons']))] for r in summary
    ],[35*mm,32*mm,23*mm,23*mm,61*mm])
    heading('8. 实际场景诊断与可归因边界')
    text('normal：固定1.2s和稳定窗方法都可能得到支持路径；单帧组虽3/3流程完成，却均不是参考支持路径。说明流程走完与安全推进必须分开。delayed：固定时间与当前响应延迟不匹配，无支持推进不能因完成快而算成功。')
    text('partial_stall：模型明确设置首次尝试部分到达停滞，Retry会改变该模型的后续运动响应；BTQ/F完成不等于证明真实液滴均可如此恢复。deviation：P_B主要通过无进展后Retry，P_F通过持续Deviation后Recovery再返回目标。桥接对照表明行为归属于保护分支，不应归因于S/K到达增量。')
    text('jitter：端到端四组共同P0均失败，全部36个主组计划步未尝试。受控运输诊断中，固定时间能完成参考支持路径，稳定窗组则出现恢复确认超时。这是稳定确认的适用边界，不删除、不以绕过P0的诊断取代端到端结果。')
    text('dropout：每主组有1个共同源准备失败；BTQ/F另各有1个运输预算超时。受控运输中仍有恢复预算相关终止。failure：固定时间可以把流程推进至Complete，却没有支持路径；反馈策略在有限预算后保护停止。以上为开发机制现象，不进行n=3正式显著性比较。')
    text(f"259个推进完成事件（包括无电极事务的Complete）中，独立审计请求支持{audit['supported_requests']}、无支持{audit['unsupported_requests']}。模拟Applied支持{audit['supported_applied']}；Complete没有伪造Applied，故两种分母不同。U不能笼统写成提前确认：若本任务根本无参考到达，则属于unsupported，而非对已发生参考的premature。各逐事件标签保存在原始评分与独立CSV中。")
    text('终止类别按优先级互斥：基础设施无效、源准备失败、运输中止、流程完成但路径无支持、参考支持路径完成。错误事件、Retry/Recovery、Unknown、删失是独立标签。未尝试步保留；真实参考未知时另记Unknown，不强制归为已知错误。固定24s失败预算化成本不是生存分析估计。')
    heading('9. 过程图与可追溯性')
    text('五张图后附：正常/偏离seed264000四策略运动及实际处理Mask、相同记录的位置-覆盖-状态-事件时间线、全部主组互斥终止与预算计数。normal/deviation及seed264000在运行前manifest中预声明。每个面板为自己的同一trial，不把四策略不同闭环轨迹拼成同一次运行。')
    text('图内线表示内部模拟轨迹，交叉表示观测质心，橙色轮廓直接读取保存的SyntheticCamera Mask PNG；无重建或插值补造Mask。金线是独立参考完成，控制请求和绿色Applied分别标记。所有曲线、未知和事件来自实际日志。运动图只展示路线ROI而非宣称真实420几何。')
    text(f"独立审计核验{audit['files_hash_verified']:,}个manifest文件摘要、{audit['decoded_masks_raw_hash_verified']:,}张Mask及解码像素摘要；每trial封存77个核心源码。来源见figures/figure_sources.json，源码快照在各trial/source_code。既有dirty源码由内容hash而非HEAD单独标识。")
    heading('10. 回归、图稿检查与复现入口')
    table(['验证','实际结果','记录'],[[k,str(v['tests'])+' tests' if v['tests'] is not None else 'exit 0',v['log']] for k,v in checks.items()])
    text('图稿检查：SVG/PDF与600dpi PNG齐备；预览300dpi；5图字体下限和面板对齐通过，自动碰撞无FAIL。两项源级WARN有明确边界：没有用户未要求的TIFF；开发原始计数不做不适当的n=3性能置信区间。最终仍需按论文版心确定缩放和中文图注。')
    commands=[
        'python run_chapter2_s3.py plan',
        'python -m unittest discover -s tests -p "test_chapter2_s3*.py" -v',
        'python -m unittest discover -s tests -v',
        'python -m compileall -q main.py app_controller.py controllers dmf simulation validation',
        'python -m validation.closed_loop_chain.run_validation',
        'python scripts/audit_chapter2_s3.py',
        'python scripts/protect_chapter2_s3.py verify',
        'python scripts/plot_chapter2_s3_development.py',
        'python scripts/report_chapter2_s3_development.py']
    for c in commands:text(c)
    text('开发批次入口为python run_chapter2_s3.py development --output <全新目录>。本阶段120条已经完成，不建议再次执行或覆盖本目录。绘图与报告脚本只读现有数据。核心计算使用Python3.14；图稿/报告使用Codex bundled Python3.12（Matplotlib3.10.7、ReportLab4.4.9）；缺失的绘图依赖只安装在文档运行时。')
    heading('11. G3冻结建议及G4准入')
    text('建议G3逐项冻结：①P0及源失败分母；②A每次Applied后1.2s；③G/Q/W及原始历史采样；④P_B/P_F共同保护与分支差异；⑤每步7次Applied和24s预算；⑥独立物理连续参考、左极限及请求/Applied分开评分；⑦三计划步与互斥终止；⑧未来正式seed与配对统计、延迟删失及失败代价预声明。')
    text('G4工程机制前置检查已满足，但正式运行批准条件尚未满足：仍需用户审阅并冻结G3，确认正式比较要回答控制策略安全性/效率及边界，而不是预设F必胜。当前同保护下BTQ/F到达和控制没有增量差异，S/K贡献应引用S2的限定合成压力证据，不能由S3桥接Recovery差异替代。')
    text('仍未验证：真实Mask、真实U-Net、实际曝光与真实ACK物理因果、液滴真实动力学、实物路径成功率及真实五状态准确率；S/K在闭环随机场景的独立收益、普遍性及误拒代价仍未建立。S1/S2冻结结果、旧v1/v2版本及seed不与本批合池。')
    heading('附录：实际新增文件与来源索引')
    files=[str(p.relative_to(ROOT)).replace('\\','/') for p in sorted((ROOT/'dmf/chapter2_sim/s3').glob('*.py'))]
    files += ['run_chapter2_s3.py']+[str(p.relative_to(ROOT)).replace('\\','/') for p in sorted((ROOT/'tests').glob('test_chapter2_s3*.py'))]
    files += ['scripts/'+n for n in ('audit_chapter2_s3.py','check_chapter2_s3_figures.py','plot_chapter2_s3_development.py','protect_chapter2_s3.py','report_chapter2_s3_development.py','run_chapter2_s3_checks.py','verify_chapter2_s3_delivery.py')]
    table(['新增文件（1）','新增文件（2）'],[files[i:i+2]+([''] if len(files[i:i+2])==1 else []) for i in range(0,len(files),2)])
    text('方案来源：docs/chapter2-s3-study-design-2026-10-26.md；第二章S2收尾与S3研究方案_审查包_r5.pdf。新增执行计划位于docs/superpowers/plans/2026-10-26-chapter2-s3-g0-g2.md。')
    names=('planned_trials.json','config_manifest.json','development_trials.csv','development_steps.csv','request_applied_evaluation.csv','development_summary.csv','development_audit.json')
    table(['开发数据文件','SHA256'],[[name,sha(DATA/name)] for name in names],[69*mm,105*mm])
    (OUT/(TITLE+'.md')).write_text('\n'.join(md)+'\n',encoding='utf-8')
    (ROOT/'docs/chapter2-s3-g0-g2-implementation-2026-10-26.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    def foot(c,d):
        c.setFont('CJK',7);c.setFillColor(colors.HexColor('#64717C'));c.drawString(18*mm,12*mm,'SIMULATION | S3 G0-G2 | DEVELOPMENT ONLY | 2026-10-26');c.drawRightString(192*mm,12*mm,str(d.page))
    temp=OUT/'QA/report_text.pdf'
    SimpleDocTemplate(str(temp),pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=17*mm,bottomMargin=20*mm).build(story,onFirstPage=foot,onLaterPages=foot)
    writer=PdfWriter();writer.append(temp)
    for name in ('motion_normal_264000','timeline_normal_264000','motion_deviation_264000','timeline_deviation_264000','stage_and_budget_counts'):
        writer.append(OUT/'figures'/('S3-dev-'+name+'.pdf'))
    target=OUT/(TITLE+'.pdf')
    with target.open('wb') as f:writer.write(f)
    report_manifest=dict(report_sha256=sha(target),markdown_sha256=sha(OUT/(TITLE+'.md')),report_pages=len(PdfReader(target).pages),
                         no_simulation_execution=True,bridge_equal_pairs=equal,bridge_pairs=len(bridge),new_files=files)
    (OUT/'QA/report_manifest.json').write_text(json.dumps(report_manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report_manifest,ensure_ascii=False))

if __name__=='__main__':build()
