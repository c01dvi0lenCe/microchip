"""Package G1/G2 findings without altering the annotation workspace."""
from pathlib import Path
from collections import Counter
from datetime import datetime
import argparse,csv,json,shutil,sys
import cv2,numpy as np
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph,Table,TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib import colors
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.segmentation_research.data import sha256,write_csv
from dmf.vision.image_io import read_image


def package(output,workspace):
    summary=json.loads((output/'技术验收汇总.json').read_text(encoding='utf-8'))
    with (output/'reviewed_snapshot/samples.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    reservoirs={'ROI013','ROI014','ROI019','ROI020','ROI028','ROI029','ROI074','ROI075','ROI086','ROI087'}
    holes={};notes=[]
    for r in rows:
        m=read_image(output/'reviewed_snapshot'/r['mask_path'],cv2.IMREAD_UNCHANGED)
        c,h=cv2.findContours(m,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        areas=[cv2.contourArea(q) for q,v in zip(c,h[0]) if v[3]>=0] if h is not None else []
        if max(areas,default=0)>=32:holes[r['sample_id']]=max(areas)
        reasons=[]
        if r['sample_id'] in reservoirs:reasons.append('储液主体与Ignore边界一致性复核；不能仅排除设计电极中心')
        if r['sample_id'] in holes:reasons.append('原始Mask存在较大内部孔洞；核对有效域内反光/液体归属，不自动填孔')
        notes.append(dict(sample_id=r['sample_id'],technical_pass=r['mechanical_pass'],
            visual_coverage='assistant_reviewed_all_12_contact_sheets_not_second_human_GT',
            priority_recheck=bool(reasons),priority_reasons='；'.join(reasons),
            small_component_warning=int(r['tiny_components_lt16px'])>0,
            small_component_action='保持原标注；不可凭面积自动删除真实微滴',
            edge_status='可见部分标注；实例测量需处理裁切' if r['foreground_touches_roi_edge']=='True' else '',
            empty_status='人工审核Mask有效前景为零' if int(r['valid_foreground_px'])==0 else '含人工前景',
            algorithm_training_released=False))
    priorities=[r for r in notes if r['priority_recheck']]
    write_csv(output/'G1_180张视觉复核与疑点清单.csv',notes)
    write_csv(output/'G1_优先返修14张.csv',priorities)
    write_csv(output/'G1_微小连通域提示90张_不自动删除.csv',[n for n in notes if n['small_component_warning']])
    source=Path(json.loads((workspace/'workspace.json').read_text(encoding='utf-8'))['dataset'])
    inventory=json.loads((source/'inventory.json').read_text(encoding='utf-8'))
    videos=[];previous_end=None
    for v in inventory['videos']:
        path=Path(v['source']).with_suffix('.timestamps.csv')
        with path.open(encoding='utf-8-sig',newline='') as f:t=list(csv.DictReader(f))
        start,end=datetime.fromisoformat(t[0]['host_time_utc']),datetime.fromisoformat(t[-1]['host_time_utc'])
        own=[r for r in rows if r['parent_video_id']==v['video_id']]
        videos.append(dict(video_id=v['video_id'],samples=len(own),proposed_split=own[0]['proposed_split'],
            operation_groups=len({r['operation_group'] for r in own}),
            first_receive_utc=t[0]['host_time_utc'],last_receive_utc=t[-1]['host_time_utc'],
            gap_from_previous_video_s=(start-previous_end).total_seconds() if previous_end else '',
            independent_loading_or_assembly_verified=False,cross_file_lineage_verified=False))
        previous_end=end
    write_csv(output/'G2_视频操作组与采集时间边界.csv',videos)
    final=dict(summary,visual_review_status='all180_visually_screened_with_priority_recheck',
        G1_status='TECHNICAL_PASS_SEMANTIC_IGNORE_RECHECK_REQUIRED',
        G2_status='INTERNAL_VIDEO_GROUP_STRUCTURE_PASS_NOT_RELEASED',
        priority_recheck_count=len(priorities),priority_ids=[r['sample_id'] for r in priorities],
        small_component_warning_is_not_rejection=True,training_released=False,
        automatic_electrode_ID_association_allowed=True,
        manual_electrode_number_confirmation_required=False,
        G3_G5_executed=False,source_annotations_modified=False)
    (output/'最终验收结论.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
    protected=json.loads((output/'输入保护hash.json').read_text(encoding='utf-8'))
    if any(sha256(p)!=h for p,h in protected.items()):raise ValueError('human inputs changed; rerun in new version')
    shutil.copyfile(workspace/'workspace.json',output/'reviewed_snapshot/source_workspace.json')
    for src in [ROOT/'scripts/audit_real_segmentation_acceptance.py',Path(__file__),ROOT/'tests/test_real_segmentation_acceptance.py']:
        dest=output/'processing_sources'/src.name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(src,dest)
    report_pdf(output,final,videos)
    print(json.dumps(dict(priority_recheck=len(priorities),priority_ids=final['priority_ids'],training=False,pdf_created=True),ensure_ascii=False))


def report_pdf(output,info,videos):
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    target=output/'真实液滴分割_G1验收与G2分组_审查报告.pdf'
    c=canvas.Canvas(str(target),pagesize=A4)
    c.setTitle('真实液滴分割 G1验收与G2分组审查')
    style=ParagraphStyle('body',fontName='STSong-Light',fontSize=11,leading=18,wordWrap='CJK',textColor=colors.HexColor('#26394c'))
    page=0;y=0;pw,ph=A4
    def new(title,wide=False):
        nonlocal page,y,pw,ph
        if page:c.showPage()
        page+=1;pw,ph=landscape(A4) if wide else A4;c.setPageSize((pw,ph))
        c.setFillColor(colors.HexColor('#173c60'));c.setFont('STSong-Light',16);c.drawString(38,ph-42,title)
        c.setStrokeColor(colors.HexColor('#315d80'));c.line(38,ph-54,pw-38,ph-54)
        c.setFont('STSong-Light',9);c.drawString(38,24,'真实图像 / 数据验收；非仿真、非模型性能评价')
        c.drawRightString(pw-38,24,str(page));y=ph-74
    def para(text,gap=10):
        nonlocal y
        p=Paragraph(escape(text),style);w,h=p.wrap(pw-76,1000)
        if y-h<48:raise ValueError('report paragraph exceeds page')
        p.drawOn(c,38,y-h);y-=h+gap
    def table(data,widths):
        nonlocal y
        small=ParagraphStyle('table',parent=style,fontSize=10,leading=15)
        cells=[[Paragraph(escape(str(v)),small) for v in row] for row in data]
        t=Table(cells,colWidths=widths,repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f0f6')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#c4d0da')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        w,h=t.wrap(pw-76,1000)
        if y-h<48:raise ValueError('report table exceeds page')
        t.drawOn(c,38,y-h);y-=h+16
    new('G1/G2验收结论 | 2026-11-05')
    para('结论：180张通过来源、文件格式、尺寸和有效域等技术检查；整批尚不放行训练。需先复核14张储液排除域/内部孔洞疑点。G2建议划分144/36结构可追溯，但只适用于同日内部开发，正式独立测试为0。')
    table([['检查项','实际结果'],['人工语义 / 边界 / 排除审核记录','180 / 180 / 180'],['技术检查通过','180/180'],['有效前景为空 / 含Ignore','19 / 19'],['含小于16像素连通域 / 触ROI边缘','90 / 57（警告，不自动剔除）'],['实例审核 / 正式独立测试','0 / 0'],['优先复核 / 训练执行','14 / 0']], [205,314])
    para('原始人工工作区保持只读。已另存180对原图、语义Mask及Ignore的字节快照，并保存来源hash和逐图核对页。全部180张已经过助手视觉筛查；这不是第二位人工评审，也不构成双评审一致性。')
    para('本轮不运行Otsu评价、深度训练、仿真或硬件输出；没有S1/S2/S3、AM控制或原人工Mask改动。')
    new('G1 | 需要关闭的标注口径疑点')
    para('1. 储液区：ROI013、014、019、020、028、029、074、075、086、087共10张复核储液主体的Ignore边界。设计电极轮廓只能导航，不能代表实际储液液体范围。ROI087的Ignore为0，而相邻ROI086对储液主体设有排除，存在明确的一致性疑点。')
    para('2. 内部孔洞：ROI019、074、075、080、086、087、097、098、150共9张原始Mask存在面积至少32平方像素的内部孔洞候选。其中与储液组重叠5张，合计优先复核14张。孔洞不自动判错，应核对是否位于Ignore内、是否为反光或确实非液体区域；不自动填孔。')
    para('3. 微小连通域：90张包含小于16像素连通域。该阈值仅作技术提示，不是前景最小面积，也不是删除规则。真实微滴/卫星滴保留；噪声或误点由人工核实。')
    para('4. 空背景：20张空背景候选中19张人工Mask有效前景为空，ROI157保留389平方像素人工前景。候选名不是真值，不强制把它清空，也不以算法草稿否定人工小目标。')
    para('5. 裁边与身份：57张含触边前景，标注可见部分本身合理；完整实例质心/漏检率评价须处理截断。实例ID及谱系目前未审核，不伪造；它们不是二分类语义训练的必需真值，但限制实例级测量。')
    new('G2 | 按来源与操作分组的内部候选划分')
    table([['原视频末尾标识','建议用途','ROI数','操作/背景组']]+[[v['video_id'][-13:],v['proposed_split'],v['samples'],v['operation_groups']] for v in videos],[195,90,90,144])
    para('同一原视频、相同操作组、视频内同草案轨迹均未跨建议集合。180条完整分组清单和train144/val36候选表已保存；实际split仍为unassigned，待G1问题关闭后单独放行。未进行逐帧随机抽样划分或数据增强。')
    para('4段视频不能当4个独立加液/装夹组。连续文件接收时间间隔约4.365、4.573和29.773秒；train与val交界仅约4.573秒，提示可能是连续采集。自动轨迹在文件边界重置，不能证明物理液滴谱系独立。')
    para('因此，该建议只能支持同日、同装置的内部选型；不支持跨批次泛化。若要求严格谱系/采集组留出，当前元数据不足，需要补充独立素材或明确已知谱系后整组重划。不能用180张作为180次独立实物重复，也不按4视频生成独立批次置信区间。')
    new('下一阶段准入与当前不可评价项')
    table([['项目','当前口径'],['二分类Dice / IoU','G1返修关闭、实际划分放行后可做内部比较；空Mask和失败保留'],['实例质心 / 漏检率','缺经审核的实例与截断规则；不能用联合前景质心替代目标实例'],['目标电极覆盖率误差','编号可自动关联；现有配准为候选，只能作明确标注的开发诊断'],['背景差分','需同视频同ROI、严格更早且人工核查的背景；无参考记为不可用'],['U-Net / DeepLabv3+','尚未训练；后续统一ResNet34初始化、ROI、增强、损失和预算'],['独立测试 / 不同材料','未开展；透明液滴、牛奶、血浆等另建挑战集，不并入本批核心总体']], [175,344])
    para('不要求用户逐个确认电极编号。可依据已确认420设计地图、原图和候选H自动关联编号并保存版本；编号对应不等于配准计量精度已经验收。人工Mask与状态/到达事件GT分开。')
    para('下一步：仅修订优先清单中确需修改的语义/Ignore标注，保留小滴和形变，重新核验后冻结新的审核快照与实际内部train/val清单，再决定G3-G5。当前不删失败样本、不改GT来迎合算法、不提前给出四算法排名。')
    for sid in ['ROI019','ROI080','ROI087','ROI157']:
        new(sid+' | 原生图与人工标注对照',True)
        path=output/'visual_review'/(sid+'_原生疑点核对.png')
        from PIL import Image
        with Image.open(path) as im:iw,ih=im.size
        scale=min((pw-76)/iw,(ph-115)/ih)
        c.drawImage(str(path),38,52,width=iw*scale,height=ih*scale)
    for i in range(1,13):
        new(f'全部标注核对 {i}/12 | 绿色：Mask轮廓；紫色：Ignore',True)
        path=output/'visual_review'/f'标注核对_{i:02d}.jpg'
        scale=min((pw-76)/1500,(ph-125)/1050)
        width=1500*scale;height=1050*scale
        c.drawImage(str(path),(pw-width)/2,52,width=width,height=height)
    c.save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True)
    a=p.parse_args();package(a.output.resolve(),a.workspace.resolve())
