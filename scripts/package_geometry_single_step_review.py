"""Build an evidence-bound review PDF from saved data, never run a trial."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from xml.sax.saxutils import escape

import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.audit import audit_trial

CH = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
TRIAL = CH/'仿真结果/2026-10-28_实验一_真实几何4mm到达识别_v1'
SPEED = CH/'真实分割研究/2026-10-28_视频时间与迁移速度核查_v1'
OUT = CH/'审查材料/2026-10-28_实验一审查报告_v1'
TITLE = '实验一_真实几何单液滴到达识别仿真_审查报告'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def js(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def build():
    OUT.mkdir(parents=True,exist_ok=False)
    qa=OUT/'QA';qa.mkdir()
    audit=audit_trial(TRIAL/'trial')
    if not audit['passed']:
        raise ValueError(audit)
    m=js(TRIAL/'trial/manifest.json');s=m['summary'];cfg=m['config']
    speed=js(SPEED/'manifest.json')
    analysis=js(SPEED/'analysis_r2_same_metric/analysis_manifest.json')
    proposal=analysis['proposed_configuration']
    figure_index=js(TRIAL/'final_figure_index.json')
    checked=[]
    def verify_file(path,digest,role):
        actual=sha(path)
        if actual!=digest:
            raise ValueError(f'hash mismatch {path}')
        checked.append(dict(role=role,path=str(path),sha256=actual))
    for rel,h in m['artifacts'].items():verify_file(TRIAL/'trial'/rel,h,'trial artifact')
    for rel,h in m['source_code']['files'].items():verify_file(ROOT/rel,h,'trial implementation')
    for rel,h in figure_index['final_files'].items():verify_file(TRIAL/rel,h,'final visualization')
    for rel,h in speed['files'].items():verify_file(SPEED/rel,h,'video measurement')
    verify_file(ROOT/'scripts/measure_chapter2_video_speed.py',speed['code_sha256'],'measurement source')
    verify_file(ROOT/'scripts/analyze_chapter2_video_speed.py',analysis['analysis_source_sha256'],'analysis source')
    for rel,h in analysis['files'].items():verify_file(SPEED/'analysis_r2_same_metric'/rel,h,'speed analysis')
    for r in speed['all_video_hash_checks']:verify_file(Path(r['path']),r['sha256'],'original video')
    verify_file(Path(m['source_map_path']),m['source_map_sha256'],'original design map')
    template=js(TRIAL/'template_provenance.json')
    # The reviewed template source is already verified by audit_trial and indexed
    # through its persisted provenance document rather than guessed key names.
    with (OUT/'数据与源码来源索引.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['role','path','sha256']);w.writeheader();w.writerows(checked)
    command=[sys.executable,'-m','unittest','tests.test_geometry_single_step',
             'tests.test_chapter2_geometry_sim','tests.test_video_geometry_estimate',
             'tests.test_electrode_design_map','tests.test_chapter2_evidence',
             'tests.test_chapter2_causality','tests.test_video_speed_check','-v']
    test=subprocess.run(command,cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace')
    (qa/'local_tests.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
    if test.returncode!=0:raise ValueError('local tests failed')
    if 'Ran 93 tests' not in test.stderr:raise ValueError('unexpected test count')
    compile_result=subprocess.run([sys.executable,'-m','compileall','-q',
        'dmf/chapter2_geometry_sim','scripts/measure_chapter2_video_speed.py',
        'scripts/analyze_chapter2_video_speed.py','scripts/package_geometry_single_step_review.py'],
        cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace')
    if compile_result.returncode:raise ValueError('compile failed')
    (qa/'fresh_checks.json').write_text(json.dumps(dict(trial_audit=audit,
        hash_records=len(checked),local_tests=93,local_test_exit=test.returncode,
        compile_exit=compile_result.returncode,new_persisted_trials=0,
        speed_proposal_applied=False),ensure_ascii=False,indent=2),encoding='utf-8')

    pdfmetrics.registerFont(TTFont('Song', 'C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    styles={
      'title':ParagraphStyle('title',fontName='Song',fontSize=19,leading=27,textColor=colors.HexColor('#173a53'),spaceAfter=12),
      'h':ParagraphStyle('h',fontName='Song',fontSize=14,leading=20,textColor=colors.HexColor('#173a53'),spaceAfter=8),
      'body':ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK'),
      'small':ParagraphStyle('small',fontName='Song',fontSize=9,leading=14,spaceAfter=5,wordWrap='CJK'),
      'cell':ParagraphStyle('cell',fontName='Song',fontSize=9.5,leading=14,wordWrap='CJK')}
    story=[];markdown=[]
    def p(text,style='body'):
        story.append(Paragraph(escape(text),styles[style]));markdown.append(text+'\n')
    def h(text):p(text,'h')
    def table(headers,rows,widths):
        values=[[Paragraph(escape(str(c)),styles['cell']) for c in r] for r in [headers]+rows]
        t=Table(values,colWidths=[v*mm for v in widths],repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),
             ('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),
             ('LINEBELOW',(0,-1),(-1,-1),.5,colors.HexColor('#9aa7b0')),
             ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
             ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.extend([t,Spacer(1,9)])
        markdown.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n')
        markdown.extend('| '+' | '.join(map(str,r))+' |\n' for r in rows)
    def page():story.append(PageBreak());markdown.append('\n---\n')

    p('实验一审查报告','title')
    p('基于真实电极几何的单液滴到达状态识别仿真','h')
    p('2026-10-28  |  SIMULATION  |  normal机制单例，n=1','small')
    h('一、验收结论')
    p('第一版机制实验已运行并通过持久化数据审计，可用于解释真实设计几何下的单步液滴运动、Mask空间特征和到达事件判定。它不是实物动力学标定，也不是完整闭环策略性能实验。降速新版仍未运行。')
    table(['核查对象','状态','含义'],[
        ['190→191原速度例','通过机制验收','4.8 mm/s模拟峰值，1条normal记录；原结果保持。'],
        ['几何、观测、三方法比较','已完成','301个内部时刻、60个实际生成并处理的Mask。'],
        ['真实视频速度核查','粗估完成','接收时间与近似网格标尺，不是曝光/毫米正式标定。'],
        ['1.4 mm/s降速建议','未应用、未运行','另存建议文件，不能称降速仿真已完成。'],
        ['真实准确率或普遍优势','未建立','没有多seed统计、异常对照或实物视觉闭环结果。']], [43,33,94])
    h('二、实际时间线')
    table(['事件','simulation时间/s','事件语义'],[
        ['请求激活191',f"{s['request_s']:.2f}",'唯一运输请求，保持到记录结束。'],
        ['模拟Applied',f"{s['applied_s']:.2f}",'模拟应用，不是真实串口ACK或高压测量。'],
        ['响应起点 / 首个移动tick',f"{s['response_start_s']:.2f} / {s['first_motion_tick_s']:.2f}",'响应延迟后开始平滑运动。'],
        ['质心到目标中心',f"{s['center_reached_s']:.2f}",'模拟内部位置事件。'],
        ['独立参考确认',f"{s['reference_confirmation_s']:.2f}",'内部距离、速度和驻留条件独立生成。']], [65,34,71])
    p('范围限定：仅190→191；没有192请求。初始源区是受控初始条件，不是已执行的P0源准备确认。三方法只记录事件，不反作用于当前轨迹。','small')
    page()

    h('三、模型、地图和输入隔离')
    p('地图直接读取已确认的FBC6-3 Gerber设计轮廓，保留400核心与20外围电极；设计中心节距3.2 mm。地图是设计几何和已确认编号关系，不等同于实物尺寸、电气连通或相机标定验收。')
    p('液滴形状取已审核视频第153帧的紧凑轮廓，归一化至等效直径4.0 mm，投影面积12.566371 mm²。视频像素尺寸没有被冒称为已标定毫米尺寸。0.8 mm垫片高度只记录为元数据，不参与体积、接触角或驱动力计算。')
    p('运动采用最小跃度位移q(u)=10u³-15u⁴+6u⁵，T=1.875L/v_peak。按模拟Applied、响应延迟和邻接交叠触发；无交叠时运动时钟不推进。形变采用轴向拉伸与横向逆缩放保持面积，属于二维现象学模型，不是CFD或真实电润湿动力学。')
    table(['参数','已运行值','证据属性'],[
        ['峰值 / 积分步长','4.8 mm/s / 0.01 s','模拟假设，非视频标定。'],
        ['相机 / 名义曝光 / 处理','20 fps / 8 ms / 40 ms','模拟时钟，非真实相机曝光。'],
        ['观测栅格 / 随机扰动','40 px/mm / 0','无附加噪声、丢帧；仍有栅格离散误差。'],
        ['记录 / 开发seed','3.0 s / 264900','单例，不形成准确率或置信区间。']], [59,49,62])
    h('四、静态几何阈值可达性')
    pre=js(TRIAL/'geometry_preflight.json')
    table(['路径位置','rho_target','eta_source','候选G'],[
        [f"{r['fraction']*100:.0f}%",f"{r['rho_target']:.4f}",f"{r['eta_source']:.4f}",'满足' if r['candidate_gate'] else '不满足'] for r in pre['rows']], [37,45,45,43])
    p('rho_target为重叠面积/目标电极面积；eta_source为源区重叠面积/液滴面积。候选G要求rho_target≥0.90且eta_source≤0.08，紧凑形状居中终点可同时满足。五个静态位置是几何预检查，不是动态采样帧，也不说明阈值已获实物验证。','small')
    page()

    h('五、三种到达判据与实际结果')
    p('三方法共享同一已保存Mask、地图、任务和simulation时钟。算法仅使用观测Mask特征；独立评分参考读取内部位置、速度与驻留，不由算法覆盖门生成。')
    table(['方法','到达门','确认/s','相对参考/s'],[
        ['M1 单帧覆盖','C0+G',f"{s['single_confirmation_s']:.2f}",f"{s['single_confirmation_s']-s['reference_confirmation_s']:+.2f}"],
        ['M2 连续稳定','C0+G+Q+W',f"{s['window_confirmation_s']:.2f}",f"{s['window_confirmation_s']-s['reference_confirmation_s']:+.2f}"],
        ['M3 时空联合','C0+G+Q+W+S+K',f"{s['spatiotemporal_confirmation_s']:.2f}",f"{s['spatiotemporal_confirmation_s']-s['reference_confirmation_s']:+.2f}"],
        ['独立内部参考','距离+速度+连续驻留',f"{s['reference_confirmation_s']:.2f}",'0.00']], [42,65,28,35])
    p('C0处理帧身份、时序和任务完整性。Q要求非空、单连通域且不触ROI边界；W要求至少5帧且跨度至少0.25 s，最大间隔0.18 s；在20 fps规则序列中实际使用6帧。S要求观测质心距目标中心不超过0.576 mm；K为原始有效历史的速度连续性，限值19.2 mm/s，断档后重建。未启用单调前进或走廊宽度门。')
    p('M2/M3确认使用曝光标签1.90至2.15 s的6帧证据，处理可用后在2.20 s确认。标签是模拟曝光时刻，不是真实设备测量。独立参考要求内部目标距离≤0.288 mm、速度≤0.192 mm/s、连续驻留≥0.15 s，在2.06 s形成确认。')
    h('六、结果可以支持什么')
    p('本例显示单帧覆盖在所定义独立参考确认之前0.11 s触发；增加连续稳定窗口后晚于参考0.14 s确认，体现可靠性与等待时间的机制权衡。由于没有实际下一电极切换，不能据此断言单帧已导致实物运输失败。')
    p('M2与M3的时刻完全相同。本例未证明S/K的额外识别收益；正常无噪声场景也不足以衡量五状态准确率、异常拒绝能力、Retry/Recovery或闭环路径完成率。M3是纯到达门，不是完整五状态控制器。')
    h('七、图稿含义')
    p('附图1为完整设计地图；附图2为五位置静态交叠；附图3为同一trial的六个真实日志时刻；附图4为内部/观测位置与空间特征；附图5为到达事件时序。内部分布、已处理Mask和观测质心不同步是处理延迟的表现，不能将内部真值误认为算法输入。')
    page()

    h('八、速度问题与视频核查')
    timing=speed['timing']
    p(f"有sidecar的原视频包含{timing['saved_frames']}个保存帧。容器帧率{timing['container_fps']:.6f} fps，而保存帧主机接收速率约{timing['host_receive_saved_fps']:.6f} fps；首末帧间隔分别为{timing['container_first_to_last_s']:.3f} s和{timing['host_receive_duration_s']:.3f} s。文件播放约快{timing['playback_speedup_vs_receive']:.3f}倍，按播放器时间推算可能明显高估速度。")
    p('主机接收仍非曝光时间；未知设备ticks未换算。固定核查630—810帧，复用原生ROI(1566,2760,570,336)，以既有118×119 px网格周期及3.2 mm设计节距作近似标尺，没有使用旧照片H。')
    table(['可见迁移片段','方法','中段平均速度粗估/(mm/s)'],[
        [f"{r['start_frame']}—{r['end_frame']}",r['method'],
         f"{r['approx_average_progress_speed_bounds_mm_s'][0]:.3f}—{r['approx_average_progress_speed_bounds_mm_s'][1]:.3f}"] for r in analysis['results']], [60,35,75])
    p('两段为同轮采集的描述片段，端点位移约1.20和1.78个近似节距，并非已验证的两个单电极运输任务。范围只反映10%/90%穿越的采样括区，不包含空间标尺、形变质心及接收-曝光偏差，不是置信区间。自动Mask未人工审核，不能作为到达GT。')
    p('181帧中Otsu在末尾805—810帧有6次缺失，画面显示液滴越过ROI边界；记录完整保留。Adaptive此时的小对象检出不作为液滴有效轨迹。6个原审核帧只用于量测合理性检查，不能代表跨批次泛化。')
    h('九、未运行的降速建议')
    p(f"按同一最小跃度模型比较10%—90%平均进展速度，建议名义峰值{proposal['nominal_peak_speed_mm_s']:.1f} mm/s，对应一格完整迁移{proposal['nominal_3_2mm_motion_duration_s']:.3f} s，中段平均约{proposal['comparable_10_90_progress']['mean_progress_speed_10_90_mm_s']:.3f} mm/s，总保存时长建议6 s。该建议未写回旧参数、未运行新trial。")
    p('初步2.0 mm/s建议已由同口径换算后的1.4 mm/s建议取代；两份建议均保留且均未应用。速度降低后必须重新形成观测和事件，不能把旧1.95/2.20 s确认时间移入新版。')
    page()

    h('十、验收记录与不足')
    table(['项目','核查结果','审查意见'],[
        ['420地图/原始来源','hash一致','保留真实设计轮廓和编号；无制造计量结论。'],
        ['面积保持','几何最大相对误差约1.44×10^-15；Mask约0.362%','分别低于0.5%和2%目标。'],
        ['控制事件','仅1次191请求及1次模拟Applied；无192','识别方法不控制下一步，因果链可追溯。'],
        ['数据/源码/图稿',f'{len(checked)}条来源hash核验通过','包含新视频量测和三方法输入；全索引另附CSV。'],
        ['新增/相关局部回归','93项通过；编译通过','含7项速度量测测试与86项相关回归；未跑全量测试。'],
        ['机制保护','无交叠不移动、延迟、帧/任务/窗口回归通过','是软件夹具验证，不是实物测量。'],
        ['动画/关键帧','同一trial原始日志；既有动画4倍慢放','回放速度不等于模型速度；附图不插值造事件。']], [38,65,67])
    p('主要局限：n=1、无附加观测噪声；速度/响应/形变均为简化假设；4 mm为人为归一化尺寸；高度不参与动力学；视频空间绑定和曝光时间未完成；独立参考阈值仍属模拟操作定义。以上限制阻止真实准确率或普遍控制优势结论，但不否定本例的软件机制可用性。')
    h('十一、后续最小工作与停止条件')
    p('如采用降速建议，另建版本只调整声明的模拟速度与足够的记录时长，复验几何、Mask面积、唯一191事务、窗口及三方法时刻，然后先人工审查。不扩展多seed或异常批次，不改S1/S2/S3冻结结果，不改真实AM控制或第三章。正式物理参数仍待最终装夹下的视频空间配准、可靠时序与独立迁移标注。')
    h('十二、可复核材料')
    p('正式记录：仿真结果/2026-10-28_实验一_真实几何4mm到达识别_v1/trial。速度量测：真实分割研究/2026-10-28_视频时间与迁移速度核查_v1，最新建议为analysis_r2_same_metric。以上路径均相对于第二章目录。','small')
    p('本报告附原图PDF副本，未改原图；完整绝对路径与SHA256见同目录“数据与源码来源索引.csv”，机器核查见QA/fresh_checks.json，测试输出见QA/local_tests.txt。本轮新增持久化仿真trial为0，无Commit/Push。','small')

    (OUT/(TITLE+'.md')).write_text('\n'.join(markdown),encoding='utf-8')
    body=qa/'report_body.pdf'
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#d5dce2'));canvas.line(20*mm,18*mm,190*mm,18*mm)
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'实验一机制与证据审查 | 2026-10-28')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    doc=SimpleDocTemplate(str(body),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
                         topMargin=18*mm,bottomMargin=24*mm,title=TITLE,author='Chapter 2 research review')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    combined=fitz.open(body)
    if len(combined)!=5:
        raise ValueError(f'Expected 5 body pages, got {len(combined)}; inspect layout')
    figures=['map_full_clean','static_geometry','movement_keyframes','feature_timeline','arrival_timeline']
    appendix=[]
    for name in figures:
        path=TRIAL/'visualization_clean_v2/figures_final'/(name+'.pdf')
        part=fitz.open(path)
        appendix.append(dict(name=name,report_page=len(combined)+1,path=str(path),sha256=sha(path)))
        combined.insert_pdf(part);part.close()
    pdf=OUT/(TITLE+'.pdf');combined.save(pdf);combined.close()
    rendered=[]
    with fitz.open(pdf) as final:
        for i,page in enumerate(final):
            png=qa/f'page_{i+1:02d}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.15,1.15),alpha=False).save(png)
            rendered.append(str(png))
    result=dict(pdf=str(pdf),pdf_sha256=sha(pdf),pages=10,body_pages=5,appendix=appendix,
                source_hash_records=len(checked),new_persisted_trials=0,
                old_trial_passed=audit['passed'],test_count=93,tests_passed=True,
                generated_source=str(Path(__file__).resolve()),source_sha256=sha(__file__),
                output_files={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
                rendered_pages=rendered)
    (OUT/'交付索引.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(pdf=str(pdf),pages=10,hash_records=len(checked),tests=93),ensure_ascii=False))


if __name__=='__main__':
    build()
