"""Create a source-traceable Chat review report from completed DEV artifacts only."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import re
import shutil
from xml.sax.saxutils import escape

import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak

ROOT = Path(__file__).resolve().parents[1]
TITLE = '实验一B_随机接口双seed开发与协议修订_Chat审查报告'
METHODS = ['M1', 'GQ', 'M2', 'M2_S', 'M2_K', 'M3']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    return '—' if value in ('', None) else f'{float(value):.2f}'


def build(data, verification_dir, output):
    data, verification_dir, output = map(lambda p: Path(p).resolve(), (data, verification_dir, output))
    if output.exists():
        raise FileExistsError('Preserve earlier review packages: '+str(output))
    audit = load(data/'independent_audit.json')
    verification = load(verification_dir/'verification.json')
    reviews = load(verification_dir/'code_reviews.json')
    if not audit['passed'] or len(verification) != 7 or any(v['exit_code'] for v in verification.values()):
        raise ValueError('Completed passing audit and all seven verification stages required')
    if not reviews['spec_approved'] or not reviews['quality_approved']:
        raise ValueError('Two independent code-review stages must be closed')
    records = rows(data/'planned_method_results.csv')
    sensitivity = rows(data/'reference_sensitivity_results.csv')
    config = load(data/'effective_config.json')
    manifest = load(data/'manifest.json')
    seeds = config['actual_development_seeds']
    if seeds != [268000, 268001] or len(records) != 144 or len(sensitivity) != 1008:
        raise ValueError('This report is exclusively for the approved two-seed development batch')
    failures = load(data/'failures.json')
    output.mkdir(parents=True)
    qa = output/'QA'; qa.mkdir()
    index = []

    def record(path, role, expected=None, snapshot=False):
        path = Path(path).resolve(); digest = sha(path)
        if expected and digest != expected:
            raise ValueError('Source changed after run: '+str(path))
        item = dict(role=role, path=str(path), sha256=digest, snapshot_path='')
        if snapshot:
            try:
                relative = path.relative_to(ROOT)
            except ValueError:
                relative = Path('external')/path.name
            target = output/'源码与协议快照'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if sha(target) != digest:
                raise ValueError('Snapshot mismatch')
            item['snapshot_path'] = str(target)
        index.append(item)

    for relative, digest in manifest['artifacts'].items():
        record(data/relative, 'persisted simulation artifact', digest)
    for path, digest in manifest['source_code'].items():
        record(path, 'frozen DEV runtime source', digest, True)
    for path in [data/'manifest.json', data/'independent_audit.json', verification_dir/'verification.json',
                 verification_dir/'code_reviews.json', verification_dir/'environment.json',
                 ROOT/'configs/chapter2_geometry_exp1b_random_dev_v1.json',
                 ROOT/'docs/chapter2-geometry-exp1b-random-protocol-revision-v2-2026-10-29.md',
                 ROOT/'tests/test_geometry_exp1b_random.py', Path(__file__)]:
        record(path, 'protocol and verification', snapshot=path.is_relative_to(ROOT))
    for path in sorted(verification_dir.glob('*.txt')):
        record(path, 'regression log')
        target = qa/path.name
        shutil.copyfile(path, target)
        if sha(target) != index[-1]['sha256']:
            raise ValueError('Regression log snapshot mismatch')
        index[-1]['snapshot_path'] = str(target)
    for name in ['code_reviews.json','environment.json','verification.json']:
        shutil.copyfile(verification_dir/name, qa/name)
    for name in ['planned_method_results.csv', 'reference_sensitivity_results.csv', 'development_summary.json',
                 'independent_audit.json', 'effective_config.json', 'failures.json']:
        shutil.copyfile(data/name, output/name)
    with (output/'来源与hash索引.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['role', 'path', 'sha256', 'snapshot_path'])
        writer.writeheader(); writer.writerows(index)

    pdfmetrics.registerFont(TTFont('Song', 'C:/Windows/Fonts/simsun.ttc', subfontIndex=0))
    body = ParagraphStyle('body', fontName='Song', fontSize=10.5, leading=17, spaceAfter=7, wordWrap='CJK')
    heading = ParagraphStyle('heading', parent=body, fontSize=14, leading=21,
                             textColor=colors.HexColor('#173a53'), spaceAfter=10, keepWithNext=True)
    cell = ParagraphStyle('cell', parent=body, fontSize=9.2, leading=14, spaceAfter=0)
    story, markdown = [], []

    def p(text, h=False):
        story.append(Paragraph(escape(str(text)), heading if h else body)); markdown.append(str(text)+'\n')

    def table(headers, data_rows, widths):
        values = [[Paragraph(escape(str(c)), cell) for c in row] for row in [headers]+data_rows]
        t = Table(values, colWidths=[v*mm for v in widths], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaf0f5')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, 0), .7, colors.HexColor('#173a53')),
            ('LINEBELOW', (0, -1), (-1, -1), .4, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4)]))
        story.extend([t, Spacer(1, 8)])
        markdown.extend(['| '+' | '.join(headers)+' |\n', '| '+' | '.join(['---']*len(headers))+' |\n'])
        markdown.extend('| '+' | '.join(map(str, row))+' |\n' for row in data_rows)

    def page():
        story.append(PageBreak()); markdown.append('\n---\n')

    p('实验一B：随机接口双seed开发与协议修订', True)
    p('2026-10-29 | SIMULATION / DEVELOPMENT | 非正式性能统计')
    p('一、实际完成范围', True)
    executed = sum(r['status'] == 'executed' for r in records)
    table(['项目', '实际记录与边界'], [
        ['开发身份', '268000、268001；分别使用预声明低强度槽位0和高强度槽位10。每一压力层仅1个开发实例。'],
        ['基本分母', f"8个基础运动World、24个共同观测缓存、144条R0方法记录、1008条七参考评分。实际执行{executed}条，未执行{144-executed}条；生成/执行失败{len(failures)}项。"],
        ['非独立重复', '六方法共享缓存；多种观测扰动共享基础运动；七参考只重新评分，不改变预测。144条不是144个独立运动实例。'],
        ['算法与形态', 'M1/GQ/M2/M2+S/M2+K/M3保持原门限；430个已保存有效轮廓按进度最近邻重放，仅平移至独立运动质心。'],
        ['正式批次', '20正式seed、80 World、240缓存、1440预测仅为原计划，本轮未运行。正式入口仍锁闭；实验二未运行。']
    ], [30, 140])
    p('本轮检验接口、共同输入、随机复现、TF联合负对照和10 s端点评分机制，不用于估计正式错误率或证明M3优于M2。不进行新的形态建模、阈值调优或异常类型扩充。')
    m2={ (r['seed'],r['condition']):r for r in records if r['method']=='M2' }
    m3={ (r['seed'],r['condition']):r for r in records if r['method']=='M3' }
    categories_equal=sum(m2[k]['primary_outcome']==m3[k]['primary_outcome'] for k in m2)
    times_differ=sum(m2[k]['decision_s']!=m3[k]['decision_s'] for k in m2)
    p(f'实际负面发现：M2/M3在{categories_equal}/24个缓存中的R0主分类相同，其中{times_differ}个缓存确认时间不同。两个TF缓存中六方法均出现无参考确认；增加K只延后部分事件，没有排除持续伪观测。该事实不作为调阈值或重抽seed的理由。')
    p('三类运动正常/慢速/暂停恢复及永久卡滞均为简化二维模型；真实Gerber设计几何和视频约束形态并不使运动参数成为实测标定。模拟Mask不是U-Net真实分割结果；本轮不评价真实电极安全切换。')
    p('二、协议冻结状态', True)
    p('修订协议与开发配置可交审，但正式240缓存执行仍等待开发结果审查及明确授权。配置加载绑定已审阅原方案的固定SHA256，并校验TF分布、种子、槽位和规模；不能通过更换配置文件绕过限制。')
    page()
    p('三、TF：卡滞后持续伪目标的实际时间', True)
    tf_items = []
    for seed in seeds:
        cache = load(data/'caches'/str(seed)/'TF'/'manifest.json')
        tf_items.append([seed, number(cache['permanent_stall_started_s']),
                         number(cache['first_exactly_stationary_stall_tick_s']),
                         number(cache['false_target_start_s']), number(cache['false_target_end_s']),
                         cache['actual_false_frames']])
    table(['seed', '卡滞开始/s', '零速首tick/s', '伪目标开始/s', '结束/s', '帧数'], tf_items, [28, 28, 30, 32, 28, 24])
    p('伪目标计划始于卡滞开始+0.20 s，向上对齐20 fps采样栅格；低强度7–9帧、高强度10–12帧。首个钳制tick与有限差分速度首次严格为零的tick分开记录。审计逐帧核实整个伪目标片段速度为零、运动进度不变；没有按算法结果重抽样。')
    table(['seed', '参考', 'M1', 'GQ', 'M2', 'M2+S', 'M2+K', 'M3'], [
        [seed, number(next(r for r in records if int(r['seed']) == seed and r['condition']=='TF')['reference_confirmed_s'])]+
        [number(next(r for r in records if int(r['seed']) == seed and r['condition']=='TF' and r['method']==m)['decision_s']) for m in METHODS]
        for seed in seeds], [28, 22, 20, 20, 20, 20, 20, 20])
    p('上表为模拟确认时刻/s。“—”表示没有参考或没有事件，不赋零。本例为永久卡滞且持续伪观测的合成压力；发生确认时记录无参考确认，仍不等于实物已经发生错误推进。')
    p('四、10 s端点的互斥主分类', True)
    table(['参考/确认情况', '主分类及解释'], [
        ['H内完成参考，确认受支持', 'reference_supported；另外记录支持延迟。'],
        ['确认先于H内完成参考', 'before_reference；带符号时差，不自动解释为物理错误。'],
        ['H内完成参考，但算法未确认', 'reference_not_confirmed；即使仍有排队图像也保留截至H的漏确认。'],
        ['参考仍建立/接近或未获证实', 'confirmation_reference_pending_at_H或no_confirmation_reference_pending_at_H；不解释为已证实无到达。'],
        ['明确永久卡滞、无参考', '有确认为no_reference_confirmation；无确认为permanent_stall_no_confirmation。'],
        ['未执行', 'unattempted；计划分母不删除。']
    ], [54, 116])
    p('事件、参考、观测的删失分别记录。无事件不计为“含无支持确认”；物理错误推进字段为空。端点分支以可手算测试核验，不要求两个开发seed自然产生全部边界情形。')
    observed=Counter(r['reference_status'] for r in records)
    p('本批R0实际参考状态：'+'；'.join(f'{k}={v}条方法记录' for k,v in sorted(observed.items()))+'。参考仍建立/接近H的分支未在本批自然出现，其正确性来自独立手算回归，不冒充实际发生的仿真结果。')

    lookup = {(int(r['seed']), r['condition'], r['method']): r for r in records}
    labels = {'N':'正常', 'V':'慢速', 'P':'暂停恢复', 'T':'永久卡滞', 'J':'抖动', 'O':'偏移',
              'C':'局部缺失', 'R':'破碎', 'F':'伪目标', 'D':'丢帧', 'L':'延迟乱序', 'TF':'卡滞+伪目标'}
    for seed in seeds:
        page(); p(f'五、开发seed {seed}：全部判定记录', True)
        p('模拟时间单位s。N/V/P/T为运动模型工况；其余为synthetic stress。每种方法读取完全相同的Mask、时钟及任务输入。任何到达判定均不改变当前运动。')
        table(['条件', '参考', 'M1', 'GQ', 'M2', 'M2+S', 'M2+K', 'M3'], [
            [c['id']+' '+labels[c['id']], number(lookup[seed,c['id'],'M1']['reference_confirmed_s'])]+
            [number(lookup[seed,c['id'],m]['decision_s']) for m in METHODS]
            for c in config['conditions']], [37, 19, 19, 19, 19, 19, 19, 19])
        p('主方法的互斥类别计数（12个缓存，不是独立总体准确率）：')
        count_rows = []
        for m in ['M1', 'M2', 'M3']:
            counts = Counter(r['primary_outcome'] for r in records if int(r['seed'])==seed and r['method']==m)
            count_rows.extend([m, name, count] for name, count in sorted(counts.items()))
        table(['方法', '互斥主类别', '缓存数'], count_rows, [25, 120, 25])
        p('参考前确认只是相对于所设距离、速度及驻留标准；本轮没有下一电极切换，不能据此计算实际运输失败或安全收益。完整六方法及全部删失字段见附带CSV。')

    page(); p('六、七参考敏感性：仅评分改变', True)
    p('同一批144条预测在7种独立参考定义下评分，共1008行；不是新增运动或新增独立试验。表内“支持/参考前”均为24缓存上的分类计数，不报告小样本性能区间。')
    ref_rows=[]
    ref_labels={'R0':'R0','R_dist_low':'距离-20%','R_dist_high':'距离+20%',
                'R_speed_low':'速度-20%','R_speed_high':'速度+20%',
                'R_dwell_low':'驻留0.10s','R_dwell_high':'驻留0.20s'}
    for spec in config['reference']['one_factor_sensitivity']:
        rid=spec['id']; values=[]
        for m in ['M1','M2','M3']:
            chosen=[r for r in sensitivity if r['reference_id']==rid and r['method']==m]
            cc=Counter(r['primary_outcome'] for r in chosen)
            values.append(f"{cc['reference_supported']}/{cc['before_reference']}")
        ref_rows.append([ref_labels[rid], str(spec.get('distance_mm', spec.get('radius_mm', ''))),
                         str(spec.get('max_speed_mm_s', '')), str(spec.get('dwell_s', ''))]+values)
    table(['参考', '距离/mm', '速度/mm/s', '驻留/s', 'M1支持/前', 'M2支持/前', 'M3支持/前'], ref_rows, [20, 26, 29, 23, 24, 24, 24])
    changed=[]
    for rid in [s['id'] for s in config['reference']['one_factor_sensitivity'] if s['id']!='R0']:
        n=sum(r['primary_outcome'] != lookup[int(r['seed']),r['condition'],r['method']]['primary_outcome']
              for r in sensitivity if r['reference_id']==rid)
        changed.append([ref_labels[rid],n])
    table(['相对R0的参考', '144条记录中主分类改变数'], changed, [70,100])
    p('参考敏感性用于显示评价标准对结论的影响，不根据上述开发结果挑选最有利参考。原R0及六个单因素参考均完整保留；未到达的任务没有人为指定参考时刻或零延迟。')
    p('七、判据保持不变', True)
    table(['模块', '共同定义'], [
        ['C0/G','完整性与任务因果始终开启；目标电极覆盖率≥0.90、源区液滴残留≤0.08。'],
        ['Q/W','有效单连通且不触ROI边界；至少5帧且跨度≥0.25 s、最大断档0.18 s。在20 fps等间隔下实际至少6帧。'],
        ['S/K','目标距离≤0.576 mm；共同原始有效历史速度上限19.2 mm/s。没有按开发结果调严。'],
        ['方法','M1=C0+G；GQ加Q；M2加Q/W；M2+S、M2+K分别加单门；M3加S/K。']
    ], [27,143])
    page(); p('八、独立审计与回归', True)
    p('独立审计从保存的模拟内部轨迹重建参考，从Mask像素复算特征及共同历史，并核对全部主表与敏感性表。算法执行不读取评分真值；源World/Mask/随机数组及源码摘要保持绑定。')
    p('代码审查关闭三项问题：配置不能替换已审阅的基础hash/TF规则；审计核对全部结果字段及主表与R0的一致性；缓存失败时保留已经由World建立的独立模拟参考，仅将算法标为未执行。均增加先失败后通过的回归测试；旧失败尝试不删除。')
    table(['审计项目','实际结果'], [[k, str(v)] for k,v in audit.items()
          if isinstance(v,(bool,int,float,str)) and k not in ('version','root')], [85,85])
    table(['软件验证','实际结果'], [[k, f"exit={v['exit_code']}"+(f"；{v['tests']}项测试" if v['tests'] is not None else '')]
          for k,v in verification.items()], [60,110])
    log=(verification_dir/'full.txt').read_text(encoding='utf-8')
    p('全量摘要：'+'；'.join(line for line in log.splitlines() if re.match(r'^(Ran |OK|FAILED|FAIL:|ERROR:)',line)))
    p('保护边界：新增接口以独立命名空间实现，旧方法门、形态重放、旧S1/S2/S3及真实控制代码不改。543份既有源码及3493份r3文件内容摘要核验；另核对460份旧源码内容hash及352135项旧资产大小/mtime，后者不是全部内容hash。')
    p('九、阶段结论与下一步', True)
    p('本开发批次最多证明修订协议可以执行、随机源可复现、输入共享与评分分母可审计；不构成正式算法性能优势。持续伪观测、源残留变化及S/K信息重叠等负面结果应继续保留。M3不预设优于M2。')
    p('正式运行仍需审阅本批实际结果及代码审计，补齐正式分层统计汇总与受控执行入口，并经批准后另存正式批次。开发seed不进入正式合池；正式seed没有用于筛选或调参。实验二固定等待与总预算仍属于独立设计任务，本轮没有运行多电极闭环。')
    p('请Chat重点审查：TF持续伪观测是否确实覆盖永久卡滞；10 s未完成参考与永久无到达是否区分；主分类与辅助漏确认是否避免重复独立计数；两开发seed能否支持接口准入而非性能结论；正式统计单位是否仍以配对基础运动/缓存分层而非帧或方法行数计算。')
    p('追溯：完整CSV、开发配置、独立审计、源码与协议快照及来源hash索引随报告保存。原始模拟Mask/World留在结果目录，不复制为新的独立数据。')

    def footer(canvas, doc):
        canvas.setFont('Song',8.5); canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'SIMULATION / DEVELOPMENT | 双seed接口验证，非正式性能统计')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    pdf=output/(TITLE+'.pdf')
    SimpleDocTemplate(str(pdf),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
                      topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    (output/(TITLE+'.md')).write_text('\n'.join(markdown),encoding='utf-8')
    check=[]
    with fitz.open(pdf) as document:
        for i,pdf_page in enumerate(document):
            text=pdf_page.get_text()
            if '\x00' in text or '\ufffd' in text:
                raise ValueError('Missing glyph on page '+str(i+1))
            spans=[span for block in pdf_page.get_text('dict')['blocks'] if 'lines' in block
                   for line in block['lines'] for span in line['spans'] if span['text'].strip()]
            if any(s['bbox'][0]<0 or s['bbox'][1]<0 or s['bbox'][2]>pdf_page.rect.width+1 or s['bbox'][3]>pdf_page.rect.height+1 for s in spans):
                raise ValueError('Text outside page '+str(i+1))
            check.append(dict(page=i+1,spans=len(spans),minimum_font_pt=min(s['size'] for s in spans),missing_glyph=False))
            pdf_page.get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False).save(qa/f'page_{i+1:02d}.png')
    (qa/'text_layout_check.json').write_text(json.dumps(check,indent=2),encoding='utf-8')
    print(json.dumps(dict(pdf=str(pdf),pages=len(check),source_index_entries=len(index)),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data'); parser.add_argument('verification'); parser.add_argument('output')
    args=parser.parse_args(); build(args.data,args.verification,args.output)
