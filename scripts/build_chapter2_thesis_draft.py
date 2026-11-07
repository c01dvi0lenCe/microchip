"""Build an editable, evidence-bound Chinese Chapter 2 methods-first draft.

Uses python-docx and native OMML. Does not run research algorithms or experiments.
Existing target documents are refused unless --replace-generated is explicit.
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
from pathlib import Path
from zipfile import ZipFile
from copy import deepcopy

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

from chapter2_thesis_evidence import REPO, ROOT, OUT, S1, S2, CLOSE, PILOT, REG, collect, dump, sha

CONTENT=REPO/'docs/chapter2_thesis_draft_content_v1.md'
NAME='第二章_单液滴视觉闭环控制_硕士论文工作初稿_v1.docx'

TABLES={
 'times':('视觉闭环系统中的时间尺度', ['层次','时间来源与作用','本文记录原则'], [
 ['外部激励波形','外部电源的高压激励频率','实物参数待记录；不等于AM刷新'],
 ['AM阵列扫描','20×21扫描，接口约定300 Hz','与第一章一致；实测仍需硬件证据'],
 ['相机采样','曝光或SDK/主机接收事件','标明来源；容器fps不替代曝光'],
 ['图像与状态处理','图像可用后推理、计算与确认','分段记录耗时与证据等待'],
 ['电极任务更新','到达事件或有界保护动作','事件触发，不设为固定刷新频率']
 ],[2.7,6.0,7.3]),
 'gates':('状态与到达判定的信息约束', ['符号','信息来源','作用与边界'],[
 ['C0','帧身份、时钟、StepContext、Applied','始终开启；非法数据与跨任务证据不进入确认'],
 ['G','η_s、η_t','液滴面积为分母的源释放与目标覆盖'],
 ['Q','置信、面积、显著连通区域','观测质量约束，不保证高置信Mask一定正确'],
 ['W','连续帧、跨度、断档及稳定范围','连续证据，不能替代独立参考'],
 ['S','当前源/目标多边形与观测质心','任务空间位置；不是任意电极检测'],
 ['K','质心历史与实际时间差','有限历史一致性；首帧与持续伪观测有边界']
 ],[1.4,5.4,9.2]),
 'states':('生产识别器的状态含义与确认逻辑', ['输出','候选条件概括','确认或可靠性要求'],[
 ['Stationary','有效、空间/时序一致且速度低于阈值','一般一致性窗口；并非源准备事件的别名'],
 ['Moving','有效、空间/时序一致且速度达到阈值','一般一致性窗口；仍受无进展保护'],
 ['Partial','目标进入阈值已满足，源残留仍高','按规则形成候选；不代表无限等待'],
 ['Arrived','目标覆盖、源释放和目标位置满足','到达连续窗口完成后才输出'],
 ['Deviation','有效且时序一致的空间偏离','持续偏离确认；孤立异常不直接Recovery'],
 ['Unknown','无效、时序冲突或证据尚不足','可靠性标记，不宣称真实第六运动状态']
 ],[2.8,6.5,6.7]),
 'thresholds':('生产初始配置与S2研究配置的区别', ['参数','生产初始配置','S2强组研究配置'],[
 ['η_t / η_s门','≥0.75 / ≤0.10','≥0.85 / ≤0.08'],
 ['最少帧数 / 跨度','5帧 / 0.25 s','5帧 / 0.25 s'],
 ['最大证据间隔','0.25 s','0.18 s'],
 ['质心稳定跨度','0.5 mm，须真实标定','0.11 pitch'],
 ['覆盖稳定极差','0.15','0.15'],
 ['位置外扩容差','0.5 mm，须真实标定','0.18 pitch'],
 ['质量检查','置信≥0.2；面积10—100000 px；1个显著连通区域','相同数值定义；合成置信非真实校准'],
 ['适用边界','初始软件参数，未实物调优','冻结模拟对照参数，不外推毫米尺度']
 ],[4.2,5.7,6.1]),
 'actions':('事件驱动控制动作与证据要求', ['动作','触发或目的','执行后证据与边界'],[
 ['Hold','尚未获得推进或保护证据','维持当前目标；等待新观测'],
 ['Start','源准备连续确认','首次激活目标；不同于Arrived更新'],
 ['Update','当前步ArrivalEvent有效且未消费','激活下一目标；新上下文重建窗口'],
 ['Retry','无进展或尝试超时且预算允许','重试当前目标；与通信同序列重发分开'],
 ['Recovery','持续Deviation或重试耗尽且预算允许','只回当前源区；确认后再恢复运输'],
 ['Complete / Stop','终点确认 / 超时、质量或预算保护','结束或保护停止；不伪造后续Applied']
 ],[3.1,6.0,6.9]),
 'simulation':('当前算法仿真的基础参数与单位', ['项目','值或定义','解释'],[
 ['几何','420电极示例模板；pitch','非Gerber真实设计毫米地图'],
 ['路线','190→191→192→172','S2只固定首步190→191'],
 ['积分 / 名义速度','0.01 s / 1.5 pitch/s','每seed速度因子0.8—1.2；小随机扰动'],
 ['模拟Applied / 常规响应','0.04 s / 0.18 s','与真实ACK、物理响应分开'],
 ['模拟相机','20 fps；曝光0.008 s','显式simulation时间'],
 ['处理可用时间','曝光结束＋0.04 s＋[0,0.015) s抖动','不是U-Net实测耗时'],
 ['Mask','圆形；半径0.26 pitch；48 px/pitch','半径扰动0.015 pitch；非真实分割'],
 ['位置误差 / 基础丢帧','0.018 pitch / 0.03','异常场景按冻结规则变化'],
 ['独立参考','半径0.09 pitch；速度≤0.06 pitch/s；驻留0.15 s','只供评分，算法不可见']
 ],[4.1,6.3,5.6]),
 'methods':('S2同输入到达事件比较方法', ['方法','G/C0','Q','W','S','K'],[
 ['B_single_frame','开','关','关','关','关'],
 ['BTQ','开','开','开','关','关'],
 ['BTQ+S','开','开','开','开','关'],
 ['BTQ+K','开','开','开','关','开'],
 ['F_arrival','开','开','开','开','开'],
 ['BQ_single_frame（辅助）','开','开','关','关','关']
 ],[6.4,2.0,1.9,1.9,1.9,1.9]),
 'conditions':('S2条件及研究目的', ['条件','来源类型','检验问题'],[
 ['A_normal','model-generated','正常稳定到达负对照'],
 ['B_flash_short','synthetic stress','短暂覆盖闪变与连续证据'],
 ['B_flash_window','synthetic stress','达到窗口长度的伪覆盖'],
 ['C_jump_short','synthetic stress','合法新帧中的短暂位置跳变'],
 ['C_jump_persistent','synthetic stress','持续伪观测与有限历史适应'],
 ['D_tail_false','synthetic stress','覆盖满足但质心空间异常'],
 ['D_tail_true_cost','synthetic stress','真实到达与异常Mask共存；代价可辨识性待审'],
 ['E_lowconf_false','synthetic stress','低质量伪观测的拒绝'],
 ['E_lowconf_true','synthetic stress','低质量真实到达的拒绝代价'],
 ['E_highconf_false','synthetic stress','高置信错误Mask边界'],
 ['F_jitter','model-generated','位置抖动与稳定窗口'],
 ['F_dropout','model-generated','丢帧与确认时效'],
 ['F_gap','synthetic stress','长断档与窗口重建']
 ],[5.1,4.0,6.9]),
 'studies':('闭环与消融研究的比较层次', ['研究层次','共同条件','主要评价'],[
 ['S2同输入到达门','共同缓存、G/Q/W/C0与任务','事件支持、错误、漏确认、延迟'],
 ['S3四策略系统比较','源准备、模型、外生随机流、预算','参考支持路径、安全更新、时间/动作代价'],
 ['S3到达门×保护桥接','固定其中一个因素，比较另一因素','区分S/K到达门与五状态保护作用'],
 ['S4独立模块分析','C0常开，S/W/K/Q正交','模块收益、拒绝代价及失效边界']
 ],[4.2,5.9,5.9])
}

FIGURES={
 1:dict(title='单液滴视觉闭环控制系统架构',section='2.2.1',source='source-01.png（F01）',status='原图已核实；本版预留，未改图'),
 2:dict(title='视觉成像与芯片结构',section='2.2.1',source='source-04.png（F02）',status='保留原第4页图；设备型号待核实'),
 3:dict(title='图像采集、识别与电极控制的多时间尺度关系',section='2.2.2',source='source-05.png（F03）',status='原Fig.2-3保留；未重绘'),
 4:dict(title='420电极数字地图与图像—电极配准原理',section='2.3.2',source='source-06.png（F04）',status='原Fig.2-4保留；非实拍精度结果'),
 5:dict(title='任务空间与连续时序先验的状态识别框架',section='2.4.1',source='source-07.png（F05）',status='原Fig.2-5保留；不改技术关系'),
 6:dict(title='五状态识别与事件驱动控制逻辑',section='2.4.3',source='source-08.png（F06）',status='原Fig.2-6保留；正文以当前代码为准'),
 7:dict(title='真实液滴分割Pilot及算法对比位置',section='2.5.1',source='Pilot分割基线_v2的review.html、per_image.csv（E12—E14）',status='已有真实Pilot；正式U-Net图及结果待补'),
 8:dict(title='单照片配准独立检查点与残差',section='2.5.2',source='independent_points.csv、residual_vectors.png（E15—E16）',status='预实验素材已有；本版暂不展开结果'),
 9:dict(title='单液滴六阶段空间观测与电极任务关系（S1-A）',section='2.5.3',source='S1-A_六阶段空间观测.png（E18）',status='已定稿，原样插入',asset='s1a',
     note='SIMULATION，n=1机制示例；trial为normal:262000:F:end_to_end，单位pitch。内部位置、模拟Mask和观测质心分别显示；六时刻与日志一致。0.50 s为源准备确认与启动，不改写为Stationary；不补造未发生状态或动作。'),
 10:dict(title='同一闭环trial的任务阶段与空间特征（S1-B）',section='2.5.3',source='S1-B_分阶段空间特征.png（E19）',status='已定稿，原样插入',asset='s1b',
     note='SIMULATION，n=1；来源同图2-9。保留内部/观测x、y及η_s、η_t。目标距离和方向进展由实际处理Mask质心计算，方向进展为pitch投影距离，不是无量纲p/L；模拟观测不是实际U-Net结果。'),
 11:dict(title='同一共同缓存下的到达事件判定时序（S2-A）',section='2.5.3',source='S2-A_同输入到达时序_收尾候选.png（E28）',status='正式数据图已存在；本版先保留位置，结果分析待写'),
 12:dict(title='到达算法的代表条件与失效边界（S2-B）',section='2.5.3',source='S2-B_代表条件与失效边界_正文候选.png（E29）',status='6条件正文图及完整13条件附表已存在；待结果章节修订')
}

def el(tag,**attrs):
    x=OxmlElement(tag)
    for k,v in attrs.items():x.set(qn(k),str(v))
    return x

def mt(text):
    r=el('m:r');p=el('m:rPr');p.append(el('m:sty',**{'m:val':'p'}));r.append(p)
    t=el('m:t');t.text=str(text);r.append(t);return r

def sub(base,index):
    x=el('m:sSub');e=el('m:e');e.append(mt(base));s=el('m:sub');s.append(mt(index));x.extend([e,s]);return x

def subsup(base,index,power):
    x=el('m:sSubSup');e=el('m:e');e.append(mt(base));s=el('m:sub');s.append(mt(index));p=el('m:sup');p.append(mt(power));x.extend([e,s,p]);return x

def frac(a,b):
    x=el('m:f');n=el('m:num');d=el('m:den');n.append(mt(a));d.append(mt(b));x.extend([n,d]);return x

def vec(items):
    d=el('m:d');pr=el('m:dPr');pr.extend([el('m:begChr',**{'m:val':'['}),el('m:endChr',**{'m:val':']'})]);d.append(pr)
    e=el('m:e');m=el('m:m')
    for item in items:
        row=el('m:mr');cell=el('m:e');cell.append(mt(item));row.append(cell);m.append(row)
    e.append(m);d.append(e);return d

def parts(*values):return [mt(v) if isinstance(v,str) else v for v in values]

def summation(lower,body):
    x=el('m:nary');pr=el('m:naryPr')
    pr.extend([el('m:chr',**{'m:val':'∑'}),el('m:limLoc',**{'m:val':'undOvr'}),el('m:supHide',**{'m:val':'1'})]);x.append(pr)
    lo=el('m:sub');lo.append(mt(lower));hi=el('m:sup');e=el('m:e');e.append(mt(body));x.extend([lo,hi,e]);return x

EQUATIONS={
 'latency':lambda:parts(sub('T','total'),' = ',sub('T','communication'),' + ',sub('T','vision'),' + ',sub('T','evidence')),
 'mask':lambda:parts(sub('M','i'),' = {(u,v) | ',sub('P','i'),'(u,v) ≥ τ}'),
 'centroid':lambda:parts(sub('A','i'),' = |',sub('M','i'),'|， ',subsup('c','i','px'),' = ',frac('1','Aᵢ'),' ',summation('(u,v)∈Mᵢ','(u,v)')),
 'homography':lambda:parts('λ ',vec(['x','y','1']),' = H ',vec(['u','v','1'])),
 'residual':lambda:parts(sub('e','j'),' = ‖π(H⁻¹ [',sub('q','j'),',1]ᵀ) − ',sub('p','j'),'‖₂'),
 'eta':lambda:parts(sub('η','s'),' = ',frac('|M ∩ Ωₛ|','|M|'),'， ',sub('η','t'),' = ',frac('|M ∩ Ωₜ|','|M|')),
 'rho':lambda:parts(sub('ρ','t'),' = ',frac('|M ∩ Ωₜ|','|Ωₜ|')),
 'distance':lambda:parts(sub('d','t'),' = ‖c − t‖₂， L = ‖t − s‖₂， a = ',frac('t − s','L')),
 'projection':lambda:parts('p = (c − s) · a， ',sub('e','⊥'),' = aₓ(cᵧ − sᵧ) − aᵧ(cₓ − sₓ)'),
 'velocity':lambda:parts(sub('v','i'),' = ',frac('‖cᵢ − cᵢ₋₁‖₂','tᵢ − tᵢ₋₁'),'， ',sub('v','∥,i'),' = ',frac('pᵢ − pᵢ₋₁','tᵢ − tᵢ₋₁')),
 'gate':lambda:parts(sub('g','i'),' = [ηₜ,ᵢ ≥ τₐ] ∧ [ηₛ,ᵢ ≤ τᵣ]'),
 'prediction':lambda:parts('ĉᵢ = cᵢ₋₁ + ',frac('cᵢ₋₁ − cᵢ₋₂','tᵢ₋₁ − tᵢ₋₂'),' (tᵢ − tᵢ₋₁)'),
 'kinematic':lambda:parts('‖cᵢ − cᵢ₋₁‖₂ ≤ vₘₐₓ Δt + εₚ， ‖cᵢ − ĉᵢ‖₂ ≤ εₖ + vₘₐₓ Δt'),
 'window':lambda:parts('|Jᵢ| ≥ ',sub('N','W'),'， ',sub('t','last'),' − ',sub('t','first'),' ≥ ',sub('T','W'),'， ',sub('D','c'),' ≤ ',sub('δ','c'),'， ',sub('D','η'),' ≤ ',sub('δ','η')),
 'progress':lambda:parts('pᵢ − ',sub('p','best'),' ≥ ',sub('ε','prog'),' ⇒ ',sub('p','best'),' ← pᵢ， ',sub('t','prog'),' ← tᵢ'),
 'segmentation_metrics':lambda:parts('Dice = ',frac('2TP','2TP + FP + FN'),'， IoU = ',frac('TP','TP + FP + FN')),
 'world':lambda:parts('rₖ₊₁ = rₖ + min(v₀ ',sub('a','seed'),' Δt, ‖gₖ − rₖ‖₂) ',frac('gₖ − rₖ','‖gₖ − rₖ‖₂'),' + ξₖ'),
 'reference':lambda:parts('‖r(t) − ',sub('t','center'),'‖₂ ≤ ',sub('r','ref'),'， ‖ṙ(t)‖₂ ≤ ',sub('v','ref'),'， dwell ≥ ',sub('T','ref')),
 'event_metrics':lambda:parts('支持率 = ',frac('S_H','R'),'， 提前率 = ',frac('P','N'),'， 无支持率 = ',frac('U','N'),'， 漏确认率 = ',frac('M_H','R')),
 'delay':lambda:parts(sub('ΔT','confirm'),' ∈ [c − u, c − l]')
}

class Builder:
    def __init__(self,evidence):
        self.doc=Document();self.evidence=evidence;self.eqcount=0;self.tablecount=0
        self.figure_records=[];self.table_records=[];self.heading_records=[]
        self.section='';self.setup()

    def setup(self):
        d=self.doc;s=d.sections[0]
        s.page_width=Cm(21);s.page_height=Cm(29.7)
        s.top_margin=s.bottom_margin=s.left_margin=s.right_margin=Cm(2.5)
        s.header_distance=s.footer_distance=Cm(1.25)
        for style in ('Normal','Body Text','Title','Subtitle','Heading 1','Heading 2','Caption','TOC 1','TOC 2'):
            if style not in d.styles:continue
            st=d.styles[style];st.font.name='Times New Roman';st.font.color.rgb=RGBColor(0,0,0)
            fonts=st._element.get_or_add_rPr().get_or_add_rFonts()
            for name in list(fonts.attrib):
                if 'Theme' in name:del fonts.attrib[name]
            for name,value in (('ascii','Times New Roman'),('hAnsi','Times New Roman'),('eastAsia','宋体')):fonts.set(qn('w:'+name),value)
        normal=d.styles['Normal'];normal.font.size=Pt(12)
        pf=normal.paragraph_format;pf.line_spacing=1.5;pf.first_line_indent=Pt(24);pf.space_after=Pt(0);pf.widow_control=True
        for name,size in (('Title',18),('Subtitle',12),('Heading 1',14),('Heading 2',12),('Caption',10.5)):
            st=d.styles[name];st.font.size=Pt(size);st.font.bold=name not in ('Subtitle','Caption')
            st.paragraph_format.first_line_indent=Pt(0)
            if name.startswith('Heading'):
                st.paragraph_format.keep_with_next=True;st.paragraph_format.space_before=Pt(14);st.paragraph_format.space_after=Pt(7)
                st._element.rPr.rFonts.set(qn('w:eastAsia'),'黑体')
            if name in ('Caption','Subtitle'):st.paragraph_format.line_spacing=1.15
        cap=d.styles['Caption'];cap.paragraph_format.space_before=Pt(5);cap.paragraph_format.space_after=Pt(7)
        title=d.styles['Title'];title.paragraph_format.space_after=Pt(16)
        # Some bundled blank templates include a blue rule in Title/Subtitle.
        for border in list(d.styles.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
        # Explicit multilevel heading numbering, preserving the fixed chapter 2.
        numbering=d.part.numbering_part.element
        aid=91;nid=91
        an=el('w:abstractNum',**{'w:abstractNumId':aid});an.append(el('w:multiLevelType',**{'w:val':'multilevel'}))
        for level,fmt,style in ((0,'2.%1','Heading1'),(1,'2.%1.%2','Heading2')):
            lv=el('w:lvl',**{'w:ilvl':level});lv.extend([el('w:start',**{'w:val':1}),el('w:numFmt',**{'w:val':'decimal'}),el('w:lvlText',**{'w:val':fmt}),el('w:suff',**{'w:val':'space'}),el('w:pStyle',**{'w:val':style})]);an.append(lv)
        numbering.append(an);num=el('w:num',**{'w:numId':nid});num.append(el('w:abstractNumId',**{'w:val':aid}));numbering.append(num)
        self.numid=nid
        for level,style in enumerate(('Heading 1','Heading 2')):
            pr=d.styles[style]._element.get_or_add_pPr();np=el('w:numPr');np.extend([el('w:ilvl',**{'w:val':level}),el('w:numId',**{'w:val':nid})]);pr.append(np)
        settings=d.settings.element
        settings.append(el('w:updateFields',**{'w:val':'true'}))
        settings.append(el('w:doNotAutoCompressPictures'))
        settings.append(el('m:mathPr')) if settings.find(qn('m:mathPr')) is None else None
        footer=s.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
        footer.paragraph_format.first_line_indent=Pt(0)
        self.field(footer,'PAGE','1')
        for r in footer.runs:r.font.size=Pt(10)
        d.core_properties.title='第二章 基于视觉反馈的单液滴运动状态识别与闭环控制'
        d.core_properties.subject='硕士学位论文方法型工作初稿 v1'
        d.core_properties.author='';d.core_properties.last_modified_by=''
        d.core_properties.comments='2026-10-26；来源可追溯；未运行新实验；结果分析暂缓。'

    @staticmethod
    def field(p,code,result):
        for typ in ('begin','instruction','separate','result','end'):
            r=p.add_run()
            if typ=='instruction':x=el('w:instrText');x.set(qn('xml:space'),'preserve');x.text=' '+code+' ';r._r.append(x)
            elif typ=='result':r.text=str(result)
            else:r._r.append(el('w:fldChar',**{'w:fldCharType':typ}))

    def paragraph(self,text,style=None):
        p=self.doc.add_paragraph(style=style)
        self.fill(p,text);return p

    def fill(self,p,text):
        atoms={
            'c_i^px':lambda:subsup('c','i','px'),
            'c_(i−1)':lambda:sub('c','i−1'),
        }
        for base,index in [('P','i'),('A','i'),('M','i'),('η','s'),('η','t'),('ρ','t'),('Ω','s'),('Ω','t'),
             ('d','t'),('e','⊥'),('p','j'),('q','j'),('e','j'),('g','i'),('τ','a'),('τ','r'),
             ('v','max'),('ε','p'),('ε','k'),('N','W'),('T','W'),('D','c'),('D','η'),
             ('p','best'),('ε','prog'),('t','prog'),('J','i'),('r','k'),('g','k'),('v','0'),('a','seed'),('ξ','k'),('S','H'),('M','H')]:
            atoms[base+'_'+index]=lambda b=base,i=index:sub(b,i)
        atom_pattern='|'.join(re.escape(k) for k in sorted(atoms,key=len,reverse=True))
        # Never rewrite an identifier fragment (e.g. d_t inside end_to_end).
        pattern=r'图2-(\d+)|(?<![A-Za-z0-9_])(?:'+atom_pattern+r')(?![A-Za-z0-9_])'
        last=0
        for m in re.finditer(pattern,text):
            p.add_run(text[last:m.start()]);token=m.group(0)
            if token.startswith('图2-'):
                p.add_run('图');self.field(p,f'REF ch2_fig_{m.group(1)} \\h',f'2-{m.group(1)}')
            else:
                math=el('m:oMath');math.append(atoms[token]());p._p.append(math)
            last=m.end()
        p.add_run(text[last:])

    def heading(self,text,level):
        number,title=text.split(' ',1);self.section=number
        p=self.doc.add_paragraph(title,style=f'Heading {level}')
        self.heading_records.append(dict(number=number,title=title,level=level))
        return p

    def caption(self,kind,n,title):
        p=self.doc.add_paragraph(style='Caption');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.add_run('图' if kind=='Figure' else '表')
        bid=1000+n if kind=='Figure' else 2000+n
        mark=f'ch2_fig_{n}' if kind=='Figure' else f'ch2_tbl_{n}'
        p._p.append(el('w:bookmarkStart',**{'w:id':bid,'w:name':mark}))
        p.add_run('2-');self.field(p,f'SEQ {kind}Ch2 \\* ARABIC',n)
        p._p.append(el('w:bookmarkEnd',**{'w:id':bid}));p.add_run(' '+title)
        return p

    def equation(self,key):
        self.eqcount+=1;p=self.doc.add_paragraph()
        pf=p.paragraph_format;pf.first_line_indent=Pt(0);pf.line_spacing=1.2;pf.space_before=Pt(7);pf.space_after=Pt(7)
        pf.tab_stops.add_tab_stop(Cm(7.1),WD_TAB_ALIGNMENT.CENTER);pf.tab_stops.add_tab_stop(Cm(16),WD_TAB_ALIGNMENT.RIGHT)
        p.add_run('\t');math=el('m:oMath')
        for element in EQUATIONS[key]():math.append(element)
        p._p.append(math);p.add_run('\t（2-');self.field(p,'SEQ EquationCh2 \\* ARABIC',self.eqcount);p.add_run('）')

    def table(self,key):
        title,headers,data,widths=TABLES[key];self.tablecount+=1
        p=self.caption('Table',self.tablecount,title);p.paragraph_format.keep_with_next=True
        table=self.doc.add_table(rows=1,cols=len(headers));table.alignment=WD_TABLE_ALIGNMENT.CENTER;table.autofit=False
        for c,width in zip(table.columns,widths):c.width=Cm(width)
        for c,width in zip(table.rows[0].cells,widths):c.width=Cm(width)
        for cell,text in zip(table.rows[0].cells,headers):self.fill(cell.paragraphs[0],text)
        table.rows[0]._tr.get_or_add_trPr().append(el('w:tblHeader',**{'w:val':'true'}))
        for row in data:
            cells=table.add_row().cells
            for cell,text,width in zip(cells,row,widths):self.fill(cell.paragraphs[0],text);cell.width=Cm(width)
        pr=table._tbl.tblPr;borders=el('w:tblBorders')
        for side in ('top','left','bottom','right','insideH','insideV'):borders.append(el('w:'+side,**{'w:val':'single','w:sz':4,'w:color':'D9D9D9'}))
        pr.append(borders)
        margins=el('w:tblCellMar')
        for side in ('top','bottom','left','right'):margins.append(el('w:'+side,**{'w:w':85,'w:type':'dxa'}))
        pr.append(margins)
        for ri,row in enumerate(table.rows):
            row._tr.get_or_add_trPr().append(el('w:cantSplit'))
            for ci,cell in enumerate(row.cells):
                cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                if ri==0:cell._tc.get_or_add_tcPr().append(el('w:shd',**{'w:fill':'F0F0F0'}))
                for p in cell.paragraphs:
                    f=p.paragraph_format;f.first_line_indent=Pt(0);f.space_after=Pt(0);f.space_before=Pt(0);f.line_spacing=1.15
                    if ri==0:f.keep_with_next=True
                    p.alignment=WD_ALIGN_PARAGRAPH.CENTER if ri==0 or key=='methods' and ci>0 else WD_ALIGN_PARAGRAPH.LEFT
                    for r in p.runs:r.font.size=Pt(10.5);r.bold=ri==0
        spacer=self.doc.add_paragraph();spacer.paragraph_format.space_after=Pt(2);spacer.paragraph_format.line_spacing=1;spacer.paragraph_format.first_line_indent=Pt(0)
        self.table_records.append(dict(number=f'2-{self.tablecount}',section=self.section,title=title,key=key))

    def figure(self,n):
        info=FIGURES[n]
        if 'asset' in info:
            path=Path(self.evidence['assets'][info['asset']]);p=self.doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.keep_with_next=True;p.paragraph_format.space_before=Pt(6)
            picture=p.add_run().add_picture(str(path),width=Cm(15.5))
            dp=picture._inline.docPr;dp.set('descr',info['note']);dp.set('title',info['title'])
        else:
            p=self.paragraph(f'【待插图：Fig.2-{n}，{info["title"]}，来源文件：{info["source"]}，当前状态：{info["status"]}。】')
            p.paragraph_format.first_line_indent=Pt(0)
            p.paragraph_format.space_before=Pt(6);p.paragraph_format.space_after=Pt(5);p.paragraph_format.keep_with_next=True
            for r in p.runs:r.font.size=Pt(10.5)
        self.caption('Figure',n,info['title'])
        if info.get('note'):
            p=self.paragraph(info['note']);p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.line_spacing=1.15
            for r in p.runs:r.font.size=Pt(10.5)
        self.figure_records.append(dict(number=f'2-{n}',**info))

    def front(self):
        p=self.doc.add_paragraph('硕士学位论文第二章',style='Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p=self.doc.add_paragraph('基于视觉反馈的单液滴运动状态识别与闭环控制',style='Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        for text in ('工作初稿 v1','论文题目  面向可抛式垂直激励数字微流控芯片的有源矩阵驱动平台研究','版本日期  2026年10月26日'):
            p=self.paragraph(text);p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.space_after=Pt(12)
        self.paragraph('本版先形成完整章节结构、研究方法、核心算法和实验组织正文。依当前写作顺序，正式S2性能分析暂不展开；已存在结果标为待写入，尚缺真实证据标为待采集或待验证，二者分别管理。')
        self.paragraph('S1-A与S1-B按已定稿源文件原样插入。Fig.2-1至Fig.2-6保留原研究图与编号，本版仅建立插图位置和引用。所有仿真均限定为简化二维单液滴视觉算法仿真，不是CFD或实物电润湿计算。')
        self.paragraph('排版暂采用A4、宋体正文、黑体标题及Times New Roman西文的统一工科样式，尚未套用已核实的浙江大学正式学位论文模板。正文、表格和公式均可继续编辑。')
        self.doc.add_page_break()
        p=self.doc.add_paragraph('目录',style='Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p=self.doc.add_paragraph();p.paragraph_format.first_line_indent=Pt(0)
        self.field(p,'TOC \\o "1-2" \\h \\z \\u','目录字段将在Word更新后显示章节及页码')
        self.doc.add_page_break()
        p=self.doc.add_paragraph('第二章 基于视觉反馈的单液滴运动状态识别与闭环控制',style='Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER

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
                p=self.paragraph(text[6:]);p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.keep_with_next=True;p.paragraph_format.space_before=Pt(7)
                for r in p.runs:r.bold=True
            else:self.paragraph(text.replace('\n',' '))
        self.doc.save(path)

def supporting_files(b,e,out):
    evidence=['# 第二章章节证据对应表','',
      '版本：2026-10-26。当前Word为方法型工作初稿，结果已存在但按写作顺序暂缓正文分析；缺实验与待写入分开。',
      '', '|资料ID|资料来源|章节位置|可支持的结论或用途|证据状态|','|---|---|---|---|---|']
    for r in e['evidence']:
        evidence.append(f'|{r["id"]}|{r["name"]}<br>{r["path"]}|{r["section"]}|{r["status"]}|'+('已读取/核实来源' if r['exists'] else '缺失')+'|')
    evidence.extend(['','## 当前不能支持的结论','',
        '- 配置型号不能替代相机、镜头铭牌；最终装置参数尚需核实。',
        '- 18图是人工审核开发Pilot；没有正式真实U-Net训练及独立泛化证据。',
        '- 单照片配准不是最终装置标定，也不是独立物理毫米计量精度。',
        '- S1 n=1解释软件反馈机制；不等于五状态实际准确率。',
        '- 旧21共同缓存BTQ/F事件和时间一致；正式S2压力条件不能外推普遍优势。',
        '- F_arrival不是完整五状态控制器；S2不是路径成功率研究。',
        '- 新S3/S4专项尚无正式结果，不能将v1/v2历史不同版本直接合池。',
        '- 尚未完成真实视觉闭环物理验证；软件回归不能代替实物试验。','',
        '## 数值核对而非新实验','',
        '本轮仅从36行真实Pilot逐图CSV核对汇总，从1300行S2评分核对65组计数，并核对16检查点RMSE。没有调用世界、相机、预测器或评分器生成新结果。核对快照见source/evidence_snapshot.json，完整来源hash见source/provenance_manifest.json。'])
    (out/'第二章_章节证据对应表.md').write_text('\n'.join(evidence),encoding='utf-8')
    todo=['# 第二章图表与待补内容清单','','## 图稿','',
      '|图号|Word章节|图题|来源|当前状态与下一步|','|---|---|---|---|---|']
    for r in b.figure_records:todo.append(f'|Fig.{r["number"]}|{r["section"]}|{r["title"]}|{r["source"]}|{r["status"]}|')
    todo.extend(['','## 原生可编辑表格','', '|表号|章节|内容|','|---|---|---|'])
    for r in b.table_records:todo.append(f'|表{r["number"]}|{r["section"]}|{r["title"]}|')
    todo.extend(['','## 待补或待写内容','', '|位置|类别|具体内容|是否需要新实验|','|---|---|---|---|',
      '|2.1、2.3.1|待核对文献|视觉闭环、分割原始方法、单应性与时序事件控制；从本地已下载正文核查引用|否，需文献逐条核对|',
      '|2.2.1|设备材料缺口|实际相机/镜头型号、序列号、焦点、芯片高度、盖板及照明|需实物记录，不需高压|',
      '|2.3.2、2.5.2|最终标定缺口|新参考图、H、独立检查点、畸变与装夹条件、有效manifest|需最终装置采集|',
      '|2.5.1|已有结果待写|18图传统分割Pilot的逐图/视频汇总、失败数和计时，CSV已存在|否，不应重跑来改变结果|',
      '|2.5.1|正式真实分割缺口|独立采集分组、审核GT、训练/验证/测试、模型及导出兼容性|是，按后续方案开展|',
      '|2.5.2|已有结果待写|8fit/16check预实验；RMSE/P95/max及残差分析|否，复用冻结原始坐标|',
      '|2.5.3|已有正式S2待写|五方法13条件、BQ诊断、参考、延迟/错误/漏确认与完整分母，已冻结|否，现有正式数据足够整理|',
      '|2.5.3|真实五状态缺口|独立人工状态与到达区间标注；Unknown/不确定样本规则|是，不能由算法自动造GT|',
      '|2.5.4|S3/S4专项缺口|公平源准备、到达门×保护桥接、Retry物理参考、正交消融、受控参数/参考敏感性|先实现验收和审批，再决定正式运行|',
      '|2.5.5|实物闭环缺口|波形/扫描、标定/模型、独立参考、逐trial事件和失败记录|是，本轮不开展|',
      '|整章|学校格式|可靠的浙大硕士论文模板、正式参考文献编号和格式细则|否，后续套版|','',
      '说明：S1-A/B已经定稿，不属于待优化项；本稿只原样嵌入，禁止重新设计或重绘。S2统计正文暂缓是写作顺序，不等于正式仿真未完成。'])
    (out/'第二章_图表与待补实验清单.md').write_text('\n'.join(todo),encoding='utf-8')
    guide=f'''# 第二章论文初稿生成与更新说明

## 版本记录

- 2026-10-26 v1：按用户锁定2.1—2.6结构完成方法型正文，包含系统、分割接口、真实地图、空间特征、五状态/事件控制、S1—S4研究及实物方案。遵循随后“先不写结果”的要求，正式性能分析暂不展开，已有/缺失证据分开。
- 本版不是开题报告或PPT提纲；正文可直接继续改写。未核实的学校模板不冒充官方格式。

## 文件组织

- 主文档：{NAME}
- 内容源：source/chapter2_thesis_draft_content_v1.md（标准中文正文加生成标记）
- 生成器：source/build_chapter2_thesis_draft.py
- 证据读取器：source/chapter2_thesis_evidence.py
- 证据快照与hash：source/evidence_snapshot.json、source/provenance_manifest.json
- 原始研究材料位于证据表所列目录，不迁移、不覆盖；Word仅嵌入两张S1原图。
- QA目录仅用于内部渲染、结构检查和保护核验，不是新的科研结果。

## 后续编辑方式

优先直接在Word同一文档中修改，并在重大变更前另存v2、v3。手工Word编辑不会自动回流到Markdown。生成器不会读取并合并手工修改，不得再次生成覆盖已经人工修改的主文档。

如要从源正文重新生成，先将人工修改同步到内容源，更新版本并使用新输出文件名。缺省拒绝覆盖已有Word；--replace-generated仅限生成阶段的排版修复，不用于覆盖人工工作。表格在生成器TABLES中维护，公式为原生OMML，图稿来源在FIGURES中维护。

Word标题采用原生Heading 1/2多级编号，目录为TOC字段；图表与公式使用SEQ，正文图引用使用REF书签。后续增删内容后按Ctrl+A、F9更新字段，再更新整个目录。不要手工只改一个图号而不更新相关书签。公式可在Word中点选编辑，不是图片。

## 可复现生成

在原仓库运行以下命令（路径含单引号时，PowerShell须按常规转义）：

```powershell
& "C:/Users/Rz'sLaptop/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" "{REPO.as_posix()}/scripts/build_chapter2_thesis_draft.py"
```

支持--output指定新的docx绝对路径；内容源默认是仓库docs/chapter2_thesis_draft_content_v1.md。随包源码为可追溯副本，读取现有资料仍依赖当前工作区；迁移电脑时需在证据读取器中更新REPO/ROOT，而不是静默改写来源记录。

依赖：Python、python-docx 1.2.0、lxml、Pillow（本轮使用Codex bundled runtime 26.1025.11240）。DOCX结构核查使用zipfile/lxml，无训练或仿真依赖。实际视觉渲染需Word或受支持的DOCX渲染器及Poppler；本机Windows的具体路径和QA方式记录在QA/render_verification.json。

## 证据与写作边界

不启动新仿真、训练或高压实验，不修改AM/协议/生产五状态/U-Net/第三章，不提交或推送。S2数字只读自正式CSV，当前暂未写入性能结果正文。真实Pilot只有同轮采集组1；照片预实验H不能迁移到旧视频或最终高度装置。最终文献需用户核对，所有“待补文献”均不是虚构引用。
'''
    (out/'第二章_论文初稿生成与更新说明.md').write_text(guide,encoding='utf-8')

def audit(path,b,e):
    with ZipFile(path) as z:
        from lxml import etree
        tree=etree.fromstring(z.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        text=''.join(tree.xpath('//w:t/text()',namespaces=ns))
        eqs=len(tree.xpath('//m:oMath',namespaces=ns))
        heads=tree.xpath('//w:p[w:pPr/w:pStyle[@w:val="Heading1" or @w:val="Heading2"]]',namespaces=ns)
        image_hashes={__import__('hashlib').sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}
        unchanged=all(sha(Path(e['assets'][k])) in image_hashes for k in ('s1a','s1b'))
        missing=[s for s in ('引言','单液滴实物闭环控制实验','本章小结','SIMULATION','F_arrival','【待补充S3/S4正式结果】') if s not in text]
        result=dict(equations=eqs,headings=len(heads),tables=len(tree.xpath('//w:tbl',namespaces=ns)),
                    figures=len(b.figure_records),embedded_images=len(image_hashes),s1_original_bytes_embedded=unchanged,
                    body_characters=len(text),missing_required_text=missing,
                    heading_records=b.heading_records,figure_records=b.figure_records,table_records=b.table_records,
                    performance_analysis_deferred=True,physical_validation_claimed=False)
        result['numbered_equations']=b.eqcount;result['inline_math_objects']=eqs-b.eqcount
        result['trial_id_literal_count']=text.count('normal:262000:F:end_to_end')
        assert b.eqcount==20 and len(heads)==19 and unchanged and not missing and result['trial_id_literal_count']>=2,result
        assert len(b.figure_records)==12 and len(b.table_records)==9
        return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=OUT/NAME);p.add_argument('--replace-generated',action='store_true');args=p.parse_args()
    if args.output.exists() and not args.replace_generated:raise FileExistsError('Refusing to overwrite existing Word; use a new version or deliberate generated-only replacement')
    e=collect();out=args.output.parent;out.mkdir(parents=True,exist_ok=True)
    b=Builder(e);b.build(args.output)
    source=out/'source';source.mkdir(exist_ok=True)
    for f in (CONTENT,Path(__file__),REPO/'scripts/chapter2_thesis_evidence.py'):shutil.copy2(f,source/f.name)
    dump(source/'evidence_snapshot.json',e)
    dump(source/'provenance_manifest.json',dict(date='2026-10-26',draft_scope='methods-first, results analysis deferred',
        research_runs=0,evidence=e['evidence'],content_sha256=sha(CONTENT),builder_sha256=sha(__file__),
        assets={k:dict(path=v,sha256=sha(v)) for k,v in e['assets'].items()}))
    supporting_files(b,e,out)
    report=audit(args.output,b,e);dump(out/'QA/structure_verification.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('heading_records','figure_records','table_records')},ensure_ascii=False))
    print(str(args.output))

if __name__=='__main__':main()
