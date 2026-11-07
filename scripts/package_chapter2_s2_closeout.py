"""Export S2 closeout and S3 plan; reads frozen values without re-evaluation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from chapter2_s2_closeout import OLD,read_csv,write_json,verify


def build(output,revision=''):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
    from pypdf import PdfWriter
    out=Path(output);verify(out)
    if revision and not re.fullmatch(r'r[0-9]+',revision):raise ValueError('revision must be r plus digits')
    suffix='_'+revision if revision else ''
    final=out/('第二章S2收尾与S3研究方案_审查包'+suffix+'.pdf')
    if final.exists():raise FileExistsError(final)
    pdfmetrics.registerFont(TTFont('CJK','C:/Windows/Fonts/simhei.ttf'))
    styles={
        'body':ParagraphStyle('body',fontName='CJK',fontSize=9,leading=13.5,spaceAfter=6),
        'small':ParagraphStyle('small',fontName='CJK',fontSize=7,leading=10,spaceAfter=3),
        'head':ParagraphStyle('head',fontName='CJK',fontSize=12,leading=18,spaceAfter=9,spaceBefore=10,keepWithNext=True,textColor=colors.HexColor('#174b70')),
        'title':ParagraphStyle('title',fontName='CJK',fontSize=17,leading=24,spaceAfter=14,textColor=colors.HexColor('#174b70'))}
    def text(s):return escape(s.replace('**','').replace('`',''))
    def para(s,key='body'):return Paragraph(text(s),styles[key])
    def table(headers,rows,widths,small=True):
        data=[[para(str(v),'small') for v in headers]]+[[para(str(v),'small') for v in row] for row in rows]
        t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5eef4')),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#174b70')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f7f9')])]))
        return t
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('CJK',7);canvas.setFillColor(colors.HexColor('#5b6b76'))
        canvas.drawString(18*mm,12*mm,'SIMULATION | S2冻结结果收尾 / S3仅方案 | 2026-10-26')
        canvas.drawRightString(doc.pagesize[0]-18*mm,12*mm,str(doc.page));canvas.restoreState()
    def markdown(path):
        lines=path.read_text(encoding='utf-8').splitlines();result=[];i=0
        while i<len(lines):
            line=lines[i].strip()
            if not line:i+=1;continue
            if line.startswith('|'):
                block=[]
                while i<len(lines) and lines[i].strip().startswith('|'):
                    cells=[s.strip() for s in lines[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r':?-+:?',c) for c in cells):block.append(cells)
                    i+=1
                n=len(block[0]);ratios={2:[.26,.74],3:[.21,.33,.46],4:[.17,.32,.22,.29]}.get(n,[1/n]*n)
                result.append(table(block[0],block[1:],[175*mm*r for r in ratios]));result.append(Spacer(1,8));continue
            if line.startswith('# '):result.append(para(line[2:],'title'))
            elif line.startswith('## '):result.append(para(line[3:],'head'))
            elif line.startswith('### '):result.append(para(line[4:],'head'))
            else:result.append(para(line))
            i+=1
        return result
    story=[para('第二章S2结果收尾与S3研究方案','title'),
        para('2026-10-26 | 全部已有数值为SIMULATION | 本轮无新研究trial、预测或评分'),
        para('S2结论锁定：单帧覆盖门容易提前；共同稳定窗减少特定瞬态错误；S/K只在部分合成压力下额外拒绝；持续伪观测、jitter、dropout仍是失效边界；尚无真实液滴普遍优势证据。'),
        para('本包的两张图仅改变可视化。S2-A保留四层结构及原时刻，参考区间按真实宽度；S2-B正文采用用户确认的六代表条件，全部13条件/五方法仍在完整附表与逐字节复制CSV中。'),
        para('冻结保护：旧S2全目录25199文件的内容hash已另存，新包不写入旧目录，也不设置旧文件属性。科学版本仍为chapter2_s2_single_task_confirmatory_v1。'),
        para('正文主图中[M]表示模型生成观测，[X]表示synthetic stress；比例分母、NA和晚确认含义不变。图中的“P/U”是提前/无参考确认两个计数，不是二者比值。'),
        para('阅读顺序：S2实验分析 → S3公平方案 → 两张矢量图 → 完整13条件附表。后附表含计数、Wilson95%、条件延迟；原始1300主评分/260BQ诊断及全部配对表随包保存。'),
        PageBreak()]
    analysis=ROOT/'docs/chapter2-s2-limitations-2026-10-26.md'
    plan=ROOT/'docs/chapter2-s3-study-design-2026-10-26.md'
    story+=markdown(analysis);story.append(PageBreak());story+=markdown(plan)
    body=out/('审查包正文'+suffix+'.pdf')
    SimpleDocTemplate(str(body),pagesize=A4,leftMargin=18*mm,rightMargin=17*mm,topMargin=18*mm,bottomMargin=20*mm).build(story,onFirstPage=footer,onLaterPages=footer)

    rows=read_csv(out/'tables/condition_statistics.csv')
    counts=['planned_steps','reference_arrivals','supported_confirmations','premature_confirmations',
        'unsupported_confirmations','missed_supported_confirmation','late_supported_confirmations',
        'timing_uncertain_confirmations','confirmation_right_censored','reference_right_censored','unattempted_steps','infrastructure_unknown']
    count_rows=[[r['condition'],r['method']]+[r[k] for k in counts] for r in rows]
    appendix=[para('S2完整结果附表：13条件×5方法（65行）','title'),
        para('SIMULATION | 每条件20配对seed | N计划、R参考、S主支持、P提前、U无参考、M主漏、L晚支持、TI时间不确定、CC确认删失、RC参考未知、NA未尝试、I基础设施未知。M包含L，不相加。','small'),
        table(['条件','方法','N','R','S','P','U','M','L','TI','CC','RC','NA','I'],count_rows,
              [113,82]+[36]*12),PageBreak(),para('完整结果附表：区间与条件延迟（65行）','title'),
        para('所有数值读取封存CSV，只作显示精度格式化，未重新估计统计。率为估计[Wilson95%CI]；延迟为H内支持样本的平均[c-u,c-l]秒区间及n，不是均值置信区间。NA=原CSV缺少可定义值。','small')]
    def interval(r,name):
        if r[name]=='':return 'NA'
        return f"{float(r[name]):.3f} [{float(r[name+'_lo']):.3f},{float(r[name+'_hi']):.3f}]"
    def latency(r):
        if r['mean_latency_lower_s']=='':return 'NA'
        return f"[{float(r['mean_latency_lower_s']):.6f},{float(r['mean_latency_upper_s']):.6f}]"
    rate_rows=[[r['condition'],r['method']]+[interval(r,k) for k in ('S_H_yield','premature_rate','unsupported_rate','miss_rate')]+[latency(r),r['latency_n']] for r in rows]
    appendix.append(table(['条件','方法','S/R及CI','P/N及CI','U/N及CI','M/R及CI','平均延迟区间/s','n'],rate_rows,[109,80,85,85,85,85,120,22]))
    appendix_pdf=out/('tables/S2_完整13条件附表'+suffix+'.pdf')
    SimpleDocTemplate(str(appendix_pdf),pagesize=landscape(A4),leftMargin=18*mm,rightMargin=17*mm,
        topMargin=18*mm,bottomMargin=20*mm).build(appendix,onFirstPage=footer,onLaterPages=footer)
    pdfs=[body,next((out/'figures/S2-A').glob('S2-A_*.pdf')),next((out/'figures/S2-B_main').glob('S2-B_*.pdf')),appendix_pdf]
    writer=PdfWriter()
    for p in pdfs:writer.append(p)
    with final.open('wb') as handle:writer.write(handle)
    shutil.copyfile(analysis,out/analysis.name);shutil.copyfile(plan,out/plan.name)
    integrity=verify(out)
    copied=[]
    for name in ('condition_statistics.csv','paired_contrasts.csv','diagnostic_contrasts.csv','statistics_manifest.json'):
        a,b=OLD/'formal/statistics'/name,out/'tables'/name
        if a.read_bytes()!=b.read_bytes():raise ValueError('copied table differs from frozen CSV')
        copied.append(name)
    manifest=dict(final_pdf=str(final),new_trials=0,new_predictions=0,new_scoring_runs=0,
        frozen_integrity=integrity,complete_summary_rows=len(rows),primary_contrast_rows=len(read_csv(out/'tables/paired_contrasts.csv')),
        byte_identical_copies=copied,source_docs={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (analysis,plan)},
        result_status='S2 closeout candidates; S3 protocol only, no formal S3 authorization',
        pdf_sha256=hashlib.sha256(final.read_bytes()).hexdigest(),pdf_parts=[str(p) for p in pdfs])
    write_json(out/('delivery_manifest'+suffix+'.json'),manifest)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--revision',default='')
    args=parser.parse_args();print(json.dumps(build(args.output,args.revision),ensure_ascii=False))
