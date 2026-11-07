"""Author an evidence-grounded thesis candidate; only reads frozen research outputs."""
from pathlib import Path
import argparse, csv, hashlib, json, re, shutil
from zipfile import ZipFile
from collections import Counter, defaultdict
from copy import deepcopy
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from lxml import etree
import build_chapter2_thesis_draft as old
from chapter2_restructure_inventory import ROOT, REPO, OUT, V1, S3, S3Q, sha, dump, readcsv, NS

CONTENT=REPO/'docs/chapter2_thesis_restructured_content_20261028.md'
DATASET=REPO/'docs/chapter2_real_dataset_expansion_20261028.md'
NAME='第二章学术化重写候选v2.docx'
FIGDIR=ROOT/'仿真结果/2026-10-27_仿真论文图_移除说明小字_v4/figures'

def load():
    e=json.loads((OUT/'source/legacy_evidence_snapshot.json').read_text(encoding='utf-8'))
    s=readcsv(S3/'formal_summary.csv')
    assert len(s)==40 and sum(int(x['planned_trials']) for x in s)==800
    main=[x for x in s if x['cohort']=='main'];assert len(main)==28
    assert all(int(x['planned_trials'])==20 and int(x['planned_steps'])==60 for x in main)
    lookup={(x['scenario'],x['method']):x for x in main}
    expected={'normal':[20,0,20,20],'delayed':[0,0,20,20],'partial_stall':[0,0,20,20],
      'jitter':[0,0,0,0],'dropout':[14,0,12,12],'deviation':[0,0,20,20],'failure':[0,0,0,0]}
    methods=('A_fixed','B_single','BTQ','F_full')
    for scenario,v in expected.items():assert [int(lookup[(scenario,m)]['path_complete']) for m in methods]==v
    assert abs(float(lookup[('deviation','F_full')]['budgetized_mean_s'])-11.792)<.00051
    assert abs(float(lookup[('deviation','BTQ')]['budgetized_mean_s'])-10.891)<.00051
    ss={(x['condition'],x['method']):x for x in e['stats']}
    checks=[('A_normal','B_single_frame','premature_confirmations',20),('A_normal','BTQ','supported_confirmations',20),
      ('C_jump_short','BTQ','unsupported_confirmations',17),('C_jump_short','F_arrival','unsupported_confirmations',1),
      ('D_tail_false','BTQ','unsupported_confirmations',20),('D_tail_false','F_arrival','unsupported_confirmations',0),
      ('C_jump_persistent','F_arrival','unsupported_confirmations',20),('F_jitter','F_arrival','late_supported_confirmations',2),
      ('F_dropout','F_arrival','supported_confirmations',5),('F_dropout','F_arrival','late_supported_confirmations',10)]
    for c,m,k,v in checks:assert int(ss[c,m][k])==v,(c,m,k,ss[c,m][k])
    return e,s,lookup

def configure_tables(e,s):
    t=old.TABLES
    t['times']=('视觉闭环中的多时间尺度',['层次','功能','时间语义'],[
      ['外部激励波形','决定高压激励条件','电源/独立电气测量'],['AM阵列刷新','20×21寻址与保持，设计300 Hz','阵列扫描周期'],
      ['相机采样','产生离散图像','曝光/取流时间，不等同容器fps'],['视觉与证据处理','分割、状态及连续确认','图像可用与证据跨度'],['任务更新','推进或保护动作','事件驱动而非固定刷新']], [3.0,6.4,6.6])
    t['gates']=('到达信息约束及研究作用',['约束','判断问题','独立作用与边界'],[
      ['C0','数据是否有效且属于当前任务','帧身份、时间、任务因果；始终保留'],['G','主体是否进入目标并释放源区','η_t与η_s联合门；不单独保证稳定'],
      ['Q','观测质量是否满足要求','置信、面积及连通区域；非真实性保证'],['W','证据是否连续稳定','帧数、跨度、间隔与波动'],
      ['S','位置是否符合当前任务','任务区域及目标位置容差'],['K','短时运动是否历史一致','位移/预测残差；存在初始化与适应边界']], [1.3,5.1,9.6])
    t['states']=('五状态及观测可靠性标记',['名称','可观测含义','证据性质'],[
      ['Stationary','可辨静止','有效观测和运动特征'],['Moving','正在迁移','有效时序位移'],['Partial','目标进入伴源区残留','空间覆盖关系'],
      ['Arrived','当前任务可靠到达','合格连续证据及一次性事件'],['Deviation','持续任务空间偏离','有效观测中的连续偏离'],['Unknown','当前不可可靠判定','可靠性标记，不是第六物理状态']], [3.2,6.1,6.7])
    t['actions']=('事件控制动作及预算意义',['动作','目标与作用','任务身份'],[
      ['Hold','维持当前激励、等待证据','不推进'],['Update','到达后推进下一目标','推进一个计划步'],['Retry','同目标再次尝试','增加尝试，不增加计划步'],
      ['Recovery','切回局部源并再确认','有界恢复，不自动改道'],['保护停止','缺观测、无进展或预算耗尽','保留失败与未尝试'],['通信重发','相同事务序列重新发送','与液滴Retry分账']], [2.7,7.0,6.3])
    t['pilot_results']=('真实图像分割Pilot的描述结果',['方法','Dice / IoU','质心误差 / px','空Mask','平均 / P95耗时 ms'],[],[2.0,3.7,3.7,2.0,4.6])
    for r in e['pilot']:
        t['pilot_results'][2].append([{'otsu':'Otsu','adaptive':'自适应阈值'}[r['method']],f"{float(r['mean_dice']):.4f} / {float(r['mean_iou']):.4f}",f"{float(r['mean_centroid_error_px']):.3f} (n={r['centroid_denominator']})",f"{r['empty_masks']}/18",f"{float(r['mean_ms']):.3f} / {float(r['p95_ms']):.3f}"])
    t['simulation']=('简化二维仿真的共同基础参数',['类别','设置','单位/作用'],[
      ['几何与积分','420电极示例模板；Δt=0.01','pitch；不是Gerber动力学'],['迁移速度','名义1.5；seed因子0.8–1.2','pitch/s；有限速点运动'],
      ['模拟执行/响应','Applied延迟0.04；常规响应0.18','s；延迟场景另有响应规则'],['相机','20 fps；曝光0.008','模拟时钟'],
      ['可用延迟','曝光结束后0.04+[0,0.015)','s；处理与抖动'],['Mask','圆半径0.26；48 px/pitch','合成二值观测，非U-Net'],
      ['基本视觉误差','位置噪声0.018；半径噪声0.015；丢帧0.03','pitch及概率；异常场景另设'],['独立参考','距离0.09；速度0.06；驻留0.15','pitch、pitch/s、s']], [3.0,7.0,6.0])
    t['s3_methods']=('S3主策略及保护桥接定义',['策略','到达条件','保护策略'],[
      ['A_fixed','模拟Applied后1.2 s；无ArrivalEvent','P_B'],['B_single','G+C0；Q/W/S/K关闭','P_B'],
      ['BTQ','G+C0+Q+W','P_B'],['F_full','F_arrival：G+C0+Q+W+S+K','P_F'],['桥接补充','BTQ/P_F及F_arrival/P_B','固定门或保护进行归因']], [3.0,9.0,4.0])
    t['conditions'][2][6][2]='参考到达与异常Mask共存；误拒代价未独立隔离'
    t['conditions'][2][8][2]='参考到达时低质量观测的拒绝代价'
    t['s3_results']=('S3主组独立参考支持路径完成数',['场景','A_fixed','B_single','BTQ','F_full'],[],[4.0,3.0,3.0,3.0,3.0])
    for scene in ('normal','delayed','partial_stall','jitter','dropout','deviation','failure'):
        t['s3_results'][2].append([scene,*[f"{int(x['path_complete'])}/20" for x in s if x['cohort']=='main' and x['scenario']==scene]])
    # Keep the original five-method and thirteen-condition definitions verbatim.

