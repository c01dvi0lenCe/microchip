"""Package actual fixed-mechanism findings, including the uncompleted slow case."""
import csv
import json
from pathlib import Path
import re
import subprocess
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
from dmf.chapter2_geometry_sim.exp1b.audit import read,load,sha
from dmf.chapter2_geometry_sim.sdf_trial import js

CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
DATA=CH/'仿真结果/2026-10-29_实验一B_固定机制核查_r2'
OUT=CH/'审查材料/2026-10-29_实验一B固定机制_Chat审查包_v1'
TITLE='实验一B_异常到达判定与消融机制核查_Chat审查报告'


def build():
    if (OUT/(TITLE+'.pdf')).exists():raise FileExistsError('completed review report already exists')
    OUT.mkdir(parents=True,exist_ok=True);qa=OUT/'QA';qa.mkdir(exist_ok=True)
    audit=load(DATA/'independent_audit.json')
    if not audit['passed']:raise ValueError('audit consistency failed')
    verification=load(DATA/'QA/software/verification.json')
    if 'full' not in verification:raise ValueError('full test process still running')
    # Final protection check after all regression/validator processes.
    protection=subprocess.run([sys.executable,'.planning/geometry_single_step_20261028/protect.py','verify'],
        cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'final_protection.txt').write_text(protection.stdout+protection.stderr,encoding='utf-8')
    if protection.returncode:raise ValueError('protected baseline changed')
    figures=DATA/'figures_r3';qa_tools=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
    figure_checks=[]
    validator=subprocess.run([sys.executable,str(qa_tools/'validate_figure.py'),str(ROOT/'scripts/plot_geometry_exp1b.py')],
        capture_output=True,text=True,encoding='utf-8',errors='replace')
    source_log=qa/'plot_source_validation.txt'
    if source_log.exists() and 'verdict: FIX BEFORE DELIVERY' in source_log.read_text(encoding='utf-8'):
        (qa/'plot_source_validation_pre_correction.txt').write_bytes(source_log.read_bytes())
    source_log.write_text(validator.stdout+validator.stderr,encoding='utf-8')
    if validator.returncode==1:raise ValueError('figure source preflight FAIL')
    for pdf in figures.glob('*.pdf'):
        text=subprocess.run([sys.executable,str(qa_tools/'audit_pdf_text.py'),str(pdf),'--min-pt','5','--json'],
            capture_output=True,text=True,encoding='utf-8',errors='replace')
        (qa/(pdf.stem+'_text.json')).write_text(text.stdout,encoding='utf-8')
        collision=subprocess.run([sys.executable,str(qa_tools/'audit_figure_collisions.py'),str(pdf),
            '--json-out',str(qa/(pdf.stem+'_collision.json'))],capture_output=True,text=True,encoding='utf-8',errors='replace')
        (qa/(pdf.stem+'_collision.txt')).write_text(collision.stdout+collision.stderr,encoding='utf-8')
        figure_checks.append(dict(figure=pdf.name,text_exit=text.returncode,collision_exit=collision.returncode))
    js(qa/'figure_checks.json',figure_checks)
    if any(r['text_exit'] or r['collision_exit'] for r in figure_checks):raise ValueError('figure QA needs correction')
    results=read(DATA/'planned_method_results.csv');config=load(DATA/'config.json');counts=read(DATA/'gate_trigger_counts.csv')
    index={(r['case_id'],r['method']):r for r in results}
    sources=[]
    def record(path,role,expected=None):
        digest=sha(path)
        if expected and digest!=expected:raise ValueError('source changed '+str(path))
        sources.append(dict(role=role,path=str(path),sha256=digest))
    manifest=load(DATA/'manifest.json')
    for rel,digest in manifest['artifacts'].items():record(DATA/rel,'saved raw development data',digest)
    for path,digest in manifest['source_code'].items():record(Path(path),'mechanism implementation',digest)
    for path in [DATA/'manifest.json',DATA/'independent_audit.json',DATA/'gate_trigger_counts.csv',
        DATA/'QA/software/verification.json',ROOT/'tests/test_geometry_exp1b.py',ROOT/'scripts/plot_geometry_exp1b.py',
        ROOT/'scripts/check_geometry_exp1b.py',ROOT/'scripts/verify_geometry_exp1b.py',Path(__file__),
        CH/'仿真结果/2026-10-29_实验一B_固定机制核查_v1/aborted_preacceptance_attempt.json']:
        record(path,'audit and provenance')
    figure_manifest=load(figures/'figure_manifest.json')
    for rel,digest in figure_manifest['files'].items():record(figures/rel,'saved scientific figure',digest)
    record(figures/'figure_manifest.json','figure inventory')
    with (OUT/'来源与hash索引.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['role','path','sha256']);writer.writeheader();writer.writerows(sources)
    shutil_files=['planned_method_results.csv','gate_trigger_counts.csv']
    for name in shutil_files:(OUT/name).write_bytes((DATA/name).read_bytes())
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=body,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),spaceAfter=10)
    cell=ParagraphStyle('cell',parent=body,fontSize=9.3,leading=14,spaceAfter=0)
    story=[];md=[]
    def p(text,h=False):story.append(Paragraph(escape(text),heading if h else body));md.append(text+'\n')
    def table(headers,items,widths):
        t=Table([[Paragraph(escape(str(c)),cell) for c in row] for row in [headers]+items],
            colWidths=[v*mm for v in widths],repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),
            ('LINEBELOW',(0,-1),(-1,-1),.5,colors.grey),('TOPPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
        story.extend([t,Spacer(1,9)])
        md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n')
        md.extend('| '+' | '.join(map(str,row))+' |\n' for row in items)
    def page():story.append(PageBreak());md.append('\n---\n')
    p('实验一B：异常到达判定与消融机制核查',True)
    p('2026-10-29 | SIMULATION | 固定开发机制集，非随机性能试验')
    p('一、阶段结论',True)
    p('共同缓存、六种到达门、异常递交、独立参考和一次性事件机制已实现。实际完成15/16个缓存，90/96条计划方法记录。慢速B1在形态生成阶段失败，6条方法记录保留为未执行。数据一致性审计通过不等于全部机制案例通过；本轮不批准20配对seed探索或实验二。')
    table(['层次','实际数量/状态'],[
        ['计划与执行','16缓存、4基础运动World；完成15缓存、3完整World，1个部分生成失败World。'],
        ['方法分母','6方法×16计划=96条；90执行、6未执行，不把方法数当独立重复。'],
        ['实际观测','3000张生成Mask；2995次处理递交（丢6帧、重复1次）；17970条方法逐帧记录。'],
        ['独立复算','保存Mask的特征、原始历史/门、到达事件、参考区间、评分分母逐项一致；正常前120Mask与旧版字节摘要相同。'],
        ['随机与硬件','开发身份seed264900，随机抽样0次；无正式seed、无高压、无真实相机/AM输出。']], [32,138])
    p('二、固定与未标定部分',True)
    p('真实FBC6-3的420电极Gerber设计轮廓、3.2 mm节距、4.0 mm面积等效轮廓、视频约束SDF库保持不变。1.4 mm/s、0.50 s请求、0.54 s模拟Applied、0.72 s响应、20 fps、10 s随访均为模拟设置；0.8 mm高度只记录。旧6 s正常例不改，新正常随访只延长静止尾段。')
    p('物理停顿/卡滞是现象学假设；观测偏移、破碎、伪目标和时序异常均无独立实测误差分布，标为synthetic stress。算法读取同一Mask、任务及模拟时间，不读取内部位置、异常标签或参考。事件不触发192，因此本轮不是闭环性能比较。')
    p('三、为什么仍不把M3当作更优算法',True)
    p('S在全部已执行缓存的GQ候选上新增拒绝为0；K在C5/C6/D6各新增拒绝1帧，但没有改变最终正确/错误类别。连续W避免一帧伪目标造成的早期确认，却无法排除持续伪Mask。Q对破碎观测生效，增加等待；局部缺失反而降低源残留，促使更早确认。以上是固定机制事实，不是概率或泛化精度。')
    page()
    p('四、全部16工况的实际到达时刻',True)
    p('单位s。表中参考为内部距离/速度/0.15 s驻留完成时刻；“无”表示未发生参考或未确认，“NA”表示生成失败而没有评价。M1/GQ无W；M2+S/M2+K为各自独立加门。')
    def number(x):return f'{float(x):.2f}' if x not in ('',None) else '无'
    items=[]
    for case in config['cases']:
        c=case['name'];base=index[c,'M1']
        items.append([c+(' M' if case['source_type']=='model_generated' else ' X'),
            'NA' if base['status']!='executed' else number(base['reference_confirmed_s'])]+[
            'NA' if index[c,m['name']]['status']!='executed' else number(index[c,m['name']]['decision_s']) for m in config['methods']])
    table(['工况','参考','M1','GQ','M2','M2+S','M2+K','M3'],items,[30,20,20,20,20,20,20,20])
    p('M=model-generated运动机制；X=synthetic stress观测/时序扰动。A0正常；B1慢速；B2暂停恢复；B3卡滞；C1小抖动；C2偏移；C3局部缺失；C4破碎；C5一帧伪目标；C6七帧伪目标；D1单帧丢失；D2五帧丢失；D3重复；D4乱序延迟；D5旧任务；D6合法新帧突跳。')
    p('严格参考下，正常M1早0.32 s，M2/M3早0.07 s；这不是重新发现的计时故障。W保持G合格，未要求内部低速驻留。评分以处理决策时间比较参考完成时间，另存“驻留建立中”等时间位置，不能把负偏差直接宣称为实际运输损害。')
    p('B3停在约55%进展，参考为无，所有方法不确认；这是正确不触发，不计为到达漏检。C5/C6后来仍有真实模拟参考，故其早期伪目标确认记提前，不与“无参考错误确认”重复计数。')
    page()
    p('五、完整计划分母与条件计数',True)
    aggregate=[]
    for m in config['methods']:
        selected=[r for r in results if r['method']==m['name']];done=[r for r in selected if r['status']=='executed']
        total=lambda k:sum(int(r[k]) for r in done)
        aggregate.append([m['name'],len(selected),len(done),total('reference_arrivals'),total('supported_confirmations'),
            total('premature_confirmations'),total('unsupported_confirmations'),total('missed_references'),len(selected)-len(done)])
    table(['方法','计划','执行','参考','支持','提前','无支持','漏参考','未执行'],aggregate,[26,18,18,18,18,18,18,18,18])
    p('这些是开发夹具计数，不是算法成功率或独立统计样本。每方法14个可评价参考事件、1个无到达卡滞缓存、1个生成失败缓存。“漏参考”与此前提前消费可以并存，二者不是同一互斥分类分母。没有随机重复，不给95%置信区间。')
    p('六、约束贡献、重叠与代价',True)
    table(['对照/工况','实际机制结果'],[
        ['W：C5一帧伪目标','M1/GQ于2.05 s消费；M2/M3保留至4.65 s。说明W拒绝短暂伪目标，但最终仍早于严格参考0.07 s。'],
        ['W/K：C6持续伪目标','M2在2.30 s确认，M2+K/M3在2.35 s确认。首跳K拒绝后适应固定错误位置，剩余六帧又形成窗口；K仅增加0.05 s，未排除错误。'],
        ['Q：C4破碎','7帧Q失败。M1=4.40，GQ=4.60，M2/M3=4.85 s；展示质量门与W等待的分别作用，不代表总体准确率。'],
        ['S：全部15缓存','GQ候选新增拒绝为0。原始S大量不满足发生在G之前；目前没有S独立增量证据。'],
        ['K：D6跳变恢复','K共拒绝跳出和返回两帧，其中1帧是GQ候选；M3从M2的4.75推迟至4.80 s，正确性类别相同，体现额外等待代价。'],
        ['G：C3局部缺失','裁去后部使源残留下降；M1=4.25，M2/M3=4.50 s，比正常更早。单连通/未触边不保证Mask正确，Q对此未报警。'],
        ['C0/W：D1—D5','缺帧、重复、旧任务和乱序均导致证据重建；M1若已消费不会事后撤销，不能拿后续拒绝补记早先确认安全。']], [36,134])
    page()
    p('七、慢速B1失败与不扩大形态研究的处理',True)
    p('0.7 mm/s版本在t=7.97 s、内部形态进展q=0.9713094425380367、最后一组SDF插值权重约0.3151469时失败。8个输入多边形均有效，但零水平栅格提取出的单轮廓存在Ring Self-intersection[-2.03125,0.26875]，发生在面积归一化之前。正常轨迹未采到这个进度，故正常单例通过不等于整个连续进度域均有效。')
    p('保留首轮中止目录及诊断；续跑r2字节复用已完成正常World，未再生成正常运动。B1仍失败并保存部分轨迹，6方法未执行且参考NA。没有自动补桥、buffer修复、相位吸附或改旧形态/门限。数据一致性审计通过与“全部16案例通过”明确分开。')
    p('下一步最小选择应单独审查：可考虑将慢速作为已保存有效轮廓的时间重放，显式记录相位量化误差，避免重新设计形态；也可先保留B1缺口继续分析其余机制。两者均不能静默替换本次失败记录。本轮不自行采用新表示。')
    p('八、软件回归与保护',True)
    table(['检查','实际记录'],[[name,f"exit={r['exit_code']}; tests={r['tests']}" if r['tests'] is not None else f"exit={r['exit_code']}"]
        for name,r in verification.items()],[42,128])
    full_log=(DATA/'QA/software/full.txt').read_text(encoding='utf-8')
    summary_lines=[line for line in full_log.splitlines() if re.match(r'^(Ran |OK|FAILED|FAIL:|ERROR:)',line)]
    p('全量摘要：'+'；'.join(summary_lines[-8:]))
    p('旧成果最终保护：460个源码内容hash、352135个旧资产大小/mtime记录，changed=[]。后者不是全内容hash。S1/S2/S3与原SDF工作模型未改；不Commit/Push。图稿使用原始CSV，PDF/SVG及600 dpi PNG均另存，说明文字留在图注。')
    p('九、Chat审查问题与准入判断',True)
    p('1. 当前证据是否支持将S视为本范围内冗余，而不是继续制造有利S场景？2. 持续伪Mask下K仅一帧延迟及局部缺失早确认，是否应作为明确失效边界？3. 正常例参考前0.07 s应如何与后续真实视频参考区间校准对应？4. 不改形态模型的前提下，是否采用已保存有效轮廓的时间重放来补慢速机制，还是保留缺口？')
    p('结论：可接受已执行案例的软件机制与数据一致性；实验一B完整机制准入暂缓，20配对seed和实验二不启动。不能据固定夹具宣称M3性能更优、真实五状态准确率或闭环运输收益。')
    (OUT/(TITLE+'.md')).write_text('\n'.join(md),encoding='utf-8')
    def footer(canvas,doc):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'SIMULATION | 固定开发机制；B1未完成；非性能统计')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    body_pdf=qa/'正文.pdf'
    SimpleDocTemplate(str(body_pdf),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    doc=fitz.open(body_pdf);body_pages=len(doc)
    figure_names=['Exp1B_1_event_outcomes','Exp1B_2_timing_tradeoff','Exp1B_3_gate_overlap']
    for name in figure_names:
        with fitz.open(figures/(name+'.pdf')) as fig:doc.insert_pdf(fig)
    pdf=OUT/(TITLE+'.pdf');doc.save(pdf);doc.close()
    with fitz.open(pdf) as final:
        for i,page in enumerate(final):page.get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False).save(qa/f'page_{i+1:02d}.png')
    captions=[
        '图1 固定机制工况的到达事件类别。全部96个计划单元保留；B1叉号为生成失败而非零错误，B3无事件且无参考到达。提前类别使用当前严格模拟驻留参考，不等同实际控制损害。M为模型运动、X为合成压力，工况对应正文表。',
        '图2 相对参考的处理决策时差与受支持确认延迟。a仅对可匹配参考的事件画带符号时差；b仅画受支持事件，M1本轮无受支持事件。B1斜纹为未执行，B3浅灰为无参考。其余缺点均可在图1及完整CSV追溯，不按成功样本虚构总体性能；无统计误差棒。',
        '图3 原始门拒绝与GQ候选上的增量拒绝。a包括到达之前的全部观测，不能直接当收益；b显示S新增拒绝为0，K在C5/C6/D6各1帧。B1斜纹为缺失，不是0；帧不是独立试次。']
    (OUT/'图注草稿.md').write_text('\n\n'.join(captions),encoding='utf-8')
    js(OUT/'交付manifest.json',dict(pdf=str(pdf),pdf_sha256=sha(pdf),body_pages=body_pages,pages=body_pages+3,
        executed_caches=15,planned_caches=16,executed_method_records=90,planned_method_records=96,
        generation_failure='B1_slow',research_gate=audit['research_gate'],independent_audit_consistent=True,
        no_new_trials_during_packaging=True,performance_claim=False,source_records=len(sources),
        files={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(pdf,flush=True)


if __name__=='__main__':build()
