"""Package completed internal development records without training or rescoring."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import pymupdf as fitz
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_real_segmentation_internal_baselines import _sha
from scripts.train_real_segmentation_g4 import write_json

SKILL = Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
sys.path.insert(0, str(SKILL))
from audit_panel_alignment import require_matplotlib_panel_alignment

PAGE = (841.89, 595.28)
FONT = 'STSong-Light'
COLORS = {'unet': '#185078', 'deeplabv3plus': '#B96C39'}
DISPLAY = {'otsu':'Otsu', 'background':'Background', 'unet':'U-Net', 'deeplabv3plus':'DeepLabv3+'}


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def curves(run, output):
    plt.rcParams.update({'font.family':'Arial', 'font.size':10, 'pdf.fonttype':42,
                         'svg.fonttype':'none', 'axes.spines.top':False, 'axes.spines.right':False})
    for quantity in ('loss', 'dice'):
        fig, ax = plt.subplots(figsize=(7.2, 4.1))
        for name in ('unet', 'deeplabv3plus'):
            rows = read_csv(run/name/'epochs.csv')
            epochs = [int(r['epoch']) for r in rows]
            if quantity == 'loss':
                ax.plot(epochs, [float(r['train_loss']) for r in rows], color=COLORS[name], lw=1.5, label=DISPLAY[name]+' train')
                ax.plot(epochs, [float(r['val_loss']) for r in rows], color=COLORS[name], lw=1.5, ls='--', label=DISPLAY[name]+' validation')
            else:
                ax.plot(epochs, [float(r['native_val_dice']) for r in rows], color=COLORS[name], lw=1.5, label=DISPLAY[name])
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Masked BCE + Dice loss' if quantity=='loss' else 'Native validation Dice')
        if quantity=='dice': ax.set_ylim(0, 1.02)
        ax.legend(frameon=False, fontsize=10)
        fig.tight_layout()
        stem = output / ('learning_'+quantity)
        require_matplotlib_panel_alignment(fig, json_out=str(stem)+'.alignment.json', strict=True)
        fig.savefig(str(stem)+'.svg')
        fig.savefig(str(stem)+'.pdf')
        fig.savefig(str(stem)+'.png', dpi=600)
        fig.savefig(str(stem)+'.tiff', dpi=600)
        plt.close(fig)


class Report:
    def __init__(self, path):
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        self.canvas = Canvas(str(path), pagesize=PAGE)
        self.canvas.setTitle('真实液滴分割G4匹配训练与内部验证Chat审查报告')
        self.n = 0
        self.y = 0

    def page(self, title):
        if self.n: self.canvas.showPage()
        self.n += 1
        self.canvas.setFillColor(HexColor('#173B51'))
        self.canvas.rect(0,PAGE[1]-10,PAGE[0],10,fill=1,stroke=0)
        self.y=PAGE[1]-42
        self.text(title,20)
        self.text('真实视频分割 | 同日内部开发验证 | 正式独立 test = 0',10)
        self.canvas.setFont(FONT,9)
        self.canvas.drawRightString(PAGE[0]-36,18,str(self.n))

    def text(self, body, size=11):
        style=ParagraphStyle('p',fontName=FONT,fontSize=size,leading=size*1.5,wordWrap='CJK',textColor=HexColor('#253746'))
        p=Paragraph(body,style)
        _,h=p.wrap(PAGE[0]-72,1000)
        if self.y-h<40: raise ValueError('report text overflow')
        p.drawOn(self.canvas,36,self.y-h)
        self.y-=h+10

    def table(self, rows, widths, size=10):
        style=ParagraphStyle('t',fontName=FONT,fontSize=size,leading=size*1.4,wordWrap='CJK')
        data=[[Paragraph(escape(str(x)),style) for x in row] for row in rows]
        table=Table(data,colWidths=widths)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#EAF0F3')),
                   ('GRID',(0,0),(-1,-1),.35,HexColor('#CCD6DC')),('VALIGN',(0,0),(-1,-1),'TOP'),
                   ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                   ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        _,h=table.wrap(PAGE[0]-72,1000)
        if self.y-h<40: raise ValueError('report table overflow')
        table.drawOn(self.canvas,36,self.y-h)
        self.y-=h+10

    def picture(self, path, x=36, y=42, w=769, h=450):
        self.canvas.drawImage(ImageReader(str(path)),x,y,width=w,height=h,preserveAspectRatio=True,anchor='c')


def preview(root, run, samples, output):
    rows=read_csv(run/'evaluation/per_image.csv')
    by={(r['sample_id'],r['method']):r for r in rows}
    fig, axes=plt.subplots(2,6,figsize=(13.2,5.7))
    columns=['Original','Human GT','Otsu','U-Net','DeepLabv3+','Background']
    methods=[None,None,'otsu','unet','deeplabv3plus','background']
    for i,sample in enumerate(samples):
        sid=sample['sample_id']
        ignore=np.asarray(Image.open(root/'G2'/sample['exclusion_mask_path']))>0
        for j,method in enumerate(methods):
            ax=axes[i,j]
            # NA cells need the same square plot rectangle as image cells.
            # Without this, imshow's equal aspect shrinks only the image axes.
            ax.set_box_aspect(1)
            if j==0:
                image=Image.open(root/'G2'/sample['frame_path']).convert('RGB')
            else:
                if j==1:
                    file=root/'G2'/sample['mask_path']
                else:
                    r=by[(sid,method)]
                    if r['eligible']!='True':
                        ax.text(.5,.5,'NA',ha='center',va='center',fontsize=16,color='#7A8790')
                        ax.set_axis_off()
                        if i==0: ax.set_title(columns[j],fontsize=11,pad=8)
                        continue
                    file=(root/'G3_initial_baselines_v1' if method in ('otsu','background') else run/'evaluation')/r['prediction_path']
                mask=np.asarray(Image.open(file))>0
                array=np.full((*mask.shape,3),255,np.uint8)
                array[mask]=(0,119,117)
                array[ignore]=(210,198,220)
                image=Image.fromarray(array)
            ax.imshow(image)
            ax.set_xticks([]); ax.set_yticks([])
            for spine in ax.spines.values(): spine.set_visible(False)
            if i==0: ax.set_title(columns[j],fontsize=11,pad=8)
        axes[i,0].set_ylabel(sid,fontsize=11)
    fig.subplots_adjust(left=.035,right=.995,top=.91,bottom=.025,wspace=.08,hspace=.14)
    require_matplotlib_panel_alignment(fig,json_out=str(output)+'.alignment.json',strict=True)
    fig.savefig(str(output)+'.png',dpi=300)
    # PDF preserves the diagnostic image grid; source predictions remain native PNG.
    fig.savefig(str(output)+'.pdf')
    plt.close(fig)


def package(root, run):
    # Preserve the first incomplete packaging attempt and its alignment failure.
    out=run/'reports_final'
    out.mkdir(exist_ok=True)
    curve_dir=out/'curves'; curve_dir.mkdir(exist_ok=True)
    curves(run,curve_dir)
    manifests=[read_json(run/m/'training_manifest.json') for m in ('unet','deeplabv3plus')]
    gpu=read_json(run/'gpu_preflight.json')
    data=read_json(run/'data_check.json')
    scores=read_csv(run/'evaluation/summary.csv')
    common=read_csv(run/'evaluation/common_background_subset_summary.csv')
    timing=read_csv(run/'evaluation/timing_summary.csv')
    audit=read_json(run/'independent_audit.json')
    tests=read_json(run/'verification/full_unittest_summary.json')
    report=Report(out/'真实液滴分割_G4匹配训练与内部验证_Chat审查报告.pdf')
    report.page('1 研究范围、数据检查与定向复筛')
    report.text('本轮已完成两模型本地GPU开发训练与共同36张验证图评价。原180张ROI、人工GT、Ignore、144/36划分及G3结果保持原样；本轮不构建正式独立测试集、不修改S1/S2/S3或AM控制。')
    report.table([['项目','实际状态'],['数据','train144 / val36 / test0，同日内部；独立采集批次未确认'],
                  ['空GT','ROI145 / ROI167 / ROI178；ROI157是有效小液滴正样本'],
                  ['检查','180图尺寸/hash/二值编码/缩放对齐通过；无正样本整体消失'],
                  ['定向复筛','36图助手视觉检查；未新增人工真值、未改标注'],
                  ['待人工细节复核','149/150底部触边液滴窄缝、细小碎片身份、反光边界'],
                  ['背景资格','109/180；验证6/36，其中3阳性、3空GT。NA不是0分']],[130,639])
    report.text('已有人工GT是本轮依据。助手筛查不能取代新的人工双评审；未发现明确重大错配时沿用原标注。未来更正必须另存数据版本并重验，不覆盖本批。')
    report.page('2 匹配训练协议与GPU试运行')
    report.table([['条目','两模型共同设置'],['模型','SMP0.5.0，ResNet34 ImageNet1K V1编码器；初始encoder逐tensor hash一致'],
                  ['输入与有效域','RGB/NCHW512；GT最近邻，Ignore保守汇聚；padding无效；原生域评分'],
                  ['增强','共同sample/epoch随机翻转、90°旋转、亮度±0.05、对比度0.9-1.1'],
                  ['训练','AdamW lr1e-4 / wd1e-4；masked BCE+Dice各0.5；AMP fp16'],
                  ['预算/选择','seed269000，batch4，最多60轮，patience12；原生val macro Dice；同分取早'],
                  ['推理','sigmoid≥0.5，无连通域过滤；最近邻还原原生ROI']],[130,639])
    report.table([['模型','参数量','峰值分配显存/MB','前反向'],*[[DISPLAY[r['model']],str(r['parameters']),f"{r['peak_allocated_mb']:.1f}",'通过'] for r in gpu]],[180,180,220,189])
    report.text('两模型试运行后销毁并全新初始化；试运行更新未进入训练。架构的解码器/ASPP及参数量不同，匹配的是数据、优化与停止规则，而非强行相同计算量。')
    report.page('3 实际训练记录与共同36图结果')
    report.table([['模型','完成轮数','最佳轮','停止原因','训练耗时/s'],*[[DISPLAY[r['model']],r['epochs'],r['best_epoch'],r['stop_reason'],f"{r['total_elapsed_s']:.1f}"] for r in manifests]],[180,120,120,200,149])
    report.table([['方法','可用/计划','Dice','IoU','Precision','Recall'],*[[DISPLAY[r['method']],r['eligible']+'/'+r['planned'],*[f"{float(r[k]):.4f}" for k in ('dice_mean','iou_mean','precision_mean','recall_mean')]] for r in scores]],[165,124,120,120,120,120])
    report.text('Otsu、U-Net、DeepLabv3+共用36张；背景差分只有合格6张，不能将该行直接列入36图总体排名。所有深度模型数值均为最佳验证权重的同日内部开发成绩；验证数据参与早停/选型，不是独立测试。')
    report.text('训练期选型使用batch4，最终导出与计时使用batch1；近阈值像素可能有小的数值差异，完整预测与最佳轮记录分别保留。单开发seed不支持模型训练稳定性或普遍优势结论。')
    report.page('4 空背景、假阳性与背景共同子集')
    report.table([['方法','阳性Dice','空GT误检/空GT','FP面积均值/px','有效域FP比例'],*[[DISPLAY[r['method']],f"{float(r['positive_dice_mean']):.4f}",r['empty_GT_false_positive_images']+'/'+r['empty_GT'],f"{float(r['false_positive_area_px_mean']):.1f}",f"{float(r['false_positive_area_fraction_mean']):.6f}"] for r in scores]],[160,130,160,160,159])
    report.table([['共同背景6图','Dice','IoU','阳性Dice','空GT误检'],*[[DISPLAY[r['method']],f"{float(r['dice_mean']):.4f}",f"{float(r['iou_mean']):.4f}",f"{float(r['positive_dice_mean']):.4f}",r['empty_GT_false_positive_images']+'/'+r['empty_GT']] for r in common]],[220,130,130,160,129])
    report.text('合格背景子集仅3阳性+3空GT，构成与全部36图不同。空GT有任意有效域FP即记误检图；同时报告FP面积，避免把极少散点与整片网格误检等同解释。此处不作帧独立置信区间或显著性检验。')
    image_rows=read_csv(run/'evaluation/per_image.csv')
    small={r['method']:r for r in image_rows if r['sample_id']=='ROI157'}
    report.text('小液滴反例ROI157：人工GT为389px，U-Net召回率'+f"{float(small['unet']['recall']):.4f}"+
                '，DeepLabv3+召回率'+f"{float(small['deeplabv3plus']['recall']):.4f}"+
                '。两模型未整图漏检，但存在明显面积漏分；较高平均Dice不代表小液滴边界已经可靠。全部样本保留，不据此回调本轮阈值。')
    report.page('5 推理耗时、研究边界与审计')
    report.table([['模型/范围','均值/ms','P50/ms','P95/ms'],*[[DISPLAY[r['method']]+' / '+('GPU流程' if r['timing_scope'].startswith('GPU') else '纯CUDA'),*[f"{float(r[k]):.3f}" for k in ('mean_ms','p50_ms','p95_ms')]] for r in timing]],[320,150,150,149])
    report.text('RTX5060 Laptop；每图预热5次，36图×10次，batch1、512×512、AMP。GPU流程含letterbox/RGB/归一化、传输、网络、阈值及原生还原；纯CUDA仅forward/sigmoid/threshold，不含传输。均不含解码、评分、写盘。传统CPU计时保留于G3，硬件口径不同，不宣称无条件加速。')
    report.text(f"独立审计：{audit['native_predictions_checked']}张深度预测逐像素复算与保存指标一致；冻结输入和控制源码保护摘要一致；共同encoder、数据顺序与增强规则通过核查。")
    report.text(f"全量软件回归：{tests['tests_run']}项，失败{tests['failures']}，错误{tests['errors']}，跳过{tests['skipped']}。已有GUI/Tk清理提示若出现单独记录，不改GUI隐藏。")
    report.text('边界：同日、单开发seed、144张训练样本、只有2个验证视频，不能支持跨批次泛化；微小液滴/液桥/反光边界仍须独立评价。实例真值未审核，实例质心与身份安全漏检为NA。电极覆盖诊断仍使用候选配准，不是最终计量精度。')
    report.page('6 交付、复现与下一步')
    report.table([['资料','内容'],['frozen_protocol.json / G4数据检查结论.md','协议、范围、GT说明文字更正及数据检查'],
                  ['unet/ 与 deeplabv3plus/','best.pt / last.pt，epochs.csv，训练manifest'],
                  ['environment.json / pip_freeze.txt','环境、CUDA、库版本、官方预训练来源'],
                  ['evaluation/','逐图、逐视频、共同子集、耗时、原生PNG预测'],
                  ['independent_audit.json / verification/','原生独立复算、源文件保护及测试记录'],
                  ['reports/curves/ 与 validation_previews/','完整学习曲线，全部36验证样本，不挑最好案例']],[300,469])
    report.text('下一步先由人工复核困难边界和全部模型预测，明确小液滴漏检/空背景误检的具体类型。后续冻结模型后新增独立采集批次，才能放行正式独立测试；不依据本次验证成绩改写GT以抬高指标。')
    report.text('本轮没有改AM控制、五状态、仿真冻结数据，没有实物高压操作，没有Commit/Push。网络训练是实际GPU执行，不把模拟Mask当作真实训练样本。')
    for q in ('loss','dice'):
        report.page('训练过程：'+('有效域损失' if q=='loss' else '原生验证Dice'))
        report.picture(curve_dir/('learning_'+q+'.png'))
    preview_dir=out/'validation_previews'; preview_dir.mkdir(exist_ok=True)
    samples=[s for s in read_csv(root/'G2/frozen_samples.csv') if s['split']=='val']
    for i in range(0,len(samples),2):
        stem=preview_dir/f'validation_{i//2+1:02d}'
        preview(root,run,samples[i:i+2],stem)
        report.page(f'完整验证集逐例对照 {i//2+1:02d}/18')
        report.picture(str(stem)+'.png')
    report.canvas.save()
    pdf=out/'真实液滴分割_G4匹配训练与内部验证_Chat审查报告.pdf'
    qa=out/'pdf_qa'; qa.mkdir(exist_ok=True)
    doc=fitz.open(pdf)
    for i,page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(qa/f'page_{i+1:02d}.png')
    write_json(out/'packaging_manifest.json',dict(pages=len(doc), pdf_sha256=_sha(pdf),
               protocol_sha256=_sha(run/'frozen_protocol.json'),
               report_source_sha256=_sha(Path(__file__)),
               scores_source_sha256=_sha(run/'evaluation/per_image.csv'),
               unchanged_frozen_inputs=read_json(run/'read_only_verification.json')))
    print(pdf)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args()
    package(args.root,args.run)