def figures(e):
    originals={int(r['id'][1:]):Path(r['path']) for r in e['evidence'] if r['id'].startswith('F')}
    f={}
    titles={1:'单液滴视觉闭环控制系统架构',2:'视觉成像与芯片结构',3:'图像采集、识别与电极控制的多时间尺度关系',4:'420电极数字地图与图像—电极配准原理',5:'任务空间与连续时序先验的状态识别框架',6:'单液滴五状态与事件驱动控制'}
    for n,p in originals.items():f[n]=dict(title=titles[n],path=p,section={1:'2.2.1',2:'2.2.1',3:'2.2.2',4:'2.3.2',5:'2.4.1',6:'2.4.3'}[n],note='')
    f[1]['note']='图中部件表示各功能层级，设备标识及成像参数尚待最终装置资料核验。'
    f[7]=dict(title='不同成像条件下的真实液滴分割比较',path=None,section='2.5.1',note='')
    f[8]=dict(title='单照片配准预实验的独立检查点残差',path=Path(e['assets']['reg']),section='2.5.2',note='8个拟合点、16个独立检查点；残差为设计点逆投影至图像域的像素误差，非最终装置物理测量精度。')
    f[9]=dict(title='S1单液滴迁移的六阶段空间观测',path=Path(e['assets']['s1a']),section='2.5.3',note='SIMULATION，n=1机制示例；normal、seed 262000、F、end_to_end。0.50 s为Moving/Start；1.46 s为独立参考区间上界，1.92 s为确认，1.96 s为下一模拟Applied。单位pitch，模拟观测并非真实U-Net结果。')
    f[10]=dict(title='S1分阶段空间特征演化',path=Path(e['assets']['s1b']),section='2.5.3',note='与图2-9来自同一trial，SIMULATION，n=1。内部与观测x/y分列；目标距离及方向进展均由观测Mask质心计算，进展为pitch单位投影距离。')
    f[11]=dict(title='S2共同输入下的到达判定时序',path=next(FIGDIR.glob('S2-A*.png')),section='2.5.3',note='SIMULATION；正式正常缓存A_normal、seed 263000，n=1时序示例。五方法读取同一缓存；独立参考区间与算法证据分列，重叠事件保持原时刻。')
    f[12]=dict(title='S2到达判据比较与失效边界',path=next(FIGDIR.glob('S2-B*.png')),section='2.5.3',note='SIMULATION；每条件20个配对seed。M为模型生成，X为合成压力；NA为无可评价参考分母。提前与无参考确认分别统计；主窗口漏确认包括晚支持，不与晚支持相加。率区间为Wilson 95%，配对差为既有seed bootstrap区间；完整13条件另表保留。')
    f[13]=dict(title='S3四策略的运动轨迹与覆盖变化',path=next(FIGDIR.glob('S3-A1*.png')),section='2.5.4',note='SIMULATION，FORMAL；deviation、seed 265000，各策略n=1。来源为预声明正式案例，四策略共享外生条件，但各自闭环轨迹不同；内部位置与实际模拟观测用不同线/点表示。单位pitch。')
    f[14]=dict(title='S3四策略的状态及控制事件',path=next(FIGDIR.glob('S3-A2*.png')),section='2.5.4',note='与图2-13来自相同四条正式trial，SIMULATION、FORMAL、各n=1。P_B组Unknown包含策略屏蔽的非到达标签，不直接表征物理状态未知。只显示日志中实际发生的状态、Retry、Recovery及resend。')
    f[15]=dict(title='S3路径完成、安全性与执行代价',path=next(FIGDIR.glob('S3-B*.png')),section='2.5.4',note='SIMULATION；(a)(b)每条件每组20个配对trial，误差棒为Wilson 95%区间；三个计划步不作为独立样本。(c)点值为预算化时间均值，严格成功取实际完成时间，其余按24 s惩罚；误差棒为既有2000次seed bootstrap百分位95%区间，惩罚值非实际失败耗时。(d)偏离场景桥接每单元n=20，展示每trial Retry/Recovery/resend的平均Applied次数；各单元计数无组内变化。保护差异不归因于S/K门。')
    assert all(v['path'] is None or v['path'].is_file() for v in f.values())
    return f

