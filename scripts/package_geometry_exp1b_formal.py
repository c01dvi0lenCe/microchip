"""Package actual formal results, provenance and paper figures for external review."""
import argparse
import csv
from collections import Counter
import hashlib
import json
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
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak

ROOT=Path(__file__).resolve().parents[1]
TITLE='实验一B_正式随机配对仿真与统计验收_Chat审查报告'
FIGNAMES=['Exp1B_formal_1_reference_categories','Exp1B_formal_2_reliability_and_time','Exp1B_formal_3_ablation_and_reference']
CONDITIONS=['N','V','P','T','J','O','C','R','F','D','L','TF']
LABELS=dict(N='正常',V='慢速',P='暂停',T='卡滞',J='抖动',O='偏移',C='缺失',R='破碎',F='伪目标',D='丢帧',L='延迟',TF='卡滞伪目标')


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()
def one(rows,**keys):
    selected=[r for r in rows if all(str(r[k])==str(v) for k,v in keys.items())]
    if len(selected)!=1:raise ValueError('Statistical row identity mismatch: '+str(keys))
    return selected[0]
def pp(row):
    est=row['estimate']
    if est in ('',None):return 'NA'
    lo,hi=row['ci_lower'],row['ci_upper']
    if lo in ('',None):return f"{float(est)*100:.1f} [识别界{float(row['ident_lower'])*100:.1f},{float(row['ident_upper'])*100:.1f}]"
    return f'{float(est)*100:.1f} [{float(lo)*100:.1f},{float(hi)*100:.1f}]'


