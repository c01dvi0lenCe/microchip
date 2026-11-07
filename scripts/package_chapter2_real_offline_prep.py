"""Package four preparation documents and empty annotation/log templates.

No segmentation, event prediction, model training or simulation is executed.
"""
from pathlib import Path
import csv
import hashlib
import html
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/审查材料/2026-10-27_真实视觉离线验证准备与S3封存_v1')
DOCS={
    'chapter2-s3-final-archive-evidence-2026-10-27.md':'第二章S3仿真最终封存与论文证据索引.md',
    'chapter2-real-visual-annotation-plan-2026-10-27.md':'第二章真实视觉数据与独立标注实施方案.md',
    'chapter2-real-map-binding-gaps-2026-10-27.md':'第二章真实地图绑定与配准缺口清单.md',
    'chapter2-s3-real-consistency-test-plan-2026-10-27.md':'第二章S3至实物控制算法一致性测试方案.md',
}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def prepare(evidence):
    templates=OUT/'templates';templates.mkdir(exist_ok=True)
    shared=['trial_id','task_id','step_id','video_id','video_sha256','clock_domain']
    reviewer=shared+['reviewer_id','annotation_version','annotation_source','reviewed','provenance',
        'observation_start_frame','observation_end_frame','observation_start_s','observation_end_s',
        'status','last_definitely_not_arrived_frame','first_definitely_arrived_frame',
        'arrival_lower_s','arrival_upper_s','left_censored','timing_quality','uncertainty_reason',
        'reviewer_exposure','source_ready_label','notes']
    headers={
        'planned_tasks.csv':shared+['source_electrode','target_electrode','task_evidence','start_frame','end_frame',
            'acquisition_group','chip_id','loading_id','mounting_id','binding_id','eligibility_status','notes'],
        'reviewer_A_events.csv':reviewer,
        'reviewer_B_events.csv':reviewer,
        'adjudication.csv':shared+['reviewer_A_file_sha256','reviewer_B_file_sha256','adjudicator',
            'final_status','arrival_lower_s','arrival_upper_s','disagreement_reason','decision_reason','reviewed','provenance'],
        'reference_episodes.csv':shared+['episode_id','inside_start_frame','inside_end_frame','support_lower_s',
            'support_upper_s','leave_interval_lower_s','leave_interval_upper_s','activation_context_status',
            'activation_evidence','visibility','reviewer_id','reviewed','provenance'],
        'raw_features.csv':['case_id','layer','implementation','config_sha256','input_sha256','frame_id','context',
            'timestamp','clock_domain','coordinate_domain','unit','centroid_x','centroid_y','eta_source','eta_target',
            'rho_target','distance','progress','lateral','velocity','predicted_x','predicted_y',
            'history_before','history_after','history_appended','history_reset_reason','computed_status'],
        'gate_trace.csv':['case_id','implementation','frame_id','context','G_target','G_release','C0_pass','C0_reason',
            'raw_Q','raw_S_area','raw_S_position','raw_K','Q_computed','S_computed','K_computed',
            'enabled_Q','enabled_W','enabled_S','enabled_K','effective_Q','effective_S','effective_K',
            'W_count','W_duration','W_gap','W_centroid_span','W_coverage_span','W_rebuild','confirmed'],
        'protection_inputs.csv':['case_id','implementation','frame_id','context','observation_valid','error',
            'spatial_ok','temporal_ok','target_position_ok','progress','progress_unit','last_reliable_time',
            'attempt_start','no_progress_status','no_observation_status','retry_remaining','recovery_remaining',
            'protection_policy','state_received','action','reason'],
        'arrival_events.csv':['case_id','implementation','event_id','run_id','step_id','attempt','epoch',
            'first_frame','last_frame','evidence_start','evidence_end','clock_domain','causality','consumed'],
        'mock_transactions.csv':['case_id','implementation','request_id','sequence','action','request_time',
            'clock_domain','pending','mock_ack_time','mock_ack_result','communication_retry','liquid_retry','hv_time'],
        'differences.csv':['case_id','layer','field','S3_value','real_pipeline_value','category','explanation','status'],
    }
    for name,cols in headers.items():
        with (templates/name).open('w',encoding='utf-8-sig',newline='') as f:
            csv.writer(f).writerow(cols)
    with (templates/'consistency_cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['case_id','status','executed','new_seed','reference_origin'])
        for i in range(1,19):w.writerow([f'C{i:02}','PLANNED_NOT_RUN',False,'','synthetic_software_fixture_only'])
    binding=dict(schema='chapter2_video_binding_preparation_draft_v1',status='draft_not_valid',
        runtime_compatible=False,video_sha256=None,reference_frame_id=None,reference_sha256=None,
        source_image_size=None,image_domain=None,roi_xywh=None,view_transform=None,
        design_map_sha256=None,image_to_design_mm=None,fit_points=[],independent_check_points=[],
        acceptance_thresholds=None,independently_reviewed=False,
        final_apparatus=False,old_photo_H_reused=False)
    save(templates/'video_binding_TEMPLATE_INVALID.json',binding)
    (templates/'字段与使用说明.md').write_text('''# 标注与一致性测试空表说明

这些CSV除consistency_cases.csv中的18条待执行身份外均只有表头，没有人工标签或测试结果。

1. planned_tasks先登记所有计划任务，包括不可辨/失败/未尝试；任务不明不猜电极ID。
2. A/B独立标注，annotation_source、reviewed、reviewer_id与provenance需真实人工填写，不预填human/True。
3. status采用arrived/not_arrived/uncertain/occluded/right_censored；left_censored为扩展字段，当前评分器不直接支持。只有独立审核后才导出评分输入。
4. adjudication保留A/B文件哈希，不覆盖A/B；reference_episodes记录到达后离开和激励证据，不把首次到达永久当支持。
5. 时间不可靠时只填原始帧号与timing_quality，秒为空；不能用容器fps伪造曝光或ACK对齐。
6. raw_features、gate_trace、protection_inputs分开。not_computed用空值+reason，不用False替代；unit/clock_domain明确。
7. mock_transactions只允许mock，hv_time必须为空，不生成真实ACK或高压记录。
8. video_binding模板故意无H且invalid，不能加载为实际配准；不填入旧照片H。
9. 新反例未执行。正式使用前须按实施方案冻结测试输入和配置，再审查结果。
''',encoding='utf-8')

def build():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,CondPageBreak,PageBreak
    import pymupdf as fitz
    from PIL import Image,ImageDraw
    e=load(OUT/'QA/本轮只读核查.json');assert e['passed']
    target=OUT/'第二章真实视觉离线验证准备与S3最终封存审查包.pdf'
    if target.exists() and '--replace-generated-report' not in sys.argv:raise FileExistsError(target)
    prepare(e)
    baseline=fitz.open(e['latest_baseline_pdf']['path'])
    (OUT/'QA/基线PDF全文只读提取.txt').write_text('\n\n'.join(f'PAGE {i+1}\n'+p.get_text() for i,p in enumerate(baseline)),encoding='utf-8')
    for i in (0,4,8):
        baseline[i].get_pixmap(matrix=fitz.Matrix(1,1),alpha=False).save(OUT/f'QA/基线页_{i+1}.png')
    content=[]
    for src,name in DOCS.items():
        body=(ROOT/'docs'/src).read_text(encoding='utf-8')
        (OUT/name).write_text(body,encoding='utf-8');content.append(body)
    summary=f'''# 第二章真实视觉离线验证准备与S3最终封存审查包

2026-10-27 | 只读审查与实施准备 | v1

## 本轮结论

S3最终证据链完整，保留既有800条正式trial/2400计划步及历史G5独立审计。当前实物总体PARTIAL；本轮没有新增seed、推理、训练、正式评价或硬件连接。

既有冻结资产{e['previous_scope_protection']['checked_files']:,}份哈希一致，变化0。G3定义/准入、G4聚合源、G5报告及图稿源数据/表格/脚本/示例trial的引用链均已实际核对，结果见sources目录。

10段原视频SHA256均一致；18张审核图/Mask哈希、二值尺寸及原视频ROI逐像素核对通过{e['real_data']['raw_roi_pixel_matches']}/18。它们仍来自同次采集n=1，仅支持分割Pilot，不是状态GT或跨批次泛化证据。

真实420设计轮廓、单照片预实验H与最终在线配准分别建账。旧照片H未绑定这些旧视频或最终装夹；视频当前未验证绑定，不等于已经证明几何错误。

S3与PriorFeatures的K历史采样、Q/K耦合和断档处理不同。已设计18个同输入离线反例及独立gate/保护日志规范，状态全部PLANNED_NOT_RUN；未将设计预期冒充通过结果。

## 四项交付

| 文档 | 核心用途 | 当前边界 |
|---|---|---|
| S3最终封存与论文证据索引 | 问题—结论—负面结果—图表—来源链 | 不重算正式统计，不扩展结论 |
| 真实视觉数据与独立标注实施方案 | 视频/Mask资格、双评审、区间/删失、独立采集 | 未新增人工GT、不训练 |
| 真实地图绑定与配准缺口清单 | Gerber/模板/照片H/视频域/最终装置区分 | 无新H，不强绑定 |
| S3至实物控制算法一致性测试方案 | 同Mask/时间/任务反例及分层日志 | 未执行新增case，不改实现 |

## 下一步的最小闭环

先确认候选视频任务与地图绑定，再开展6–10个连续片段的双评审规范Pilot；并行执行另行批准的18个确定性同输入软件反例。真实标注与算法输出分开封存。当前缺有效H、任务或时间的片段只用于适合的分割/资源任务，不强行进入到达性能评价。

## 核查范围说明

本轮文档/文件/像素来源核对不是新的控制回归或性能复现。原G5评分复算作为已封存证据引用；原S1/S2、120开发和800正式记录不合池。仿真不是CFD或真实电润湿动力学，不将高置信伪Mask、jitter、dropout或恢复时间代价隐藏。无Commit/Push。

## 目录内容

sources包含10视频、18Mask/ROI、S3引用链和图稿导出摘要。templates包含双评审、裁决、驻留段、任务清单、分层算法日志空表以及无效H草稿。QA包含本轮核查、源快照、基线阅读记录和PDF逐页检查。详细四份文档如下。
'''
    pdfmetrics.registerFont(TTFont('CJK','C:/Windows/Fonts/simhei.ttf'))
    st={k:ParagraphStyle(k,fontName='CJK',fontSize=size,leading=lead,wordWrap='CJK',
        spaceBefore=before,spaceAfter=after,textColor=colors.HexColor('#17385b') if k.startswith('h') else colors.black)
        for k,size,lead,before,after in [('body',9.4,15.2,0,5),('cell',7.7,11.5,0,0),
        ('h1',17,24,14,12),('h2',12,18,12,8),('h3',10,16,9,6)]}
    def p(text,style='body'):
        text=re.sub(r'\*\*(.*?)\*\*',r'\1',text).replace('`','')
        return Paragraph(html.escape(text.replace('\u2011','-').replace('\u2013','-').replace('\u2014','-')),st[style])
    def parse(text):
        lines=text.splitlines();items=[];i=0
        while i<len(lines):
            s=lines[i].strip()
            if not s:i+=1;continue
            if s.startswith('|'):
                data=[]
                while i<len(lines) and lines[i].strip().startswith('|'):
                    row=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r'[-: ]+',x or '-') for x in row):data.append([p(x,'cell') for x in row])
                    i+=1
                n=len(data[0]);assert all(len(row)==n for row in data)
                table=Table(data,colWidths=[491/n]*n,repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf6')),
                    ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#bdcad7')),
                    ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                items.extend([table,Spacer(1,8)]);continue
            if s.startswith('### '):items.extend([CondPageBreak(75),p(s[4:],'h3')])
            elif s.startswith('## '):items.extend([CondPageBreak(100),p(s[3:],'h2')])
            elif s.startswith('# '):items.extend([CondPageBreak(130),p(s[2:],'h1')])
            else:items.append(p(s))
            i+=1
        return items
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('CJK',8);canvas.setFillColor(colors.HexColor('#566779'))
        canvas.drawString(52,28,'第二章 | 真实视觉离线准备与S3封存 | 2026-10-27')
        canvas.drawRightString(A4[0]-52,28,str(doc.page));canvas.restoreState()
    full=summary+'\n\n'+'\n\n'.join(content)
    (OUT/'第二章真实视觉离线验证准备与S3最终封存审查包.md').write_text(full,encoding='utf-8')
    story=parse(summary)
    for body in content:story.extend([PageBreak(),*parse(body)])
    SimpleDocTemplate(str(target),pagesize=A4,leftMargin=52,rightMargin=52,topMargin=45,bottomMargin=45,
        title='第二章真实视觉离线验证准备与S3最终封存',author='Chapter 2 research').build(story,onFirstPage=footer,onLaterPages=footer)
    pdf=fitz.open(target);preview=OUT/'QA/page_previews';preview.mkdir(exist_ok=True)
    tiles=[];page_checks=[]
    for i,page in enumerate(pdf):
        image_path=preview/f'page_{i+1:02}.png';page.get_pixmap(matrix=fitz.Matrix(1.1,1.1),alpha=False).save(image_path)
        im=Image.open(image_path).convert('RGB');im.thumbnail((300,425));tile=Image.new('RGB',(320,455),'#dce2e8')
        tile.paste(im,((320-im.width)//2,10));ImageDraw.Draw(tile).text((12,435),f'Page {i+1}',fill='black');tiles.append(tile)
        blocks=page.get_text('blocks')
        page_checks.append(dict(page=i+1,text_chars=len(page.get_text()),out_of_bounds=[b[:4] for b in blocks if b[0]<45 or b[2]>A4[0]-45 or b[1]<20 or b[3]>A4[1]-15]))
    sheet=Image.new('RGB',(1280,455*((len(tiles)+3)//4)),'white')
    for i,tile in enumerate(tiles):sheet.paste(tile,((i%4)*320,(i//4)*455))
    sheet.save(OUT/'QA/全页预览.png')
    for old in preview.glob('page_*.png'):
        if int(old.stem.split('_')[1])>len(pdf):old.unlink()
    qa=dict(pages=len(pdf),page_checks=page_checks,rendered_pages=len(pdf),
        bounds_passed=all(not r['out_of_bounds'] for r in page_checks),
        source_documents={src:sha(ROOT/'docs'/src) for src in DOCS},
        new_trials=0,inference_calls=0,hardware_connections=0,planned_counterexamples=18,executed_counterexamples=0)
    save(OUT/'QA/文档检查.json',qa)
    files={str(x.relative_to(OUT)):sha(x) for x in OUT.rglob('*') if x.is_file()
        and 'page_previews' not in str(x) and x.name not in ('交付manifest.json','最终交付核查.json')}
    save(OUT/'交付manifest.json',dict(schema='chapter2_real_offline_preparation_delivery_v1',date='2026-10-27',
        files=files,source_documents=qa['source_documents'],new_trials=0,
        helper_scripts={name:sha(ROOT/'scripts'/name) for name in ('audit_chapter2_real_offline_prep.py','package_chapter2_real_offline_prep.py')}))
    print(json.dumps(dict(pdf=str(target),pages=len(pdf),bounds=qa['bounds_passed']),ensure_ascii=False));assert qa['bounds_passed']

if __name__=='__main__':build()