class Thesis(old.Builder):
    def __init__(self,evidence,figs):
        # Reuse the retained DOCX's true styles, numbering, section and footer.
        self.doc=Document(str(V1));self.evidence=evidence;self.figs=figs
        self.eqcount=0;self.tablecount=0;self.figure_records=[];self.table_records=[];self.heading_records=[];self.section=''
        for child in list(self.doc._element.body):
            if child.tag!=qn('w:sectPr'):self.doc._element.body.remove(child)
        self.doc.core_properties.subject='第二章学术结构重构候选v2'
        self.doc.core_properties.comments='2026-10-28；正文重构；冻结研究数据只读复用。'
        self.doc.core_properties.author='';self.doc.core_properties.last_modified_by=''
    def front(self):
        for text in ('第二章','基于视觉反馈的单液滴运动状态识别与闭环控制'):
            p=self.doc.add_paragraph(text,style='Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p=self.paragraph('面向可抛式垂直激励数字微流控芯片的有源矩阵驱动平台研究');p.paragraph_format.first_line_indent=Pt(0)
        p=self.paragraph('2026年10月28日');p.paragraph_format.first_line_indent=Pt(0)
        self.doc.add_page_break();p=self.doc.add_paragraph('目录',style='Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p=self.doc.add_paragraph();self.field(p,'TOC \\o "1-2" \\h \\z \\u','更新目录')
        self.doc.add_page_break()
    def figure(self,n):
        info=self.figs[n];path=info['path']
        if path:
            p=self.doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            pf=p.paragraph_format;pf.first_line_indent=Pt(0);pf.keep_with_next=True;pf.line_spacing=1;pf.space_before=Pt(6)
            pic=p.add_run().add_picture(str(path),width=Cm(16))
            pic._inline.docPr.set('title',info['title']);pic._inline.docPr.set('descr',info['title'])
        else:
            p=self.paragraph(f'【待插图：Fig.2-{n}，{info["title"]}，真实三方法比较图待完成。】')
            p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.keep_with_next=True
        self.caption('Figure',n,info['title'])
        if info['note']:
            p=self.paragraph(info['note']);p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.line_spacing=1.15
            for r in p.runs:r.font.size=Pt(10.5)
        self.figure_records.append(dict(number=f'2-{n}',title=info['title'],section=info['section'],source=str(path) if path else None,sha256=sha(path) if path else None,note=info['note']))
    def build(self,path):
        self.front()
        for block in re.split(r'\n\s*\n',CONTENT.read_text(encoding='utf-8').strip()):
            text=block.strip()
            if text.startswith('## '):self.heading(text[3:],2)
            elif text.startswith('# '):self.heading(text[2:],1)
            elif text.startswith('@eq '):self.equation(text[4:])
            elif text.startswith('@table '):self.table(text[7:])
            elif text.startswith('@fig '):self.figure(int(text[5:]))
            elif text.startswith('@lead '):
                p=self.paragraph(text[6:]);p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.keep_with_next=True
                for r in p.runs:r.bold=True
            else:self.paragraph(text.replace('\n',' '))
        # Repeated old TOC fields were removed with the old body; a single fresh one remains.
        self.doc.save(path)

SECTIONS=[
 ('2.1','引言','固定等待和单帧观测为什么不足','问题分解、贡献与证据范围','真实Pilot/配准预实验＋S1/S2/S3分层证据','核实相关文献'),
 ('2.2','单液滴视觉闭环控制系统设计','如何连接感知与电极执行','架构及多时间尺度','Fig.2-1—3','最终设备资料与物理时钟'),
 ('2.2.1','视觉成像与闭环控制系统架构','观测怎样变成控制依据','Mask接口、空间特征、状态事件和执行','既有接口/原图','相机镜头铭牌及最终结构'),
 ('2.2.2','图像采集、状态识别及电极控制的多时间尺度关系','曝光、ACK和视觉确认有何不同','异步时间链、连续证据跨度','时钟字段与模拟事件','曝光—主机—HV映射'),
 ('2.3','单液滴视觉识别与电极空间映射','怎样定义可观测的任务空间','Mask—H—电极特征数学链','真实设计地图和预实验','真实视频有效绑定'),
 ('2.3.1','液滴图像分割与识别方法','跨成像条件怎样保持边界识别','Otsu/自适应/U-Net公平比较','18张审核Mask Pilot','独立三照明组及U-Net训练测试'),
 ('2.3.2','420电极数字地图构建与图像配准','图像与实际任务电极怎样关联','Gerber轮廓、ID核对、单应与独立检查','420地图，8fit/16check','最终装夹及视频绑定'),
 ('2.3.3','液滴—电极空间特征提取','哪些几何量能描述迁移','η/ρ、距离、进展、偏差与速度','公式与几何实现、S1','Mask误差传播真实评价'),
 ('2.4','基于时空先验的单液滴状态识别与事件驱动控制','何时可可靠推进任务','任务、证据、状态及有界控制','方法实现及S2/S3对照','实物参数/一致性验证'),
 ('2.4.1','基于电极任务约束与运动时序的状态特征构建','信息门各解决什么歧义','C0/G/Q/W/S/K分层','冻结到达门及公共历史','实物历史与研究K同输入核对'),
 ('2.4.2','单液滴五状态识别与可靠到达判定','候选状态怎样形成一次性到达证据','五状态、Unknown、窗口与事件消费','状态实现、S1机制、S2到达','独立真实状态GT'),
 ('2.4.3','基于状态事件的闭环控制与异常处理','异常时如何有限等待/恢复','进展监测、Retry/Recovery与P_B/P_F','S3正式及桥接','真实Retry与恢复有效性'),
 ('2.5','仿真与实验验证','证据能支持哪一层结论','真实/模拟、机制/统计分开','Pilot、预实验、S1—S3','真实独立评价'),
 ('2.5.1','真实液滴分割算法对比实验','三照明下分割性能与代价如何变化','组隔离测试＋Mask误差传播','现有传统Pilot描述结果','U-Net、独立测试组'),
 ('2.5.2','图像—电极配准与空间映射验证','映射一致性及误差如何界定','独立检查点、重复点选与绑定','单照片RMSE1.968px','最终装夹/畸变/测量不确定性'),
 ('2.5.3','单液滴状态及到达事件识别算法验证','运动特征及同输入到达门有什么作用','S1机制→S2公平输入与独立参考','S1定稿、S2正式13条件','真实状态/到达及S/K误拒代价'),
 ('2.5.4','事件驱动闭环控制算法仿真与消融分析','反馈能否改善完成、安全与代价','四主组、保护桥接、分阶段分母','S3正式800条及G5审计','无正式必要S4时不扩展；实物外推未证'),
 ('2.5.5','单液滴实物闭环控制实验','模型结论如何在实物检验','真实视频参考及Request/ACK/HV计量','就绪性PARTIAL与对应合同','最终视频、标定、模型、安全与实物试验'),
 ('2.6','本章小结','已有发现及边界是什么','综合而非软件模块复述','已完成层次的有限结论','真实U-Net与闭环仍未完成')]

def paragraph_advice(r):
    tx=r['text'];sec=r['section'].split(' ')[0];style=r['style'].lower()
    if style.startswith('toc'):return '删除','旧目录为自动生成结果，重建字段与页码','前置目录','不属于研究论述'
    if sec=='前置页':return '压缩','只保留章名、论文题名和日期；版本与写作管理移出正文','版本与更新说明','写作管理'
    if style.startswith('heading'):return '保留','保持锁定2.1—2.6层级；内部段落按科学问题重排',sec,'章节结构'
    if r['image_count']:return '保留','原图字节保留，来源与hash转独立索引',sec,'已定稿图'
    if tx.startswith('【待插图'):return '重写','找到的原图原样嵌入；不保留临时source文件名',sec,'内部来源/占位'
    if '待补充S3/S4' in tx or ('S3' in tx and any(x in tx for x in ('尚需闸门','后续动作反馈','后实施','尚无专项','待实施'))):
        return '重写','按G3-G5正式800条、主/桥接/诊断分层结果更新；S4未完成不合并表述',sec,'过期进度'
    if tx.startswith('【待补数据'):
        if sec in ('2.5.2','2.5.3'):return '重写','已有预实验/正式CSV结果写入正文；只有真实缺口保留占位',sec,'有证据无结果'
        return '压缩','仅保留可检索的真实材料缺口，删除作者指令与禁止语',sec,'待办混入'
    if tx.startswith('【待补文献'):return '压缩','保留简洁论断主题，逐条引用核验工作转内部清单',sec,'文献缺口'
    if r['in_table']:
        if any(x in tx for x in ('生产','S3/S4','待','仓库','版本','_mm')):return '重写','区分正式协议/实物初始值及历史进度，参数保留在必要表或附录',sec,'参数/版本混合'
        return '保留','保留可比较定义和数值；冗余解释移正文或参数附录',sec,'表格单元'
    if r['math_count'] and '（2-' in tx:return '保留','沿用原生公式结构、定义和单位；随正文核查不改判据',sec,'数学模型'
    if any(x in tx for x in ('FramePacket','StepContext','EvidenceWindow','ProgressMonitor','PriorFeatures','BEGIN/SET/COMMIT','ACK:sequence','NCHW','float32','[1,1,H,W]','calibration_manifest','world.active')):
        return '转入附录','正文保留输入—作用—输出及关键约束，接口字段/张量/事务细节登记技术附录',sec,'实现细节过密'
    if any(x in tx for x in ('当前仓库','用户确认','本版','本工作初稿','旧GUI','待写入','后续结果分析须')):
        return '重写','改为设计依据、实际结果及适用边界，删除面向作者的管理措辞',sec,'开发过程/过期写法'
    if sec=='2.5.4':return '重写','以完成性—安全—代价—桥接归因组织S3正式结果，保留源失败/未尝试与负面结果',sec,'方法有余而正式结果缺失'
    if sec=='2.6':return '重写','总结实际发现及边界，删除软件步骤和过期未来任务',sec,'小结缺研究发现'
    if sec=='2.5.3':return '保留','保留同输入/独立参考/分母；压缩文件身份说明并接入正式结果与机制讨论',sec,'结果链衔接'
    if tx.startswith(('图2-','表2-')):return '保留','保留编号与研究图意；版本、路径转来源索引，统计口径写图注',sec,'图表说明'
    if any(x in tx for x in ('不能','不得','禁止','须','应')):return '重写','将写作指令转换为模型假设、测量范围或证据限制，不删除真实边界',sec,'提醒性表达'
    if sec.startswith(('2.2','2.4')):return '压缩','围绕设计动机—方法—可验证作用组织，去重复接口说明',sec,'方法论证需聚焦'
    return '保留','保留科学事实与必要限定，整合到该节问题—方法—证据链',sec,'科学论述'

def support(b,e,s,figs):
    src=OUT/'source';src.mkdir(exist_ok=True)
    original=json.loads((src/'v1_all_paragraphs.json').read_text(encoding='utf-8'))
    newblocks=[];section='';counts=Counter();newids=defaultdict(list)
    for i,blk in enumerate(re.split(r'\n\s*\n',CONTENT.read_text(encoding='utf-8').strip()),1):
        if blk.startswith('#'):section=blk.lstrip('# ').split(' ')[0]
        newblocks.append(dict(id=f'N{i:03d}',section=section,text=blk))
        if not blk.startswith(('#','@')):counts[section]+=len(blk);newids[section].append(f'N{i:03d}')
    dump(src/'v2_paragraph_map.json',newblocks)
    advice=[]
    for r in original:
        action,why,dest,issue=paragraph_advice(r);sec=r['section'].split(' ')[0]
        target=newids.get(sec,[])
        advice.append(dict(**r,action=action,issue=issue,reason=why,destination=dest,new_blocks=', '.join(target[:2])+('…'+target[-1] if len(target)>2 else '')))
    with (OUT/'第二章逐段审查完整对照.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(advice[0]));w.writeheader();w.writerows(advice)
    md=['# 第二章逐节重写建议与段落对照','','2026-10-28；原稿非空段落、表格单元、公式、图题及目录均独立登记。P编号为原Word正文XML内段落次序，包含表格段落；N编号对应本次正文源块，不冒充Word页码。完整原文见同目录CSV及source/v1全文逐段提取.md。','',
       '## 逐节处置与论证重排','','|章节|原文主问题|候选正文组织|','|---|---|---|',
       '|2.1|方法列表及工作初稿说明多于研究缺口|固定等待/单帧局限→任务分解→证据范围|',
       '|2.2|采集对象、模式与配置字段铺陈过长|架构功能→异步时间链→测量约束|',
       '|2.3|分割接口细节较多，成像研究动机不足|跨照明问题→Mask定义→真实几何→配准与可观测特征|',
       '|2.4|软件数据类型与研究门、状态保护混写|C0/G/Q/W/S/K各自歧义→五状态/Unknown→一次性事件→有界策略|',
       '|2.5.1–2|已有Pilot/配准结果仍标待写|描述数值＋独立性/测量边界；新增真实数据为计划|',
       '|2.5.3|有正式S2证据而没有结果分析|S1 n=1机制→S2同输入→增量拒绝→失败与误拒未隔离|',
       '|2.5.4|S3尚待实施的进度已过期|800正式记录→严格路径/风险/代价→保护桥接与负面结果|',
       '|2.5.5|实物路线与仿真结论界限需加强|对应关系与独立计量/人工参考；明确实物结果缺口|',
       '|2.6|重复软件模块与未来任务|综合条件性研究发现、负面证据与真实验证边界|',
       '', '## 全部原段落处置','','|原段ID/章节|原文摘要|问题|处置|具体建议/去向|新正文块|','|---|---|---|---|---|---|']
    for r in advice:
        excerpt=r['text'][:90].replace('|','／').replace('\n',' ')
        md.append(f"|{r['id']} / {r['section']}|{excerpt}{'…' if len(r['text'])>90 else ''}|{r['issue']}|{r['action']}|{r['reason']}；{r['destination']}|{r['new_blocks']}|")
    oldcounts=Counter()
    for r in original:
        if not r['in_table'] and r['style'].lower()=='normal':oldcounts[r['section'].split(' ')[0]]+=len(r['text'])
    md+=['','## 正文篇幅变化（中文字符口径，非英文word count）','','|节|原稿正文字符（含原提醒）|新正文字符（不含图表/公式/图注）|','|---|---:|---:|']
    for sec in sorted(set(counts)|set(oldcounts)):
        if sec!='前置页':md.append(f'|{sec}|{oldcounts[sec]}|{counts[sec]}|')
    (OUT/'第二章逐节重写建议与段落对照.md').write_text('\n'.join(md),encoding='utf-8')
    outline=['# 第二章最新详细目录与各节研究任务','','保持用户锁定的2.1—2.6及全部二级结构。小节内部的括号分段仅作论证组织，不新增编号层级。','',
      '|章节|标题|科学问题|方法/研究任务|现有证据|待补材料|','|---|---|---|---|---|---|']
    for row in SECTIONS:outline.append('|'+'|'.join(row)+'|')
    outline+=['','## 正文证据顺序','','2.1提出问题；2.2说明反馈与时间链；2.3建立可观测空间量；2.4给出证据、状态和控制规则；2.5按分割—配准—S1/S2—S3—实物对应展开；2.6只综合已支持结论。',
      '', '2.5.3内部：环境与参考→S1机制→S2同输入对照→正确/错误/漏确认及机制边界。',
      '', '2.5.4内部：四策略与桥接→严格评分→正式完成性/风险/时间→保护归因及S4缺口。']
    (OUT/'第二章最新详细目录与各节研究任务.md').write_text('\n'.join(outline),encoding='utf-8')
    shutil.copyfile(DATASET,OUT/'真实液滴数据集采集和评价方案.md')
    evidence=[]
    for x in e['evidence']:
        x=dict(x)
        if x['id']=='E30':x['status']='历史S3设计；正式状态以G3/G4/G5索引为准，不能用于判定尚未运行'
        evidence.append(x)
    extra={
      'S3_G3':(ROOT/'仿真结果/2026-10-26_S3_G3协议冻结_v1/S3_正式冻结协议.json','2.4、2.5.4','冻结定义及科学计算源摘要'),
      'S3_G4':(S3/'completion_manifest.json','2.5.4','正式800条完成索引'),
      'S3_STATS':(S3/'formal_summary.csv','2.5.4','主/桥接/诊断40组统计，禁止合池'),
      'S3_TRIALS':(S3/'formal_trials.csv','2.5.4','800trial完整分母'),
      'S3_STEPS':(S3/'formal_steps.csv','2.5.4','2400计划步'),
      'S3_EVENTS':(S3/'request_applied_evaluation.csv','2.5.4','请求/Applied分别评价'),
      'S3_G5':(S3Q/'QA/independent_final_audit.json','2.5.4','历史独立审计，不是本轮重跑'),
      'S3_BRIDGE':(S3Q/'tables/bridge_control_identity.csv','2.5.4','80条同保护配对身份核对结果'),
      'S3_INTERVALS':(S3Q/'tables/time_and_action_intervals.csv','2.5.4','既有时间/动作均值及区间'),
      'S3_FIG_SOURCES':(S3Q/'figures/figure_sources.json','2.5.4','正式案例、逐trial及绘图数据来源'),
      'FIG_LATEST':(ROOT/'仿真结果/2026-10-27_仿真论文图_移除说明小字_v4/来源/原始正式来源与hash索引.json','2.5.3—4','已有候选图对应原始结果hash链'),
      'REAL_CONTRACT':(REPO/'docs/chapter2-s3-sim-to-real-contract.md','2.5.5','实物对应与K更新差异'),
      'REAL_MAP':(REPO/'docs/chapter2-real-map-binding-gaps-2026-10-27.md','2.3、2.5.2','照片H不等于视频有效绑定'),
      'REAL_GROUP':(ROOT/'真实分割研究/2026-10-21_采集分组确认.json','2.5.1','独立组n=1'),
      'REAL_MANIFEST':(ROOT/'真实分割研究/2026-10-21_第一阶段与Pilot_v1/resource_manifest.json','2.5.1','10视频资源来源'),
      'REAL_MASKS':(ROOT/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot/snapshot_manifest.json','2.5.1','18张人工审核Mask来源'),
      'REVIEW_PDF':(ROOT/'仿真结果/2026-10-26_S3仿真与实物对应性审查_v1/第二章S3_G3仿真与实物对应性完整审查报告.pdf','2.5.4—5','总审查材料；PDF提取存在编码问题，以可读原始MD/JSON/CSV交叉核对'),
    }
    for key,(p,sec,status) in extra.items():evidence.append(dict(id=key,name=key,path=str(p),exists=p.is_file(),sha256=sha(p) if p.is_file() else None,section=sec,status=status))
    dump(src/'本次引用证据及hash索引.json',evidence)
    ix=['# 第二章章节证据及图表来源索引','','此表为内部追溯材料，不写入论文正文；来源状态与科学结论分开。','',
        '|ID|章节|材料及绝对路径|可支持内容/状态|SHA256|','|---|---|---|---|---|']
    for r in evidence:ix.append(f"|{r['id']}|{r['section']}|{r['path']}|{r['status'] if r['exists'] else '缺失'}|{r['sha256']}|")
    ix+=['','## 图稿嵌入与保持','','|图号|章节|来源|状态|SHA256|','|---|---|---|---|---|']
    for r in b.figure_records:ix.append(f"|{r['number']}|{r['section']}|{r['source'] or '暂无正式三方法图'}|{'原文件原样嵌入，未重绘' if r['source'] else '待补'}|{r['sha256'] or ''}|")
    ix+=['','S1使用原始锁定定稿字节；S2及S3使用已有无说明小字候选包原文件，未改颜色、布局、数据或图内对象。Fig.2-1—6使用原科研图字节，原PPT与可编辑源稿不变。']
    (OUT/'第二章章节证据及图表来源索引.md').write_text('\n'.join(ix),encoding='utf-8')
    dump(src/'figure_records.json',b.figure_records)
    report=f'''# 第二章学术结构重构审查报告

2026-10-28 | 对象：v1原稿 | 产物：学术化重写候选v2 | 仅写作与证据复用

## 1. 审查结论

原稿具有完整方法骨架，但研究论证被接口、版本说明及过期进度削弱，尤其2.5.3缺正式S2分析、2.5.4仍把S3列作计划。本轮保持章节和研究定义，以“科学问题—数学与方法—公平对照—结果—机制解释—边界”重组正文，补入已有Pilot、单照片预实验、正式S2和S3证据。不是将英文变量逐项改名。

原稿458个非空段落（含目录、表格单元、公式和图题）逐项登记；正文位置以P编号与N块对照。处置计数：{dict(Counter(r['action'] for r in advice))}。完整逐段CSV保留原文，而MD以90字符摘要便于审核；所有建议仍需作者逐节审定。

## 2. 主要问题与处理

|优先级|问题与依据|修订动作|剩余边界|
|---|---|---|---|
|P1|S3写为尚待闸门/正式实施，与800正式trial冲突|2.5.4改写为560主＋80桥接＋160诊断，引用G3—G5|不是本轮新仿真或独立重跑|
|P1|S2已有CSV但结果笼统待补|补正常、短跳、碎片、伪Mask、jitter/dropout及K重建分析|只支持所设合成条件|
|P1|研究门、完整五状态、保护策略混淆|分清F_arrival、F_full及P_B/P_F；B目标Q关闭|实物历史更新尚不等价|
|P1|流程完成可能被读为运输成功|严格支持路径、source/transport分层，Request/Applied分别评分|不代表真实HV/液滴成功|
|P1|真实训练/独立泛化证据不足|18Mask仅Pilot，三照明独立组方案另附|无正式U-Net与真实闭环结果|
|P1|地图设计/照片H/视频绑定混用风险|像素残差、设计毫米及有效装夹域分开|旧照片H不绑定未验证视频|
|P2|SDK、对象、配置与路径过密|方法正文保留信息作用，张量/协议/字段移技术附录|仍保留必要复现入口|
|P2|小结重述开发步骤|改为条件性发现与结论边界|不承诺普遍算法优势|

## 3. 最短证据链及结果分配

|结果/材料|功能|位置|学术主张|
|---|---|---|---|
|18图传统分割Pilot|必要支持|2.5.1表与段落|所选开发图像中的描述结果，非泛化|
|单照片8fit/16check|必要支持＋测量边界|2.5.2|像素域设计一致性，不是物理计量|
|S1单次运行|机制解释|2.5.3、图2-9/10|解释可观测特征与事件，n=1|
|S2瞬态/空间/历史压力|核心比较|2.5.3、图2-11/12|特定错误的拒绝与代价|
|持续伪Mask、K重建、jitter/dropout|结论限制|2.5.3正文保留|不能证明普遍鲁棒或独立误拒代价|
|S3严格支持路径及风险|核心比较|2.5.4、图2-15|不同策略在固定模型下的完成与安全|
|S3 dropout不利与保护时间代价|结论限制|2.5.4正文保留|完整方法并非总优|
|桥接80/80同事件|归因边界|2.5.4|未发现S/K独立闭环增益|
|源码hash、完整65/40组统计|来源/完整记录|独立证据索引及原CSV|不将研究正文写成审计日志|
|S4完整正交分析|缺失|2.5.4边界|不写为已完成|

## 4. 术语及主张一致性

|统一术语|定义/不用的混称|
|---|---|
|完整五状态识别|五种运动状态＋独立Unknown可靠性；不是S2到达门|
|F_arrival|纯到达门；不执行五状态控制|
|F_full|S3的F_arrival/P_F策略包；不是S/K单独效果|
|算法级仿真|二维点运动＋简化Mask，单位pitch；不是CFD/真实U-Net|
|独立参考支持路径完成|三计划步获当前有效独立支持；不等同流程走完|
|预算化时间代价|成功实际时间，否则24s；不是失败实际耗时|
|人工Mask GT|分割边界参考；不自动产生状态/到达GT|

结果主张在2.1只介绍问题、2.5给证据与局部解释、2.6作综合，不在每处重复全部数值。二元率及bootstrap定义在结果与图注对应，原完整表作为补充材料。未新增p值、显著性或总体准确率。

## 5. 真实数据方案的新增研究安排

以黑色小液滴为核心，三照明条件嵌套于独立加液/装夹采集组。建议先3组流程Pilot，再另采至少12组正式候选，按6/3/3组冻结训练/验证/测试；360—540张只是分层标注预算，不是效力保证。旧18图不进入盲测。透明液滴单列挑战，不新增跨物性必要实验。

增加Mask→覆盖/位置→事件的误差传播，事件真值仍由独立双评审视频区间建立。组间变异、空Mask、缺预测与删失全部保留，避免以帧作为独立n。当前无最终视频，不因方案形成而视为数据已经具备。

## 6. 未关闭的学术事实

- 实际相机/镜头型号、最终顶针装夹高度及采集条件待核验。
- 正式U-Net训练、独立采集测试和跨芯片泛化未完成。
- 最终装夹/视频配准、曝光—ACK—高压时钟计量未完成。
- 真实到达/五状态GT和物理闭环结果缺失。
- S/K误拒代价未独立量化；S4完整正交消融未完成。
- 文献编号尚未逐条核验；保留主题占位，不编造引用。
- 所给总体审查PDF的文字提取存在编码问题，科学事实以配套可读MD和正式CSV/JSON交叉核对。

## 7. 保全与格式

新文档从v1样式、节设置、自动编号与原生公式结构构建；A4、约25mm页边距，宋体12pt正文、Times New Roman西文，非已核验的学校正式模板。目录、图表/公式及图引用使用Word字段。全部插图原文件字节保留，不重绘。

原稿和冻结资料保全结果、数值引用核查、DOCX结构与Word实际渲染记录见QA。保护范围为本轮引用的11,466个既有核心/冻结文档、CSV/JSON、相关源码及索引，不宣称重新审计了全部像素payload；既有G5全payload审计作为历史证据引用。
'''
    (OUT/'第二章学术结构重构审查报告.md').write_text(report,encoding='utf-8')
    appendix='''# 第二章技术参数与实现追溯附录

本材料是内部技术附录，不替代正文论证。

## 保留的实现细节及去向

- 帧接口：SDK帧身份、曝光/接收/可用时间及质量；用于重复/倒序/跨任务防护，字段见已有FrameTiming/FramePacket定义。
- 任务接口：run、step、attempt、epoch及当前source/target；计划步与尝试分开。
- 深度适配：RGB/NCHW/float32、归一化、logits或概率、恢复原ROI；须与真实训练导出一致。
- 串口：BEGIN/SET/COMMIT与同序列ACK，最多两次通信重发；与液滴Retry、Recovery及返回resend分账。
- 研究参数：S3 G3 JSON为正式来源，24s/三计划步/7次Applied上限；实物YAML初值不冒称研究冻结参数。
- S3 raw历史与实物PriorFeatures条件历史不同，同输入一致性仍需单独验证；本轮不改任何实现。
- 未启用corridor_width或正向运动硬门不进入已经验证算法清单。

## 内部待办

设备铭牌→最终几何与H→独立采集与人工GT→真实模型和传统方法冻结比较→真实到达评价→独立电气/时钟安全验收→实物闭环。已有S3正式完成，不再列作待扫描。正式学校模板及引用由作者核验。

## 实物初始值与S3冻结值分列

|参数|实物软件初始值（未校准）|S3正式冻结值|
|---|---|---|
|目标/源覆盖门|0.75/0.10|0.85/0.08|
|到达证据|5帧且0.25s；最大间隔0.25s|5帧且0.25s；最大间隔0.18s|
|质心跨度/覆盖极差|0.5mm/0.15|0.11pitch/0.15|
|质量|置信≥0.2，面积10—100000px，1个显著组件|相同定义；合成置信不是实测概率|
|无进展/尝试上限|8s/16s|1.4s/2.6s|
|无可靠观测超时|2s|1.8s|
|源准备/恢复等待|10s/8s|2.6s/2.6s|
|Retry/Recovery预算|2/2|2/1；另有每计划步7次Applied及24s总预算|
|净改善量|0.1mm|0.04pitch|

以上引用configs/chapter2_experiment.yaml与S3 G3正式JSON，不跨单位移植。S3参数和正式结果保持冻结，不依据后续真实数据回改。

## 七场景的模型假设

normal使用基础参数；delayed在Applied后1.15s响应；partial_stall首次尝试目标限制为当前至目标方向的0.58比例，后续尝试可解除；deviation首次目标附加0.8pitch横向偏移；failure运输目标保持起点。jitter位置误差尺度至少0.085pitch；dropout丢帧概率至少0.35且0.8—1.4s有连续缺帧段。这些是既有模型规则，不是实物故障统计或液滴真实物理参数。
'''
    (OUT/'第二章技术参数与实现追溯附录.md').write_text(appendix,encoding='utf-8')
    for name,fields in {
      'acquisition_groups.csv':['group_id','parent_group','loading_id','mount_id','session_id','date','chip_id','chip_batch','volume','volume_unit','volume_method','droplet_material','camera_model','camera_serial','lens_model','chip_height','cover_plate','split','missing_reason'],
      'videos.csv':['video_id','group_id','path','sha256','light_condition','light_setting','exposure','exposure_unit','gain','auto_exposure','auto_white_balance','resolution','fps','fps_quality','timestamp_source','clock_domain','roi_x','roi_y','roi_w','roi_h','calibration_binding_id','source_id','target_id','task_verified'],
      'segmentation_samples.csv':['image_id','video_sha256','source_frame_id','image_sha256','mask_sha256','roi_x','roi_y','roi_w','roi_h','split','sampling_stratum','seg_review_status','reviewer','uncertainty','annotation_version'],
      'arrival_review.csv':['reviewer_id','task_id','group_id','video_sha256','source_id','target_id','last_not_arrived_frame','first_arrived_frame','lower_s','upper_s','clock_domain','support_episode_id','left_censored','right_censored','uncertain','reason','review_version'],
      'state_review.csv':['reviewer_id','task_id','video_sha256','frame_start','frame_end','state_label','uncertain','reason','review_version'],
    }.items():
        p=OUT/'数据集空白模板'/name;p.parent.mkdir(exist_ok=True)
        with p.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerow(fields)
    guide='''# 生成与更新说明

2026-10-28。本候选从v1结构和样式另存，不覆盖旧v1或既有语言修订v2。主文档为学术化重写，不是正式学校套版。

源正文与数据方案见source；生成器只读原DOCX、冻结CSV及图稿，不导入仿真/训练运行器。首次生成拒绝覆盖同名文件；开发排版修复必须显式使用--replace-generated，不用于覆盖后续人工编辑文档。正式研究参数、统计与图稿不由此脚本更新。

依赖：Codex bundled Python、python-docx、lxml、Pillow、PyMuPDF；实际渲染使用独立隐藏Word实例更新字段并导出内部QA PDF。保留原图hash、原生OMML及Word多级标题、SEQ/REF/TOC字段。标题和正文可直接继续编辑。

后续手工Word修改不会回流Markdown，重新生成前须同步并另存新版本。数据集模板均只有表头，不含人工标注或真实采集记录。文献及实物缺口占位尚需作者补充。

运行：在原仓库使用bundled Python执行scripts/build_chapter2_restructured_v2.py；不要重跑chapter2_s2/s3仿真入口。本轮无训练、无高压、无Commit/Push。

本次正文与证据快照已在source保存；该目录中的脚本是存档副本，仍依赖原工作区的辅助脚本和绝对来源，不能直接从source子目录当成可迁移独立程序运行。重新盘点应使用新的输出版本目录，保护基线不得覆盖。后续人工编辑后优先另存Word，避免以生成器覆盖人工修订。
'''
    (OUT/'第二章初稿生成与更新说明.md').write_text(guide,encoding='utf-8')
    shutil.copyfile(CONTENT,src/CONTENT.name);shutil.copyfile(DATASET,src/DATASET.name)
    shutil.copyfile(Path(__file__),src/Path(__file__).name)
    dump(OUT/'QA/writing_audit.json',dict(source_paragraphs=len(original),reviewed_paragraphs=len(advice),actions=dict(Counter(r['action'] for r in advice)),new_blocks=len(newblocks),new_body_characters=sum(counts.values()),source_v1_hash=sha(V1),simulations_run=0,training_runs=0,physical_experiments=0))

def audit(path,b):
    with ZipFile(path) as z:
        t=etree.fromstring(z.read('word/document.xml'));text=''.join(t.xpath('//w:t/text()',namespaces=NS))
        hashes={hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}
        assert all(r['sha256'] in hashes for r in b.figure_records if r['source'])
        required=('800','S3','20/20','14/20','12/20','1.968','0.9742','0.9129','17/20','1/20','11.792','10.891','80/80','【待补实物结果')
        assert all(x in text for x in required),[x for x in required if x not in text]
        assert not any(x in text for x in ('source-01.png','本版暂不','S3专项尚无','用户确认','当前仓库','FramePacket','StepContext'))
        findings=dict(figures=len(b.figure_records),embedded_images=len(hashes),all_inserted_bytes_preserved=True,
          equations=len(t.xpath('//m:oMath',namespaces=NS)),tables=len(t.xpath('//w:tbl',namespaces=NS)),
          headings=b.heading_records,body_text_characters=len(text),required_numeric_tokens=list(required),
          source_v1_hash=sha(V1),document_sha256=sha(path))
        dump(OUT/'QA/docx_structure_check.json',findings)
    print(json.dumps(findings,ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replace-generated',action='store_true');args=ap.parse_args()
    path=OUT/NAME
    if path.exists() and not args.replace_generated:raise FileExistsError(path)
    e,s,_=load();configure_tables(e,s);f=figures(e);b=Thesis(e,f);b.build(path);support(b,e,s,f);audit(path,b)
if __name__=='__main__':main()
