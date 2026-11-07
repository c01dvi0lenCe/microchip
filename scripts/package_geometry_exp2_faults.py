"""Package saved fault results, independent audit and figures; zero study runs."""
import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import sys
from xml.sax.saxutils import escape

import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.analyze_geometry_exp2_outcomes import load,read,sha,write_json,write_csv
from scripts.plot_geometry_exp2_faults import ORDER,PANEL_CASES

NAMES=('Exp2_fault_1_causal_trajectories','Exp2_fault_2_outcome_separation')


def fmt(value):return 'NA' if value in ('',None) else f'{float(value):.2f}'
def yes(value):return 'NA' if value in ('',None) else '是' if value is True or value=='True' else '否'


def diagnostics(data):
    results=[]
    for folder in sorted(Path(data).iterdir()):
        if not folder.is_dir():continue
        world=read(folder/'world.csv');events=read(folder/'events.csv');we=load(folder/'world_events.json')
        cfg=load(folder/'config.json')['parameters'];frames=read(folder/'frames.csv');steps=read(folder/'steps.csv')
        max_jump=0.;angle_jump=0.;phase_jump=0.
        for e in we:
            if e['event']!='simulated_applied':continue
            row=world[round(float(e['time_s'])/cfg['dt_s'])];left=e['left_limit']
            max_jump=max(max_jump,*(abs(float(row[k])-float(left[k])) for k in ('x_mm','y_mm','vx_mm_s','vy_mm_s')))
            angle_jump=max(angle_jump,abs(float(row['angle_rad'])-float(left['angle_rad'])))
            phase_jump=max(phase_jump,abs(float(row['shape_phase'])-float(left['shape_phase'])))
        c0={reason:sum(f['c0_reason']==reason for f in frames) for reason in sorted({f['c0_reason'] for f in frames}) if reason}
        results.append(dict(case=folder.name,retries=sum(int(s['retries']) for s in steps),
            recoveries=sum(int(s['recoveries']) for s in steps),resend_requests=sum(e.get('action')=='Resend' and e['event']=='request' for e in events),
            planned_steps=len(steps),attempted_steps=sum(s['attempted']=='True' for s in steps),
            captures=len(read(folder/'captures.csv')),original_replaced_masks=len(list((folder/'unmodified_source_masks').glob('*.png'))),
            deliveries=len(read(folder/'deliveries.csv')),c0_reasons=c0,
            blocked_times_s=[float(w['time_s']) for w in world if w['world_status']=='blocked_no_overlap'],
            max_position_velocity_jump_at_applied=max_jump,max_angle_jump_at_applied_rad=angle_jump,
            max_phase_jump_at_applied=phase_jump))
    return results