def build(data,figures,verification,output):
    data,figures,verification,output=map(lambda p:Path(p).resolve(),(data,figures,verification,output))
    if output.exists():raise FileExistsError('Keep prior reports: '+str(output))
    audit=load(data/'independent_audit.json');checks=load(verification/'verification.json')
    qa=load(figures/'QA/figure_checks.json')
    if not audit['passed'] or len(checks)!=7 or any(r['exit_code'] for r in checks.values()):
        raise ValueError('Passing raw-data audit and seven regression stages required')
    if len(qa)!=3 or any(r['text_exit'] or r['collision_exit'] or r['alignment_exit'] for r in qa):
        raise ValueError('Final figure QA incomplete')
    primary=read(data/'planned_method_results.csv');sensitivity=read(data/'reference_sensitivity_results.csv')
    if len(primary)!=1440 or len(sensitivity)!=10080:raise ValueError('Preserve entire formal plan')
    rates=read(data/'statistics_rates.csv');paired=read(data/'paired_binary.csv');paired_times=read(data/'paired_latency.csv')
    config=load(data/'effective_config.json');manifest=load(data/'manifest.json');frozen=load(data/'provenance/freeze.json')
    failures=load(data/'failures.json');outcome=Counter(r['primary_outcome'] for r in primary)
    output.mkdir(parents=True);outqa=output/'QA';outqa.mkdir()
    index=[]
    def record(path,role,digest=None,snapshot=None):
        path=Path(path).resolve();actual=sha(path)
        if digest is not None and actual!=digest:raise ValueError('Changed source: '+str(path))
        item=dict(role=role,path=str(path),sha256=actual,snapshot_path='')
        if snapshot:
            dest=output/snapshot;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            if sha(dest)!=actual:raise ValueError('Snapshot differs')
            item['snapshot_path']=str(dest)
        index.append(item)
    for relative,digest in manifest['artifacts'].items():record(data/relative,'formal raw artifact',digest)
    for path,digest in manifest['source_code'].items():record(path,'frozen implementation/input',digest)
    for name in ['manifest.json','independent_audit.json','planned_method_results.csv','reference_sensitivity_results.csv',
        'statistics_rates.csv','paired_binary.csv','latency_summary.csv','paired_latency.csv','outcomes_counts.csv','statistics_summary.json','failures.json']:
        record(data/name,'formal tables and audit',snapshot=Path('数据与审计')/name)
    for path in sorted(verification.glob('*')):
        if path.is_file():record(path,'regression evidence',snapshot=Path('QA/软件回归')/path.name)
    for path in sorted(figures.rglob('*')):
        if path.is_file():record(path,'paper figure and QA',snapshot=Path('图稿')/path.relative_to(figures))
    for relative in ['scripts/plot_geometry_exp1b_formal.py','scripts/package_geometry_exp1b_formal.py',
        'docs/chapter2-geometry-exp1b-formal-figure-contract-2026-10-30.md',
        'docs/superpowers/plans/2026-10-29-exp1b-formal-statistics-and-run.md']:
        record(ROOT/relative,'analysis and figure contract',snapshot=Path('源码与协议')/relative)
    record(data/'provenance/freeze.json','pre-run freeze',snapshot=Path('协议冻结/freeze.json'))
    for item in frozen['snapshots']:
        source=data/'provenance'/item['relative']
        record(source,'immutable implementation snapshot',item['sha256'],snapshot=Path('协议冻结')/item['relative'])
    with (output/'来源与hash索引.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['role','path','sha256','snapshot_path']);writer.writeheader();writer.writerows(index)

    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=7,wordWrap='CJK')
    head=ParagraphStyle('head',parent=body,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),spaceAfter=10,keepWithNext=True)
    cell=ParagraphStyle('cell',parent=body,fontSize=9.2,leading=14,spaceAfter=0)
    story=[];markdown=[]
    def p(text,h=False):story.append(Paragraph(escape(str(text)),head if h else body));markdown.append(str(text)+'\n')
    def page():story.append(PageBreak());markdown.append('\n---\n')
    def table(headers,items,widths):
        values=[[Paragraph(escape(str(c)),cell) for c in row] for row in [headers]+items]
        t=Table(values,colWidths=[w*mm for w in widths],repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.4,colors.grey),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
        story.extend([t,Spacer(1,8)]);markdown.extend(['| '+' | '.join(headers)+' |\n','| '+' | '.join(['---']*len(headers))+' |\n'])
        markdown.extend('| '+' | '.join(map(str,row))+' |\n' for row in items)

    p('实验一B：正式随机配对仿真与统计验收',True)
    p('2026-10-30 | SIMULATION | 探索性算法比较，非实物实验')
    p('一、执行范围与实际分母',True)
    table(['项目','实际结果及统计单位'],[
        ['运行身份','正式seed266000–266019，原定20个全部保留；没有开发seed混入或按结果筛选。固定随机熵20261029不随实际运行日期改变。'],
        ['运动与观测',f"计划80个World、240缓存；实际{audit['actual_base_worlds']}个World、{audit['actual_caches']}缓存，审计{audit['checked_masks']}张实际生成的模拟Mask。"],
        ['方法与参考',f"1440条六方法R0记录、10080条七参考评分。执行{sum(r['status']=='executed' for r in primary)}条、未执行{sum(r['status']!='executed' for r in primary)}条；失败记录{len(failures)}项，全部保分母。"],
        ['独立性','20个配对seed；每seed四个World共享原始运动抽样，不视为80个完全独立物理重复。多个视觉缓存共用World，方法及参考重评分均不是独立重复。'],
        ['控制边界','本实验只有190→191单步教师轨迹；方法读取共同Mask，不改变轨迹，不开启192。未评价实际下一电极错误推进或运输成功率。'],
        ['不变内容','真实设计地图、3.2 mm节距、4 mm面积等效轮廓、0.8 mm高度记录、430轮廓库及全部C0/G/Q/W/S/K门限不改。']
    ],[31,139])
    m2={(r['seed'],r['condition']):r for r in primary if r['method']=='M2'}
    m3={(r['seed'],r['condition']):r for r in primary if r['method']=='M3'}
    same=sum(m2[k]['primary_outcome']==m3[k]['primary_outcome'] for k in m2)
    changed=sum(m2[k]['decision_s']!=m3[k]['decision_s'] for k in m2)
    p(f'实际结果概览：M2与M3在{same}/240缓存中的R0主类别相同，{changed}个缓存确认时刻不同。该结果按实际数据报告，不以M3必须胜出作为验收条件。')
    p('所有新增运动与视觉扰动是预声明的模拟分布或synthetic stress，不代表真实现场发生概率。形态源于同次视频的经验轮廓，尚无跨批次形态验证；这不是CFD、U-Net真实分割或高压实物闭环。')
    page();p('二、运行前冻结与统计验收',True)
    env=frozen['environment'];scan=frozen['prior_seed_scan']
    table(['冻结项','证据'],[
        ['配置与源码',f"运行前冻结{len(frozen['source_hashes'])}项源码/输入内容摘要、完整计划身份及环境，原始快照随包保存；正式执行前再次核对。"],
        ['种子未使用检查',f"运行前检查既有结果目录中的实际CSV种子字段及运行/抽样manifest，共{len(scan['files'])}份候选文件；发现既用正式seed={scan['used_formal_seeds']}。范围外未知历史不作无依据保证。"],
        ['环境',f"Python {env['python'].split()[0]}；NumPy {env['numpy']}；OpenCV {env['opencv']}；Shapely {env['shapely']}；{env['platform']}。"],
        ['一次运行','全局独占批次登记及冻结目录局部声明；正式入口不允许换seed、子集试跑、覆盖目录或静默替换批次。'],
        ['随机源','PCG64整数SeedSequence；20个共享运动流及240组观测流，原始数组、前后状态及hash先持久化，再执行六方法。'],
        ['审查关闭','锁跨目录唯一批次；逐观测身份/时间绑定独立递交；进度及TF卡滞时刻独立推导核验。手算及篡改测试通过后才运行。']
    ],[31,139])
    gates=config['shared_gates']
    p('六方法定义：M1=C0+G；GQ=C0+G+Q；M2=C0+G+Q+W；M2_S/M2_K分别只在M2上加入S/K；M3同时加入S/K。各方法共用原始观测历史和任务因果，不将方法拒绝的观测从其他方法的原始历史删除。')
    p(f"共同门限：目标电极覆盖率≥{gates['rho_target_min']}（分母为电极面积），源区残留≤{gates['eta_source_max']}（分母为Mask面积）；W至少{gates['W_min_frames']}帧且跨度≥{gates['W_min_span_s']} s、最大间隔{gates['W_max_gap_s']} s；20 fps下满足跨度需要至少6帧。S距离≤{gates['S_target_distance_max_mm']} mm；K原始历史速度≤{gates['K_raw_history_speed_max_mm_s']} mm/s。Q为单连通且不接触ROI边界，不是经过实测校准的置信度。")
    table(['分析','冻结规则'],[
        ['单层比例','base n=20、低/高各n=10，CP双侧95%区间；0%与100%仍报告完整区间。'],
        ['压力总体','低/高等权0.5；各层97.5%CP界加权形成保守95%范围，不将两层合成普通n=20二项区间。'],
        ['配对比例差','同seed不一致对p_plus/p_minus；每层每格alpha=.05/(2×层数)，差界加权；完全一致仍保非零不确定界。'],
        ['未执行/未知','保留计划N、已知k/N及识别范围[k/N,(k+u)/N]；暂停普通CI，不以完整病例替代全计划。'],
        ['时间','带符号时差与非负支持延迟分开；支持子集及双方同时支持子集另报n。至少5对才给10000次配对bootstrap区间，分析seed930100。压力混合延迟仅作描述。'],
        ['统计主张','逐工况探索性区间，无总体准确率、显著性星号或实物普遍优势。七参考只重评分同一预测。']
    ],[31,139])
    p('手算验收例（仅统计夹具，不是新增仿真样本）：')
    table(['夹具','应有结果'],[
        ['0/5、5/5',f"CP95%界分别为[0,{1-.025**.2:.9f}]与[{.025**.2:.9f},1]。"],
        ['低10/10、高0/10',f"等权点估计0.5；由两层CP97.5%界组合得到[{.5*.0125**.1:.9f},{1-.5*.0125**.1:.9f}]，不套混合二项假设。"],
        ['20配对完全一致',f"两个不一致格均0仍有区间[-{1-.0125**.05:.9f},+{1-.0125**.05:.9f}]，不是证明等价。"],
        ['1已知成功+1未执行','计划N=2、k/N=0.5、识别范围[0.5,1]，普通CI关闭；n_joint=4不给条件时差区间。']
    ],[40,130])
    page();p('三、全部12家族的R0主结果',True)
    p('每格依次为“参考支持 / 参考前 / 明确无参考确认”的缓存数，计划分母均20。T未到达且未确认单独保留，不将0/0/0误读为未执行；TF无参考却确认属于负对照结果。')
    items=[]
    for cid in CONDITIONS:
        values=[]
        for method in ['M1','M2','M3']:
            chosen=[r for r in primary if r['condition']==cid and r['method']==method]
            cc=Counter(r['primary_outcome'] for r in chosen)
            values.append(f"{cc['reference_supported']} / {cc['before_reference']} / {cc['no_reference_confirmation']}")
        items.append([cid+' '+LABELS[cid],20]+values)
    table(['条件','计划n','M1 支/前/无','M2 支/前/无','M3 支/前/无'],items,[32,18,40,40,40])
    p('全方法互斥主类别计数（仅完整性核对，不作为合池性能率）：'+'；'.join(f'{k}={v}' for k,v in sorted(outcome.items()))+'。全部10类的零计数也保留在附表。')
    tf=[r for r in primary if r['condition']=='TF']
    p('TF实际R0类别：'+'；'.join(f"{method}:"+', '.join(f'{k}={v}' for k,v in sorted(Counter(r['primary_outcome'] for r in tf if r['method']==method).items())) for method in ['M1','M2','M3'])+'。')
    p('参考前确认只是早于所设内部距离、速度与驻留标准，不等同实物危险推进。算法无事件或无到达参考时，时间不填0；删失及未执行保留原字段。实际液滴安全切换的对应关系留给后续闭环与实物验证。')
    p('本批中，正常与暂停条件的M2/M3仍全部早于R0，慢速条件则全部获得R0支持。这说明连续窗口与运动/参考时间尺度存在相互作用，不能把较晚确认直接解释为识别能力普遍提高。破碎、丢帧和延迟条件中的支持增加也包含观测受损带来的等待，须结合时间图和完整逐帧记录解读。Q与W的独立增量分别由GQ-M1、M2-GQ对照，而不将M2-M1全部归因于W。')
    page();p('四、主方法配对差与不确定性',True)
    p('数值为百分点及95%区间，负的参考前差表示该模拟参考下减少参考前确认；正的支持差表示支持产出增加。压力行使用两层等权保守区间。不是低强度与高强度间的配对。')
    items=[]
    for cid in CONDITIONS:
        st='base' if cid in ('N','V','P','T') else 'mixture';v=[]
        for contrast in ['M2_minus_M1','M3_minus_M2']:
            for endpoint in ['before_reference_per_planned','reference_supported_per_planned']:
                v.append(pp(one(paired,reference_id='R0',condition=cid,stratum=st,contrast=contrast,endpoint=endpoint)))
        items.append([cid]+v)
    table(['条件','M2-M1 参考前差','M2-M1 支持差','M3-M2 参考前差','M3-M2 支持差'],items,[16,38.5,38.5,38.5,38.5])
    p('即使某差值为0，也不能解释为已经证明等价。区间为逐比较探索性描述，不对所有条件/模块同时作确认性显著结论；低/高层与全部六方法的完整数值均在附带CSV。')
    p('共同参考支持子集的时间比较（图2b）：')
    items=[]
    for cid in ['N','V','P']:
        for contrast in ['M2_minus_M1','M3_minus_M2']:
            r=one(paired_times,reference_id='R0',condition=cid,stratum='base',contrast=contrast)
            interval='NA' if r['ci_lower']=='' else f"[{float(r['ci_lower']):.3f},{float(r['ci_upper']):.3f}]"
            median='NA' if r['median_difference_s']=='' else f"{float(r['median_difference_s']):.3f}"
            items.append([LABELS[cid],contrast.replace('_minus_','-'),r['n_joint'],median,interval])
    table(['条件','配对','n_joint','中位时差/s','95%区间/s'],items,[29,37,25,34,45])
    p('n_joint为两方法在同一seed都得到参考支持的例数。小于5不计算区间；无共同支持不赋0。各方法支持率及其单独支持延迟仍保留，不能用较少共同样本的条件时差代表全计划效率。')
    page();p('五、参考敏感性与失效边界',True)
    refs=config['reference']['one_factor_sensitivity'];ref_labels={'R0':'R0','R_dist_low':'距离-20%','R_dist_high':'距离+20%',
        'R_speed_low':'速度-20%','R_speed_high':'速度+20%','R_dwell_low':'驻留0.10s','R_dwell_high':'驻留0.20s'}
    selected=[('N','base'),('V','base'),('F','high'),('D','high'),('TF','high')]
    table(['参考']+[LABELS[c]+('·高' if st=='high' else '') for c,st in selected],[
        [ref_labels[s['id']]]+[str(one(rates,reference_id=s['id'],condition=cid,stratum=st,method='M2',endpoint='reference_supported_per_planned')['k'])+'/'+str(one(rates,reference_id=s['id'],condition=cid,stratum=st,method='M2',endpoint='reference_supported_per_planned')['n_planned']) for cid,st in selected]
        for s in refs],[30,28,28,28,28,28])
    p('上表是每个条件在同一预测下的支持产出，不是跨条件合池或七次独立实验。其余条件、M1/M3/消融及完整区间全部保留，不依据敏感性结果修改R0、W或K。')
    p('当前研究边界：Q只检查连通与ROI，不能识别所有外观完整但位置错误的Mask；W抑制短暂异常但不能保证持续一致误观测为真；S与覆盖门可能信息重叠；K会在首跳后接纳持续错误位置历史。正式结果不用于为了M3胜出而再调阈值或新增有利工况。')
    p('六、三张图的阅读说明',True)
    p('图1：全部20条件/强度行的参考前、无参考与支持比例；M1/M2/M3共享输入。每base n=20、每压力层n=10；误差棒CP95%。未知时展示识别范围。0/100%的点与区间完整保留。')
    p('图2：(a)正常/慢速/暂停逐seed带符号时差与中位数，不把负值称负延迟；(b)同seed双方都参考支持的配对确认时差与中位bootstrap区间，NA表示无共同支持；(c)(d)两主对照的配对比例差。n_joint见前表，时间子集不是全计划控制时间。')
    p('图3：(a)Q/W消融、(b)S/K增量的配对支持差与保守95%区间；(c)(d)运行前固定六条件的同预测参考敏感性描述矩阵。矩阵不逐格叠加CI，完整区间另表；无独立重复或真实泛化主张。')
    page();p('七、独立审计、软件回归与可复现性',True)
    table(['核查','实际结果'],[
        ['原始数据',f"{audit['checked_masks']}张Mask、{audit['checked_method_frame_rows']}条方法逐帧记录；独立复算运动、注入、时间递交、空间特征、原始历史、窗口、事件、七参考及完整评分。"],
        ['统计',f"独立统计复算标志={audit['independent_statistics_recalculation']}；验证逐条件分母、配对不一致格、缺失界、条件延迟及参考敏感性。"],
        ['来源',f"{len(index)}条来源hash索引；运行前源码/输入快照、原始数组、World、Mask、递交与预测保留。"],
        ['旧成果','旧源码561项、r3和双seed开发8787项内容摘要保护；另保留旧S1/S2/S3的大小/mtime保护及旧源码内容核验。未覆盖历史数据。']
    ],[31,139])
    table(['验证阶段','结果'],[[k,f"exit={v['exit_code']}"+(f"；{v['tests']}项" if v['tests'] is not None else '')] for k,v in checks.items()],[62,108])
    full=(verification/'full.txt').read_text(encoding='utf-8')
    p('全量摘要：'+'；'.join(line for line in full.splitlines() if re.match(r'^(Ran |OK|FAILED|FAIL:|ERROR:)',line)))
    p('八、收尾与后续',True)
    p('本轮完成既定探索性批次和三图，不自动增加seed、形态库、门或压力工况。所有算法结论限于所设模拟分布和独立参考定义；不宣称真实液滴识别准确率、真实闭环可靠性或完整方法普遍优势。')
    p('实验二将使用已核验设计邻接的190→191→192→172，让算法确认真正改变下一电极Applied及后续运动；固定等待及总预算需单独验收。本轮没有运行多电极闭环或高压实物实验。')
    p('请Chat重点复核：统计分母与配对单位；低/高等权区间与未知处理；参考敏感性是否改变结论；S/K增量与代价；持续伪观测、丢帧及无到达的负面结果是否充分呈现；是否可以结束实验一B并转入实验二。')

    def footer(canvas,doc):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'SIMULATION | 正式探索性配对比较，非实物性能')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    bodypdf=outqa/'正文.pdf'
    SimpleDocTemplate(str(bodypdf),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    document=fitz.open(bodypdf);bodypages=len(document)
    for name in FIGNAMES:
        with fitz.open(figures/(name+'.pdf')) as fig:document.insert_pdf(fig)
    pdf=output/(TITLE+'.pdf');document.save(pdf);document.close()
    (output/(TITLE+'.md')).write_text('\n'.join(markdown),encoding='utf-8')
    layout=[]
    with fitz.open(pdf) as document:
        for i,pdfpage in enumerate(document):
            text=pdfpage.get_text()
            if '\x00' in text or '\ufffd' in text:raise ValueError('Missing PDF glyph')
            spans=[s for block in pdfpage.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for s in line['spans'] if s['text'].strip()]
            if any(s['bbox'][0]<-1 or s['bbox'][1]<-1 or s['bbox'][2]>pdfpage.rect.width+1 or s['bbox'][3]>pdfpage.rect.height+1 for s in spans):raise ValueError('Text outside page')
            layout.append(dict(page=i+1,min_font_pt=min(s['size'] for s in spans),missing_glyph=False))
            pdfpage.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False).save(outqa/f'page_{i+1:02d}.png')
    (outqa/'text_layout_check.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
    print(json.dumps(dict(pdf=str(pdf),body_pages=bodypages,pages=len(layout),source_index_entries=len(index)),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('data','figures','verification','output'):p.add_argument(name)
    a=p.parse_args();build(a.data,a.figures,a.verification,a.output)
