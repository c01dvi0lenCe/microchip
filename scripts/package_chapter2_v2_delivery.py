"""Package the actual stage report and three vector process figures, not new data."""
import argparse
from html import escape
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def package(root, report, output, render_python=None):
    root, report, output = Path(root), Path(report), Path(output)
    if output.exists():
        raise FileExistsError('Do not overwrite an existing delivery package')
    output.mkdir(parents=True)
    pdfmetrics.registerFont(TTFont('MicrosoftYaHei', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))
    body=ParagraphStyle('body',fontName='MicrosoftYaHei',fontSize=9.5,leading=16,
                        wordWrap='CJK',spaceAfter=6,textColor=colors.HexColor('#24384A'))
    title=ParagraphStyle('title',parent=body,fontSize=17,leading=26,spaceAfter=16,keepWithNext=True)
    heading=ParagraphStyle('heading',parent=body,fontSize=12,leading=20,spaceBefore=12,spaceAfter=7,keepWithNext=True)
    subheading=ParagraphStyle('subheading',parent=body,fontSize=10.5,leading=18,spaceBefore=8,keepWithNext=True)
    cell=ParagraphStyle('cell',parent=body,fontSize=8,leading=13,spaceAfter=0)
    story=[];lines=report.read_text(encoding='utf-8').splitlines();i=0
    def text(s):
        return escape(s.replace('**','').replace('`',''))
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line or line.startswith('```'):
            continue
        if line.startswith('|'):
            block=[line]
            while i<len(lines) and lines[i].strip().startswith('|'):
                block.append(lines[i].strip());i+=1
            cells=[]
            for row in block:
                parts=[v.strip() for v in row.strip('|').split('|')]
                if all(re.fullmatch(r'[-: ]+',v) for v in parts):continue
                cells.append([Paragraph(text(v),cell) for v in parts])
            n=len(cells[0]);widths=[(A4[0]-84)/n]*n
            table=Table(cells,colWidths=widths,repeatRows=1,hAlign=TA_LEFT)
            table.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EAF1F7')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#1C5B88')),
                ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#D8E2E9')),
                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            story += [table,Spacer(1,9)];continue
        style=title if line.startswith('# ') else subheading if line.startswith('### ') else heading if line.startswith('## ') else body
        clean=re.sub(r'^#{1,3} ', '', line)
        story.append(Paragraph(text(clean),style))
    report_pdf=output/'阶段实施报告.pdf'
    def footer(canvas,doc):
        canvas.setFont('MicrosoftYaHei',8)
        canvas.setFillColor(colors.HexColor('#5D7182'))
        canvas.drawString(42,25,'SIMULATION | E0-E3 development acceptance | 2026-10-24')
        canvas.drawRightString(A4[0]-42,25,str(doc.page))
    SimpleDocTemplate(str(report_pdf),pagesize=A4,leftMargin=42,rightMargin=42,
                      topMargin=40,bottomMargin=42,title='第二章v2 E0-E3阶段交付报告').build(story,onFirstPage=footer,onLaterPages=footer)
    writer=PdfWriter();writer.append(str(report_pdf))
    figures=root/'visualization_r2/figures'
    for name in ('V2-Process-1_仿真架构','V2-Process-2_关键帧','V2-Process-3_联合时间线'):
        writer.append(str(figures/(name+'.pdf')))
    combined=output/'第二章v2_E0-E3审查包.pdf'
    with combined.open('wb') as stream:writer.write(stream)
    shutil.copy2(report,output/'第二章v2_E0-E3阶段交付报告.md')
    code="""import json,sys
from pathlib import Path
import pymupdf
output=Path(sys.argv[1]); document=pymupdf.open(output/'第二章v2_E0-E3审查包.pdf')
preview=output/'pdf_pages'; preview.mkdir(); checks=[]
for i,page in enumerate(document):
    page.get_pixmap(matrix=pymupdf.Matrix(1.25,1.25)).save(preview/f'page-{i+1:02d}.png')
    checks.append(dict(page=i+1,characters=len(page.get_text()),width=page.rect.width,height=page.rect.height))
(output/'pdf_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(pages=len(document),rendered_pages=len(checks))))
"""
    subprocess.run([str(render_python or sys.executable),'-X','utf8','-c',code,str(output)],check=True)
    print(str(combined))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--render-python',type=Path)
    args=parser.parse_args();package(args.root,args.report,args.output,args.render_python)
