"""Package saved empirical-shape replay, without new motion or inference runs."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, PageBreak, SimpleDocTemplate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dmf.chapter2_geometry_sim.sdf_trial import OUT as DATA, BASE, CH, sha, js, audit_empirical

OUT = CH / '审查材料/2026-10-29_实验一SDF经验形态_Chat审查包_v1'
TITLE = '实验一SDF经验形态_同轨迹对照与审查报告'
LOCAL_TESTS = ['test_shape_sequence_sdf', 'test_shape_review_package', 'test_pilot_annotation',
    'test_geometry_normal_speed', 'test_geometry_single_step', 'test_chapter2_geometry_sim',
    'test_video_geometry_estimate', 'test_video_speed_check', 'test_chapter2_causality',
    'test_chapter2_evidence', 'test_electrode_design_map', 'test_segmentation_research']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def build():
    OUT.mkdir(parents=True, exist_ok=False)
    qa = OUT / 'QA'; qa.mkdir()
    audit = audit_empirical(DATA / 'trial')
    if not audit['passed']:
        raise ValueError(audit)
    m = load(DATA / 'trial/manifest.json'); old = load(BASE / 'manifest.json')
    library = load(DATA / 'shape_inputs/shape_library.json')
    visual_path = DATA / 'visualization/render_manifest.json'
    visual = load(visual_path)
    # Verify the original render inventory before adding byte-identical map links.
    for rel, digest in visual['files'].items():
        if sha(DATA / 'visualization' / rel) != digest:
            raise ValueError('render inventory changed: ' + rel)
    copied = []
    for suffix in ('pdf', 'svg', 'png'):
        source = BASE.parent / f'visualization/figures/map_full.{suffix}'
        dest = DATA / f'visualization/figures/map_full.{suffix}'
        if dest.exists():
            raise FileExistsError(dest)
        shutil.copyfile(source, dest)
        copied.append(dict(source=str(source), destination=str(dest), sha256=sha(dest)))
    visual['additional_byte_identical_map_files'] = copied
    visual['files'] = {p.relative_to(DATA / 'visualization').as_posix(): sha(p)
        for p in (DATA / 'visualization').rglob('*') if p.is_file() and p != visual_path}
    js(visual_path, visual)
    # Infer the likely software task; no conversion to image-space GT.
    activation = CH / '视频样本/2026-10-14/camera_20261014_112318_257662.frame_electrodes.csv'
    indexed = {int(r['video_frame_index']): r for r in rows(activation)}
    active = lambda frame: set(json.loads(indexed[frame]['confirmed_active_ids']))
    before, after = active(665), active(710)
    assert before == {386, 412} and after == {385, 412}
    assert active(668) == before and active(669) == after and active(712) == after
    assert active(713) != after
    inference = dict(source_candidates=sorted(before-after), target_candidates=sorted(after-before),
        common_active=sorted(before & after), switch_between_video_frames=[668, 669],
        next_activation_change_frame=713, source_log=str(activation), source_sha256=sha(activation),
        evidence='recorded confirmed software state, continuous motion and known numbering',
        physical_output_measured=False, exposure_timestamp_verified=False,
        image_map_registration_available=False, image_task_GT=False,
        virtual_task='190->191 after rotation and area normalization')
    js(OUT / '源目标电极推定记录.json', inference)
    # Fresh local regression; not a simulation rerun or a full-suite claim.
    command = [sys.executable, '-m', 'unittest'] + ['tests.'+t for t in LOCAL_TESTS] + ['-v']
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (qa / '136项局部回归.txt').write_text(result.stdout+result.stderr, encoding='utf-8')
    if result.returncode or 'Ran 136 tests' not in result.stderr:
        raise ValueError('local regressions failed or count changed')
    protection = subprocess.run([sys.executable, '.planning/geometry_single_step_20261028/protect.py', 'verify'],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (qa / '旧源码与资产保护.txt').write_text(protection.stdout+protection.stderr, encoding='utf-8')
    if protection.returncode:
        raise ValueError('protected baseline changed')
    # Audit all final exported figure PDFs at their native output size.
    scripts = Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
    figure_qa = []
    for pdf in sorted((DATA / 'visualization/figures').glob('*.pdf')):
        text = subprocess.run([sys.executable, str(scripts/'audit_pdf_text.py'), str(pdf), '--min-pt', '5', '--json'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        (qa / (pdf.stem+'_text.json')).write_text(text.stdout, encoding='utf-8')
        collision = subprocess.run([sys.executable, str(scripts/'audit_figure_collisions.py'), str(pdf),
            '--json-out', str(qa/(pdf.stem+'_collisions.json'))], capture_output=True, text=True, encoding='utf-8', errors='replace')
        (qa / (pdf.stem+'_collisions.txt')).write_text(collision.stdout+collision.stderr, encoding='utf-8')
        figure_qa.append(dict(figure=pdf.name, text_returncode=text.returncode, collision_returncode=collision.returncode))
    js(qa / 'figure_checks.json', figure_qa)
    if any(r['text_returncode'] or r['collision_returncode'] for r in figure_qa):
        raise ValueError('figure QA needs review; see QA records')
    sources = []
    def record(path, role, expected=None):
        digest = sha(path)
        if expected is not None and digest != expected:
            raise ValueError('source hash mismatch: '+str(path))
        sources.append(dict(role=role, path=str(path), sha256=digest))
    for rel, digest in m['artifacts'].items(): record(DATA/'trial'/rel, 'saved empirical replay', digest)
    for path, digest in m['source_code'].items(): record(Path(path), 'shape implementation', digest)
    for rel, digest in visual['files'].items(): record(DATA/'visualization'/rel, 'saved rendering', digest)
    for r in library['inputs']:
        for key, hash_key in [('image_path','image_sha256'), ('mask_path','mask_sha256')]:
            record(DATA/'shape_inputs'/r[key], 'frozen modeling input', r[hash_key])
    for path in [activation, DATA/'shape_inputs/shape_library.json', DATA/'trial/manifest.json', visual_path,
        DATA/'independent_audit.json', DATA/'modeling_node_shape_descriptors.csv', DATA/'paired_observed_features.csv',
        BASE/'manifest.json', BASE/'world.csv', BASE/'reference.json', Path(__file__),
        ROOT/'scripts/render_chapter2_sdf_shape_comparison.py', ROOT/'tests/test_shape_sequence_sdf.py']:
        record(path, 'traceability')
    with (OUT/'来源与hash索引.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        w=csv.DictWriter(stream, fieldnames=['role','path','sha256']);w.writeheader();w.writerows(sources)
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=body,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),spaceAfter=10)
    cell=ParagraphStyle('cell',parent=body,fontSize=9.5,leading=14,spaceAfter=0)
    story=[];md=[]
    def p(t, h=False):story.append(Paragraph(escape(t),heading if h else body));md.append(t+'\n')
    def table(headers, items, widths):
        grid=[[Paragraph(escape(str(c)),cell) for c in r] for r in [headers]+items]
        t=Table(grid,colWidths=[v*mm for v in widths])
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.5,colors.grey),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.extend([t,Spacer(1,10)])
        md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n')
        md.extend('| '+' | '.join(map(str,r))+' |\n' for r in items)
    def page():story.append(PageBreak());md.append('\n---\n')
    summary=m['summary']; old_summary=old['summary'];ref=summary['reference_confirmation_s']
    p('实验一 SDF经验形态同轨迹对照与审查',True)
    p('2026-10-29 | SIMULATION | normal，n=1 | 虚拟任务190→191')
    p('一、本轮实际完成范围',True)
    p('在已保存的1.4 mm/s正常单步运动轨迹上，仅替换液滴形态表示并重建模拟观测。新形态由同一视频迁移片段的8张Mask归一化后，以符号距离场（SDF）分阶段插值。未重新求解运动轨迹，未运行异常场景、多seed比较或下一电极切换。')
    table(['保持不变','实际设置'],[
        ['真实几何与尺寸','FBC6-3的420电极设计轮廓；节距3.2 mm；面积等效直径4.0 mm；0.8 mm高度仅为装置信息。'],
        ['运动和时钟','同一601条内部位置/速度/激活记录，dt=0.01 s，0-6 s；请求0.50 s，模拟Applied 0.54 s，响应0.72 s。'],
        ['观测与判据','20 fps，120张新Mask；三方法共用观测。阈值、稳定窗口、空间/历史门与独立参考定义不改。'],
        ['对照性质','旧版整体仿射与新版视频约束形态的同轨迹敏感性比较；不是物理动力学或算法性能统计。']], [35,135])
    p('二、源、目标编号由日志推定',True)
    p('原视频第665帧激活集为{386,412}，第669帧起为{385,412}，第713帧又发生激活变化。因此本片段候选任务为386→385，412为共同激活电极。该判断结合连续左向运动和既有编号方向，不要求用户人工辨认局部电极。')
    p('上述记录是软件任务线索，不是实测高压输出，也不是图像配准GT。没有有效的视频—Gerber变换，故不据此计算真实电极覆盖误差。用于仿真时只统一运动方向和面积，映射至虚拟190→191。')
    p('三、人工Mask状态',True)
    p('建模帧为665、670、675、680、682、688、698、710。采用当前有效Mask（工作副本优先）；原GUI仍为4张已审核、4张待核对。用户“mask基本没啥问题”记录为本次形态建模的初步视觉认可，不冒充独立测试GT或新增采集批次。')
    page()
    p('四、形态生成与数值验收',True)
    p('先将每张Mask转为单连通无孔轮廓，沿观测迁移轴旋转、质心居中，并归一化至12.5664 mm²。关键阶段由原片段质心投影进展确定；阶段间线性插值SDF，提取零水平边界，再恢复统一面积和内部轨迹质心。未自动补桥或拼接断裂轮廓。')
    table(['核查项','实际结果'],[
        ['轨迹一致性','601条时间、位置、速度、激活及响应记录与旧正常例一致；独立参考文件SHA256相同。'],
        ['轮廓面积','最大相对误差 %.3g；低于0.5%%。'%audit['geometric_area_relative_error']],
        ['栅格Mask面积','最大相对误差 %.4f%%；低于2%%。'%(100*audit['mask_area_relative_error'])],
        ['因果与交叠','迁移tick均保持对激活目标的正交叠；应用/响应前位置不迁移；只有一次191请求和Applied。'],
        ['软件验证','136项相关局部测试通过；未声称全量回归。旧源码内容hash与资产大小/修改时间保护检查通过。']], [36,134])
    p('五、真实形态与模型对照的解释',True)
    p('新表示可保留建模片段中的前后不对称和局部细颈，而非仅将同一紧凑轮廓整体拉长。细颈测量以纵向宽度剖面的局部谷值定义；紧凑轮廓无可识别细颈时记NA，而不强行赋值。')
    p('在675、680、682三个建模节点，归一化参考细颈宽度分别为1.6125、1.3500、1.3125 mm；旧仿射模型在同一相对颈部位置的宽度偏差为1.2500、1.1125、1.1375 mm。这里的mm来自4 mm面积等效归一化，不是原视频的毫米标定测量。')
    p('SDF在8个输入节点的轮廓IoU为1，是直接使用输入轮廓的构造结果，不能用作独立形态精度或泛化提升。旧仿射节点IoU为0.692-0.956；其最近持久化tick与建模阶段的小差异已逐项保存。真实覆盖率误差与留出片段IoU均记NA。')
    p('重要混杂：旧版以第153帧紧凑形状为模板，新版使用当前8阶段形态，包括不同起终形状。因此本对照说明整体形态表示影响，不将差异单独归因于SDF插值算子。')
    page()
    p('六、到达事件实际变化：不调整阈值迎合结果',True)
    table(['方法/事件','旧仿射/s','新SDF/s','新相对参考/s'],[
        ['M1 单帧覆盖',f"{old_summary['single_confirmation_s']:.2f}",f"{summary['single_confirmation_s']:.2f}",f"{summary['single_confirmation_s']-ref:+.2f}"],
        ['M2 连续稳定',f"{old_summary['window_confirmation_s']:.2f}",f"{summary['window_confirmation_s']:.2f}",f"{summary['window_confirmation_s']-ref:+.2f}"],
        ['M3 时空联合',f"{old_summary['spatiotemporal_confirmation_s']:.2f}",f"{summary['spatiotemporal_confirmation_s']:.2f}",f"{summary['spatiotemporal_confirmation_s']-ref:+.2f}"],
        ['独立模拟参考',f'{ref:.2f}',f'{ref:.2f}','0.00']], [54,37,37,42])
    p('三方法只旁路识别，不发出下一电极切换。形态替换使确认时刻均提前0.10 s；M2/M3由参考之后0.03 s变为之前0.07 s。这说明形态会改变覆盖特征及到达时刻，不说明新版识别更准确。M2=M3仍无S/K额外收益证据。')
    p('G仍为目标电极覆盖率≥0.90、源区液滴残留≤0.08；W仍为至少5帧且跨度≥0.25 s，规则20 fps下实际需6帧；Q要求非空、单连通、不触及ROI；S为目标距离≤0.576 mm；K历史速度上限19.2 mm/s。独立参考另用内部距离≤0.288 mm、速度≤0.192 mm/s、驻留≥0.15 s。')
    p('七、失败记录与证据边界',True)
    p('初次导出在审计阶段发现电极ID被写为191.0，整数解析失败。已保存验收前原文件并修复ID序列化表示；位置、Mask、特征、预测与参考未变，未再次运行运动或观测。对应整数序列化回归已通过。')
    p('SDF是经验形态仿真，不是CFD或真实电润湿计算。形状进度与模拟运动关联是建模假设；逐帧面积归一化不等于真实三维体积守恒。原视频接收时间不等于已验证曝光时间，且全部数据仍来自同一采集组。没有独立迁移片段，形态真实性与到达判定有效性尚未正式验收。')
    p('八、请Chat重点审查',True)
    p('1. 同轨迹图中的非对称与细颈形态是否已改善明显的整体椭圆失真？2. 面积/质心归一化、阶段顺序和宽度测量有无方法性风险？3. M2/M3早于既定参考0.07 s如何解释，是否需后续独立参考敏感性而非立即调门限？4. 独立片段留出与视频配准补齐前，当前结果是否仅适合作为机制和形态敏感性示例？')
    p('附图顺序：真实建模序列、同轨迹双模型、SDF运动关键帧、覆盖特征对照、SDF到达时间线。动画601帧、100 fps、1×时长6.01 s，直接读取同一持久化日志；未插值控制事件。所有旧结果保留，本例完成后停止扩展。')
    (OUT/(TITLE+'.md')).write_text('\n'.join(md),encoding='utf-8')
    def footer(canvas,doc):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'SIMULATION | 经验形态同轨迹敏感性，n=1')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    body_pdf=qa/'正文.pdf'
    SimpleDocTemplate(str(body_pdf),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
        topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    combined=fitz.open(body_pdf);body_pages=len(combined)
    if body_pages != 3:
        raise ValueError(f'Unexpected body pagination {body_pages}')
    figures=['real_shape_sequence','two_models_same_trajectory','movement_keyframes','paired_coverage_features','arrival_timeline']
    for name in figures:
        with fitz.open(DATA/f'visualization/figures/{name}.pdf') as appendix:combined.insert_pdf(appendix)
    pdf=OUT/(TITLE+'.pdf');combined.save(pdf);combined.close()
    with fitz.open(pdf) as document:
        for i,page_obj in enumerate(document):
            page_obj.get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False).save(qa/f'page_{i+1:02d}.png')
    js(OUT/'交付manifest.json',dict(pdf=str(pdf),pdf_sha256=sha(pdf),pages=body_pages+len(figures),
        trial_id=m['trial_id'],new_world_runs=0,empirical_observation_replays=1,report_new_runs=0,
        local_tests=136,full_suite_run=False,independent_shape_validation=False,source_records=len(sources),
        source_target_inferred_not_image_GT=True,files={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(str(pdf),flush=True)


if __name__ == '__main__':
    build()
