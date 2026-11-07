"""Read-only packaging of a completed internal traditional-baseline run.

No inference, training, scoring, input edits, camera or serial access. Report
statistics are descriptive aggregations of the frozen per-image CSV only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import shutil
from xml.sax.saxutils import escape

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader


PDF_NAME = '真实液滴分割_G2冻结与G3传统基线_Chat审查报告.pdf'
FONT = 'STSong-Light'
BLUE = '#173B51'
TEAL = (0, 119, 117)
IGNORE = (210, 198, 220)
PAGE = (841.89, 595.28)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def mean(rows, key):
    values = [float(r[key]) for r in rows if r.get(key) != '']
    return sum(values) / len(values) if values else None


def fmt(value, digits=6):
    return 'NA' if value is None else f'{value:.{digits}f}'


def valid(rows, method, split='all', ids=None, positive=False):
    return [r for r in rows if r['method'] == method and r['eligible'] == 'True'
            and (split == 'all' or r['split'] == split)
            and (ids is None or r['sample_id'] in ids)
            and (not positive or r['positive_gt'] == 'True')]


def result_line(rows, method, split, ids=None, positive=False):
    subset = valid(rows, method, split, ids, positive)
    return [method, split + (' / 阳性GT' if positive else ''), str(len(subset))] + [
        fmt(mean(subset, key)) for key in ('dice', 'iou', 'precision', 'recall')]


class PDF:
    def __init__(self, path):
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        self.c = Canvas(str(path), pagesize=PAGE, pageCompression=1)
        self.c.setTitle('真实液滴分割 G2内部冻结与G3传统基线审查')
        self.c.setAuthor('离线研究工作包')
        self.n = 0
        self.y = 0
        self.styles = {}
        for size in (9, 10, 11, 12, 14, 21):
            self.styles[size] = ParagraphStyle(str(size), fontName=FONT, fontSize=size,
                                              leading=size * 1.5, textColor=HexColor('#253746'),
                                              wordWrap='CJK', spaceAfter=0)

    def page(self, title, subtitle='真实视频 | 同日内部研究 | 正式 test = 0 | 未训练深度模型'):
        if self.n:
            self.c.showPage()
        self.n += 1
        self.c.setFillColor(HexColor('#FFFFFF'))
        self.c.rect(0, 0, *PAGE, fill=1, stroke=0)
        self.c.setFillColor(HexColor(BLUE))
        self.c.rect(0, PAGE[1] - 10, PAGE[0], 10, fill=1, stroke=0)
        self.y = PAGE[1] - 45
        self.text(title, 21)
        self.text(subtitle, 9)
        self.y -= 8
        self.c.setFont(FONT, 8)
        self.c.setFillColor(HexColor('#61707A'))
        self.c.drawString(36, 19, 'G2 / G3 初始传统基线 · 冻结资料只读包装 · 2026-11-05')
        self.c.drawRightString(PAGE[0] - 36, 19, f'{self.n:02d} / 23')

    def text(self, body, size=11, after=7):
        paragraph = Paragraph(body, self.styles[size])
        _, height = paragraph.wrap(PAGE[0] - 72, 1000)
        if self.y - height < 39:
            raise ValueError(f'Text overflow on page {self.n}: {body[:40]}')
        paragraph.drawOn(self.c, 36, self.y - height)
        self.y -= height + after

    def table(self, data, widths, size=10):
        styled = [[Paragraph(escape(str(cell)), self.styles[size]) for cell in row] for row in data]
        table = Table(styled, colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#EAF0F3')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), .4, HexColor('#CBD5DC')),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        _, height = table.wrap(PAGE[0] - 72, 1000)
        if self.y - height < 39:
            raise ValueError(f'Table overflow on page {self.n}')
        table.drawOn(self.c, 36, self.y - height)
        self.y -= height + 10


def mask_panel(path, ignore):
    binary = np.asarray(Image.open(path).convert('L')) > 0
    out = np.full((*binary.shape, 3), 255, np.uint8)
    out[binary] = TEAL
    out[ignore] = IGNORE
    return Image.fromarray(out)


def fit_panel(canvas, panel, xy, size=540):
    image = panel.copy()
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    x, y = xy
    canvas.paste(image, (x + (size - image.width) // 2, y + (size - image.height) // 2))


def make_preview(root, out, pair, predictions, page_number, source_paths):
    fontpath = Path('C:/Windows/Fonts/msyh.ttc')
    if not fontpath.exists():
        fontpath = Path('C:/Windows/Fonts/simhei.ttf')
    font = lambda size: ImageFont.truetype(str(fontpath), size)
    image = Image.new('RGB', (2400, 1510), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((36, 18), f'完整验证集逐例核对 {page_number:02d}/18', font=font(34), fill=BLUE)
    draw.text((36, 65), '原图仅等比例显示；青色 = 前景，灰紫 = Ignore；NA = 无合格过去背景，不是空预测', font=font(25), fill='#43535D')
    xs = [36, 632, 1228, 1824]
    titles = ['Original 原始ROI (无叠加)', 'GT 人工语义 (有效域)', 'Otsu 预测', 'Background 背景差分']
    for x, title in zip(xs, titles):
        draw.text((x, 108), title, font=font(26), fill=BLUE)
    for rownum, sample in enumerate(pair):
        sid = sample['sample_id']
        top = 154 + rownum * 660
        label = (f"{sid} | {sample['parent_video_id']} | frame {sample['source_frame_id']} | "
                 f"native {sample['width']} x {sample['height']}")
        draw.text((36, top), label, font=font(23), fill='#253746')
        yy = top + 37
        source = root / 'G2' / sample['frame_path']
        gt = root / 'G2' / sample['mask_path']
        ign = root / 'G2' / sample['exclusion_mask_path']
        source_paths.update((source, gt, ign))
        ignore = np.asarray(Image.open(ign).convert('L')) > 0
        fit_panel(image, Image.open(source).convert('RGB'), (xs[0], yy))
        fit_panel(image, mask_panel(gt, ignore), (xs[1], yy))
        for index, method in enumerate(('otsu', 'background'), start=2):
            row = predictions[(sid, method)]
            if row['eligible'] == 'True':
                path = root / 'G3_initial_baselines_v1' / row['prediction_path']
                source_paths.add(path)
                fit_panel(image, mask_panel(path, ignore), (xs[index], yy))
                caption = f"Dice {float(row['dice']):.4f} | IoU {float(row['iou']):.4f}"
                draw.text((xs[index], yy + 545), caption, font=font(23), fill='#253746')
            else:
                assert row['prediction_path'] == '' and row['dice'] == ''
                draw.rectangle((xs[index], yy, xs[index] + 540, yy + 540), fill='#FAFAFA', outline='#CCD4D9', width=2)
                draw.text((xs[index] + 195, yy + 115), 'NA', font=font(76), fill='#647580')
                lines = ['无合格过去背景', '第0帧有液滴或有效域边界不确定', '未用未来帧 / GT 修补', '未伪造空预测；保留计划分母']
                for k, line in enumerate(lines):
                    draw.text((xs[index] + 25, yy + 244 + k * 43), line, font=font(24), fill='#52636E')
                draw.text((xs[index], yy + 545), f"{row['reference_id']} | unavailable", font=font(23), fill='#52636E')
        draw.text((xs[0], yy + 545), f"ROI {sample['roi_xywh']}", font=font(22), fill='#52636E')
        draw.text((xs[1], yy + 545), f"有效前景 {sample['valid_foreground_px']} px | Ignore {sample['ignore_px']} px", font=font(22), fill='#52636E')
        for x in xs:
            draw.rectangle((x - 1, yy - 1, x + 541, yy + 541), outline='#CCD4D9', width=2)
    path = out / 'validation_previews' / f'validation_{page_number:02d}.png'
    image.save(path)
    return path


def package(root, out):
    root, out = root.resolve(), out.resolve()
    if out != root / 'reports':
        raise ValueError('Only the designated new root/reports output is allowed')
    out.mkdir(exist_ok=True)
    (out / 'validation_previews').mkdir(exist_ok=True)
    (out / 'pdf_qa').mkdir(exist_ok=True)
    files = [root / p for p in (
        'G2/frozen_samples.csv', 'G2/split_manifest.json',
        'G3_initial_baselines_v1/per_image.csv', 'G3_initial_baselines_v1/summary.csv',
        'G3_initial_baselines_v1/per_video.csv', 'G3_initial_baselines_v1/timing_summary.csv',
        'G3_initial_baselines_v1/common_background_subset_summary.csv',
        'G3_initial_baselines_v1/fixed_config.json', 'G3_initial_baselines_v1/manifest.json',
        'backgrounds/reviewed_references.json', 'backgrounds/背景参考资格清单.csv',
        '独立复算核验.json')]
    source_paths = set(files)
    before = {str(p): sha(p) for p in files}
    samples = read_csv(files[0]); split = read_json(files[1]); rows = read_csv(files[2])
    config = read_json(root / 'G3_initial_baselines_v1/fixed_config.json')
    manifest = read_json(root / 'G3_initial_baselines_v1/manifest.json')
    refs = read_json(root / 'backgrounds/reviewed_references.json')
    audit = read_json(root / '独立复算核验.json')
    timings = read_csv(root / 'G3_initial_baselines_v1/timing_summary.csv')
    val = sorted([s for s in samples if s['split'] == 'val'], key=lambda s: s['sample_id'])
    assert len(samples) == 180 and len(val) == 36 and len(rows) == 360
    assert Counter(s['split'] for s in samples) == {'train': 144, 'val': 36}
    assert split['formal_test_samples'] == 0 and config['deep_models_training_run'] is False
    assert sum(r['eligible'] == 'True' for r in rows) == 289
    assert audit['all_passed'] is True and audit['scored_rows'] == 289
    assert len(refs) == 75 and sum(r['usable'] for r in refs) == 47
    predictions = {(r['sample_id'], r['method']): r for r in rows}
    common_val = {r['sample_id'] for r in valid(rows, 'background', 'val')}
    assert len(common_val) == 6
    previews = [make_preview(root, out, val[i:i + 2], predictions, i // 2 + 1, source_paths)
                for i in range(0, len(val), 2)]

    p = PDF(out / PDF_NAME)
    p.page('1  G2冻结结论与证据边界')
    p.text('本轮已冻结180张真实视频ROI的内部划分，并完成Otsu及有合格过去背景时的背景差分。只支持同日内部开发描述，不是跨批次泛化、正式测试、四方法比较或实物闭环完成。', 12)
    p.table([['集合', '样本', '父视频', '有效GT阳性 / 空GT', '用途'],
             ['train', '144', '135940:72；141935:72', '128 / 16', '内部开发训练候选'],
             ['val', '36', '143440:12；143626:24', '33 / 3', '同日、视频不交叉的内部验证'],
             ['formal test', '0', '未建立独立采集测试', '0 / 0', '不允许正式泛化结论']], [80, 50, 225, 170, 244])
    p.text('冻结规则：父视频及源SHA、操作组、视频限定草案轨迹不跨train/val；跨文件液滴物理谱系未确认。同一采集日、芯片/装夹可能共享，4个视频不能视为4个独立批次。', 11)
    p.text('原生ROI共140张512×512、40张768×768。原图、人工语义GT与固定两出液/储液电极Ignore均按原字节快照；语义为ROI内全部实际液滴，液体伸出Ignore区域的部分仍可是有效前景。状态/实例身份GT没有被自动提升为已审核。', 11)
    p.text('G2快照与G3结果在新研究目录中独立保存；旧工作包不改写。深度训练仍未放行，本轮没有训练U-Net或DeepLabv3+。', 11)
    p.text('数据来源：G2/frozen_samples.csv、G2/split_manifest.json；统计口径以原生有效像素域为准。', 9)

    p.page('2  固定方法、因果背景与评价口径')
    p.table([['项目', '本轮实际配置 / 约束'],
             ['共同输入', f"{config['common_input_hw'][0]}×{config['common_input_hw'][1]}；缩小INTER_AREA；二值最近邻还原原生ROI；GT/Ignore不缩放"],
             ['Otsu', f"BGR转灰 + Gaussian {config['blur_kernel']}×{config['blur_kernel']} + 反向Otsu + {config['close_kernel']}×{config['close_kernel']}闭运算{config['close_iterations']}次"],
             ['背景差分', f"同样灰度/滤波；过去背景减当前的单向灰度差；阈值{config['background_threshold']}；相同闭运算"],
             ['分量 / 参数', '保留全部连通域及触边前景；无最大分量、最小面积、触边拒绝或强制填孔。首次计分前冻结参数；无验证集调参。'],
             ['算法输入', '图像、静态Ignore及必需背景参考；不向预测传GT。GT仅用于离线评分。']], [120, 649])
    p.text('背景只用同视频、完全同原生ROI的第0帧，要求帧号和主机接收相对时间严格早于样本。75个参考逐一经助手视觉检查：47个可用关联109样本；28个含液滴或边界不确定，关联71样本。它是参考资格审核，不是人工分割GT。未穷举所有其他过去帧。', 11)
    p.text('不可用背景：指标为NA、不造预测PNG、保留180个计划分母。不可用不等于运行错误；本轮首计时/后续重复/预热运行错误均0。', 11)
    p.text('Dice / IoU / Precision / Recall在原生ROI排除Ignore后逐图计算再平均；空GT保留。空GT且预测为空时得分1，空GT有假阳性时Dice/IoU为0。实例质心、实例漏检与身份安全指标均NA，不用语义联合质心替代。', 11)

    p.page('3  分割结果：完整分母与共同子集')
    full = [['方法', '集合', '可用n', 'Dice', 'IoU', 'Precision', 'Recall']]
    for split_name in ('train', 'val', 'all'):
        for method in ('otsu', 'background'):
            full.append(result_line(rows, method, split_name))
    p.table(full, [78, 78, 55, 137, 137, 137, 147], 9)
    p.text('可用率：Otsu train144/144、val36/36；背景差分train103/144、val6/36（16.67%）、总109/180。上表两方法全量分母不同，不能据此直接排序。', 10)
    paired = [['方法', '共同val分层', 'n', 'Dice', 'IoU', 'Precision', 'Recall']]
    for positive in (False, True):
        for method in ('otsu', 'background'):
            paired.append(result_line(rows, method, 'val', common_val, positive))
    p.table(paired, [78, 105, 28, 137, 137, 137, 147], 9)
    p.text('共同val只有6图（3阳性+3空GT）。空GT有像素假阳性：Otsu 3/3，背景差分1/3；阳性GT的Dice则Otsu 0.962726高于背景0.917271。聚合名次翻转来自空GT处理与组成，不能宣称背景差分整体更优。完整Otsu val阳性33图Dice=0.946514、IoU=0.924548。', 10)
    p.text('全数据空GT假阳性图数：Otsu19/19，背景11/19（从逐图fp&gt;0计数，非实例误检）。有GT而预测全空：Otsu 0/161，背景0/90；这不代表实例零漏检。', 10)

    p.page('4  耗时、候选映射诊断与独立复核')
    p.text(escape(manifest['hardware_label']) + '；OpenCV单线程；Python 3.14.3 / OpenCV 4.13.0 / NumPy 2.4.4。每个可用图-方法预热5次、计时10次；只评分保存第一次计时输出，不挑最佳重复。', 11)
    time_table = [['方法 / 集合', '计时调用', '平均 ms', 'P50 ms', 'P95 ms']]
    for t in timings:
        time_table.append([t['method'] + ' / ' + t['split'], t['timed_calls']] +
                          [fmt(float(t[k]), 4) for k in ('mean_ms', 'p50_ms', 'p95_ms')])
    p.table(time_table, [200, 110, 153, 153, 153], 9)
    p.text('计时包括当前图letterbox、预测、原生还原；背景灰度转换/滤波仍在每次调用内。固定背景letterbox初始化不计入逐帧时间；解码、GT评分、写盘不计。重复调用不是独立实验；不可用71图无耗时，不能解释为0ms或端到端实时性能。', 10)
    cov = [['候选目标电极覆盖率绝对误差', 'train 可用n / 均值', 'val 可用n / 均值', 'all 可用n / 均值']]
    for method in ('otsu', 'background'):
        cells = [method]
        for ss in ('train', 'val', 'all'):
            rr = [r for r in valid(rows, method, ss) if r['target_coverage_available'] == 'True']
            cells.append(f"{len(rr)} / {fmt(mean(rr, 'target_coverage_absolute_error'))}")
        cov.append(cells)
    p.table(cov, [280, 163, 163, 163], 9)
    p.text('覆盖率误差仅限有记录目标、完整电极多边形位于ROI且无Ignore重叠的候选配准诊断；两方法资格分母不同，不作等样本精度排名，不是最终标定或计量精度。', 10)
    p.text(f"独立复核：{audit['scored_rows']}个原生预测像素计数及Dice/IoU复算通过；{audit['output_ledger_files']}个输出账本、{audit['inputs_hashed']}个输入hash与源码hash不变。正式测试、真实模型、物理闭环均不在本轮。", 10)

    p.page('5  交付目录、审查问题与下一步')
    p.text('本PDF后18页完整展示36张验证样本，按sample_id排序、每页2例、四列原图/人工GT/Otsu/背景差分；没有挑选最佳案例。Original列不叠加、不修改原始图像；遮罩列以青色表示前景、灰紫表示Ignore。NA列明确保留不可用原因。', 11)
    p.table([['资料', '位置 / 作用'],
             ['冻结与血缘', 'G2/frozen_samples.csv；G2/split_manifest.json；G2/reviewed_snapshot/'],
             ['方法与逐图结果', 'G3_initial_baselines_v1/fixed_config.json；per_image.csv；per_video.csv；summary.csv'],
             ['配对 / 耗时', 'common_background_subset_summary.csv；timing_summary.csv；timings.csv'],
             ['参考与原生预测', 'backgrounds/背景参考资格清单.csv；reviewed_references.json；G3_initial_baselines_v1/predictions/'],
             ['只读核验', '独立复算核验.json；逐预测独立复算289条.csv；reports/包装来源与QA.json'],
             ['本轮便阅文件', 'reports/README.md；validation_previews/validation_01.png 至 validation_18.png']], [150, 619], 9)
    test_file = root / 'verification/full_unittest_summary.json'
    if test_file.exists():
        test_summary = read_json(test_file)
        source_paths.add(test_file)
        source_paths.add(root / 'verification/full_unittest.log')
        p.text(f"全量软件回归：{test_summary['tests_run']}项，失败{test_summary['failures']}、错误{test_summary['errors']}、跳过{test_summary['skipped']}；passed={test_summary['passed']}。摘要实测总耗时{test_summary['elapsed_s']:.3f}s（测试框架日志600.677s）；编译及7条独立软件控制链通过。", 10)
        p.text('既有Tk清理后出现“invalid command name ..._manual_simulation_loop”提示；本轮未修改GUI。该警告单独保留，不隐去，也不将软件回归通过等同固件烧录、仪器、最终标定或真实液滴闭环完成。', 10)
    else:
        test_summary = None
        p.text('包装时全量软件回归摘要尚未提供，因此本报告不声明全量通过；已有独立7条软件链通过由主任务验收记录负责。软件结果不替代固件烧录、仪器、标定及真实液滴实验。', 10)
    p.text('请Chat重点审查：①同日内部而非独立测试的边界是否明确；②共同6图及阳性/空GT分层是否足以避免误导排名；③完整验证预览是否仍存在语义边界/Ignore解释风险；④未来独立采集及背景资格方案是否合理。', 11)
    p.text('下一步尚未执行：先冻结U-Net与DeepLabv3+的匹配训练协议（编码器初始化、输入、增强、损失、优化器、预算、选择规则等），再获准训练；不依据本val结果回调传统参数。未来采集在加液前固定同ROI空背景，不能以未来帧为本批过去样本补背景。', 11)
    for i, preview in enumerate(previews, start=1):
        p.page(f'验证集全例预览 {i:02d} / 18', '')
        # Image includes complete row labels, masks and per-method captions.
        p.c.drawImage(ImageReader(str(preview)), 23, 40, width=PAGE[0] - 46,
                      height=PAGE[1] - 126, preserveAspectRatio=True, anchor='c')
    p.c.save()

    md = ['# 真实液滴分割 G2冻结与G3初始传统基线', '',
          '同日内部开发研究；train144、val36、正式test0。未训练U-Net/DeepLabv3+，不作独立批次泛化、四方法或实物闭环完成声明。', '',
          '## 关键结果', '',
          '- Otsu val36：Dice0.867638 / IoU0.847502；阳性GT33图Dice0.946514。',
          '- 背景差分计划180图、可用109图；val仅6/36可用（3阳性+3空GT），30图NA保留。',
          '- 共同val6：Otsu Dice0.481363，背景0.791969；阳性3图Otsu0.962726，背景0.917271。空GT假阳性3/3与1/3导致聚合翻转，不能据此宣布背景整体更优。',
          '- 独立复核289预测、301输出账本、628输入与源码保护通过；本包装不运行模型或重评分。', '',
          '## 文件', '', f'- `{PDF_NAME}`：5页方法/结果/边界 + 18页全部验证预览，共23页。',
          '- `validation_previews/validation_01.png` 至 `validation_18.png`：每张2例、4列，全36验证样本。',
          '- `pdf_qa/`：最终PDF每页渲染与总览图。', '- `包装来源与QA.json`：源文件hash、页数与样本覆盖。',
          '- `package_real_segmentation_internal_baselines.py`：只读包装脚本。', '',
          '## 耗时口径', '', manifest['hardware_label'] + '；单线程；预热5次、计时10次，第一次计时输出用于评分。',
          '当前图letterbox、预测、原生还原计入；背景灰度/滤波计入逐次调用，背景letterbox初始化排除；解码、GT评分与写盘排除。重复调用不是独立实验，无端到端实时性结论。', '',
          '## 数据与研究限制', '',
          '4视频不是4独立批次；跨文件物理液滴谱系未确认。实例GT未审核，实例质心/身份安全漏检均NA，不使用联合质心替代。候选目标电极覆盖率为非最终配准诊断，资格分母不同不直接排名。背景助手视觉资格审核不是人工Mask GT，其他过去帧未穷举。', '',
          '未来采集应在加液前固定空背景；不能用未来帧修补过去试验。先冻结深度模型匹配训练协议，训练未执行。', '',
          '## 软件回归', '',
          ('包装时未发现全量回归摘要，不声明全量通过。主任务另核验7条软件链。' if test_summary is None
           else '全量回归摘要（原样记录）：\n```json\n' + json.dumps(test_summary, ensure_ascii=False, indent=2) + '\n```'), '',
          ('全量摘要总耗时607.769s；测试框架日志为600.677s。编译与7条独立软件控制链通过。既有Tk清理后出现 `invalid command name ..._manual_simulation_loop` 提示，本轮未修改GUI；保留该警告，不将软件通过等同物理闭环完成。' if test_summary is not None else ''), '',
          '## 原始证据文件', '']
    md += [f'- `{f.relative_to(root).as_posix()}`' for f in files]
    (out / 'README.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    shutil.copyfile(Path(__file__), out / Path(__file__).name)

    doc = fitz.open(out / PDF_NAME)
    assert len(doc) == 23
    thumbnails = []
    for index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        dest = out / 'pdf_qa' / f'page_{index + 1:02d}.png'
        pix.save(str(dest))
        im = Image.open(dest).convert('RGB')
        im.thumbnail((421, 298), Image.Resampling.LANCZOS)
        tile = Image.new('RGB', (441, 328), '#EEF1F3')
        tile.paste(im, (10, 10))
        ImageDraw.Draw(tile).text((12, 309), f'Page {index + 1:02d}', fill='black')
        thumbnails.append(tile)
    montage = Image.new('RGB', (441 * 4, 328 * 6), 'white')
    for index, tile in enumerate(thumbnails):
        montage.paste(tile, ((index % 4) * 441, (index // 4) * 328))
    montage.save(out / 'pdf_qa' / 'all_pages_montage.png')
    after = {str(path): sha(path) for path in files}
    assert before == after, 'Source evidence changed during packaging'
    meta = dict(pdf=str(out / PDF_NAME), page_count=len(doc), preview_sheets=len(previews),
                validation_samples=[s['sample_id'] for s in val], validation_all_36_shown=True,
                methods_rerun=False, scores_rerun=False, original_sources_unchanged=True,
                input_metadata_hashes_before=before, input_metadata_hashes_after=after,
                source_files_sha256={str(path): sha(path) for path in sorted(source_paths)},
                script_sha256=sha(Path(__file__)), render_all_pages=True,
                visual_inspection='pending_external_visual_inspection',
                font=FONT, ignore_rgb=IGNORE, foreground_rgb=TEAL)
    (out / '包装来源与QA.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(pdf=str(out / PDF_NAME), pages=len(doc), previews=len(previews),
                qa=str(out / 'pdf_qa' / 'all_pages_montage.png'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.root / 'reports'), ensure_ascii=False))


if __name__ == '__main__':
    main()
