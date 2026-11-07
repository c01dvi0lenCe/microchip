"""Review packet from saved mechanism data only; no controller/study execution."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
from xml.sax.saxutils import escape

import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak

ROOT=Path(__file__).resolve().parents[1]
METHODS=('A_fixed','M1','M2','M3')
NAMES=('Exp2_mechanism_1_closed_loop','Exp2_mechanism_2_timing_counterfactual')


def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def read(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(p):
    d=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):d.update(b)
    return d.hexdigest()
def yn(v):return '是' if v is True or v=='True' else '否' if v is False or v=='False' else 'NA'
def number(v):return 'NA' if v in ('',None) else f'{float(v):.3f}'


def build(data,fixtures,figures,verification,output):
    data,fixtures,figures,verification,output=[Path(p).resolve() for p in (data,fixtures,figures,verification,output)]
    if output.exists():raise FileExistsError(output)
    audit=load(data/'independent_audit.json');checks=load(verification/'verification.json')
    if not audit['passed'] or len(checks)!=8 or any(v['exit_code'] for v in checks.values()):raise ValueError('actual audit/regression evidence required')
    qa=load(figures/'QA/figure_checks.json')
    if len(qa)!=2 or any(r['text_exit'] or r['collision_exit'] or r['alignment_exit'] for r in qa):raise ValueError('final figure QA required')
    output.mkdir(parents=True);(output/'QA').mkdir();index=[]
    def record(path,role,copy=None):
        path=Path(path).resolve();row=dict(role=role,path=str(path),sha256=sha(path),snapshot_path='')
        if copy:
            dest=output/copy;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            if sha(dest)!=row['sha256']:raise ValueError('snapshot hash mismatch')
            row['snapshot_path']=str(dest)
        index.append(row)
    for root,role in [(data,'deterministic normal data'),(fixtures,'World-only counterfactual')]:
        for path in sorted(root.rglob('*')):
            if path.is_file():record(path,role)
    for root,sub,role in [(figures,'图稿','figure and QA'),(verification,'QA/软件回归','verification')]:
        for path in sorted(root.rglob('*')):
            if path.is_file():record(path,role,Path(sub)/path.relative_to(root))
    sources=set()
    for method in METHODS:
        manifest=load(data/method/'manifest.json');sources.update(manifest['source_code'])
        inputs=manifest['inputs'];sources.update(inputs[k] for k in ('map_path','pool_world_path','pool_polygons_path'))
        for name in ('metrics.json','steps.csv','events.csv','arrivals.csv','reference_marks.csv','config.json','manifest.json'):
            record(data/method/name,'trial summary',Path('数据摘要')/method/name)
    sources.update(str(ROOT/p) for p in ('scripts/audit_geometry_exp2_mechanisms.py','scripts/plot_geometry_exp2_mechanisms.py',
        'scripts/package_geometry_exp2_mechanisms.py','scripts/run_geometry_exp2_counterfactuals.py',
        'scripts/check_geometry_exp2_delivery.py','scripts/verify_geometry_exp2_mechanisms.py',
        'tests/test_geometry_exp2.py','tests/test_geometry_exp2_audit.py','tests/test_geometry_exp2_figures.py',
        'docs/chapter2-geometry-exp2-mechanisms-closeout-2026-10-30.md',
        'docs/superpowers/specs/2026-10-30-geometry-exp2-mechanism-design.md',
        'docs/superpowers/plans/2026-10-30-geometry-exp2-mechanisms.md',
        'docs/chapter2-geometry-exp2-mechanism-figure-contract-2026-10-30.md'))
    for source in sorted(sources):
        path=Path(source)
        try:copy=Path('源码与协议')/path.relative_to(ROOT)
        except ValueError:copy=None
        record(path,'implementation or input',copy)
    with (output/'来源与hash索引.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['role','path','sha256','snapshot_path']);w.writeheader();w.writerows(index)
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    style=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    head=ParagraphStyle('head',parent=style,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),keepWithNext=True)
    cell=ParagraphStyle('cell',parent=style,fontSize=9.2,leading=14,spaceAfter=0)
    story=[];md=[]
    def p(text,h=False):story.append(Paragraph(escape(str(text)),head if h else style));md.append(str(text)+'\n')
    def page():story.append(PageBreak());md.append('\n---\n')
    def table(headers,rows,widths):
        t=Table([[Paragraph(escape(str(v)),cell) for v in row] for row in [headers]+rows],colWidths=[w*mm for w in widths],repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.4,colors.grey),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        story.extend([t,Spacer(1,8)]);md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n')
        md.extend('| '+' | '.join(map(str,row))+' |\n' for row in rows)
    cfg=load(data/'M1/config.json')['parameters']
    p('实验二：单活动电极因果闭环机制审查',True)
    p('2026-10-30 | SIMULATION | DEVELOPMENT | 每方法n=1；无随机性能结论')
    p('一、本轮实际完成范围',True)
    p('按确认方案采用单活动目标原子替换，路径190→191→192→172；真实420 Gerber设计几何、4 mm面积等效轮廓和0.8 mm高度记录保持。四方法各一次确定性正常开发演示，另有两个预声明World-only定时切换反例；没有正式seed、随机扰动扫描或高压实物输出。')
    p(f"实际保存{audit['checked_masks']}张模拟Mask，四trial均随访到40 s。控制器只接收Mask特征、时间、任务和事务；World内部位置/速度及参考只供运动和独立评分。旧实验一B/S1/S2/S3没有改写、重跑或合池。")
    p('二、新World与旧单步模型的区别',True)
    table(['项目','开发机制定义'],[
        ['运动',f"dt={cfg['dt_s']} s；期望速度=(目标中心-当前位置)/{cfg['settle_time_s']} s，限速{cfg['vmax_mm_s']} mm/s；速度松弛{cfg['velocity_tau_s']} s、加速度上限{cfg['acceleration_mm_s2']} mm/s²，半隐式积分。"],
        ['事务',f"Request后{cfg['applied_delay_s']} s模拟Applied，随后{cfg['response_delay_s']} s响应；真正换active时位置/速度不重置。同目标Retry不重置物理运动，软件epoch与证据可重建。"],
        ['接触/形态','只有实际轮廓与active正交叠才允许运动；无交叠停止是模型门，不是流体力学定律。430有效轮廓按进展选取、旋转和平移，不进行新SDF或拓扑修复；形态相位与转向响应是开发假设。'],
        ['模型边界','不是旧单步最小跃度模型，不能沿用旧确认时刻或把两个模型结果混作同一批。速度松弛/减速距离/转向参数没有实物标定，尚不冻结正式性能模型。']],[28,142])
    page();p('三、四方法及共同保护',True)
    table(['方法/通道','定义与公平范围'],[
        ['A_fixed','共同P0之后按本步Applied+4.65 s推进；仅开发候选，不生成视觉ArrivalEvent。'],
        ['M1','C0+G；保留单帧覆盖门。'],['M2','C0+G+Q+W；主要候选。'],['M3','C0+G+Q+W+S+K；扩展对照，不预设优势。'],
        ['共同门','G：rho_target≥0.90、eta_source≤0.08；Q单连通/不触ROI；W≥5帧且跨度≥0.25 s、最大gap0.18 s（20 fps实际至少6帧）；S距离≤0.576 mm；K≤19.2 mm/s。'],
        ['P0与保护','同一源覆盖/质量/位置连续窗；源准备2 s，尝试10 s，最多2 Retry/1局部Recovery、每计划步≤7次Applied。40 s仅开发控制预算/固定随访，不是正式预算。完整五状态保护不在本轮新增。'],
        ['结束','Complete仅工作流事件，不伪造Applied或增加电极事务；继续固定观察到H，保持最后激励。三计划步及未尝试保留。']],[28,142])
    p('四、实际正常开发结果（不作成功率推断）',True)
    rows=[]
    for method in METHODS:
        metrics=load(data/method/'metrics.json');events=read(data/method/'events.csv')
        done=next((e['time_s'] for e in events if e['event']=='Complete'),None)
        rows.append([method,number(done),yn(metrics['transport_complete']),yn(metrics['final_target_reference_completed']),yn(metrics['reference_supported_path']),metrics['terminal']])
    table(['方法','Complete/s','工作流完成','最终目标参考','严格参考路径','互斥终止类别'],rows,[21,24,23,25,25,52])
    p('最终目标参考完成与每一步request/Applied均受参考支持是不同定义。参考前或无支持推进不自动等于物理危险、液滴拉断或运输失败；本轮不根据n=1给策略排名。')
    p('本例Complete时刻分别为A_fixed 14.42 s、M1 10.00 s、M2/M3 10.75 s。M2/M3前两次Update请求为3.80/7.25 s，参考于3.81/7.26 s建立，Applied为3.84/7.29 s；请求与生效的支持结论不能相互代替。')
    page();p('五、逐步请求与Applied独立核对',True)
    rows=[]
    for method in METHODS:
        for s in read(data/method/'steps.csv'):
            rows.append([method,str(int(s['step'])+1),s['source']+'→'+s['target'],number(s['departure_request_s']),number(s['departure_applied_s']),yn(s['request_supported']),yn(s['applied_supported'])])
    table(['方法','步','任务','决策/请求/s','Applied/s','决策支持','Applied支持'],rows,[21,12,28,28,28,26,27])
    p('第三步Complete仅为完成决策，没有下一电极请求或Applied，NA不是漏日志。开发评分的unsupported_requests包含此通用完成决策，M1为3；只计真实Update请求则M1/M2/M3均为2、A为0，后续统计接口应澄清字段命名。本轮保留原始文件。')
    p('同目标Retry不打断物理驻留；Recovery实际换激励才分段。请求尚未受支持、Applied前才建立参考时分别评分，不追认请求安全。')
    p('六、预声明早/晚切换反例',True)
    cases=load(fixtures/'manifest.json')['cases']
    table(['夹具','192请求/s','无交叠阻断tick','最终距192/mm'],[[c['case'],c['request_192_s'],c['blocked_ticks'],f"{c['final_distance_to_192_mm']:.6f}"] for c in cases],[30,35,50,55])
    p('两夹具都在0.50 s请求191，仅将下一192请求设为0.80或8.00 s，H=20 s。它们不运行到达门、不使用seed，目的是检查激励改变后World确实分叉；不把人为定时反例当作两个策略的统计性能证据。')
    page();p('七、独立复核与回归',True)
    p('独立审计从保存的轨迹、多边形、PNG与事件复算运动积分、覆盖与质心、P0/C0/Q/G/S/K、连续窗和ArrivalEvent时刻；从truth与真实激励重建驻留，再独立连接请求/Applied与三步评分，不调用原控制器或评分器。')
    table(['检查','实际证据'],[[k,f"exit={v['exit_code']}"+(f"；{v['tests']}项" if v['tests'] is not None else '')] for k,v in checks.items()],[70,100])
    p('审查关闭的关键反例：预算到期前的请求曾可能在Stop后Applied；现必须为Applied留足预算，精确截止生效仍可接受，终止后Applied不能改写状态。独立审计已补连续窗/事件时间、源特征、完整捕获身份及计划步评分连接，不只核查一次性事件数量。')
    p('八、图注与后续准入',True)
    p('图1：四策略同一确定性环境的闭环轨迹与观测覆盖过程。左列World为内部位置，Mask为实际处理掩膜质心；图像不是真实U-Net。右列为当前任务目标电极覆盖率与源区残留、真实模拟request/Applied。终端后随访到40 s；图内坐标以190中心为原点，单位mm。所有方法n=1，无误差棒或性能推断。')
    p('图2：两种预声明下一目标切换时刻的World-only反例。使用真实几何及相同开发模型，方形为真实模拟Applied记录；所有轨迹来自各自同一case，无补造状态或插值事件。')
    p('仍未完成：新增World动力学与转弯形态的实物标定、固定等待与总预算正式冻结、外生扰动场公平性和正式多实例闭环对比、完整五状态保护的独立贡献。真实视频配准、人工到达区间、U-Net及高压计量仍须独立实验，不由本轮机制通过代替。')
    p(f'本包来源索引{len(index)}项，原始数据不覆盖。请Chat重点审查：因果闭环是否真实、独立参考是否与控制隔离、参考支持与实际运输是否区分、新动力学假设是否足够明确、是否具备少量开发异常验证条件。本轮完成后停止，不自动启动正式扫描。')
    def footer(c,d):
        c.setFont('Song',8.5);c.setFillColor(colors.HexColor('#65717c'))
        c.drawString(20*mm,12*mm,'SIMULATION | DEVELOPMENT | 非实物性能');c.drawRightString(190*mm,12*mm,str(d.page))
    body=output/'QA/正文.pdf'
    SimpleDocTemplate(str(body),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    doc=fitz.open(body)
    for name in NAMES:
        with fitz.open(figures/(name+'.pdf')) as f:doc.insert_pdf(f)
    pdf=output/'实验二_单活动电极闭环机制_Chat审查报告.pdf';doc.save(pdf);doc.close()
    (output/'审查报告.md').write_text('\n'.join(md),encoding='utf-8')
    layout=[]
    with fitz.open(pdf) as doc:
        for i,page in enumerate(doc):
            text=page.get_text();spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
            missing='\x00' in text or '\ufffd' in text
            outside=any(s['bbox'][0]<-1 or s['bbox'][1]<-1 or s['bbox'][2]>page.rect.width+1 or s['bbox'][3]>page.rect.height+1 for s in spans)
            layout.append(dict(page=i+1,min_font_pt=min(s['size'] for s in spans),missing_glyph=missing,outside=outside))
            page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False).save(output/'QA'/f'page_{i+1:02d}.png')
    (output/'QA/text_layout_check.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
    if any(r['missing_glyph'] or r['outside'] for r in layout):raise ValueError('PDF glyph or clipping failed')
    print(dict(pdf=str(pdf),pages=len(layout),source_records=len(index)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('data','fixtures','figures','verification','output'):p.add_argument(name)
    a=p.parse_args();build(a.data,a.fixtures,a.figures,a.verification,a.output)
