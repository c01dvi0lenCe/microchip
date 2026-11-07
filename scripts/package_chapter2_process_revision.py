"""Package the read-only process figures and the prospective research protocol."""
import argparse
from html import escape
import json
from pathlib import Path
import re
import shutil

from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak


def package(root,protocol):
    root=Path(root);protocol=Path(protocol);dest=root/'审查交付_最终';dest.mkdir(exist_ok=True)
    pdfmetrics.registerFont(TTFont('YaHei','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='YaHei',fontSize=10,leading=16,wordWrap='CJK',spaceAfter=7,textColor=colors.HexColor('#203448'))
    title=ParagraphStyle('title',parent=body,fontSize=19,leading=27,spaceAfter=16,keepWithNext=True)
    heading=ParagraphStyle('heading',parent=body,fontSize=14,leading=22,spaceAfter=10,keepWithNext=True)
    cell=ParagraphStyle('cell',parent=body,fontSize=8.5,leading=13,spaceAfter=0)
    clean=lambda s:escape(s.replace('**','').replace('`',''))
    story=[Paragraph('第二章v2过程图与下一轮研究协议',title),Paragraph('2026-10-25 · SIMULATION · 只读图稿优化与前瞻协议',body),
      Paragraph('交付判断：可审查本轮图稿，并准备受限E4/E5验证；暂不进入E6大规模扫描。E0–E3通过不代表F已具有正式性能优势。',heading),
      Paragraph('已有21份共同缓存中BTQ/F的到达事件和时间21/21相同。S和Q没有产生独立候选拒绝，jitter中的K候选拒绝也没有改变事件，因为公共W窗同样阻断确认。机制夹具与随机统计性能必须分开。',body),
      Paragraph('图稿：架构简化为5主模块和独立评分支路；190/191六阶段放大；时间线保留论文完整版并拆为两张PPT图。1.46 s为参考区间[1.45,1.46]上界，1.92 s为算法确认/Update，1.96 s为模拟Applied。来源始终为normal:262000:F:end_to_end:full。',body),
      Paragraph('本轮没有新增研究trial、参数扫描或算法修改。独立4页PPT没有替换原研究汇报。架构为原生可编辑对象，数据图保留SVG和绘图源；PPT内数据图为600 dpi图像，不宣称全部图元可编辑。',body),
      Paragraph('后附双层比较协议、机制可辨识性审查、E4目标参数与E5独立参考敏感性定义，以及5幅完整图稿。绝对来源路径、SHA256、原始CSV见交付目录图稿_交付与manifests。',body),PageBreak()]
    lines=protocol.read_text(encoding='utf-8').splitlines();i=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line:continue
        if line.startswith('|'):
            block=[line]
            while i<len(lines) and lines[i].strip().startswith('|'):block.append(lines[i].strip());i+=1
            data=[]
            for row in block:
                parts=[s.strip() for s in row.strip('|').split('|')]
                if all(re.fullmatch('[-: ]+',s) for s in parts):continue
                data.append([Paragraph(clean(s),cell) for s in parts])
            n=len(data[0]);width=landscape(A4)[0]-84
            widths=([100]+[50]*6+[width-400]) if n==8 else [width/n]*n
            table=Table(data,colWidths=widths,repeatRows=1)
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EAF1F7')),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#176EAA')),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#D8E2E9')),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story.extend([table,Spacer(1,9)]);continue
        if line.startswith('## '):story.append(PageBreak())
        style=title if line.startswith('# ') else heading if line.startswith('## ') else body
        story.append(Paragraph(clean(re.sub(r'^#{1,3} ','',line)),style))
    intermediate=dest/'协议正文.pdf'
    def footer(c,doc):
        c.setFont('YaHei',8);c.setFillColor(colors.HexColor('#687D8D'));c.drawString(42,22,'SIMULATION · prospective protocol · no E4–E7 scan');c.drawRightString(landscape(A4)[0]-42,22,str(doc.page))
    SimpleDocTemplate(str(intermediate),pagesize=landscape(A4),leftMargin=42,rightMargin=42,topMargin=34,bottomMargin=40).build(story,onFirstPage=footer,onLaterPages=footer)
    combined=dest/'第二章v2_过程图与双层比较协议_审查包.pdf'
    if combined.exists():raise FileExistsError(combined)
    writer=PdfWriter();writer.append(str(intermediate))
    figures=root/'图稿_交付/figures'
    for name in ['V2-Process-1_PPT_简化架构','V2-Process-2_六阶段放大','V2-Process-3_论文完整版','V2-Process-3_PPT-1_运动与覆盖','V2-Process-3_PPT-2_证据与事件']:writer.append(str(figures/(name+'.pdf')))
    with combined.open('wb') as f:writer.write(f)
    shutil.copy2(protocol,dest/'第二章v2_BTQ-F双层比较协议.md')
    sources=root/'复现源文件';sources.mkdir(exist_ok=True)
    for path in ['scripts/chapter2_process_figures_revision.py','scripts/chapter2_process_preview.mjs','scripts/render_chapter2_process_preview.ps1','scripts/package_chapter2_process_revision.py','tests/test_chapter2_process_figures_revision.py']:
        shutil.copy2(path,sources/Path(path).name)
    print(json.dumps({'pdf':str(combined),'pages':len(writer.pages)},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--protocol',required=True);a=p.parse_args();package(a.root,a.protocol)
