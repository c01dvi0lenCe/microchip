"""Package replay supplement and reference-relative mechanism closeout."""
import csv
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
DATA=CH/'仿真结果/2026-10-29_实验一B_机制收尾_有效轮廓重放_r3'
OUT=CH/'审查材料/2026-10-29_实验一B机制收尾_Chat审查包_v2'
TITLE='实验一B_机制收尾与正式比较准备_Chat审查报告'


def build():
    if (OUT/(TITLE+'.pdf')).exists():raise FileExistsError('do not overwrite completed report')
    OUT.mkdir(parents=True,exist_ok=True);qa=OUT/'QA';qa.mkdir(exist_ok=True)
    audit=load(DATA/'closeout_audit.json');verification=load(DATA/'QA/software/verification.json')
    if not audit['passed'] or any(r['exit_code'] for r in verification.values()):raise ValueError('verification failed')
    if len(verification)!=6:raise ValueError('verification incomplete')
    tools=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
    figures=DATA/'figures';figure_checks=[]
    source=subprocess.run([sys.executable,str(tools/'validate_figure.py'),str(ROOT/'scripts/plot_geometry_exp1b_closeout.py')],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'plot_source_validation.txt').write_text(source.stdout+source.stderr,encoding='utf-8')
    if source.returncode==1:raise ValueError('source figure validation failed')
    for pdf in sorted(figures.glob('*.pdf')):
        text=subprocess.run([sys.executable,str(tools/'audit_pdf_text.py'),str(pdf),'--min-pt','5','--json'],capture_output=True,text=True,encoding='utf-8',errors='replace')
        (qa/(pdf.stem+'_text.json')).write_text(text.stdout,encoding='utf-8')
        collision=subprocess.run([sys.executable,str(tools/'audit_figure_collisions.py'),str(pdf),'--json-out',str(qa/(pdf.stem+'_collision.json'))],capture_output=True,text=True,encoding='utf-8',errors='replace')
        (qa/(pdf.stem+'_collision.txt')).write_text(collision.stdout+collision.stderr,encoding='utf-8')
        figure_checks.append(dict(figure=pdf.name,text_exit=text.returncode,collision_exit=collision.returncode))
    js(qa/'figure_checks.json',figure_checks)
    if len(figure_checks)!=3 or any(r['text_exit'] or r['collision_exit'] for r in figure_checks):raise ValueError('figure checks failed')
    protection=subprocess.run([sys.executable,'.planning/geometry_single_step_20261028/protect.py','verify'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'final_protection.txt').write_text(protection.stdout+protection.stderr,encoding='utf-8')
    if protection.returncode:raise ValueError('protected baseline changed')
    manifest=load(DATA/'manifest.json');sources=[]
    def record(path,role,expected=None):
        digest=sha(path)
        if expected and digest!=expected:raise ValueError('changed source: '+str(path))
        sources.append(dict(role=role,path=str(path),sha256=digest))
    for rel,digest in manifest['artifacts'].items():record(DATA/rel,'persisted run data',digest)
    for path,digest in manifest['source_code'].items():record(Path(path),'run implementation',digest)
    for path in [DATA/'manifest.json',DATA/'closeout_audit.json',DATA/'independent_audit.json',DATA/'gate_trigger_counts.csv',DATA/'QA/software/verification.json',
        ROOT/'dmf/chapter2_geometry_sim/exp1b_closeout/audit.py',ROOT/'tests/test_geometry_exp1b_closeout.py',
        ROOT/'scripts/check_geometry_exp1b_closeout.py',ROOT/'scripts/plot_geometry_exp1b_closeout.py',
        ROOT/'scripts/verify_geometry_exp1b_closeout.py',Path(__file__),
        ROOT/'docs/chapter2-geometry-exp1b-paired-protocol-draft-2026-10-29.md']:
        record(path,'audit and study protocol')
    fm=load(figures/'figure_manifest.json')
    for rel,digest in fm['files'].items():record(figures/rel,'new mechanism figure',digest)
    record(figures/'figure_manifest.json','figure manifest')
    for item in sources:
        if item['role'] not in ('run implementation','audit and study protocol'):continue
        source_path=Path(item['path'])
        try:relative=source_path.resolve().relative_to(ROOT)
        except ValueError:continue
        snapshot=OUT/'源码快照'/relative;snapshot.parent.mkdir(parents=True,exist_ok=True)
        snapshot.write_bytes(source_path.read_bytes())
        if sha(snapshot)!=item['sha256']:raise ValueError('snapshot mismatch')
        item['snapshot_path']=str(snapshot)
    with (OUT/'来源与hash索引.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['role','path','sha256','snapshot_path']);writer.writeheader();writer.writerows(sources)
    for name in ['planned_method_results.csv','exclusive_step_outcomes.csv','gate_trigger_counts.csv']:(OUT/name).write_bytes((DATA/name).read_bytes())
    (OUT/'正式配对比较_待冻结协议.md').write_bytes((ROOT/'docs/chapter2-geometry-exp1b-paired-protocol-draft-2026-10-29.md').read_bytes())
    results=read(DATA/'planned_method_results.csv');config=load(DATA/'config.json');index={(r['case_id'],r['method']):r for r in results}
    replay=audit['replay'];b1=load(DATA/'caches/B1/manifest.json');core=audit['core_audit']
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=body,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),spaceAfter=10)
    cell=ParagraphStyle('cell',parent=body,fontSize=9.3,leading=14,spaceAfter=0)
    story=[];md=[]
    def p(text,h=False):story.append(Paragraph(escape(text),heading if h else body));md.append(text+'\n')
    def table(headers,items,widths):
        t=Table([[Paragraph(escape(str(c)),cell) for c in row] for row in [headers]+items],colWidths=[v*mm for v in widths],repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.5,colors.grey),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
        story.extend([t,Spacer(1,9)]);md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n')
        md.extend('| '+' | '.join(map(str,row))+' |\n' for row in items)
    def page():story.append(PageBreak());md.append('\n---\n')
    p('实验一B：机制收尾与正式比较准备',True)
    p('2026-10-29 | SIMULATION | 确定性开发机制，非正式性能统计')
    p('一、收尾结论与本轮边界',True)
    p('B1慢速补例已完成，16个计划缓存、96条方法记录全部具备可审计结果。本轮仅新增1个B1缓存及6条方法记录，其余15缓存和90条方法记录原样复用；不是新增96次独立试验。旧B1形态失败及原15案例均保留，未覆盖r2和S1/S2/S3。')
    p('本轮可接受的是软件机制、观测一致性和统计分母收尾；不据此批准正式随机批次。M2仍是有机制依据的候选方法，M3是未证明增量收益的扩展。没有新识别约束、阈值调整、新seed扫描、多电极切换或实物输出。')
    table(['检查项','实际结果'],[
        ['慢速形态替代','从旧正常例430个已保存有效轮廓中按运动进度选最近轮廓，仅平移到独立运动质心；不做SDF插值、缩放或拓扑修复。'],
        ['离散进度误差',f"最大{replay['maximum_phase_error']:.8f}；上界{replay['theoretical_phase_error_bound']:.8f}。乘3.2 mm约为{replay['equivalent_progress_distance_mm']:.6f} mm进度差，不是质心、边界或物理测量误差。"],
        ['数值一致性',f"1001个World时刻；质心平移误差最大{replay['maximum_centroid_error_mm']:.2e} mm；面积相对误差{replay['maximum_area_relative_error']:.2e}；Mask面积误差最大{b1['max_mask_area_relative_error']*100:.3f}%。"],
        ['B1判定','0.7 mm/s模拟慢速：独立参考8.12 s；M1/GQ 8.05 s；M2、M2+S、M2+K、M3均8.30 s。'],
        ['保留与审计',f"{audit['preserved_assets']}个复用资产hash一致，90旧方法记录逐字段一致；原生成失败另存历史索引。"]],[32,138])
    p('真实Gerber轮廓、3.2 mm节距、4 mm面积等效液滴保持不变。1.4 mm/s正常、0.7 mm/s慢速及20 fps均为模拟假设；0.8 mm高度仅记录。形态库来自同次真实视频的归一化轮廓，尚无独立形态验证或视频毫米标定；不是CFD或真实U-Net分割结果。')
    page()
    p('二、全部工况的到达时刻与输入性质',True)
    p('单位s。M=model-generated运动；X=synthetic stress。无参考或无事件写“无”，不赋0。所有方法共享各工况Mask/时间/任务，旁路判断不改变运输轨迹。')
    def num(value):return '无' if value in ('',None) else f'{float(value):.2f}'
    items=[]
    for case in config['cases']:
        c=case['name'];items.append([c+(' M' if case['source_type']=='model_generated' else ' X'),num(index[c,'M1']['reference_confirmed_s'])]+[num(index[c,m['name']]['decision_s']) for m in config['methods']])
    table(['工况','参考','M1','GQ','M2','M2+S','M2+K','M3'],items,[30,20,20,20,20,20,20,20])
    p('A0正常；B1慢速；B2暂停恢复；B3最终卡滞；C1抖动；C2位置偏移；C3局部缺失；C4破碎；C5一帧伪目标；C6七帧伪目标；D1单帧丢失；D2五帧丢失；D3重复；D4乱序延迟；D5旧任务；D6合法新帧突跳。')
    p('真实扰动复核：C1-C4各7帧发生指定像素变化，C5为1帧、C6为7帧、D6为1帧；D1/D2分别少递交1/5帧，D3多1次重复递交，D4处理时间乱序，D5携带旧epoch。逐Mask和递交时间与声明一致。无观测异常不是“算法没有识别出异常”的替代解释。')
    p('独立参考只读内部位置、速度和驻留，不读算法G/W：距离不超过0.288 mm、速度不超过0.192 mm/s且驻留0.15 s。当前参考尚未建立与安全下一电极切换的实测关系。M2正常早0.07 s、B1晚0.18 s均只解释为相对这个模拟参考的时间关系。')
    page()
    p('三、互斥主结果与不重复计数',True)
    p('每个计划方法/任务仅一个主类别。保留原CSV和评分器；新增exclusive_step_outcomes.csv提供互斥视图。参考前、无参考确认、参考存在未确认、无参考且未确认分开。原“参考未匹配”保留为辅助诊断，不与参考前重复相加当作多个独立失败。')
    rows=[]
    for m in config['methods']:
        cnt=audit['primary_outcomes'][m['name']];rows.append([m['name'],16,cnt.get('reference_supported',0),cnt.get('before_reference',0),cnt.get('no_reference_confirmation',0),cnt.get('reference_not_confirmed',0),cnt.get('no_reference_no_confirmation',0)])
    table(['方法','计划','参考支持','参考前','无参考确认','有参考未确认','无参考无确认'],rows,[24,15,26,21,28,28,28])
    p('16个任务中15个有独立参考，1个卡滞无参考。全部96条记录无未执行或删失。上述是夹具计数，不是概率、准确率或多seed证据，不给置信区间。本实验不切换192，实际错误推进均未评价。')
    p('四、保留的负面结果及机制解释',True)
    table(['机制','本轮核查后的结论'],[
        ['W与短伪目标','C5的M1=2.05 s，M2/M3=4.65 s；W抑制一帧伪观测。但M2/M3正常仍在严格参考前0.07 s，不能把等待更久直接当准确性提高。'],
        ['持续伪目标与K','C6中M2=2.30，M3=2.35 s。首跳拒绝后，错误位置进入原始历史，六帧仍可形成窗口；额外等待0.05 s没有消除错误观测造成的参考前确认。'],
        ['Q的适用边界','C4破碎触发7帧Q拒绝，确认推迟；C3局部缺失降低源残留，M2/M3反而提前至4.50 s。单连通、未触边不等于轮廓可信。'],
        ['S与G信息重叠','16个工况的GQ候选中S新增拒绝均为0；不能用到达前原始S拒绝次数证明独立收益。'],
        ['K与额外等待','C5/C6/D6各拒绝1个GQ候选。D6使M3比M2再晚0.05 s，最终类别不变。未观察到M3相对M2的类别改善。']],[31,139])
    p('现有B3是无到达但无误观测，C5/C6则最终有到达；本组没有“无到达且持续伪Mask”的联合负对照。因此无参考误确认计数为0不等于已证明对此鲁棒。')
    page()
    p('五、独立审计、回归与旧成果保护',True)
    p(f"审计通过：{core['checked_masks']}张Mask、{core['checked_method_frame_rows']}条方法逐帧记录、3195次递交；独立复算特征、原始历史、到达门、证据窗口、一次性事件及参考。B1全部1001轮廓另与源池逐点核对。评分器读内部真值，算法端不读参考。")
    table(['验证','实际结果'],[[name,f"exit={v['exit_code']}"+(f"；{v['tests']}项测试" if v['tests'] is not None else '')] for name,v in verification.items()],[40,130])
    full=(DATA/'QA/software/full.txt').read_text(encoding='utf-8')
    lines=[line for line in full.splitlines() if re.match(r'^(Ran |OK|FAILED|FAIL:|ERROR:)',line)]
    p('全量日志摘要：'+'；'.join(lines[-4:]))
    p('旧成果保护：460个源码内容hash、352135个旧资产大小/mtime记录保持一致；后者不是全部资产内容hash。本轮另对3265个复用资产逐个计算内容hash。软件闭环链验证通过不代表实物高压、相机时序或液滴运输验证。')
    p('六、正式比较准入与停止点',True)
    p('机制收尾可交审；正式配对比较仍需冻结随机分布、seed、条件数、截止窗和统计方法。当前是确定性机制集，开发身份seed264900但随机抽样为0次。将同一缓存重复20遍不构成独立试验。本轮未运行新seed、参考敏感性重评分或实验二。')
    p('待冻结协议已另存：以M1/M2/M3为主，三个消融为诊断；共用Mask，保留全部计划任务和配对单位。参考敏感性保持算法预测不变，只改变独立参考，报告类别和时间关系的稳定性。联合负对照若需要，须事先声明且不预设M3胜出。')
    p('实验二须重新核验Gerber邻接、共同保护及预算。旧模型1.2 s固定等待和24 s总预算不能直接移植到新3.2 mm/1.4 mm/s模型；不能让固定基线因不公平设置而失败。到达门收益与完整五状态保护效应分开归因。')
    p('七、请Chat重点审查',True)
    p('1. 最近有效轮廓重放及量化误差是否足以关闭B1数值问题，而无需继续形态建模？2. 互斥主类别与参考未匹配诊断是否清楚，是否避免把参考前当真实危险？3. 是否接受M2候选、M3未证明增量的当前结论？4. 正式比较前还需冻结哪些随机分布、负对照和参考敏感性范围？')
    p('本轮结论：实验一B软件机制与证据收尾完成；不扩充识别约束、不宣称普遍性能提升。正式统计与实验二等待独立协议审查。')
    page()
    p('八、共享到达门及附图图注',True)
    p('各门保持旧实现，不依据本轮结果调整。G使用观测Mask，Q只检验基本形态有效性；S/K均来自算法可见观测，不读内部参考。')
    table(['约束','本次实际设置'],[
        ['C0','共同数据完整性、模拟时间及任务因果；旧任务、重复/倒序、Applied前观测不能累积证据。'],
        ['G','rho_target≥0.90，分母为目标电极面积；eta_source≤0.08，分母为液滴Mask面积。'],
        ['Q','有效单连通且不触ROI边界；不是经过实测校准的Mask正确概率。'],
        ['W','至少5帧且时间跨度≥0.25 s，最大间隔0.18 s。20 fps等间隔时实际至少6帧；拒绝/断档重建窗口。'],
        ['S','观测质心至任务目标中心距离≤0.576 mm；未添加新走廊或正向运动门。'],
        ['K','共同原始有效历史的观测速度≤19.2 mm/s；不是低速到达条件，持续伪位置能进入历史。'],
        ['方法','M1=C0+G；GQ=C0+G+Q；M2=GQ+W；M2+S、M2+K单独加门；M3=GQ+W+S+K。']],[27,143])
    p('图1 到达事件互斥类别。16个确定性缓存×6方法，96条记录完整保留；B1为重放补例，其余15缓存原样复用。参考前不代表已证实的错误切换，B3无参考且无事件；无随机性能区间。')
    p('图2 决策相对参考时差与条件确认延迟。(a) 有参考和确认时的带符号时差；(b) 仅参考支持确认的延迟，M1无此类事件。B3灰带为无参考，不赋零延迟；其余缺失点对应图1/CSV的参考前事件。横向错位仅避免遮挡。')
    p('图3 门拒绝及重叠。(a) 全观测的原始Q/S/K拒绝次数，不直接表示收益；(b) C0/G/Q合格候选上的S/K新增拒绝。S均为0，K在C5/C6/D6各1帧；帧不是独立试次。')
    p('追溯：报告旁保留完整96条结果、互斥结果、门触发计数及3534项来源hash索引；原始Mask/World仍在独立r3结果目录。索引中的snapshot_path指向本审查包保存的源码快照。绘图仅读取CSV，三图另存SVG/PDF/600 dpi PNG；图内无说明段落。')
    (OUT/(TITLE+'.md')).write_text('\n'.join(md),encoding='utf-8')
    def footer(canvas,doc):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'SIMULATION | 固定机制收尾；非正式性能批次')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    body_pdf=qa/'正文.pdf'
    SimpleDocTemplate(str(body_pdf),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    doc=fitz.open(body_pdf);body_pages=len(doc)
    names=['Exp1B_closeout_1_exclusive_outcomes','Exp1B_closeout_2_reference_timing','Exp1B_closeout_3_gate_overlap']
    for name in names:
        with fitz.open(figures/(name+'.pdf')) as fig:doc.insert_pdf(fig)
    pdf=OUT/(TITLE+'.pdf');doc.save(pdf);doc.close()
    with fitz.open(pdf) as final:
        for i,page in enumerate(final):page.get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False).save(qa/f'page_{i+1:02d}.png')
    captions=[
        '图1 到达事件互斥类别。16个确定性机制缓存×6方法，96条记录完整保留；B1为有效轮廓进度重放补例，其他15缓存原样复用。参考前表示早于独立模拟驻留参考，并非已证实的错误切换；B3无参考且无事件。无随机性能区间。',
        '图2 决策相对参考时差与条件确认延迟。(a) 有参考和确认时的带符号时差；(b) 仅参考支持确认的延迟，M1无此类事件。B3灰带表示无参考，不赋零延迟；其他缺失点对应图1和完整CSV中的参考前事件。横向错位仅避免标记遮挡，不表示工况进度差。',
        '图3 门拒绝及重叠。(a) 全观测的原始Q/S/K拒绝次数，不直接表示算法收益；(b) C0、G、Q合格候选上的S/K新增拒绝。S均为0，K在C5/C6/D6各1帧；帧不是独立试次。']
    (OUT/'图注草稿.md').write_text('\n\n'.join(captions),encoding='utf-8')
    js(OUT/'交付manifest.json',dict(pdf=str(pdf),pdf_sha256=sha(pdf),body_pages=body_pages,pages=body_pages+3,
        executed_caches=16,method_records=96,new_cache_runs=1,reused_caches=15,new_method_records=6,
        source_records=len(sources),performance_claim=False,formal_statistics_run=False,
        files={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(pdf,flush=True)


if __name__=='__main__':build()
