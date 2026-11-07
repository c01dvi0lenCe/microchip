"""Package saved normal-speed outputs and the unresolved shape concern."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from xml.sax.saxutils import escape

import cv2
import numpy as np
import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak,Image

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.normal_speed import audit_normal_trial

CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
DATA=CH/'仿真结果/2026-10-28_实验一_正常速度1p4mmps_v2'
SNAP=CH/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot'
OUT=CH/'审查材料/2026-10-28_实验一正常速度版_Chat审查包_v1'
TITLE='实验一正常速度版_Chat审查报告_含形变问题'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))


def build():
    OUT.mkdir(parents=True,exist_ok=False);qa=OUT/'QA';qa.mkdir()
    audit=audit_normal_trial(DATA/'trial')
    if not audit['passed']:raise ValueError(audit)
    m=load(DATA/'trial/manifest.json');summary=m['summary'];cfg=m['config']
    visual=load(DATA/'visualization/render_manifest.json')
    sources=[]
    def record(p,role,expected=None):
        digest=sha(p)
        if expected is not None and digest!=expected:raise ValueError('source changed '+str(p))
        sources.append(dict(role=role,path=str(p),sha256=digest))
    for rel,digest in m['artifacts'].items():record(DATA/'trial'/rel,'saved trial',digest)
    for rel,digest in visual['files'].items():record(DATA/'visualization'/rel,'saved visualization',digest)
    record(DATA/'trial/manifest.json','trial manifest');record(DATA/'visualization/render_manifest.json','render manifest')
    with (SNAP/'samples.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    selected=[next(r for r in rows if r['parent_video_id']=='camera_20261014_112318_257662' and int(r['source_frame_id'])==frame) for frame in (675,682,717)]
    for r in selected:
        if r['mask_reviewed']!='True':raise ValueError('unreviewed comparison Mask')
        for name,key in [('frame_path','frame_path_sha256'),('mask_path','mask_path_sha256')]:
            record(SNAP/r[name],'real video qualitative comparison',r[key])
    # Confirm that each saved simulation outline is precisely the same affine
    # transform of the compact template; no new world step or prediction runs.
    vertices=np.array(load(DATA/'trial/template.json')['normalized_vertices_mm'])
    world=list(csv.DictReader((DATA/'trial/world.csv').open(encoding='utf-8-sig')))
    shapes=load(DATA/'trial/world_polygons.json');residual=0.;peak_stretch=0.
    for row,shape in zip(world,shapes):
        p=np.array(shape['polygon_mm'])[:-1]
        center=np.array([float(row['x_mm']),float(row['y_mm'])]);stretch=float(row['stretch'])
        normalized=(p-center)*np.array([1/stretch,stretch])
        residual=max(residual,float(np.max(np.abs(normalized-vertices))))
        peak_stretch=max(peak_stretch,stretch)
    if residual>1e-8:raise ValueError('affine mechanism reconstruction inconsistent')
    (qa/'shape_mechanism_check.json').write_text(json.dumps(dict(inverse_affine_max_coordinate_residual_mm=residual,
        max_stretch=peak_stretch,relative_axis_ratio_multiplier=peak_stretch**2,
        new_simulation_runs=0,physical_shape_similarity_measured=False),indent=2),encoding='utf-8')
    command=[sys.executable,'-m','unittest','tests.test_geometry_normal_speed','tests.test_geometry_single_step',
        'tests.test_chapter2_geometry_sim','tests.test_video_geometry_estimate','tests.test_electrode_design_map',
        'tests.test_chapter2_evidence','tests.test_chapter2_causality','tests.test_video_speed_check','-v']
    test=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'96项局部回归.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
    if test.returncode or 'Ran 96 tests' not in test.stderr:raise ValueError('tests failed or count changed')
    with (OUT/'来源与hash索引.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['role','path','sha256']);w.writeheader();w.writerows(sources)
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=body,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),spaceAfter=10)
    cell=ParagraphStyle('cell',parent=body,fontSize=9.5,leading=14,spaceAfter=0)
    story=[];md=[]
    def p(t,h=False):story.append(Paragraph(escape(t),heading if h else body));md.append(t+'\n')
    def table(headers,items,widths):
        t=Table([[Paragraph(escape(str(c)),cell) for c in r] for r in [headers]+items],colWidths=[v*mm for v in widths])
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
          ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.5,colors.grey),
          ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
          ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.extend([t,Spacer(1,10)]);md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n')
        md.extend('| '+' | '.join(map(str,r))+' |\n' for r in items)
    def page():story.append(PageBreak());md.append('\n---\n')
    p('实验一正常速度版 Chat审查报告',True)
    p('2026-10-28。SIMULATION；normal；n=1；190→191。报告整理新增仿真trial=0。')
    p('一、阶段判断',True)
    p('正常速度单例已完成软件执行和数据审计；用户指出液滴拉伸不像真实视频。当前形态真实性未通过验收，模型仍需针对性修订。不能将软件测试通过与实物形变一致混为一谈。')
    table(['项目','实际设置/状态'],[
       ['地图与尺寸','FBC6-3真实420设计轮廓；节距3.2 mm；4.0 mm面积等效液滴；0.8 mm高度只作记录。'],
       ['速度与时钟','名义峰值1.4 mm/s；6 s；dt=0.01 s；20 fps；均属simulation，不是实测标定。'],
       ['本轮范围','唯一191请求及模拟Applied；不激活192；无异常或多seed扫描。'],
       ['输入隔离','三到达门只读同一观测Mask与任务；独立参考使用内部距离/速度/驻留。'],
       ['交付状态','601 ticks、120 Masks、1×动画、关键帧及特征/事件图已保存；旧4.8 mm/s例保留。']], [37,133])
    p('二、实际到达事件，不沿用旧版时刻',True)
    ref=summary['reference_confirmation_s']
    table(['方法/事件','simulation时刻/s','相对参考/s'],[
       ['M1 单帧覆盖',f"{summary['single_confirmation_s']:.2f}",f"{summary['single_confirmation_s']-ref:+.2f}"],
       ['M2 连续稳定',f"{summary['window_confirmation_s']:.2f}",f"{summary['window_confirmation_s']-ref:+.2f}"],
       ['M3 时空联合',f"{summary['spatiotemporal_confirmation_s']:.2f}",f"{summary['spatiotemporal_confirmation_s']-ref:+.2f}"],
       ['独立参考',f'{ref:.2f}','0.00']], [73,50,47])
    p('M2/M3一致，尚无S/K增量收益证据。M1早于所定义参考0.22 s，但未进行下一步控制，不等同于已发生实物控制错误。参考容许低速、近目标位置和驻留，故4.72 s可早于严格中心到达5.01 s。')
    page()
    p('三、真实视频轮廓与模拟拉伸的差异',True)
    p('下列来自同一真实视频的3个审核样本，分别显示伸展、双叶/细颈和紧凑外观。这里只作质性形态对照，不与模拟时间逐帧对应，也不构成独立批次或五状态GT。')
    grid=[]
    grid.append([Paragraph('原视频帧 '+r['source_frame_id'],cell) for r in selected])
    grid.append([Image(str(SNAP/r['frame_path']),width=54*mm,height=54*336/570*mm) for r in selected])
    grid.append([Image(str(SNAP/r['mask_path']),width=54*mm,height=54*336/570*mm) for r in selected])
    t=Table(grid,colWidths=[56*mm]*3);t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),1),('RIGHTPADDING',(0,0),(-1,-1),1)]))
    story.extend([t,Spacer(1,10)])
    p('上排为真实ROI，下排为已有人工审核分割Mask。此处展示的是外形，不重新标注到达或状态；没有把实拍视频当作仿真输出。')
    p('四、已核实的原因与仍待量测的因素',True)
    p('当前形状变换为x方向乘λ、y方向乘1/λ，整体面积保持。λ随迁移进展平滑增大、恢复；它会整体拉长整个轮廓，不会产生由前端伸出、后部滞留而形成的新局部细颈。源视频紧凑Mask的像素阶梯也被一并拉伸，而非真实界面演化。')
    p(f'逐tick逆变换核查表明，所有模拟轮廓均可还原为同一个紧凑模板，最大坐标残差{residual:.2e} mm。λ最大约{peak_stretch:.3f}，使相对轴比增加约{peak_stretch**2:.3f}倍。该结果证明执行符合当前简化模型，不证明外形真实。')
    p('三项诊断分别为：整体仿射无法生成局部细颈，源码与逆变换支持；初始像素边界在伸展中保留，源码与图稿支持；形变幅度/恢复时长不符合视频，尚未做独立时空拟合，不能给出相似度或精确偏差。仅降低速度没有解决形变模型问题。')
    page()
    p('五、验收与科学边界',True)
    table(['层次','结论','依据/缺口'],[
       ['数据与软件机制','通过','新日志独立审计；96项局部回归通过；来源hash一致。'],
       ['几何/面积','通过声明的数值容差','面积相对误差约1.67×10^-15；Mask误差约0.511%，低于2%。'],
       ['外观真实性','未通过/待修订','用户反馈与视频质性对照；无局部形态拟合。'],
       ['三方法性能','未完成','正常n=1，M2=M3；无异常、消融或独立多试次证据。'],
       ['真实物理/实物控制','未验证','无视频有效毫米配准、曝光时序或实物输出测量。']], [34,38,98])
    p('六、下一步建议与Chat待审问题',True)
    p('优先修订形态表示，而不是继续降速或增加仿真次数。可考虑从已审核的紧凑、伸展、细颈轮廓建立保持面积的分阶段形态序列，并保留前后非对称性；需要先检查轮廓配准、重采样和中间形状是否自交。此为待审方案，本报告未修改运动、Mask、阈值或旧结果。')
    p('请Chat审查：当前证据是否足以把整体仿射确认为主要外观失真来源？下一版采用视频约束的分阶段形态是否合适？在形态通过质性检查前，是否应暂缓异常工况与性能统计？应如何将形态拟合材料与后续评价材料分开，避免用同一片段反复调参并评价？')
    p('七、来源与复核',True)
    p('附录依次为正常速度版的运动关键帧、特征曲线和到达事件时间线，原图PDF字节未变。完整绝对路径、SHA256和媒体核查见同目录来源索引、交付manifest及QA。当前两套速度例均保留，不重新运行、不Commit/Push。')
    p('后续每轮仿真固定交付：模型/参数、输入输出和hash、实际结果与分母、关键图稿、软件/外观/性能分层验收、负面结果、未关闭问题和下一步审查问题。详见仓库独立交付约定。')
    (OUT/(TITLE+'.md')).write_text('\n'.join(md),encoding='utf-8')
    def footer(canvas,doc):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'SIMULATION | 正常速度机制例；形态待修订')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    tmp=qa/'正文.pdf'
    SimpleDocTemplate(str(tmp),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    combined=fitz.open(tmp);body_pages=len(combined)
    if body_pages!=3:raise ValueError(f'Expected3 body pages, got {body_pages}')
    for name in ('movement_keyframes','feature_timeline','arrival_timeline'):
        with fitz.open(DATA/'visualization/figures'/(name+'.pdf')) as fig:combined.insert_pdf(fig)
    pdf=OUT/(TITLE+'.pdf');combined.save(pdf);combined.close()
    with fitz.open(pdf) as doc:
        for i,page in enumerate(doc):page.get_pixmap(matrix=fitz.Matrix(1.3,1.3),alpha=False).save(qa/f'page_{i+1:02d}.png')
    result=dict(pdf=str(pdf),pdf_sha256=sha(pdf),pages=6,software_mechanism_passed=True,shape_validation='NOT_ACCEPTED_PENDING_REVISION',
                performance_validation='NOT_ESTABLISHED_NORMAL_N1',new_simulation_runs=0,local_tests=96,
                trial_id=m['trial_id'],source_records=len(sources),authoring_source_sha256=sha(__file__),
                files={p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
    (OUT/'交付manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':build()
