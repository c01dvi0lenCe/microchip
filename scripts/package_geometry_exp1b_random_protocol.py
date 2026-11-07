"""Author a proposed protocol review packet; never initialise simulation RNGs."""
import csv
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from xml.sax.saxutils import escape
import pymupdf as fitz
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b.audit import load,sha
from dmf.chapter2_geometry_sim.exp1b.spec import METHODS,GATES
from dmf.chapter2_geometry_sim.model import DesignGeometry,footprint
from dmf.chapter2_geometry_sim.sdf_trial import js

CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
OUT=CH/'审查材料/2026-10-29_实验一B随机协议拟冻结_Chat审查包_v3'
DATA=CH/'仿真结果/2026-10-29_实验一B_机制收尾_有效轮廓重放_r3'
CONFIG=ROOT/'configs/proposals/chapter2_geometry_exp1b_random_v1.json'
PROTOCOL=ROOT/'docs/chapter2-geometry-exp1b-random-protocol-proposed-v1-2026-10-29.md'
EXP2=ROOT/'docs/chapter2-geometry-exp2-architecture-proposed-2026-10-29.md'
TITLE='实验一B_随机配对协议拟冻结与实验二设计_Chat审查稿'


def build():
    if OUT.exists():raise FileExistsError('new review packet only; never overwrite')
    OUT.mkdir(parents=True);qa=OUT/'QA';qa.mkdir()
    config=load(CONFIG);design=config['design'];g=config['shared_gates']
    assert config['execution_allowed'] is False and config['status']=='PROPOSED_AWAITING_REVIEW'
    assert config['formal_seed_reservation_only']==list(range(266000,266020))
    assert len(config['conditions'])==12 and len({r['id'] for r in config['conditions']})==12
    assert design['planned_shared_mask_caches']==12*20==240
    assert design['planned_main_predictions']==design['planned_ablation_predictions']==240*3
    assert design['unique_base_worlds']==4*20==80
    assert len(design['stress_strata']['low_seed_slots'])==len(design['stress_strata']['high_seed_slots'])==10
    names={r['name']:r for r in config['methods']}
    for method in METHODS:
        for key in 'qwsk':assert names[method.name][key.upper()]==getattr(method,key)
    for key,newkey in [('rho_target','rho_target_min'),('eta_source','eta_source_max'),('min_frames','W_min_frames'),
        ('min_span_s','W_min_span_s'),('max_gap_s','W_max_gap_s'),('target_distance_mm','S_target_distance_max_mm'),('max_history_speed_mm_s','K_raw_history_speed_max_mm_s')]:
        assert GATES[key]==g[newkey]
    assert len(config['reference']['one_factor_sensitivity'])==7
    base=config['reference']['base']
    for r in config['reference']['one_factor_sensitivity']:
        assert sum(r[k]!=base[k] for k in base)<=1
    assert load(DATA/'closeout_audit.json')['passed']
    frozen=load(DATA/'manifest.json');source_rows=[]
    for path,digest in frozen['source_code'].items():
        assert sha(path)==digest;source_rows.append(dict(role='unchanged_mechanism_source',path=path,sha256=digest))
    for rel,digest in frozen['artifacts'].items():assert sha(DATA/rel)==digest
    geometry=DesignGeometry(config['geometry']['map_path'])
    assert len(geometry.polygons)==420 and geometry.sha256==config['geometry']['map_sha256']
    e={r['control_id']:r for r in geometry.document['electrodes']};route=[]
    for a,b in [(190,191),(191,192),(192,172)]:
        source_rc=(e[a]['logical_row'],e[a]['logical_col']);target_rc=(e[b]['logical_row'],e[b]['logical_col'])
        distance=float(np.linalg.norm(geometry.center(b)-geometry.center(a)))
        assert sum(abs(x-y) for x,y in zip(source_rc,target_rc))==1 and abs(distance-3.2)<1e-8
        route.append(dict(source=a,target=b,source_rc=source_rc,target_rc=target_rc,center_distance_mm=distance,
            polygon_gap_mm=geometry.polygons[a].distance(geometry.polygons[b]),
            compact_initial_neighbor_overlap_mm2=footprint(geometry.center(a),4.).intersection(geometry.polygons[b]).area))
    js(qa/'static_geometry.json',dict(map_sha256=geometry.sha256,route=route,static_only=True,new_world_runs=0))
    test=subprocess.run([sys.executable,'-m','unittest','tests.test_geometry_exp1b','tests.test_geometry_exp1b_closeout','-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'existing_local_tests.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
    assert test.returncode==0
    match=re.search(r'Ran (\d+) tests',test.stdout+test.stderr);test_count=int(match.group(1));assert test_count==25
    protect=subprocess.run([sys.executable,'.planning/geometry_single_step_20261028/protect.py','verify'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'old_asset_protection.txt').write_text(protect.stdout+protect.stderr,encoding='utf-8');assert protect.returncode==0
    for p in [CONFIG,PROTOCOL,EXP2,Path(__file__),DATA/'manifest.json',DATA/'closeout_audit.json',DATA/'planned_method_results.csv',
        DATA/'exclusive_step_outcomes.csv',DATA/'gate_trigger_counts.csv',Path(config['geometry']['map_path'])]:
        source_rows.append(dict(role='proposal_or_evidence',path=str(p),sha256=sha(p)))
    for p in sorted((ROOT/'.planning/geometry_exp1b_random_protocol_20261029').glob('*')):
        if p.is_file():source_rows.append(dict(role='research_scope_and_claims',path=str(p),sha256=sha(p)))
    for row in source_rows:
        path=Path(row['path'])
        try:rel=path.resolve().relative_to(ROOT)
        except ValueError:continue
        snap=OUT/'源码与协议快照'/rel;snap.parent.mkdir(parents=True,exist_ok=True);snap.write_bytes(path.read_bytes())
        row['snapshot_path']=str(snap)
    with (OUT/'来源与hash索引.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['role','path','sha256','snapshot_path']);writer.writeheader();writer.writerows(source_rows)
    for source,name in [(CONFIG,'实验一B_机器可读拟冻结配置.json'),(PROTOCOL,'实验一B_随机配对拟冻结协议.md'),(EXP2,'实验二_架构与公平基线草案.md')]:
        (OUT/name).write_bytes(source.read_bytes())
    pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=body,fontSize=14,leading=21,textColor=colors.HexColor('#173a53'),spaceAfter=10)
    cell=ParagraphStyle('cell',parent=body,fontSize=9.2,leading=14,spaceAfter=0)
    story=[]
    def p(text,h=False):story.append(Paragraph(escape(text),heading if h else body))
    def page():story.append(PageBreak())
    def table(headers,rows,widths):
        t=Table([[Paragraph(escape(str(c)),cell) for c in row] for row in [headers]+rows],colWidths=[v*mm for v in widths],repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173a53')),('LINEBELOW',(0,-1),(-1,-1),.5,colors.grey),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]));story.extend([t,Spacer(1,9)])
    p('实验一B：随机配对协议拟冻结与实验二设计',True)
    p('2026-10-29 | SIMULATION研究方案 | 待审，未冻结，未运行')
    p('一、准入状态及本轮实际工作',True)
    p('用户已批准确定性机制收尾，并原则同意进入随机协议准备。当前只完成具体分布、独立配置、评分/统计规则和实验二架构草案；execution_allowed=false。没有初始化新seed、生成World/Mask、执行算法预测或参考重评分。')
    table(['已有事实','证据与处理'],[
        ['机制完成','r3的16缓存/96方法记录保留，B1已关闭；本轮不再做形态优化。'],
        ['研究主方法','M1/M2/M3保留；M2是有依据候选，M3没有已证明增量，S/K阈值不调。'],
        ['科学边界','参考前不是已验证的危险切换；确定性计数不是随机错误率。'],
        ['新增负对照','预声明卡滞且持续伪目标；可能全部方法误确认，不保证M3获胜。'],
        ['实物边界','真实误差分布、跨批次形态和闭环收益缺失；本方案只评价给定合成分布。']],[33,137])
    p('二、推荐规模与备选取舍',True)
    p('推荐12类×20实例=240共同缓存，主方法720条、消融720条预测；80个基础运动World。同seed跨场景和观测变体相关，不合池当独立物理重复。N/V/P/T各20；8个压力类各低、高10例，不能把每层写成20。')
    p('备选340缓存（16旧夹具加联合负对照后各20）会重复确定性C0机制；全强度扫描更大。本轮推荐240的探索性规模，不作功效保证，不继续增加算法或条件。数字均为计划，不是已运行数量。')
    p('请先审查具体范围和参数，再决定是否进入独立命名空间实现及两个开发seed的冒烟；正式批次仍需代码/配置冻结和单独运行批准。')
    page()
    p('三、算法和形态表示不再扩展',True)
    table(['方法','C0/G','Q','W','S','K','角色'],[
        [r['name'],'开','开' if r['Q'] else '关','开' if r['W'] else '关','开' if r['S'] else '关','开' if r['K'] else '关',r['role']] for r in config['methods']],[25,25,20,20,20,20,40])
    p('G：rho_target≥0.90（目标电极面积分母），eta_source≤0.08（Mask面积分母）。Q：有效单连通且未触ROI边界，不是概率置信度。W：至少5帧且跨度0.25 s、最大间隔0.18 s；均匀20 fps需6帧。S：距离≤0.576 mm。K：共同原始观测历史速度≤19.2 mm/s。C0常开，开关不改变raw历史，事件每任务只消费一次。')
    p('全部新World统一复用430个已保存有效轮廓的最近进度重放，仅平移质心；不调用新的SDF插值、不拓扑修复。保留约0.00218749进度量化上界；等效0.007 mm是进度差，不是测量误差。旧正常SDF及旧16案例不替换。')
    p('四、共同运动与相机参数',True)
    table(['项目','提议分布/固定值'],[
        ['几何','420 Gerber设计轮廓，pitch 3.2 mm；4 mm面积等效液滴，垫片0.8 mm仅记录。'],
        ['控制及积分','190→191一次request 0.50 s，模拟Applied 0.54 s；dt=0.01 s，H=10 s；不发192。'],
        ['运动','q=10*u^3-15*u^4+6*u^5，T=1.875L/v_peak；Applied、响应及激励交叠满足后运动。'],
        ['随机速度/响应','normal峰值U(1.2,1.6) mm/s；slow U(0.7,0.9)；响应U(0.14,0.22) s。均为假设。'],
        ['暂停/卡滞','pause在q=U(0.4,0.6)暂停U(0.5,1.25) s；stall在q=U(0.35,0.65)永久停止。'],
        ['相机','20 fps，曝光0.008 s、处理延迟0.04 s；虚拟40 px/mm；原始Mask逐张保存。']],[32,138])
    p('最慢名义全程约0.76+1.875×3.2/0.7=9.331 s，10 s有约0.669 s余量。仍保存删失，不能预设每例一定完成参考。')
    page()
    p('五、12类条件及随机压力强度',True)
    table(['ID','World/压力','低强度','高强度'],[
        ['N','normal，干净','base n=20','无分层'],['V','slow，干净','base n=20','无分层'],
        ['P','pause，干净','base n=20','无分层'],['T','stall，干净','base n=20','无分层'],
        ['J','逐帧位置抖动','坐标幅度U(0.025,0.05) mm','U(0.10,0.20) mm'],
        ['O','固定偏移','幅度U(0.05,0.10) mm','U(0.20,0.40) mm'],
        ['C','后部局部缺失','bbox轴长U(5%,10%)','U(15%,25%)'],
        ['R','破碎','删除质心1 px横带','2 px横带'],
        ['F','伪目标','连续1-3帧','连续7-12帧'],
        ['D','逐帧丢失','p=0.05','p=0.25'],
        ['L','逐帧延迟概率0.1','额外U(0.05,0.10) s','额外U(0.20,0.40) s'],
        ['TF','stall+持续伪目标','连续7-9帧','连续10-12帧']],[12,42,58,58])
    p('J/O/C/R始于首个q≥U(0.80,0.95)的捕获帧，持续U(0.35,0.65) s，窗内每帧施加。J的每帧dx/dy独立U(-a,a)；O方向U(0,2π)。F/TF用同一紧凑目标模板连续替换，开始进度抽U(0.25,0.45)。TF实际起点取min(抽样起点,0.8×卡滞进度)，预先声明，记录变换，不重抽。')
    p('每个条件化压力例安排一次episode（概率1），不是现实误检概率。D/L作用于Applied后的捕获帧；丢帧保留Mask和原ID，延迟只改递交，不改曝光时间。片段破碎是否触发Q取决于实际连通数，不直接写Q=false。')
    p('只有TF叠加物理/视觉异常，其他条件分别检验。TF是边界负对照，不是完整因子设计，不能据F/TF差异声称已估计物理卡滞与伪观测的独立交互。实际幅度、帧数、变更像素和门触发全部记录。')
    p('保留旧重复帧、旧任务和合法跳变作为确定性回归，不为增加随机数量重复列新主条件。全部视觉压力未经过实测分布标定，标注synthetic stress。')
    page()
    p('六、随机单位、时间与独立参考',True)
    p('正式候选seed266000-266019只登记不执行；开发候选268000-268001。各seed生成normal/slow/pause/stall四个基础World，共80；观察变体共用World，6方法共用缓存。不同seed改变速度/响应等，不只是同轨迹图像加噪。低/高slot各10，方法配对而低/高不作同World配对。')
    p('拟采用NumPy PCG64/SeedSequence，整数熵[20261029,seed,组码,流码,条件码]；运动raw流共用，参数/空间/丢失/延迟分流。先持久化全部raw数组及状态，后运行方法；保存NumPy版本和hash，不以Python hash生成流ID。未初始化本轮任何研究随机流。')
    p('曝光0.00-9.95 s共200帧；可用=曝光+0.048 s，处理向上取0.01 s网格。10.00 s先处理再评分；之后待递交保留且不执行。反序/重复/旧任务不能推进共同证据。')
    table(['独立参考','距离/mm','速度/(mm/s)','驻留/s'],[
        ['R0基准',.288,.192,.15],['距离收紧',.2304,.192,.15],['距离放宽',.3456,.192,.15],
        ['速度收紧',.288,.1536,.15],['速度放宽',.288,.2304,.15],['驻留缩短',.288,.192,.10],['驻留延长',.288,.192,.20]],[45,40,45,40])
    p('只从World位置、有限差分速度、active和模拟时间生成驻留区间；7参考只重评分同一预测，不改变G/W或形态。±20%和±0.05 s为敏感性假设，不是实测安全容差。')
    p('必须关闭端点测试：真实离开时支持区间右开；H时仍在目标则包含H。旧评分对所有end作排他比较，新命名空间需区分离开与随访结束，不改旧记录。驻留在H仍建立中标参考右删失，不填“无到达”。')
    page()
    p('七、互斥结果、完整分母与统计',True)
    p('每方法/计划任务一个主类别：参考支持、参考前、无参考确认、参考区间外、参考存在未确认、无参考无确认、删失或未执行。参考未匹配另作诊断，不能和参考前重复相加成两次失败。')
    p('优先顺序：执行失败为未执行；有H内决策按参考区间评分；无决策且参考仍建立或有待递交则删失；其余按参考有无分类。已有事件不被后续缺观测抹除。无效/无Mask/C0拒绝逐帧保留；本实验只预测到达，不生成五状态准确率。')
    p('固定H指标与未来删失分开：完整执行但H内无事件，三种H内确认指示量均为0；后续是否会确认可右删失。H内已完成参考仍计漏确认诊断，不借删失删除分母。只有未执行/日志不全才导致固定H端点未知。')
    table(['分析','预声明规则'],[
        ['主要比较/端点','M2-M1及M3-M2；分别报告参考前、无参考确认、参考支持/计划任务。无总体合池准确率。'],
        ['样本量/分层','base n=20；每压力层n=10。压力总体为低/高各0.5权重，不是自然事件发生率。'],
        ['率区间','单层用精确Clopper-Pearson 95%；压力总体两层各97.5%边界加权，形成保守95%区间。'],
        ['配对率差','A-B中p+=P(A=1,B=0)，p-=P(A=0,B=1)。各层用精确二项Bonferroni边界，alpha=0.05/(2×层数)；差界p+下-p-上至p+上-p-下，加权。风险差负、支持产出差正表示改善。'],
        ['延迟/时间偏差','带符号时差不叫负延迟。只有两法同时参考支持的seed计算条件中位配对延迟差，报告n_joint；≥5才做10000次配对bootstrap，分析seed930100。'],
        ['未知/未执行','计划N不变。已知k/N并列识别范围[k/N,(k+u)/N]；有未决端点时暂停通常率/方法差CI，不静默完整病例。'],
        ['推断边界','逐条件探索性区间；无星号、总体显著性或真实优势主张。全相同二元配对不使用退化bootstrap证明等价。']],[31,139])
    p('只在共同成功子集分析的延迟不能代表全计划运行效率。若n_joint小于5只展示原值；0宽时间区间也不等于连续物理时间精度。所有失败、Unknown观测、无事件、未尝试及删失各有完整表。')
    page()
    p('八、正式图稿任务和实施闸门',True)
    table(['拟议图','要回答的问题/必要图注'],[
        ['图1 类别与扰动强度','M1/M2/M3的参考前、无参考确认、参考支持及区间；标清n=20或n=10，不把参考前称真实危险。'],
        ['图2 可靠性-时间代价','正常、慢速及压力条件的支持比例与条件延迟并列，原始配对差可追溯；无确认不赋0延迟。'],
        ['图3 消融及敏感性','GQ→M2的W增量，M2→+S/+K/M3的事件与等待代价，7参考下预测不变的类别变化；拒绝帧数不代替收益。']],[40,130])
    p('图内仅必要坐标、图例、SIMULATION；来源、n、模型边界放caption。当前无新数据，因此没有提前绘制预期曲线。')
    table(['闸门','要求与当前状态'],[
        ['G0 数值协议批准','具体240规模、分布和端点待用户/Chat审查；配置仍禁止执行。'],
        ['G1 实现与手算','新exp1b_random命名空间，复用门/重放；补H端点、真实离开、删失、配对区间和分层n测试。尚未实施。'],
        ['G2 实现冒烟','最多2开发seed×12=24缓存/144方法；只验复现与机制，不根据结果调门限或筛正式seed。尚未运行。'],
        ['G3 代码配置冻结','实际源码/环境/配置/原始流规则hash及独立审计，正式执行另获批准。'],
        ['G4/G5 正式与停止','一次240缓存；预测不变的7参考复算、独立审计和3图。无M3收益也停止，不追加有利条件。']],[36,134])
    p('本轮源码核对：旧单步Config严格限定seed264900和190→191，旧参考阈值写死，原生成器是固定夹具；不能宣称现有入口已能执行本随机协议。采用独立适配层而非篡改旧模块。')
    page()
    p('九、实验二架构与公平基线',True)
    table(['路径','逻辑行列（零基）','中心距/mm','间隙/mm'],[
        [f"{r['source']}→{r['target']}",str(r['source_rc'])+'→'+str(r['target_rc']),f"{r['center_distance_mm']:.6f}",f"{r['polygon_gap_mm']:.7f}"] for r in route],[30,72,34,34])
    p('4 mm圆形居中源区时与相邻目标设计电极交叠约0.607862 mm²。以上是静态设计核算，不是新运动试验或实物可运输证明。旧preflight只查横向邻接，第三步需一般四邻接检查；旧函数不改。')
    p('共同P0 → 模拟相机Mask输入判定 → request → pending → 模拟Applied变更active → 响应/交叠 → 运动反馈 → 新Mask。必须保留内部实际位置，不因step更新瞬移；任何位置切换的速度连续性和形态进度先做机制测试。新World适配尚未实现，不把旧点运动World冒充已完成的新闭环。')
    p('主组A_fixed/M1/M2/M3共享P0、基础保护和控制预算。A固定计时不产生视觉ArrivalEvent；完整五状态保护若需另测，通过桥接单独归因，不把保护收益归S/K。外生场按时间/空间索引，策略分叉可以产生不同Mask，但随机场相同。')
    p('固定时间不能沿用旧1.2 s。一个可审查的名义候选：0.18+1.875×3.2/1.4+0.15≈4.616 s，按相机周期向上为Applied后4.65 s；这是模型推导候选，不是已冻结或实测参数。另一方案为独立开发数据一次选定，均不得正式seed调参。')
    p('三步总预算需覆盖最慢声明运动及共同保护；旧24 s不能自动移植。工作流完成与独立支持路径完成分开，请求/Applied分别评分，并观察后续实际模拟运输结果，才可评价“错误推进”。')
    p('停止扩展：实验一B完成一轮冻结随机比较后进入实验二，不等待M3胜出；当前不生成多电极性能结论。')
    page()
    p('十、检查记录、资料索引与审查问题',True)
    p(f'本轮协议静态检查：12类、20seed、240缓存、80基础World、6方法/1440预测及7个一因子参考相互一致；所有算法开关和门限逐项与现有代码一致。existing_local_tests实际{test_count}项通过；未重跑全量，前轮950项记录不冒充本轮结果。')
    p('冻结r3的来源代码及全部manifest资产hash只读一致；旧成果保护通过。没有改动形态、算法、seed结果、AM、STM32、U-Net或第三章，无Commit/Push。配置只存于proposals，尚无执行入口消费它。')
    p('报告旁保留：机器可读拟冻结JSON、完整随机协议Markdown、实验二架构Markdown、来源hash索引、源码与协议快照。QA含静态邻接值、25项局部日志、旧资产保护及配置核对。全部建议分布与区间算法是计划，非已完成分析。')
    p('当前阻断正式运行的项目',True)
    table(['项目','处理'],[
        ['数值范围尚待批准','本报告交审；不把原则同意当具体分布已冻结。'],
        ['新随机接口尚未实现','批准后G1/G2；不声称现有固定夹具入口可直接正式运行。'],
        ['H端点/删失与参考敏感性','独立新reference/evaluation手算测试，旧记录不改。'],
        ['随机源与层级复现','记录80World与240缓存对应、原始数组及状态；逐数组复现后再准入。'],
        ['实物参数缺失','不阻断给定假设下算法仿真，但限制外推；真实闭环另行计量和安全验证。']],[42,128])
    p('请Chat/用户重点审查',True)
    p('1. 是否接受12类×20实例及压力层各10的收敛规模？2. 未经实测的速度/响应与视觉压力范围是否作为声明假设保留？3. 是否认可统一有效轮廓重放、TF不重抽的起点规则、10 s端点及删失定义？4. 是否认可保守配对区间、未决端点不做通常CI、M3可无收益的停止条件？')
    p('建议准入结论：确定性机制已获批准；本轮交付拟冻结协议供审查。审查通过后只进入独立实现与少量开发冒烟，不直接启动正式seed或实物实验。')
    def footer(canvas,doc):
        canvas.setFont('Song',8.5);canvas.setFillColor(colors.HexColor('#56636e'))
        canvas.drawString(20*mm,12*mm,'拟冻结研究协议 | 本轮0新仿真/预测/重评分')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    pdf=OUT/(TITLE+'.pdf')
    SimpleDocTemplate(str(pdf),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=footer,onLaterPages=footer)
    with fitz.open(pdf) as doc:
        pages=len(doc)
        assert '\x00' not in '\n'.join(page.get_text() for page in doc),'font contains missing glyphs'
        for i,pdfpage in enumerate(doc):pdfpage.get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False).save(qa/f'page_{i+1:02d}.png')
    js(qa/'protocol_static_checks.json',dict(passed=True,execution_allowed=False,gate_config_unchanged=True,new_runs=0,new_predictions=0,new_rescores=0,
        local_tests=test_count,full_tests_rerun=False,source_records=len(source_rows),frozen_artifacts_checked=len(frozen['artifacts']),
        planned_caches=240,planned_base_worlds=80,planned_predictions=1440,reference_versions=7))
    js(OUT/'交付manifest.json',dict(pdf=str(pdf),pdf_sha256=sha(pdf),pages=pages,status='PROPOSED_AWAITING_REVIEW',
        execution_allowed=False,simulation_runs=0,new_predictions=0,new_reference_rescores=0,
        planned_caches=240,planned_predictions=1440,files={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(pdf,flush=True)


if __name__=='__main__':build()
