"""Readable audit PDF plus all 28 method/scene counts; no new simulation."""
import argparse
import csv
from html import escape
import json
from pathlib import Path
import shutil
import subprocess

from pypdf import PdfReader,PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak

from package_chapter2_v2_delivery import package


def run(root,audit,report,render_python):
    root,audit,report=map(Path,(root,audit,report));work=audit/'pdf_work'
    package(root,report,work,render_python)
    cell=ParagraphStyle('auditcell',fontName='MicrosoftYaHei',fontSize=8,leading=10,wordWrap='CJK')
    title=ParagraphStyle('audittitle',parent=cell,fontSize=15,leading=22,spaceAfter=10)
    note=ParagraphStyle('auditnote',parent=cell,fontSize=9,leading=14,spaceAfter=7)
    with (audit/'v2_scene_method_counts.csv').open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
    def p(s):return Paragraph(escape(str(s)),cell)
    def table(columns,widths):
        contents=[[p(label) for label,key in columns]]
        for row in rows:
            rendered=[]
            for label,key in columns:
                v=row[key]
                if key=='stop_reasons':
                    d=json.loads(v);v='S×3' if 'source confirmation timeout' in d else 'L×3' if 'local recovery limit reached' in d else '-'
                rendered.append(p(v))
            contents.append(rendered)
        t=Table(contents,colWidths=widths,rowHeights=[30]+[14]*len(rows),repeatRows=1)
        t.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9F0F6')),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#205D87')),
            ('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#DBE4EB')),
            ('TOPPADDING',(0,0),(-1,-1),1),('BOTTOMPADDING',(0,0),(-1,-1),1)]))
        return t
    story=[Paragraph('附表A｜7场景×4方法的独立评价计数',title),
           Paragraph('每组3个开发seed；每组9个计划步骤。支持确认与参考到达分别计数；无到达时recall为NA。',note),
           table([('场景','scenario'),('方法','method'),('计划','planned_trials'),('源确认','source_prepared'),('执行完成','transport_complete'),
                  ('正确路径','path_complete'),('参考到达','reference_arrivals'),('支持确认','supported'),('无支持','unsupported'),('提前','premature'),('漏确认','missed')],
                 [83,95,40,50,55,55,55,55,50,45,50]),
           Spacer(1,8),Paragraph('不确定/错误目标/重复事件在这28组均为0，仍保留于CSV；failure/jitter的零事件不等于成功。',note),PageBreak(),
           Paragraph('附表B｜保护行为、Unknown及未尝试情况',title),
           Paragraph('R=运输Retry；Recovery后重发另列RR。Unknown为方法预测输出，不是共同状态真值。',note),
           table([('场景','scenario'),('方法','method'),('R','retries'),('Recovery','recoveries'),('RR','recovery_resends'),
                  ('未尝试步','unattempted_steps'),('Unknown帧','unknown_frames'),('缺Mask','missing_mask_frames'),('停止原因','stop_reasons')],
                 [90,100,45,60,45,65,75,60,75]),Spacer(1,8),
           Paragraph('S×3：源确认超时3次；L×3：局部恢复次数限制3次。未尝试步骤仍在各组9个计划步骤中。',note)]
    annex=work/'计数附表.pdf'
    SimpleDocTemplate(str(annex),pagesize=landscape(A4),leftMargin=30,rightMargin=30,topMargin=26,bottomMargin=24).build(story)
    base=PdfReader(work/'第二章v2_E0-E3审查包.pdf');writer=PdfWriter()
    for page in base.pages[:-3]:writer.add_page(page)
    writer.append(str(annex))
    for page in base.pages[-3:]:writer.add_page(page)
    final=audit/'第二章v2_阶段验收与图稿审查.pdf'
    with final.open('wb') as stream:writer.write(stream)
    shutil.copy2(report,audit/'第二章v2_简洁阶段验收报告.md')
    code="""import json,sys
from pathlib import Path
import pymupdf
p=Path(sys.argv[1]); d=pymupdf.open(p/'第二章v2_阶段验收与图稿审查.pdf'); preview=p/'pdf_review';preview.mkdir(); checks=[]
for i,page in enumerate(d):
 page.get_pixmap(matrix=pymupdf.Matrix(1.15,1.15)).save(preview/f'page-{i+1:02d}.png')
 checks.append(dict(page=i+1,characters=len(page.get_text()),width=page.rect.width,height=page.rect.height))
(p/'pdf_review_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print(json.dumps(dict(final_pages=len(d),rendered=len(checks))))
"""
    subprocess.run([str(render_python),'-X','utf8','-c',code,str(audit)],check=True)
    print(str(final))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--render-python',type=Path,required=True)
    a=p.parse_args();run(a.root,a.audit,a.report,a.render_python)
