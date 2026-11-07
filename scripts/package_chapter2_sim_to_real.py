"""Build an independent audit report from documents and existing saved evidence.

Requires reportlab, PyMuPDF and Pillow from the bundled document runtime.
Does not import any simulation, camera, serial, scoring or model module.
"""
from pathlib import Path
import csv
import hashlib
import html
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
OUT = BASE / '2026-10-26_S3仿真与实物对应性审查_v1'
DOCS = ('chapter2-s3-sim-to-real-contract.md', 'chapter2-real-experiment-readiness.md')

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def create():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                   TableStyle, CondPageBreak)
    import fitz
    from PIL import Image, ImageOps, ImageDraw

    evidence_path = OUT / '只读审查证据.json'
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['protected']['passed'] and not evidence['weight_search']['paths']
    target = OUT / '第二章S3_G3仿真与实物对应性完整审查报告.pdf'
    if target.exists() and '--replace-generated-report' not in sys.argv:
        raise FileExistsError(target)
    font_path = Path('C:/Windows/Fonts/simhei.ttf')
    pdfmetrics.registerFont(TTFont('AuditCJK', str(font_path)))
    styles = {
        'body': ParagraphStyle('Body', fontName='AuditCJK', fontSize=9.4, leading=15.2,
                               spaceAfter=7, wordWrap='CJK'),
        'table': ParagraphStyle('Cell', fontName='AuditCJK', fontSize=7.7, leading=11.5,
                                wordWrap='CJK'),
        'h1': ParagraphStyle('H1', fontName='AuditCJK', fontSize=17, leading=24,
                             spaceBefore=12, spaceAfter=12, keepWithNext=True, textColor=colors.HexColor('#17385b')),
        'h2': ParagraphStyle('H2', fontName='AuditCJK', fontSize=12, leading=18,
                             spaceBefore=12, spaceAfter=8, keepWithNext=False, textColor=colors.HexColor('#17385b')),
        'h3': ParagraphStyle('H3', fontName='AuditCJK', fontSize=10, leading=16,
                             spaceBefore=9, spaceAfter=6, keepWithNext=True),
    }
    def clean(s):
        s = re.sub(r'\*\*(.*?)\*\*', r'\1', s)
        s = s.replace('`', '')
        s = s.replace('\u2011','-').replace('\u2013','-').replace('\u2014','-')
        return html.escape(s)
    def para(s, style='body'):
        return Paragraph(clean(s), styles[style])
    def markdown(s):
        lines=s.splitlines(); items=[]; i=0
        while i < len(lines):
            line=lines[i].strip()
            if not line:
                i+=1;continue
            if line.startswith('|'):
                rows=[]
                while i<len(lines) and lines[i].strip().startswith('|'):
                    row=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r'[-: ]+', c or '-') for c in row):
                        rows.append([para(c,'table') for c in row])
                    i+=1
                n=max(map(len,rows))
                assert all(len(r)==n for r in rows)
                table=Table(rows,colWidths=[491/n]*n,repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([
                    ('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf6')),
                    ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#bbc7d3')),
                    ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
                    ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
                ]));items.extend([table,Spacer(1,8)]);continue
            if line.startswith('### '):items.extend([CondPageBreak(75),para(line[4:],'h3')])
            elif line.startswith('## '):items.extend([CondPageBreak(100),para(line[3:],'h2')])
            elif line.startswith('# '):items.append(para(line[2:],'h1'))
            else:items.append(para(line))
            i+=1
        return items
    formal=BASE/'2026-10-26_S3正式仿真_v1'
    with (formal/'formal_summary.csv').open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    main=[r for r in rows if r['cohort']=='main']
    result_rows=[]
    for scenario in ('normal','delayed','partial_stall','jitter','dropout','deviation','failure'):
        r={x['method']:x for x in main if x['scenario']==scenario}
        result_rows.append('| '+scenario+' | '+' | '.join(str(int(float(r[k]['path_complete'])))+'/20'
            for k in ('A_fixed','B_single','BTQ','F_full'))+' |')
    summary=f'''# 第二章S3 G3仿真与实物对应性完整审查报告

2026-10-26 | 版本1.0 | 只读追加审查

## 结论摘要

仿真科学协议：未发现新增A类阻断项。实物就绪性：PARTIAL，尚不具备正式实物闭环结果的证据。本轮0条新仿真、0次模型推理、0次硬件连接；不重新执行G4，不修改算法或冻结数据。

任务上下文已经发生阶段推进：当前磁盘不仅有120条G0-G2开发记录，还已有G3协议、800条S3正式记录及独立G5审计。本次将其全部作为只读材料，不将旧批次记为本轮新增工作，也不改写原批准时点。

关键迁移风险：研究与实物管线的K历史更新不同；默认实物YAML仍是占位配置；真实地图未替换运行模板；预实验H不能绑定旧视频或最终高度；曝光和ACK/HV时序尚需独立计量；同目标Retry不保证真实运动模型中的解锁效果。

## 本轮实际文件验证

受保护文件共{evidence['protected']['checked_files']:,}份，与既有SHA256一致，变化0。10段原视频、18张审核图像及Mask均通过相应来源哈希核对；420轮廓JSON实际记录{evidence['map']['actual_rows']}个电极。未重新解码全部视频，未将历史视频元数据当成本轮重新采集。

限定仓库与第二章目录搜索未定位可验证U-Net权重。已配置SDK目录不存在；这不代表设备不存在，也不代表其他位置没有安装SDK。辅助点选已完成两轮各16点，属于非严格盲法重复性，早期尚未完成的报告不作为最新状态。

## 既有S3结果的科学范围

下表只读取已冻结formal_summary.csv，展示严格独立参考支持路径完成数，不是本轮新性能复算；每格分母20个配对seed，三步不作为独立n。主组560条、桥接80条、诊断160条不合池。

| 场景 | A_fixed/P_B | B_single/P_B | BTQ/P_B | F_full/P_F |
|---|---|---|---|---|
{chr(10).join(result_rows)}

各数值仅在所设二维模型、合成观测和冻结参数下成立。jitter的源准备失败不能解释成运输判据全部失效；dropout中F/BTQ未优于A。既有同保护桥接80/80控制事件及时间一致，不能声称S/K已具有独立闭环收益；旧21份共同缓存BTQ/F确认相同仍成立。Deviation中F额外Recovery可以增加时间成本，不预设完整策略必胜。真实五状态准确率、实际分割泛化和物理闭环成功率均未由这些数据建立。

## 审查深度与证据责任

本轮完成源码语义、接口、真实资源与冻结文件一致性审查，不重新执行G1/G4/G5或全量控制回归。独立数值复算、统计区间和既有测试结果以封存G5报告为历史证据；本轮不把文件哈希验证称为再次独立性能复现。

## A/B/C分层决定

| 类别 | 本轮决定 | 后续动作 |
|---|---|---|
| A 仿真科学协议 | 未发现新增阻断；保留B_single实际Q关闭及公共raw Q优先级解释 | 不新增正式仿真；若出现定义/评分/随机/分母或哈希异常再做勘误 |
| B 实物准备 | 可并行，不否决算法仿真 | 真实GT与模型、最终H、曝光时钟、研究profile、人工参考与离线接口一致性 |
| C 实物启动 | 尚未独立验收 | 电极对应、最终标定、SDK/仪器对时、实际高压与释放、独立联锁、真实分割和批准 |

后附两份完整协议分别说明算法对应、评价及标定，以及真实资源READY/PARTIAL/MISSING证据与安全计量闸门。它们不是高压操作许可。
'''
    bodies=[(ROOT/'docs'/n).read_text(encoding='utf-8') for n in DOCS]
    for name in DOCS:
        shutil.copy2(ROOT/'docs'/name,OUT/name)
    full=summary+'\n\n'+'\n\n'.join(bodies)
    (OUT/'第二章S3_G3仿真与实物对应性完整审查报告.md').write_text(full,encoding='utf-8')
    story=markdown(summary)
    for body in bodies:story.extend([Spacer(1,16),*markdown(body)])
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('AuditCJK',8);canvas.setFillColor(colors.HexColor('#566779'))
        canvas.drawString(52,28,'第二章S3 | 仿真与实物对应性 | 只读审查 2026-10-26')
        canvas.drawRightString(A4[0]-52,28,str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(str(target),pagesize=A4,leftMargin=52,rightMargin=52,
        topMargin=45,bottomMargin=45,title='第二章S3仿真与实物对应性完整审查报告',author='Chapter 2 research audit')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    renders=OUT/'QA/page_previews';renders.mkdir(parents=True,exist_ok=True)
    pdf=fitz.open(target);thumbs=[];page_qa=[]
    for i,page in enumerate(pdf):
        p=renders/f'page_{i+1:02}.png';page.get_pixmap(matrix=fitz.Matrix(1.1,1.1),alpha=False).save(p)
        thumb=Image.open(p).convert('RGB');thumb.thumbnail((300,425))
        tile=Image.new('RGB',(320,455),'#dce2e8');tile.paste(thumb,((320-thumb.width)//2,10))
        ImageDraw.Draw(tile).text((12,435),f'Page {i+1}',fill='black');thumbs.append(tile)
        blocks=page.get_text('blocks'); outside=[b[:4] for b in blocks if b[0]<45 or b[2]>A4[0]-45 or b[1]<20 or b[3]>A4[1]-15]
        page_qa.append(dict(page=i+1,text_characters=len(page.get_text()),out_of_bounds=outside))
    cols=4;sheet=Image.new('RGB',(cols*320,((len(thumbs)+cols-1)//cols)*455),'white')
    for i,tile in enumerate(thumbs):sheet.paste(tile,((i%cols)*320,(i//cols)*455))
    sheet.save(OUT/'QA/全页预览.png')
    qa=dict(pdf_pages=len(pdf),pages=page_qa,all_pages_rendered=True,
        text_bounds_passed=all(not r['out_of_bounds'] for r in page_qa),
        new_trials=0,simulator_imports=False,hardware_connections=0,
        source_documents={n:sha(ROOT/'docs'/n) for n in DOCS})
    (OUT/'QA/文档检查.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'交付manifest.json').write_text(json.dumps(dict(schema='s3_sim_to_real_audit_delivery_v1',
        files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and 'page_previews' not in str(p) and p.name!='交付manifest.json'},
        preserved_files=evidence['protected']['checked_files'],source=DOCS,new_trials=0),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(pdf=str(target),pages=len(pdf),bounds=qa['text_bounds_passed']),ensure_ascii=False))
    assert qa['text_bounds_passed']

if __name__=='__main__':create()
