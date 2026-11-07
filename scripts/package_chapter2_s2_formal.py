"""Build an auditable S2 review PDF from completed, persisted outputs only."""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_sim.batch import _write_json
from dmf.chapter2_sim.s2.spec import CONDITIONS,METHODS,MODEL_GENERATED
from dmf.chapter2_sim.s2.study import _rows


def build(package):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
    from pypdf import PdfWriter
    from dmf.chapter2_sim.s2.confirmatory import audit_confirmatory,verify_seal
    from verify_chapter2_s2_formal import protect
    package=Path(package);study=package/'formal';qa=package/'QA'
    audit=audit_confirmatory(study)
    seal=verify_seal(ROOT/'configs/chapter2_s2_confirmatory.yaml',package/'freeze')
    protection=protect(qa/'protection_final.json')
    scores=_rows(study/'step_scores.csv');summary=_rows(study/'statistics/condition_statistics.csv')
    contrasts=_rows(study/'statistics/paired_contrasts.csv');gates=_rows(study/'gate_diagnostics.csv')
    report=json.loads((study/'run_report.json').read_text(encoding='utf-8'))
    lookup={(r['condition'],r['method']):r for r in summary}
    paired={r['condition']:r for r in contrasts if r['baseline']=='BTQ' and r['comparison']=='F_arrival'}
    log=(qa/'full_unittest.txt').read_text(encoding='utf-8',errors='replace')
    count=re.search(r'Ran (\d+) tests in ([0-9.]+)s',log)
    if not count or not re.search(r'^OK',log,re.M):raise ValueError('complete passing unittest log required')
    skipped=int(re.search(r'skipped=(\d+)',log).group(1)) if re.search(r'skipped=(\d+)',log) else 0
    validation=(qa/'closed_loop_validation.txt').read_text(encoding='utf-8')
    if validation.count('PASS')!=7:raise ValueError('seven software-chain passes required')
    version={name:importlib.metadata.version(name) for name in ('numpy','opencv-python','matplotlib','PyYAML','reportlab','pypdf')}
    event_same={}
    for condition in CONDITIONS:
        same=0
        for seed in range(263000,263020):
            def events(method):
                path=study/'predictions'/f'{condition}_{seed}'/method/'prediction_manifest.json'
                return [(e['step_id'],e['target'],e['timestamp_s']) for e in json.loads(path.read_text(encoding='utf-8'))['events']]
            same+=events('BTQ')==events('F_arrival')
        event_same[condition]=same
    pdfmetrics.registerFont(TTFont('CJK','C:/Windows/Fonts/simhei.ttf'))
    pdfmetrics.registerFont(TTFont('Latin','C:/Windows/Fonts/arial.ttf'))
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CBody',fontName='CJK',fontSize=9,leading=14,spaceAfter=7))
    styles.add(ParagraphStyle(name='CTitle',fontName='CJK',fontSize=18,leading=24,textColor=colors.HexColor('#174b70'),spaceAfter=14))
    styles.add(ParagraphStyle(name='CHead',fontName='CJK',fontSize=12,leading=18,textColor=colors.HexColor('#174b70'),spaceBefore=8,spaceAfter=8))
    styles.add(ParagraphStyle(name='SmallC',fontName='CJK',fontSize=7,leading=10,spaceAfter=5))
    story=[];md=[]
    def heading(text):story.append(Paragraph(escape(text),styles['CHead']));md.extend(['','## '+text,''])
    def p(text):story.append(Paragraph(escape(text),styles['CBody']));md.extend([text,''])
    def table(headers,rows,widths):
        data=[[Paragraph(escape(str(c)),styles['SmallC']) for c in headers]]
        data += [[Paragraph(escape(str(c)),styles['SmallC']) for c in row] for row in rows]
        t=Table(data,colWidths=[w*mm for w in widths],repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5eef4')),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#174b70')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),4),
            ('RIGHTPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f7f9')])]))
        story.append(t);story.append(Spacer(1,7))
        md.append('| '+' | '.join(headers)+' |');md.append('| '+' | '.join(['---']*len(headers))+' |')
        md.extend('| '+' | '.join(map(str,r))+' |' for r in rows);md.append('')
    story.append(Paragraph('第二章S2正式仿真与审查报告',styles['CTitle']))
    p('2026-10-25 | SIMULATION | chapter2_s2_single_task_confirmatory_v1')
    heading('1. 验收结论与实际完成量')
    p('G1-G3时序、评分和五方法公平性核验完成；G4原13条件开发验收保留；本轮按用户授权封存并完成G5正式S2及S2-A/S2-B图稿。验收通过仅针对软件完整性与本批条件性仿真证据，不代表F普遍优于BTQ或真实液滴性能已验证。')
    table(['项目','实际结果'],[
        ['G1：任务因果','独立固定教师190→191；任务[0,4)s，唯一模拟Applied=0.04s，response_at=0.22s。非S1旧轨迹重标。'],
        ['G2：独立参考与评分',f"重建{audit['independent_references_recomputed']}份参考，重算{audit['scores_recomputed']}个主评分；完整计划分母。"],
        ['G3：五方法公平性','每缓存六接口同输入、同raw历史；五主方法与BQ辅助分离；强四方法G/Q/W/C0相同。'],
        ['G4：开发测试','既有3开发seed×13条件，195主预测；8机制夹具不参与性能统计；本轮不合池。'],
        ['G5：正式批次',f"40 base world，{report['input_caches']}缓存，{report['primary_prediction_runs']}主预测，{report['diagnostic_prediction_runs']}BQ诊断；每条件20配对seed。"],
        ['正式错误与缺失',f"基础设施错误{report['infrastructure_errors']}；完整逐步、逐帧与事件文件保留。"],
        ['回归与保护',f"全量{count.group(1)}项：{int(count.group(1))-skipped}通过、{skipped}可选跳过；7软件链通过。旧代码/S1/v1/v2/S2开发保护核查通过。"],
    ],[38,137])
    p('旧v2的21份共同缓存中BTQ/F到达目标与时刻全部一致，此事实没有被新批次覆盖或改写。新条件有可辨别输入，但属于新的独立固定任务仿真，不能代替旧结果。')
    story.append(PageBreak());heading('2. 冻结判据、时钟与独立统计单位')
    table(['方法','G/C0','Q','W','S','K'],[
        ['B_single_frame','开','关','关','关','关'],['BTQ','开','开','开','关','关'],
        ['BTQ+S','开','开','开','开','关'],['BTQ+K','开','开','开','关','开'],
        ['F_arrival','开','开','开','开','开'],['BQ_single_frame（辅助）','开','开','关','关','关']],
        [60,23,23,23,23,23])
    p('G：eta_target≥0.85且eta_source≤0.08，分母均为液滴Mask面积。W：至少5帧且曝光跨度≥0.25s，gap≤0.18s、质心跨度≤0.11pitch、覆盖跨度≤0.15。Q：confidence≥0.2、面积10-100000px、恰一显著连通域。S：任务合法且观测质心在目标多边形向外容差0.18pitch内。K：最近两帧C0可解析历史，位移残差容差0.18+6dt；不开新方向门。')
    p('共同数据完整性、旧帧/重复帧/任务屏障与事件一次性消费始终开启。所有时钟均为simulation；没有真实ACK、相机曝光校准或毫米尺度。每缓存80条捕获/缺失记录，Mask缺失不补值。原点运动与SyntheticCamera代码未改。')
    p('参考只读内部模拟位置/速度：目标半径0.09pitch、速度≤0.06pitch/s、驻留0.15s完成的网格区间[l,u]。算法不读取真值。c<l提前；l≤c<u不确定；c≥u有支持；c≤u+1s属于主支持，之后晚支持单列。早报消耗唯一事件后仍可计漏确认；无参考事件与提前互斥。')
    p('主支持产出S_H以独立参考数R为分母；提前/无参考确认以完整计划步为分母。R=0标NA。所有Unknown、未尝试、缺失、失败和删失保留。S2不报告路径完成率、Retry或Recovery效果，也不声称验证五状态准确率。')
    p('独立统计单位是每条件内20个配对seed，不是帧数、1300次算法调用或跨条件260个独立世界。40个base world在条件间复用；不合池总体准确率。二元率Wilson95%；配对差2000次seed重采样95%区间；延迟只比较双H内支持的相同参考对，报告支持n和排除n。没有显著性星号或样本量适应。')
    p('B→BTQ同时变化Q/W，不能单独归因W；BQ→BTQ用于匹配Q后诊断W，B→BQ用于诊断Q。辅助诊断有独立目录和统计表。')
    story.append(PageBreak());heading('3. 正式五方法逐条件结果')
    p('每单元依次为 S/P/U/M：H内支持、确定提前、无参考确认、完整H漏确认。P和M可同时发生，不能相加当互斥类别。每方法每条件计划20步；M标签为model-generated，X为synthetic stress。R按条件列出，R=0召回NA。')
    matrix=[]
    for condition in CONDITIONS:
        r=lookup[condition,'BTQ'];label=('M ' if condition in MODEL_GENERATED else 'X ')+condition
        cells=[]
        for method in METHODS:
            v=lookup[condition,method]
            cells.append('/'.join(v[k] for k in ('supported_confirmations','premature_confirmations','unsupported_confirmations','missed_supported_confirmation')))
        matrix.append([label,str(r['reference_arrivals'])]+cells)
    table(['条件','R','B','BTQ','+S','+K','F'],matrix,[47,8,24,24,24,24,24])
    extra=('late_supported_confirmations','timing_uncertain_confirmations','confirmation_right_censored',
           'reference_right_censored','unattempted_steps','infrastructure_unknown')
    p('全主方法记录的附加计数（含方法重复，非独立n）：'+ '；'.join(f'{k}={sum(int(r[k]) for r in scores)}' for k in extra)+'。逐条件/逐方法明细与Wilson区间见condition_statistics.csv。')
    p('D_tail_true_cost不隔离S额外拒绝本可正确确认的代价：静态异常观测在内部世界真正到达前已存在，BTQ先提前确认。这一局限保留，不根据新结果重做条件。持续伪Mask和高置信紧凑伪目标同样保留，不把K可触发理解为可持续识别所有错误观测。')
    story.append(PageBreak());heading('4. BTQ/F配对与科学归因')
    pairrows=[]
    def fmt(x):return 'NA' if x in ('',None) else f'{float(x):.3f}'
    for condition in CONDITIONS:
        r=paired[condition]
        pairrows.append([condition,f"{event_same[condition]}/20",
            fmt(r['support_difference']),fmt(r['premature_difference']),fmt(r['unsupported_difference']),
            str(r['dual_supported_n']),fmt(r['latency_difference_s'])])
    table(['条件','事件/时间同','Δ支持','Δ提前','Δ无支持','双支持n','Δ延迟s'],pairrows,[47,24,20,20,24,20,20])
    p('Δ均为F-BTQ。前3项是配对二元率差，延迟为双H支持子集的(c-u)差。完整2000次bootstrap区间与S/K单独增量在paired_contrasts.csv。相同事件并不等于算法一般等效；零差区间不证明物理风险为零。')
    for c in ('A_normal','C_jump_short','C_jump_persistent','D_tail_false','E_highconf_false','F_jitter','F_dropout'):
        a,b=lookup[c,'BTQ'],lookup[c,'F_arrival']
        p(f"{c}：BTQ/F H支持={a['supported_confirmations']}/{b['supported_confirmations']}（R={a['reference_arrivals']}）；提前={a['premature_confirmations']}/{b['premature_confirmations']}；无参考确认={a['unsupported_confirmations']}/{b['unsupported_confirmations']}；漏确认={a['missed_supported_confirmation']}/{b['missed_supported_confirmation']}；事件及时间一致{event_same[c]}/20。")
    for condition in ('C_jump_short','D_tail_false'):
        r=paired[condition]
        p(f"{condition}：F-BTQ无参考确认率差={float(r['unsupported_difference']):.3f}，配对bootstrap95%区间[{float(r['unsupported_difference_lo']):.3f}, {float(r['unsupported_difference_hi']):.3f}]。这只是固定输入压力分布下的效应；全seed均相同的退化区间不代表物理零风险。")
    p('F-BTQ在所有有参考条件中的H内支持率差均为0；正常20/20、jitter 0/20、dropout 5/20、gap 20/20。jitter两者各有2次晚支持与18次无预测；dropout各有10次晚支持与5次无预测。因此20次及15次主漏确认并不等于全部永远无事件，晚于H的事件不能补回主成功数。')
    p('剩余短跳变误确认：C_jump_short_263016/F_arrival在1.161926817s确认；frame16无Mask，frame17的帧号缺口使ObservationPipeline清空K历史。新历史首帧K默认通过，随后曝光证据[0.858,1.108]s达到0.25s。这表明K在缺帧后的历史重建有可辨识性边界；本轮仅报告，不修改冻结判据。')
    case_path=study/'predictions/C_jump_short_263016/F_arrival/gate_trace.csv'
    case=[]
    for r in _rows(case_path):
        if 15<=int(r['frame_id'])<=22:
            raw=json.loads(r['raw']) if r.get('raw') else {}
            case.append(dict(frame_id=r['frame_id'],processing_s=r['processing_s'],C0=r['C0_passed'],reason=r['C0_reason'],
                K=raw.get('K'),velocity=raw.get('velocity_pitch_s'),window_count=r['window_count'],
                window_start_s=r['window_start_s'],window_end_s=r['window_end_s'],confirmed=r['confirmed']))
    _write_json(qa/'remaining_jump_false_confirmation.json',dict(cache_id='C_jump_short_263016',method='F_arrival',
        source=str(case_path),source_sha256=hashlib.sha256(case_path.read_bytes()).hexdigest(),rows=case,
        interpretation='missing capture identity clears K history; first parsable observation has no history constraint'))
    aux=_rows(study/'diagnostic_scores.csv')
    bq_flash=sum(int(r['unsupported_confirmations']) for r in aux if r['condition']=='B_flash_short')
    bq_low=sum(int(r['unsupported_confirmations']) for r in aux if r['condition']=='E_lowconf_false')
    p(f'辅助归因：B_flash_short中BQ有{bq_flash}/20次无参考确认，BTQ为0/20，支持此人工短闪变条件下W的独立阻断作用；E_lowconf_false中BQ为{bq_low}/20，B为20/20，支持人为置信度门的机制作用。不将这些压力结果外推为真实U-Net误差鲁棒性。')
    story.append(PageBreak());heading('5. 审查发现、修复与剩余风险')
    table(['核查项','修复/边界'],[
        ['正式seed隔离','开发入口仍拒绝263000；正式严格263000-263019；不修改旧开发契约。'],
        ['完整计划审计','精确冻结13×20×5身份多重集；丢一个全方法共同seed也不能生成正式统计。BQ另验完整260行。'],
        ['原始历史完整性','新增raw历史篡改回归：审计逐缓存核验六接口原始特征hash一致，不仅相信运行报告。'],
        ['封存计数与渲染','freeze中实际seed数0、计划20；run_report记实际20。科学源seal与独立渲染源区分，完整初始源码仍归档。'],
        ['算法贡献边界','仅受控条件到达事件证据。不能从D碎片压力推出真实形变鲁棒性，不能从K触发帧数推出统计收益。'],
        ['未完成问题','S/K额外误拒代价仍需辨别条件；真实误差分布、真实人工到达标注、U-Net泛化和实物视觉闭环尚缺。'],
        ['不利结果','jitter、dropout、持续假观测、低置信真到达和高置信假目标全部保留。无seed筛选，无正式结果后调参。'],
    ],[38,137])
    p('审查结论：可锁定本批正式S2作为限定条件下的算法到达判定对照，不作普遍性能优势结论；不自动进入S3或新的正式扫描。若追加更真实误差或误拒代价研究，先独立定义输入与负对照，再版本化运行，不回改本批。')
    heading('6. 交付位置与复现入口')
    p('本包：freeze为配置与执行源码，formal/inputs为共同Mask缓存，scoring_side为算法不可见真值/参考，predictions为五主方法，diagnostics为BQ，statistics为65行主汇总与39组主配对/26组辅助对照；figures为S2-A/S2-B矢量及600dpi图，QA为测试和检查日志。')
    p('本轮代码仅修改s2/spec.py、s2/study.py、s2/plotting.py；新增s2/confirmatory.py、s2/statistics.py、正式YAML、两份测试及三份绘图/核查/打包脚本和规格记录。生产控制/运动模型/评分核心不改。没有Commit或Push。')
    for command in [
        'python -m dmf.chapter2_sim.s2.confirmatory freeze --output <NEW>/freeze',
        'python -m dmf.chapter2_sim.s2.confirmatory run --seal <NEW>/freeze --output <NEW>/formal',
        'python -m dmf.chapter2_sim.s2.confirmatory audit --output <NEW>/formal',
        'python -m dmf.chapter2_sim.s2.confirmatory analyse --output <NEW>/formal',
        'python -m dmf.chapter2_sim.s2.plotting --study <NEW>/formal --cache A_normal_263000 --output <NEW>/S2-A',
        'python scripts/chapter2_s2_formal_figures.py --study <NEW>/formal --output <NEW>/S2-B']:
        story.append(Paragraph(escape(command),styles['SmallC']));md.extend(['```powershell',command,'```'])
    p('复现须用全新空目录；所有默认配置与seal必须匹配。代码HEAD='+seal['git_head']+'，执行基线为dirty工作区，不以HEAD假称包含未提交改造。封存hash='+seal['seal_sha256']+'。运行环境：Python '+sys.version.split()[0]+'；'+json.dumps(version,ensure_ascii=False)+'。')
    story.append(PageBreak());heading('7. 图注与阅读说明')
    p('S2-A：预先指定正常条件A_normal_263000，单缓存n=1机制示例。共同Mask覆盖、原始G/Q/S/K、连续曝光证据和五方法事件均取自该缓存。横轴为模拟可用/决策时间；金带是独立驻留完成参考，虚线为H截止。相同事件不加人工横移。与S1不同trial，不沿用S1的1.46/1.92s。')
    p('S2-B：全部13条件、每条件20配对seed。面板a列H内支持/参考与漏确认数；b列提前和无参考事件；c列F-BTQ配对率差与95%区间；d仅双H支持参考的配对延迟差和支持n。灰格R=0为NA。描述计数面板不画边际误差条，Wilson区间完整保存于源表；配对效应区间2000次重采样。')
    p('两图全部SIMULATION；420模板、pitch单位、简化二维点运动和模拟Mask，不是Gerber实物配准、CFD、电润湿动力学或真实U-Net分割结果。后附图为同源矢量PDF，未截图替代原始数据。')
    body=package/'审查报告正文.pdf';final=package/'第二章S2_G1-G5完成与正式结果审查报告.pdf'
    if final.exists():raise FileExistsError(final)
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('CJK',7);canvas.setFillColor(colors.HexColor('#5b6b76'))
        canvas.drawString(18*mm,12*mm,'SIMULATION | S2正式仿真审查 | 2026-10-25')
        canvas.drawRightString(192*mm,12*mm,str(doc.page));canvas.restoreState()
    SimpleDocTemplate(str(body),pagesize=A4,rightMargin=17*mm,leftMargin=18*mm,
        topMargin=18*mm,bottomMargin=20*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    figure_pdfs=[next((package/'figures/S2-A').glob('S2-A_*.pdf')),next((package/'figures/S2-B_r2').glob('S2-B_*.pdf'))]
    writer=PdfWriter();writer.append(body)
    for path in figure_pdfs:writer.append(path)
    with final.open('wb') as handle:writer.write(handle)
    (package/'第二章S2_G1-G5完成与正式结果审查报告.md').write_text('\n'.join(md),encoding='utf-8')
    with zipfile.ZipFile(package/'交付源码与复现说明.zip','w',zipfile.ZIP_DEFLATED) as archive:
        selected=list((ROOT/'dmf/chapter2_sim/s2').glob('*.py'))+list((ROOT/'tests').glob('test_chapter2_s2*.py'))
        selected += [ROOT/'configs/chapter2_s2_arrival.yaml',ROOT/'configs/chapter2_s2_confirmatory.yaml',ROOT/'run_chapter2_s2.py']
        selected += [ROOT/'scripts'/name for name in ('chapter2_s2_formal_figures.py','verify_chapter2_s2_formal.py','package_chapter2_s2_formal.py')]
        selected += [ROOT/'docs/superpowers/specs/2026-10-25-chapter2-s2-confirmatory-design.md',ROOT/'docs/superpowers/plans/2026-10-25-chapter2-s2-confirmatory-execution.md']
        for path in selected:archive.write(path,str(path.relative_to(ROOT)))
    result=dict(pdf=str(final),body_pdf=str(body),event_identical=event_same,integrity=audit,
        tests=int(count.group(1)),skipped=skipped,test_seconds=float(count.group(2)),
        protection_passed=protection['all_protected_unchanged'],runtime=version,
        figure_pdf_sources=[str(p) for p in figure_pdfs],report_sha256=hashlib.sha256(final.read_bytes()).hexdigest())
    _write_json(package/'delivery_manifest.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True)
    print(json.dumps(build(parser.parse_args().package),ensure_ascii=False))