def build(data,analysis,audit,figures,verification,output):
    data,analysis,audit,figures,verification,output=[Path(p).resolve() for p in (data,analysis,audit,figures,verification,output)]
    if output.exists():raise FileExistsError(output)
    audited=load(audit/'independent_audit.json');tests=load(verification/'verification.json')
    qa=load(figures/'QA/figure_checks.json')
    if not audited['passed'] or audited['checked_masks']!=8000 or audited['source_sha256']!=sha(ROOT/'scripts/audit_geometry_exp2_faults.py'):
        raise ValueError('final independent audit missing or source changed')
    if len(tests)!=9 or any(t['exit_code'] for t in tests.values()):raise ValueError('nine regression/protection gates required')
    if any(r['text_exit'] or r['collision_exit'] or r['alignment_exit'] for r in qa):raise ValueError('figure QA failed')
    if load(figures/'QA/final_additional_regression.json')['exit_code']:raise ValueError('final additional tests failed')
    for row in qa:
        if sha(figures/(row['figure']+'.pdf'))!=row['pdf_sha256']:raise ValueError('figure changed after QA')
    summary={r['trial']:r for r in read(analysis/'outcome_summary.csv')}
    if set(summary)!=set(ORDER):raise ValueError('all 14 rows required')
    diag=diagnostics(data);by_case={r['case']:r for r in diag}
    if sum(r['captures'] for r in diag)!=8000 or sum(r['original_replaced_masks'] for r in diag)!=28:raise ValueError('Mask denominator differs')
    output.mkdir(parents=True);(output/'QA').mkdir();records=[]
    def record(path,role,copy=None):
        path=Path(path).resolve();item=dict(role=role,path=str(path),sha256=sha(path),snapshot_path='')
        if copy is not None:
            destination=output/copy;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
            if sha(destination)!=item['sha256']:raise ValueError('copied artifact hash mismatch')
            item['snapshot_path']=str(destination)
        records.append(item)
    for folder,role in ((data,'ten deterministic raw cases'),):
        for path in sorted(folder.rglob('*')):
            if path.is_file():record(path,role)
    for folder,prefix,role in ((analysis,'分列评价','independent outcome separation'),(audit,'独立审计','independent audit'),
        (figures,'图稿','figure and QA'),(verification,'QA/软件回归','regression')):
        for path in sorted(folder.rglob('*')):
            if path.is_file():record(path,role,Path(prefix)/path.relative_to(folder))
    sources=set()
    for folder in sorted(data.iterdir()):
        if not folder.is_dir():continue
        manifest=load(folder/'manifest.json');sources.update(manifest['source_code'])
        sources.update(manifest['inputs'][k] for k in ('map_path','pool_world_path','pool_polygons_path'))
        for name in ('config.json','case.json','manifest.json','events.csv','steps.csv','metrics.json','interventions.csv'):
            record(folder/name,'trial compact evidence',Path('数据摘要')/folder.name/name)
    # Baseline files are linked by read-only analysis; no baseline trial is rerun.
    for origin in load(analysis/'manifest.json')['origins']:
        trial=Path(origin['trial'])
        if trial.parent!=data:
            for name in ('world.csv','events.csv','config.json','manifest.json','metrics.json'):record(trial/name,'old normal read-only source')
    for name in ('analyze_geometry_exp2_outcomes.py','audit_geometry_exp2_faults.py','plot_geometry_exp2_faults.py',
        'check_geometry_exp2_fault_figures.py','verify_geometry_exp2_faults.py','package_geometry_exp2_faults.py',
        'audit_geometry_exp2_mechanisms.py','plot_geometry_exp2_mechanisms.py'):
        sources.add(str(ROOT/'scripts'/name))
    sources.update(str(p) for p in (ROOT/'tests').glob('test_geometry_exp2_fault*.py'))
    sources.add(str(ROOT/'tests/test_geometry_exp2_outcomes.py'))
    sources.add(str(ROOT/'tests/test_geometry_exp2.py'))
    for name in ('audit_panel_alignment.py','audit_pdf_text.py','audit_figure_collisions.py','validate_figure.py'):
        sources.add(str(Path.home()/'.agents/skills/nature-figure/scripts'/name))
    for name in ('docs/superpowers/specs/2026-10-30-geometry-exp2-fault-mechanisms-design.md',
        'docs/superpowers/plans/2026-10-30-geometry-exp2-fault-mechanisms.md',
        'docs/chapter2-geometry-exp2-fault-figure-contract-2026-10-30.md',
        'docs/chapter2-geometry-exp2-fault-closeout-2026-11-01.md'):
        sources.add(str(ROOT/name))
    for name in sorted(sources):
        path=Path(name)
        try:snapshot=Path('源码与协议')/path.relative_to(ROOT)
        except ValueError:snapshot=None
        record(path,'source/input',snapshot)
    write_csv(output/'来源与hash索引.csv',records);write_json(output/'mechanism_diagnostics.json',diag)
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    style=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=style,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),keepWithNext=True)
    small=ParagraphStyle('table',parent=style,fontSize=9,leading=14,spaceAfter=0)
    story=[];markdown=[]
    def paragraph(text,head=False):story.append(Paragraph(escape(str(text)),heading if head else style));markdown.append(str(text)+'\n')
    def page():story.append(PageBreak());markdown.append('\n---\n')
    def table(headers,values,widths):
        tab=Table([[Paragraph(escape(str(x)),small) for x in row] for row in [headers]+values],colWidths=[v*mm for v in widths],repeatRows=1)
        tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.4,colors.grey),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        story.extend([tab,Spacer(1,8)]);markdown.append('| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n')
        markdown.extend('| '+' | '.join(map(str,row))+' |\n' for row in values)
    paragraph('实验二：十条异常机制开发与分列评价审查',True)
    paragraph('收尾日期：2026-11-01 | 数据批次：2026-10-30 | SIMULATION / DEVELOPMENT / 每案例n=1')
    paragraph('一、本轮完成与研究定位',True)
    paragraph('按批准范围完成10条预声明、无随机调用的异常开发案例；本次收尾不重跑。真实420电极设计几何、190→191→192→172路径、4 mm面积等效轮廓及首版速度松弛World保持。另4条旧正常案例只读复算，不能与新10条合池计算算法性能。')
    paragraph('保存8000张算法可见模拟Mask，28个替换帧另存原始Mask；固定30个计划步，实际尝试26步、4步未尝试保留。13个交付丢帧和1次重复交付均显式记录，摄像采样、交付、判定、request、模拟Applied及响应分开。没有正式seed、真实ACK、实际高压输出或实物性能数据。')
    paragraph('阶段判断：异常机制与日志链路可继续用于开发审查，但正式随机性能比较仍暂缓。持续伪观测、模型交叠门以及未标定动力学的限制保留；没有将M3设定为必须胜出。')
    paragraph('二、审查意见处理',True)
    table(['审查要求','本轮处理'],[
        ['三类评价','决策参考支持、实际Update请求/Applied支持、实际内部运动结果分别保存，不合称安全成功率。'],
        ['电极身份','completed_task_target、commanded_active_electrode、applied_active_electrode分列；最终Complete没有新电极事务。'],
        ['完成与到达','工作流完成、最终参考首次建立、Complete当时支持与H时支持分列；不以未来到达追认过去。'],
        ['动力学身份','首版exp2保持；异常夹具单独命名。Applied延迟0.30 s仅作为压力干预，其他正常动力学参数不调整。'],
        ['正式准入','小规模确定性机制，不新增正式扫描或参数敏感性批次。正式基线/预算/动力学仍需独立冻结依据。']],[35,135])
    page();paragraph('三、首版正常案例只读复核',True)
    values=[]
    for name in ORDER[:4]:
        r=summary[name];values.append([name,fmt(r['workflow_complete_s']),fmt(r['final_target_reference_first_s']),yes(r['final_reference_supported_at_complete']),yes(r['final_reference_supported_at_horizon']),r['unsupported_update_requests']+'/'+r['unsupported_update_applied']])
    table(['方法','Complete/s','最终参考/s','完成时支持','H时支持','无支持请求/Applied'],values,[23,27,27,27,23,43])
    paragraph('M1在10.00 s宣布工作流完成，但最终参考在10.21 s才建立；M2/M3在10.75 s完成时，参考已于10.71 s建立。随访至40 s最终均获支持，不能据此消除M1完成时尚未获支持的事实。')
    paragraph('M2/M3前两次Update请求在3.80/7.25 s，当前任务目标分别为191/192；命令的下一活动电极分别为192/172，Applied为3.84/7.29 s。独立参考在3.81/7.26 s建立，因此请求不支持而Applied支持。这不等同于实际运输危险，也不等同于请求已获支持。')
    paragraph('四、统计分母与事件口径',True)
    table(['字段','定义'],[
        ['决策','当前任务推进或最终Complete；最多三次，不等于三次电极Update。'],
        ['Update请求','只有真实request且action=Update；最多两次，记录被判定完成的任务目标和下一命令电极。'],
        ['Update Applied','与真实Update请求ID匹配的模拟电极生效；用当前旧任务目标的左极限参考评分。'],
        ['最终参考','只从内部位置、速度及实际激励下的驻留重建。Complete当时及H时支持各自计算。'],
        ['NA/失败','未发生Complete、无Applied或未尝试均不填0成功；不将同一trial多个失败标签当作独立样本。']],[35,135])
    paragraph('所有事件与单位均为simulation时间和毫米设计坐标。内部参考不是经测量的物理安全切换标准。旧unsupported_requests通用字段包含Complete，本包保留旧文件，另以实际Update字段消除命名歧义。')
    page();paragraph('五、全部10条异常案例（完整保留）',True)
    values=[]
    for name in ORDER[4:]:
        r=summary[name];d=by_case[name]
        values.append([name,fmt(r['workflow_complete_s']),fmt(r['final_target_reference_first_s']),yes(r['final_reference_supported_at_complete']),yes(r['final_reference_supported_at_horizon']),r['unsupported_update_requests']+'/'+r['unsupported_update_applied'],str(d['retries'])+'/'+str(d['recoveries']),str(r['attempted_steps'])+'/3'])
    table(['案例','Complete/s','最终参考/s','完成时','H时','无支持请求/Applied','Retry/Recovery','尝试/计划'],values,[39,20,20,15,14,22,22,18])
    paragraph('本表每行仅一个确定性夹具，没有随机发生概率、置信区间或可外推的成功率。七条发生Complete，三条40 s预算耗尽；后者分别保留未尝试步骤及无最终参考。两个stall_false案例均有1次无支持Update请求/Applied。')
    paragraph('注意：同名外生干预不意味着不同控制策略后续Mask完全相同。控制一旦分叉，后续World和观察随之变化；这是闭环机制比较，不是实验一B的共同缓存到达算法评测。')
    page();paragraph('六、五类机制的实际诊断',True)
    paragraph('1. 提前伪目标：2.05 s曝光的单帧伪191导致M1于2.10 s推进，M2仍于3.80 s推进。该M1案例最终在9.41 s获得目标参考，没有无交叠阻断。因此，不能从“早确认”直接推出“最终运输失败”。')
    paragraph('2. 永久卡滞叠加持续伪目标：2.00 s固定内部质心/速度，2.20–2.75 s的12帧报告伪191。M2在2.50 s、M3在2.55 s均推进到192；之后各执行2 Retry、1 Recovery，并于40 s预算耗尽。K增加0.05 s等待，没有排除这类持续一致错误观测。')
    paragraph('3. 相机丢帧/时序：camera_gap丢弃13次交付，late_duplicate保留帧69两次交付及帧68延迟。重复帧69在3.52 s、旧帧68在4.45 s处理，C0按优先级记DUPLICATE_OR_REVERSED；不能把同一次拒绝重复归因于多个独立gate。两案例Complete仍为10.75 s。这次丢帧和重复发生在关键覆盖确认窗之前，不能据此证明关键确认期丢帧没有代价。')
    paragraph('4. Applied/保护：0.30 s延迟案例Complete为11.75 s，最终参考11.72 s；无重试。单独卡滞案例没有ArrivalEvent，执行2 Retry、1 Recovery后40 s预算终止。三个失败案例均没有Resend。完整Recovery重确认→Resend分支由既有确定性单测覆盖，本批未自然触发；没有虚构Resend曲线。')
    paragraph('5. 转弯：turn_early_M1在4.85 s请求172，出现2个无交叠阻断tick，但最终8.72 s仍获得参考；M2保留正常10.75 s Complete。Applied瞬间的位置、速度、方向和形态连续；后续无交叠门可令速度直接归零，这一不连续来自模型规则，不能写成真实液滴转弯动力学已验证。')
    paragraph('结论限于机制：单帧异常、持续伪目标和运输故障能沿日志链传播至控制与后续World；W能拒绝本例瞬态错误，M3对持续伪观测仍无有效排除。没有形成普遍性能优势、物理安全或实物准确率结论。')
    page();paragraph('七、独立审计与软件回归',True)
    paragraph('最终v2审计逐一核查10案例/8000张可见Mask及原Mask、World积分/卡滞、G/Q/S/K/C0、连续窗、一次性ArrivalEvent、真实request/Applied和独立参考。审计不调用World、控制器或原评分器。')
    paragraph('复核过程中关闭5个审计盲区：跨运行身份、speed与vx/vy不一致、消费帧缺行、干预日志缺失、delivery_uid错连。均以修改后重新hash的反例先证伪，再修复验证；研究轨迹未改写或重跑。')
    table(['检查','保存结果'],[[key,'exit='+str(value['exit_code'])+(('；'+str(value['tests'])+'项') if value['tests'] is not None else '')] for key,value in tests.items()],[75,95])
    paragraph('全量记录1100项包含1项可选跳过；最终专项34项另验16接口、7分列、8审计和3绘图测试，全部通过。专用测试与全量有重叠，不能相加为独立试验数量。首版审查包、旧正式结果及原源码保护通过。')
    paragraph('八、文件与来源',True)
    paragraph('本包含10例数据索引、全部14行分列评价、逐计划步电极身份/决策对齐CSV、最终独立审计、干预诊断、源码/配置/环境回归记录、两图PDF/SVG/600dpi PNG。原始8000张Mask在实验结果目录保留，不在审查包重复复制；来源与hash索引可逐项复核。')
    page();paragraph('九、两张图的图注',True)
    paragraph('图1：预声明提前伪目标、卡滞＋持续伪目标与转弯伪观测的三组对照。实线/虚线为同trial内部World x/y，圆/叉为实际处理Mask的质心，三角/方形为真实模拟request/Applied。坐标以190初始中心为原点，mm；横轴为simulation时间。各面板n=1，无随机统计，不是真实分割或流体动力学。')
    paragraph('图2：全部4条旧正常与10条新异常的Complete、最终参考首次时刻及无支持Update次数。左图同一行两标记仅纵向错位以避免遮挡，横轴时间不变；NA为事件未发生，不是46 s到达。右图只计实际Update请求/Applied，不含Complete。没有置信区间，因为每行是一个确定性机制夹具，不是正式性能均值。')
    paragraph('十、正式随机比较准入意见',True)
    paragraph('本阶段收尾：异常接口、分列指标和关键机制分支通过开发验收；正式随机性能比较暂缓。未完成的门槛包括：独立确定固定等待基线及总预算、预声明最小动力学敏感性、检查排序是否依赖速度松弛/加速度/目标常数/交叠门、以及公平外生扰动来源和完整统计分母。')
    paragraph('本次不增加算法约束、不修改液滴形态库、不调整阈值或根据失败结果挑选新时刻；不启动新seed。真实Mask、配准时间/空间绑定、人工到达参考、实际高压输出及安全计量仍需独立实验。')
    paragraph('请Chat集中审查：①决策、Applied和运输结论是否分开；②持续伪目标和提前但最终成功的反例是否恰当解释；③未触发分支是否如实标注；④模型参数与无交叠停止是否仍可能主导结论；⑤下一步是否只需最小参数敏感性和基线冻结，而非扩大机制种类。')
    paragraph('本轮完成后停止扩展。所有原始版本保留，无Commit/Push。')
    def footer(canvas,document):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#65717c'))
        canvas.drawString(20*mm,12*mm,'SIMULATION | DEVELOPMENT | 非实物性能')
        canvas.drawRightString(190*mm,12*mm,str(document.page))
    body=output/'QA/正文.pdf'
    SimpleDocTemplate(str(body),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    doc=fitz.open(body)
    for name in NAMES:
        with fitz.open(figures/(name+'.pdf')) as f:doc.insert_pdf(f)
    pdf=output/'实验二_十条异常机制与分列评价_Chat审查报告.pdf';doc.save(pdf);doc.close()
    (output/'审查报告.md').write_text('\n'.join(markdown),encoding='utf-8')
    layout=[]
    with fitz.open(pdf) as document:
        for i,page in enumerate(document):
            spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
            text=page.get_text();outside=any(s['bbox'][0]<-1 or s['bbox'][1]<-1 or s['bbox'][2]>page.rect.width+1 or s['bbox'][3]>page.rect.height+1 for s in spans)
            layout.append(dict(page=i+1,min_font_pt=min(s['size'] for s in spans),outside=outside,missing_glyph='\ufffd' in text or '\x00' in text))
            page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False).save(output/'QA'/f'page_{i+1:02d}.png')
    write_json(output/'QA/text_layout_check.json',layout)
    if any(r['outside'] or r['missing_glyph'] for r in layout):raise ValueError('PDF glyph or clipping check failed')
    print(dict(pdf=str(pdf),pages=len(layout),indexed_sources=len(records),diagnostic_cases=len(diag)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('data','analysis','audit','figures','verification','output'):p.add_argument(name)
    a=p.parse_args();build(a.data,a.analysis,a.audit,a.figures,a.verification,a.output)
