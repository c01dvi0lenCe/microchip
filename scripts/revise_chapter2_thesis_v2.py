"""Targeted academic-language edits to the existing v1 DOCX, never a rebuild.

Reads frozen statistics only. No research model, prediction or scoring is run.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
import argparse
import csv
import hashlib
import json
import re
import shutil

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from chapter2_thesis_evidence import ROOT, REPO, OUT as V1DIR, S1, S2, CLOSE, PILOT, REG, sha, js, dump, rows, collect
from build_chapter2_thesis_draft import Builder

V1=V1DIR/'第二章_单液滴视觉闭环控制_硕士论文工作初稿_v1.docx'
OUT=ROOT/'论文初稿/2026-10-26_第二章学术语言修订_v2'
V2=OUT/'第二章_单液滴视觉闭环控制_硕士论文工作初稿_v2.docx'

# Original v1 paragraph indexes are checked against the original document hash.
# Headings, numbered equations, S1 drawings and caption fields are retained.
REVISIONS={
2:'工作初稿 v2',
5:'本章面向给定相邻电极路径上的单液滴迁移任务，研究图像分割、电极空间映射、连续状态识别与事件驱动控制之间的关系。通过真实图像预实验和算法级仿真，分别考察空间映射一致性、到达判定行为及闭环运行机制。',
6:None,7:None,
34:'视觉反馈提供了直接的运动观测通道，但目标检测与可靠到达判定具有不同的信息要求。单帧质心接近目标时，液滴仍可能横跨源、目标电极；目标覆盖率较高的图像也可能由短暂跨区、位置抖动或错误分割产生。因此，本文结合源—目标任务关系与连续观测构建到达证据，以支持电极更新决策。',
35:None,
37:'本章从真实图像与算法级仿真两个层次开展研究。真实图像部分采用工业相机视频和人工审核Mask进行分割Pilot，并利用Gerber设计轮廓与芯片照片建立图像—电极配准。算法级仿真部分构建简化二维运动与模拟视觉环境，研究空间特征变化、同输入到达判定及控制反馈。两类证据分别对应成像与几何一致性、判据行为与控制机制，其验证对象和适用范围相互区别。',
41:'【图2-1插图位置】',
43:'上位机按照观测、特征提取、状态识别、事件生成和控制执行组织数据流。帧数据包保存图像、帧身份、接收时间及可用的设备时间信息；分割模块输出与输入图像同坐标域的二值Mask和置信信息；空间映射模块计算液滴与当前源、目标电极的关系。完整五状态识别算法形成状态证据，视觉闭环控制器据此决定保持、更新或异常处理，各模块通过显式数据接口衔接。',
44:'相机采集与分割处理采用不同执行节奏。采集接口通过有界等待和最新帧机制限制图像积压，帧数据包保留SDK帧号与主机接收时间，并记录时间质量。接收时间用于判断软件处理的新鲜度；曝光与电极应用之间的物理先后关系还依赖曝光时间与控制时钟的映射。',
45:'【图2-2插图位置】',
47:'系统设置离线重放模式、实时无输出模式和实物控制模式。离线重放模式读取视频或时间表，用于检验图像处理与状态判定；实时无输出模式采用相机输入并记录控制决策，电极输出保持关闭；实物控制模式在输出、标定和通信条件有效时发送AM电极事务。三种模式共享主要识别接口，分别对应记录数据分析、实时软件联调和实际电极执行。',
48:'成像系统通过USB3及厂商SDK接入上位机。相机、镜头及装配参数决定视场、像素尺度和成像稳定性，其实际型号与最终安装条件尚待实物核验。',
49:'【待核验事实F01：相机与镜头型号、序列号及最终装配参数】',
51:'视觉闭环包含激励波形、阵列刷新、相机采样、图像处理与任务更新等时间尺度。高压波形决定激励条件，AM帧刷新维持阵列寻址和输出，相机产生离散观测，状态证据完成后才触发任务更新。阵列扫描独立于逐帧图像处理，视觉等待期间维持当前目标激活。',
54:'AM驱动接口按20×21阵列组织扫描，设计刷新频率为300 Hz。相机采样频率取决于曝光与采集节奏，视频容器播放帧率仅描述记录的时间基准。视觉闭环采用事件更新，其间隔由液滴迁移、有效采样和处理延迟共同决定，与AM固定刷新频率具有不同含义。',
55:'【图2-3插图位置】',
57:'对于第i次电极任务，系统分别记录请求、APPLIED软件接收、帧曝光、图像可用及算法确认时间。同一时钟域或经验证映射后的时间用于计算分段延迟；设备原始计数值保留其原始单位，UTC用于文件检索，主机单调时钟用于进程内时序分析。由此将闭环等待分解为通信、视觉处理及证据确认等部分。',
59:'式中，各时间量以秒为单位，分解以事件记录完整且时钟可比较为前提。算法级仿真采用独立simulation时钟，显式记录模拟曝光和模拟Applied。实物控制模式中，现有记录尚缺经验证的曝光时钟映射，因此目前的顺序检查主要反映主机接收与软件执行关系。',
60:'连续到达证据同时采用帧数与时间跨度约束。在理想20 fps采样下，五幅观测的首末时刻相差0.20 s，尚未达到0.25 s的跨度要求。联合检查最少帧数、首末时间差与帧间连续性，可使低帧率和丢帧条件下的证据积累遵循同一时间定义。',
63:'图像分割提取单液滴投影区域，为质心与交叠面积计算提供统一输入。真实图像Pilot以核心电极区内运动的黑色小液滴为目标，储液区、透明圆环、气泡及大面积液体边界归为非目标结构。传统分割、U-Net输出和人工Mask采用相同目标定义。',
64:'图像处理采用完整视场或显式定义的感兴趣区域（ROI）。ROI记录原图身份、裁剪偏移与尺寸，使Mask、质心和电极多边形处于一致坐标域。预处理直接作用于算法输入；显示缩放与调色独立于测量数据。原始视频及抽帧通过文件摘要与资源清单建立对应关系。',
65:'传统基线采用Otsu全局阈值与自适应阈值。前者依据整体灰度分布选择阈值，后者依据局部邻域处理亮度不均。Pilot对暗前景执行平滑、形态学开闭运算及连通区域筛选，输出原ROI尺寸的Mask。由于当前材料缺少经核验的同装置无液滴背景，第二种传统方法选用自适应阈值，而非背景差分。',
66:None,
67:'U-Net通过编码器提取多尺度特征，由解码器恢复空间分辨率，并通过跳跃连接保留局部信息。本文将其输出限定为液滴像素概率，状态和控制决策由后续模块完成。推理接口支持ONNX与TorchScript二值分割模型；真实数据目前处于18幅审核Mask的Pilot阶段，尚未形成跨采集训练与独立泛化评价。',
68:'推理接口将BGR图像转为RGB，调整至模型输入尺寸后除以255，并按训练定义的均值和标准差归一化为NCHW格式的float32张量。模型输出形状为[1,1,H,W]；logits经过sigmoid，概率输出直接使用。概率图插值回原输入尺寸后按阈值二值化。接口初始配置为256×256输入及0.5阈值，真实模型应用时需与训练预处理一致。',
70:'式中，P_i(u,v)为第i帧的液滴概率，τ为分割阈值，M_i为前景像素集合。工程接口以0/255表示二值Mask，面积为非零像素数；非空Mask的质心由当前二值图像矩计算。',
72:'式中，A_i为Mask像素数，质心c_i^px的单位为px。空Mask对应无有效质心，并作为检测失败或无观测记录保留。置信信息用于质量约束，其数值与实际分割正确概率之间的关系尚未完成校准。',
74:'本文从FBC6-3芯片Gerber设计提取420个电极轮廓，包括20×20核心阵列的400个电极及20个外围电极。外围由8个小电极、8个大电极和4个角部L形电极组成。数字地图保存多边形顶点、面积质心、设计单位、坐标方向及来源信息，以表示非规则外围结构。',
75:'数字地图采用与上位机控制布局一致的正面俯视编号：核心左上、右上、左下和右下分别为1、20、381和400，外围按既定控制布局绑定。轮廓来自Gerber几何，编号通过布局对应关系建立。该绑定描述设计空间中的控制位置关系；电气连通及实物制造尺寸属于独立验证对象。',
76:'图像配准建立像素坐标(u,v)与电极设计平面坐标(x,y)之间的单应性变换。在芯片近似平面且成像装置固定的条件下，采用3×3矩阵H描述透视关系。模型未显式包含镜头畸变、盖板折射及平面起伏，这些因素与人工点选误差共同影响残差。',
78:'式中，λ为齐次尺度，H的方向为图像坐标至设计平面坐标。像素单位为px，设计坐标单位为mm，欧氏坐标由齐次除法获得。计算前检查对应点非退化性、矩阵有限性与可逆性、投影分母及图像/ROI绑定关系。',
79:'【图2-4插图位置】',
81:'拟合点用于估计H，独立检查点评价未参与拟合位置的投影一致性。本文将检查点的设计坐标经H逆变换投回图像，与人工像素坐标比较得到像素残差；设计域残差另以mm记录，两者采用各自坐标域的单位。',
83:'式中，p_j为人工检查点像素坐标，q_j为对应设计坐标，π为齐次归一化，e_j单位为px。N个检查点的RMSE为误差平方均值的平方根，P95为逐点误差模长的95%分位数。该评价反映单幅图像与设计几何的一致性，包含点选及模型误差，与独立物理计量精度相区别。',
84:'配准参数与相机位置、芯片高度、盖板、焦点、分辨率及ROI绑定。装置几何改变后采用新的参考图与独立检查点重新估计和验收H。当前照片配准尚未绑定既有视频，因此视频Mask的电极空间分析仍依赖各自有效的配准关系。',
86:'设源电极区域为Ω_s、目标电极区域为Ω_t、液滴Mask为M。为区分液滴进入目标的比例与目标电极被覆盖的比例，分别定义液滴面积归一化覆盖率和电极面积归一化覆盖率。源区残留与目标覆盖由同一Mask和同一坐标域内的交叠计算获得。',
89:'η_s表示液滴在源区的残留比例，η_t表示液滴进入目标区的比例，ρ_t表示目标电极被覆盖的比例，三者均无量纲。η_s与η_t以液滴面积为分母，ρ_t以完整目标电极面积为分母。目标区域为空或被ROI裁切时，ρ_t标记为几何无效。本文提取ρ_t作为空间描述量，当前到达门尚未加入经真实数据验证的独立ρ_t阈值。',
93:'式中，L为源目标中心距，a=(t−s)/L为单位方向向量，p为有符号投影距离，p/L为无量纲归一化进展，e_⊥的符号由任务方向确定。设计标定域距离以mm表示，算法级仿真距离以pitch表示，两类尺度分别报告。',
96:'时间差非正、时钟域改变、任务几何切换或历史间隔过长时，速度历史重建并等待新观测。长断档后的两个位置不提供期间连续稳定运动的证据。区域交叠像素数、几何质量及时间来源与特征同步记录，用于解释到达判定的接受或拒绝。',
99:'本文将状态识别定义为在源目标任务与可用观测历史下估计液滴运动状态，并判断是否具备推进任务的证据。输入包括Mask、帧及时间元数据、电极地图和任务上下文；输出包括空间特征、观测可靠性、五状态及到达事件。算法级仿真的内部位置与参考到达仅用于生成观测和独立评分，与算法输入分离。',
100:'【图2-5插图位置】',
102:'判据按信息来源分为C0、G、Q、W、S和K。C0表示数据完整性与任务因果，G表示源目标覆盖，Q表示观测质量，W表示连续稳定证据，S表示任务空间位置，K表示运动历史一致性。完整五状态识别算法和S2纯到达判定算法分别按各自任务使用这些信息，前者输出状态，后者专门输出到达事件。',
106:'任务上下文包含运行标识、计划步、尝试、证据纪元、源目标ID、任务阶段及Applied时间质量。计划步区分路径任务，尝试区分同一步的重复执行，证据纪元界定控制动作接受后的有效观测域。帧身份高水位跨任务保留，重复、倒序、非法时间及上下文不匹配的帧被拒绝，不进入当前证据窗口。',
107:'算法级仿真显式给出曝光起止与可用时间，C0据此检验模拟Applied后的观测资格。实物控制模式仅有主机接收时间时，以接收新鲜度执行软件屏障检查，同时保留因果不确定标记。严格曝光—电极应用顺序仍依赖经验证的设备与主机时钟映射。',
109:'覆盖门联合检查η_t达到到达阈值与η_s低于释放阈值。Q检查置信、面积范围和显著连通区域数量，识别低质量及多目标歧义。数据格式、非空Mask和时钟等基本可解析条件归入始终启用的C0，独立于Q的研究开关。',
111:'式中，g_i表示单帧覆盖资格，τ_a与τ_r分别为目标覆盖和源释放阈值。S2纯到达判定算法采用0.85和0.08，完整五状态识别算法的初始配置采用0.75和0.10。两组阈值分别服务于冻结仿真比较与初始实验接口，尚未建立真实液滴数据下的统一参数标定。',
113:'S结合当前源目标多边形及观测质心约束任务位置。S2到达门同时检查任务区域与目标电极外扩容差，其中0.18 pitch为相对多边形边界的容差。完整五状态识别算法还可在声明的局部候选区域内检查空间一致性，并单独评价目标位置条件。',
114:'覆盖率与质心位置包含不同几何信息。少量远端碎片可使整体质心偏移，而主体仍保持较高目标覆盖；质心接近目标时也可能存在源区残留。当前空间门依据电极多边形位置构建，通道宽度和正向运动约束未作为实际启用的到达判据。其真实误差适用性仍取决于实拍分割形态。',
116:'K比较当前质心、短时位移与预测位置。两个历史观测可形成匀速外推，位移和预测残差分别由速度界与容差约束。状态更新依据当前有效证据，允许直接到达等跨状态转换，不以固定状态链作为运动发生的必要条件。',
119:'式中，v_max为速度界，ε_p与ε_k分别为位移及预测残差容差。S2中速度界为6 pitch/s，相关容差为0.18 pitch。历史不足时比较信息减少，长间隔、缺帧或任务切换触发历史重建，其初始化行为构成到达门的一个边界条件。',
120:'完整五状态识别算法仅将满足空间与时序一致性的观测写入运动历史；S2纯到达判定算法则先对所有C0可解析帧计算原始S/K/Q，再应用开关，低质量和空间异常帧也进入该原始历史。后一采样方式保持各消融组历史一致，同时使持续伪观测可能逐渐影响预测依据。',
122:'五状态为Stationary、Moving、Partial、Arrived和Deviation，描述任务相关的静止、迁移、部分进入目标、可靠到达及持续空间偏离。Unknown表示观测无效、时序冲突或证据不足，属于可靠性标记。单次异常首先降低可判定性，持续有效的空间偏离才形成Deviation证据。',
125:'识别器先检查观测与时间有效性，再形成候选状态。有效且时序一致的空间异常对应Deviation候选；目标覆盖、源释放与目标位置满足时对应Arrived候选；目标进入且源残留仍较高时对应Partial候选；其余按速度阈值区分Stationary与Moving。缺少速度信息时保持Unknown。',
126:'候选状态经连续证据确认后输出。完整五状态识别算法初始配置采用2帧一般一致性、至少2帧持续偏离，以及至少5帧且跨度0.25 s的到达要求。孤立空间异常因证据不足保持Unknown，尚不触发Recovery；有效证据满足时可直接发生跨状态转换。',
127:'连续证据窗口维护同一任务和候选状态下的有效后缀。任务或状态改变时重建窗口；重复或倒序观测清除证据并保留身份高水位；断档、帧号缺口、身份来源改变及资格不满足均引起重建。质心包围盒对角跨度和目标覆盖极差进一步约束窗口稳定性。',
129:'式中，J_i为当前连续证据后缀，N_W和T_W分别为最少帧数与最短跨度，D_c为质心包围盒对角跨度，D_η为覆盖极差。S2强组共同采用5帧、0.25 s、最大间隔0.18 s、质心跨度0.11 pitch及覆盖极差0.15。上述量用于观测确认，独立参考到达另行定义。',
132:'当前任务的合格窗口完成后生成到达事件ArrivalEvent，记录首末帧、证据时间、任务上下文及因果质量。事件与当前运行、计划步、尝试和证据纪元绑定，台账按计划步实施一次性消费。重复事件及旧任务事件因此不再触发新的电极更新。',
133:'S2纯到达判定算法F_arrival在共同C0/G/Q/W下增加S与K，仅评价到达事件；完整五状态识别算法另行输出状态并为视觉闭环控制器提供输入。两类算法的输出层次不同，S2事件指标反映到达判据行为。真实五状态混淆矩阵仍缺少独立人工状态标注。',
135:'视觉闭环控制器按源准备、运输等待、局部恢复以及完成或停止组织执行。源区连续确认后首次激活目标，运输中保持目标电极有效，并依据状态和进展选择保持、重试、回源或停止。研究范围为给定相邻电极路径的单滴运输，未纳入全局自动改道或多液滴调度。',
136:'【图2-6插图位置】',
140:'电极事务采用BEGIN/SET/COMMIT协议，并等待对应序列的ACK:sequence:APPLIED。通信超时采用相同序列重传，最多两次，与液滴迁移Retry分账。APPLIED确认电极事务已应用；液滴运动是否到达由视觉证据判断。控制阶段在事务成功或模拟接受后提交。',
141:'Hold保持当前激活；Update在有效到达事件后激活下一目标；末目标确认后进入Complete。Retry再次尝试当前目标并重建算法证据与尝试时钟。Recovery局部切回当前源区，源区确认后恢复运输。ALL_OFF承担紧急或结束释放，未用于正常视觉等待。Complete本身未产生新目标事务时，对应Applied记录为空。',
142:'无进展监测独立于单一状态标签。对持续Partial、无净推进的Moving及往返抖动，监测器比较当前投影进展与历史最佳值，仅在净改善超过阈值时更新进展时钟。由此将非零速度与有效任务推进分别处理。',
144:'式中，p_best为已接受的历史最佳进展，ε_prog为最小净改善，t_prog为最近有效改善时刻。完整五状态识别与控制接口初始采用8 s无进展等待、16 s尝试硬上限、2 s无可靠观测超时、每循环最多2次常规Retry及每计划步最多2次局部Recovery；源准备与恢复等待为10 s和8 s。这些值为初始安全配置，实物适用性尚未完成标定。',
145:'无可靠观测超时触发保护停止，持续空间偏离确认后可进入局部Recovery。常规Retry耗尽后根据恢复预算选择回源或停止，全部预算耗尽时终止运输。观测恢复或新的控制尝试重建证据域，已消费的到达事件保持失效。',
146:'本文采用有界Retry与局部Recovery的单滴控制策略，其恢复范围限定在当前源目标任务。参数和动作定义属于视觉闭环方法，装置上的实际执行效果另通过配准、通信、波形及液滴运输试验评价。',
148:'验证分为真实图像分割、单照片配准、到达事件识别及完整闭环控制四个层次。分割评价Mask与人工GT的一致性，配准评价图像与设计点位一致性，S2评价共同观测下的事件判定，S3评价控制动作反馈后的运输过程。各指标按其验证对象分别报告。',
150:'真实图像数据包含2026年10月13日至14日采集的10段工业相机AVI，分辨率5472×3648，编码H.264。资源清单记录容器帧率、帧数、时长、读取情况与文件摘要。采集分组资料将全部视频归为同一芯片、同次加液和同轮采集，因此独立采集组为1；容器帧率用于记录时间基准，尚缺逐帧曝光验证。',
151:'Pilot从其中3段视频选择18幅ROI，并完成人工Mask审核。代表图覆盖静止、起动、跨电极、形变、接近目标及困难成像。目标为黑色小液滴投影，非目标结构与不确定边界按统一规则处理。现有运动状态标签为Unknown，Mask审核用于分割评价，状态真值尚未独立建立。',
152:'训练、验证与测试的独立性按原视频及更高层采集组约束。当前18图来自同轮材料，作为开发Pilot使用，尚未形成跨采集的独立测试集合。数据扩展需同时增加独立采集组与组内形态、成像覆盖，以区分帧间相关性和跨装置变化。',
153:'传统方法参数在Pilot评分前固定：模糊核5、形态学核3、开运算1次、闭运算2次，最小区域40 px，自适应邻域51及常数5，采用暗前景和边界组件筛选。两方法读取原生ROI尺寸的同一18幅图像，并使用相同人工审核Mask。',
155:'式中，TP、FP和FN为像素级混淆计数，Dice、IoU、Precision和Recall均无量纲。另记录质心误差、空Mask、缺预测及推理异常。质心误差以质心存在的预测为条件统计，并同时给出条件分母和检测失败数。',
156:'计时采用Intel Core Ultra 9 275HX和CPU单线程OpenCV后端，每图每方法预热5次、计时10次，汇总均值、P50和P95。计时包括预处理、分割、后处理与结果校验，不包含文件读写和指标计算。定位误差以px报告，当前材料尚未建立独立像素—毫米测量关系。',
157:'【图2-7插图位置】',
159:'@PILOT_RESULTS',
161:'配准预实验采用一张5472×3648工业相机芯片照片与FBC6-3设计地图。8个拟合点用于估计H，16个独立检查点不参与拟合。矩阵与拟合点冻结后，对检查点进行人工核对，并在像素域计算投影残差。',
162:'独立复核重新计算H逆投影及逐点残差，得到RMSE 1.968 px、P95 3.058 px和最大误差3.132 px。16个检查点均有有效记录，无缺失或排除。该结果描述单幅图像与Gerber设计点位的一致性，未包含独立物理测量基准。',
163:'【图2-8插图位置】',
165:'重复点选与配准残差分别评价。同一点位多轮点击属于技术重复，粗范围辅助定位会改变点选条件，因此其结果按辅助点选重复性解释。最终装置标定还需绑定固定的相机、芯片高度、盖板、焦点和照明，当前照片参数仅适用于预实验图像。',
166:'空间映射的实现检查覆盖ROI偏移、多边形中心、区域裁切及交叠计算。手工可核算的几何单元测试用于检查公式与实现一致性；实拍残差则同时包含点选、光学、制造及平面模型误差。当前16点及区域分布不足以区分或排除这些误差来源。',
167:'【待完成实验E-CAL：最终装置标定、独立检查与跨装夹重复性】',
170:'本文采用简化二维单液滴算法级仿真研究状态与到达判据。虚拟地图包含400核心及20外围示例电极，坐标归一化为pitch，路径为190→191→192→172。该几何用于构造可控任务环境，与真实Gerber设计毫米地图分别使用。',
171:'二维运动世界将液滴表示为位置与速度，根据当前激活目标执行有限速迁移。命令经历模拟Applied和运动响应延迟后，液滴向模型目标移动；名义速度乘以每个随机种子确定的因子，并叠加按积分时刻索引的扰动。模型描述控制作用下的运动代理，不求解电场、接触角及液滴内部流动。',
173:'式中，r_k为内部位置，g_k为模型目标，v_0为名义速度，a_seed为速度因子，ξ_k为随机扰动，Δt为积分步长。式（2-17）概括响应后的运动更新；延迟阶段、扰动启用范围与异常目标由场景规则确定，目标距离为零时保持位置。',
174:'模拟视觉观测模型SyntheticCamera依据捕获帧号读取位置与半径误差，并在内部位置附近生成圆形二值Mask。每帧记录曝光起止、可用时间及丢帧标记。识别算法只接收模拟Mask、地图、任务和时间信息；内部位置独立保存在世界日志中用于观测生成与评分，缺帧不进行Mask插值。',
177:'世界扰动与相机误差使用相互独立的随机流，分别按绝对积分时刻和捕获帧号索引。同种子比较固定模型参数、时间预算及外生数组，以减少控制分支随机调用差异。基础世界在多种观测条件中复用，配对关系由种子、参数和输入摘要共同确定。',
179:'S1采用一条正常条件下的闭环运行作为机制示例，路径为190→191→192→172。图2-9放大首步190→191，并给出完整路线；六幅画面对应该次运行的0.50、0.81、1.06、1.46、1.92和1.96 s。画面及状态取自同一次持久化日志。',
182:'SIMULATION，n=1机制示例，单位pitch。蓝色中心表示内部位置，橙色轮廓及标记表示模拟Mask与观测质心；电极边界区分源、目标及已应用激活。0.50 s对应源准备确认和运输启动。',
183:'内部位置显示世界运动，已处理Mask及质心表示算法可见观测；源目标电极描述任务，当前激活电极描述执行状态。该运行在源准备确认时记录Moving与Start，后续显示Partial、Unknown、Arrived及更新事件，未出现Stationary、Deviation、Retry或Recovery。S1用于说明特征、状态与控制事件的对应关系，不评价五状态识别准确率。',
184:'图2-10同步显示内部与观测x/y、η_s、η_t及目标距离、方向进展，并按模拟Applied划分三个运输阶段。两项空间量均由已处理Mask质心和地图中心计算；方向进展为pitch单位投影距离，归一化进展另为p/L。',
187:'SIMULATION，n=1，与图2-9为同一运行。任务阶段按模拟Applied划分，距离与进展来自模拟观测质心；本图显示算法级观测，不包含真实U-Net推理结果。',
189:'S2采用固定教师任务分离到达判定与控制反馈。教师对190→191仅提交一次运输命令，任务区间为[0,4) s，模拟Applied为0.04 s，常规运动响应始于0.22 s。五种方法分别读取同一Mask缓存、时间和任务上下文，确认事件不改变教师轨迹。',
190:'五种主方法为单帧覆盖率B_single_frame、等稳定窗口覆盖率与质量基线BTQ、增加空间约束的BTQ+S、增加运动历史的BTQ+K及联合两者的F_arrival。后四组共享G、Q、W和C0，差别仅为S/K组合。BQ_single_frame为质量匹配的辅助诊断，用于分析W的增量。全部方法仅评价到达事件。',
193:'实验包含13种条件，分别检查正常稳定到达、覆盖闪变、短暂与持续跳变、远端碎片、低/高置信伪观测、位置抖动、丢帧和长断档。正常、位置抖动和丢帧由运动—相机模型直接生成（model-generated），其余为预声明的合成压力输入（synthetic stress），用于检验判据边界。',
196:'正式批次采用20个配对随机种子，每个种子生成正常与失败两类基础世界，共40个基础世界、260份观测缓存、1300次主方法评价及260次辅助诊断。独立统计单位为条件内的随机种子，多个观测条件复用同一基础世界，因此结果按条件分别报告。',
198:'独立参考由内部位置、速度和驻留计算，与Mask覆盖和算法窗口分离。参考条件为距目标中心不超过0.09 pitch、内部速度不超过0.06 pitch/s并持续0.15 s。区间[l,u]表示驻留条件完成时刻的离散不确定性，属于模拟世界参考。',
200:'确认时刻c<l记为提前确认，l≤c<u记为时序不确定，c≥u且在预声明主窗口内记为支持确认。无参考到达但产生事件记为无支持确认。主窗口H=1 s，晚于u+H的支持事件单列为晚确认；提前事件消费唯一确认机会后，后续事件不修复该步主评价。',
202:'式中，R为可评价参考到达数，N为计划步数，S_H为主窗口支持数，P与U为提前及无支持数，M_H为主窗口漏确认数。R=0时支持率记NA，错误事件以完整N为分母。Unknown帧、未尝试、删失和基础设施不确定分别保留；晚确认是主窗口漏确认的子集。',
204:'确认延迟以[c−u,c−l]表示，单位s；无确认样本不赋零延迟。率区间采用Wilson 95%区间，配对差采用2000次种子bootstrap，延迟差仅在双方均主窗口支持的配对中计算并报告n。区间描述冻结模型与输入条件下的随机不确定性。',
209:'@S2_RESULTS',
210:'@S2_LIMITS',
212:'完整闭环仿真研究控制动作如何改变后续迁移。各控制器从共同初始状态与外生随机条件出发，分别决定更新、重试和恢复。动作分叉后轨迹与Mask随之改变，公平条件因而由共同运动模型、观测误差流、源准备与控制预算定义。',
213:'既有闭环批次包含固定等待、简单视觉及完整算法适配策略，并保存开发阶段的分阶段机制测试。这些批次采用不同策略和协议，分别作为历史算法级仿真证据。运输流程完成与参考支持的路径完成分别定义：前者表示任务流程走完，后者要求各计划步均在有效独立参考支持下确认。',
214:'S3专项方案设置固定时间策略A、单帧视觉策略B、等稳定窗口策略BTQ和完整五状态事件策略F，共享源准备、运动观测模型、外部扰动及预算。另以到达门（BTQ或F_arrival）与保护策略（共同保护或五状态保护）构成2×2桥接，分离到达判据与异常处理的系统作用。',
217:'正常、延迟、部分到达后停滞、位置抖动、丢帧、偏离和持续失败场景分别检验基本运输、延迟失配、无进展、源准备瓶颈、证据中断及保护行为。部分停滞在模型中可随重试解除，持续失败作为负对照。该设定反映预声明的故障机制，实物恢复有效性仍需独立验证。',
218:'路径评价分别记录源准备、运输进入、流程完成及各步独立支持。源准备失败和中途终止后的剩余计划步保留为未尝试。trial终止结果采用互斥类别，重试、恢复、错误更新和晚确认作为独立标签，以区分完成性与运行代价。',
219:'每个更新请求与模拟Applied通过请求身份关联，在两个时刻分别评价此前目标的独立支持。后续应用时获得支持不改变请求时的判定。物理驻留先由连续内部轨迹获得，再归属任务；同目标Retry重建算法证据，但在位置、速度与激活连续时保留物理驻留。',
220:'S4以正交S/W/K/Q开关分析模块作用，C0始终启用。到达判定比较共用原始观测历史，控制比较固定保护输入或采用桥接，同时评价错误拒绝与延迟代价。算法参数敏感性与独立参考敏感性分别考察判据变化和评分定义变化。',
221:'S3/S4专项的公平比较接口与独立参考尚待完成，上述内容为实验设计，既有机制测试尚未形成该方案下的正式系统性能评价。【待完成实验E-S3S4：闭环策略与模块消融】',
223:'实物闭环实验拟采用第一章AM-DMF平台、工业相机、最终装置配准和真实分割模型。验证依次采用离线重放、实时无输出和实物控制模式，分别检查记录数据处理、实时决策和电极执行。高压激励与阵列刷新沿用驱动平台设计。',
224:'实验条件包括芯片与表面处理、液滴材料和体积、激励设置、环境、盖板、芯片高度及成像参数，并按加液和装夹建立采集分组。路径为预声明的相邻电极序列，真实到达参考由独立人工审核区间建立，保留可见性不足和时序不确定记录。',
225:'实物验证分离电气执行、视觉可用性与任务完成性。首先检查事务身份和日志完整性，再检查配准绑定与Mask质量，最后将视觉确认与独立到达参考比较。运输等待中维持目标激活，异常处理采用相同有界策略，失败与未尝试样本保留在计划分母。',
226:'评价指标包括参考支持路径完成、提前及无支持更新、确认延迟、通信等待、视觉处理耗时、总执行时间和动作重试/恢复次数。通信重传与迁移Retry分账，独立采集组而非相邻帧作为实物重复单位。曝光级端到端分析还依赖经验证的时钟映射。',
227:'【待完成实验E-HW：真实单液滴视觉闭环控制及独立参考评价】',
229:'本章建立了单液滴视觉识别、电极空间映射、连续状态证据与事件驱动控制的方法链路。以420电极设计几何表示真实芯片空间，区分液滴面积覆盖与电极面积覆盖，并通过质心、目标距离、方向进展和时间戳速度描述任务相关运动。',
230:'完整五状态识别算法保留Unknown可靠性标记，通过连续证据和任务上下文生成一次性到达事件；视觉闭环控制器结合无进展监测、有界Retry及局部Recovery处理运输异常。S1单次运行展示了观测、状态与控制事件之间的对应关系。',
231:'真实图像材料完成了18幅审核Mask的传统分割Pilot及单照片8拟合点、16检查点的配准预实验。S2同输入比较表明，在所设条件下连续窗口降低短时覆盖错误，S/K在部分合成压力条件中提供额外拒绝；持续伪观测、历史重建、抖动和丢帧仍限制确认可靠性与时效。',
232:'上述结果支持算法机制及限定仿真条件下的到达行为分析。真实U-Net跨采集泛化、独立五状态准确率和实物闭环性能尚未完成验证，现有证据范围止于真实图像预实验与算法级仿真。'
}

CONDITION_NAMES=['正常稳定到达','短时覆盖闪变','持续至窗口长度的覆盖闪变','短时运动跳变','持续伪观测',
 '无参考到达的远端碎片','有参考到达的远端碎片','低置信伪观测','有参考到达的低置信观测','高置信伪观测','位置抖动','视觉丢帧','长断档']

def ptext(p):return ''.join(p._p.xpath('.//w:t/text()|.//m:t/text()'))

def body_signature(doc):
    formulas=[]
    for p in doc.paragraphs:
        if any('SEQ EquationCh2' in t for t in p._p.xpath('.//w:instrText/text()')):
            math=p._p.find(qn('m:oMath'));formulas.append(math_signature(math))
    return formulas

def math_signature(node):
    return (etree.QName(node).localname,node.text or '',tuple(sorted((etree.QName(k).localname,v) for k,v in node.attrib.items())),tuple(math_signature(c) for c in node))

def figure_drawings(doc):
    records=[]
    for p in doc.paragraphs:
        for drawing in p._p.xpath('.//w:drawing'):
            records.append(dict(relation=drawing.xpath('.//a:blip/@r:embed')[0],extent=[(n.get('cx'),n.get('cy')) for n in drawing.xpath('.//wp:extent')]))
    return records

def protect():
    path=OUT/'QA/protected_before.json'
    if path.exists():raise FileExistsError('Refusing to overwrite protection baseline')
    old=js(V1DIR/'QA/protected_before.json')
    paths=set(map(Path,old));paths.update(p for p in V1DIR.rglob('*') if p.is_file())
    paths.update(p for p in CLOSE.rglob('*') if p.is_file())
    dump(path,{str(p):sha(p) for p in sorted(paths)})
    print('protection files',len(paths))

def verify_protection():
    baseline=js(OUT/'QA/protected_before.json')
    changed=[p for p,h in baseline.items() if not Path(p).exists() or sha(p)!=h]
    result=dict(files=len(baseline),changes=changed,passed=not changed);dump(OUT/'QA/protection_verification.json',result)
    assert not changed,changed
    return result

def numbered_captions(doc):
    result=[]
    for p in doc.paragraphs:
        seq=[t for t in p._p.xpath('.//w:instrText/text()') if 'SEQ FigureCh2' in t or 'SEQ TableCh2' in t or 'SEQ EquationCh2' in t]
        if seq:result.append((seq[0].strip(),p._p.xpath('.//w:bookmarkStart/@w:name')))
    return result

def result_paragraphs(data):
    lookup={(r['condition'],r['method']):r for r in data['stats']}
    get=lambda c,m,k:int(lookup[c,m][k])
    # Assertions bind every fixed numerical sentence below to formal CSV fields.
    for m in ('BTQ','BTQ+S','BTQ+K','F_arrival'):
        assert get('A_normal',m,'supported_confirmations')==20
        assert get('B_flash_window',m,'unsupported_confirmations')==17
        assert get('C_jump_persistent',m,'unsupported_confirmations')==20
        assert get('E_highconf_false',m,'unsupported_confirmations')==20
        assert get('F_jitter',m,'missed_supported_confirmation')==20
        assert get('F_jitter',m,'late_supported_confirmations')==2
        assert get('F_jitter',m,'no_prediction_reference')==18
        assert get('F_dropout',m,'supported_confirmations')==5
        assert get('F_dropout',m,'late_supported_confirmations')==10
        assert get('F_dropout',m,'no_prediction_reference')==5
        assert get('F_gap',m,'supported_confirmations')==20
    assert get('A_normal','B_single_frame','premature_confirmations')==20
    assert get('C_jump_short','BTQ','unsupported_confirmations')==17 and get('C_jump_short','F_arrival','unsupported_confirmations')==1
    assert get('C_jump_short','BTQ+S','unsupported_confirmations')==17 and get('C_jump_short','BTQ+K','unsupported_confirmations')==1
    assert get('D_tail_false','BTQ+S','unsupported_confirmations')==0 and get('D_tail_false','BTQ+K','unsupported_confirmations')==20
    contrast=next(r for r in rows(S2/'formal/statistics/paired_contrasts.csv') if r['condition']=='C_jump_short' and r['comparison']=='F_arrival')
    assert [float(contrast[k]) for k in ('unsupported_difference','unsupported_difference_lo','unsupported_difference_hi')]==[-.8,-.95,-.6]
    diag=next(r for r in rows(S2/'formal/statistics/diagnostic_contrasts.csv') if r['condition']=='B_flash_short' and r['baseline']=='BQ_single_frame')
    assert float(diag['unsupported_difference'])==-1.
    norm=lookup['A_normal','BTQ']
    results=[
      '（5）到达事件比较结果',
      f'正常条件下，B_single_frame在20个计划步中均于独立参考到达前确认，主窗口支持数为0/20。BTQ、BTQ+S、BTQ+K和F_arrival均获得20/20次主窗口支持确认，平均确认延迟区间为[{float(norm["mean_latency_lower_s"]):.4f}, {float(norm["mean_latency_upper_s"]):.4f}] s，延迟样本数均为20。该区间由参考时刻的不确定性产生，不是均值置信区间。图2-11给出同一正常缓存下的判定时序。',
      '短时覆盖闪变中，B_single_frame与BQ_single_frame均产生20/20次无支持确认，BTQ及其空间/历史扩展均未确认。BQ与BTQ共享质量条件，差异对应连续窗口的作用。覆盖闪变持续至窗口长度后，四种强组均出现17/20次无支持确认，表明W对短瞬态有效，但其拒绝能力受伪观测持续时间限制。',
      '短时运动跳变中，BTQ与BTQ+S各产生17/20次无支持确认，BTQ+K与F_arrival各为1/20。F_arrival相对BTQ的配对无支持率差为−0.80，95%种子bootstrap区间为[−0.95, −0.60]。远端碎片且无参考到达时，BTQ和BTQ+K均为20/20次无支持确认，BTQ+S与F_arrival均为0/20。两组比较分别显示K与S在所设合成压力输入下的额外拒绝作用。',
      '低置信伪观测中，单帧覆盖率方法产生20/20次无支持确认，加入Q的辅助单帧方法及四种强组均未确认。在存在参考到达的低置信条件下，四种强组也均未确认，主窗口漏确认均为20/20。质量约束因此同时带来错误拒绝收益和有效确认机会损失，其适用性依赖质量信息与真实分割误差之间的对应关系。',
      '持续伪观测与高置信伪观测中，五种主方法均产生20/20次无支持确认。完整到达门仍会接受持续、稳定且满足覆盖与质量条件的错误Mask。这些失败说明当前有限历史及质量条件对系统性分割错误的可辨识性有限。',
      '位置抖动条件下，四种强组主窗口支持均为0/20，主窗口漏确认均为20/20，其中各有2次晚支持和18次无确认。丢帧条件下，四种强组主窗口支持均为5/20，漏确认均为15/20，其中10次晚支持、5次无确认；单帧覆盖率方法为2次支持和18次提前确认。晚支持仍属于主窗口漏确认的子集。图2-12同时展示正常、压力及不利观测条件。',
      '长断档条件下，四种强组重建证据后均获得20/20次主窗口支持，平均延迟区间为[0.3112, 0.3212] s；其延迟高于正常条件，反映重新积累证据的时间代价。本批计划任务均有完整输入和评分记录，未尝试、参考删失、确认删失及基础设施不确定计数均为0，模拟丢帧仍作为显式缺失观测保留。'
    ]
    limits=[
      '（6）失效机制与适用边界',
      '短时跳变仍有1次F_arrival无支持确认。该序列在缺Mask后的帧号缺口处重建K历史，首个新历史观测缺少可比较的过去位置，并按既定初始化规则通过；随后0.25 s稳定证据完成，约1.162 s产生确认。该反例说明，缺帧与历史初始化的组合仍可能使短时一致性门失去拒绝信息。',
      '持续伪观测可逐步进入原始运动历史，成为短时预测依据。即使启用K，只要错误Mask后续保持稳定且满足其他门，运动历史也可能适应该伪观测。高置信伪Mask同样表明置信与正确性并非等价；本批压力输入尚未按真实U-Net误差分布校准。',
      '有参考到达的远端碎片条件尚未隔离S的额外误拒代价。异常Mask从任务开始即存在，BTQ在独立参考到达前已消费唯一确认机会，F_arrival则始终未确认；二者主窗口支持均为0/20、漏确认均为20/20。该对照缺少无S方法原本能够正确确认的基准，因此无法估计S额外损失了多少正确确认。',
      '在全部六类存在参考到达的条件中，F_arrival与BTQ的主窗口支持数相同。此前开发阶段21份共同缓存的BTQ/F到达事件和时刻也全部一致。新增结果将S/K贡献限定为特定合成压力下的拒绝效果，未建立对一般模型条件或真实液滴观测的普遍性能优势。',
      '统计以每条件20个配对种子为单位，40个基础世界在13条件中复用。率与配对区间描述固定模型、参数和压力输入下的不确定性，不涵盖真实光学误差、流体过程及跨芯片变化。S1的单次机制轨迹、S2的同输入到达事件与完整视觉闭环控制的系统性能分别解释。'
    ]
    zero_fields=('unattempted_steps','confirmation_right_censored','reference_right_censored','infrastructure_unknown')
    assert all(sum(int(r[k]) for r in data['stats'])==0 for k in zero_fields)
    assert all(get('D_tail_true_cost',m,'supported_confirmations')==0 for m in ('BTQ','F_arrival'))
    return results,limits

def paragraph_insert_after(p):
    x=OxmlElement('w:p');p._p.addnext(x);return Paragraph(x,p._parent)

def settext(p,text,writer):
    pr=deepcopy(p._p.pPr) if p._p.pPr is not None else None
    run_pr=p._p.xpath('./w:r/w:rPr')
    run_pr=deepcopy(run_pr[0]) if run_pr else None
    for c in list(p._p):p._p.remove(c)
    if pr is not None:p._p.append(pr)
    writer.fill(p,text)
    if run_pr is not None:
        for r in p._p.xpath('./w:r'):
            current=r.find(qn('w:rPr'))
            if current is not None:r.remove(current)
            r.insert(0,deepcopy(run_pr))

def add_image(p,path,doc):
    for c in list(p._p):
        if c.tag!=qn('w:pPr'):p._p.remove(c)
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.keep_with_next=True
    p.add_run().add_picture(str(path),width=Cm(15.5))

def category(text):
    if any(x in text for x in ('【待','本版','本工作初稿','用户确认','当前仓库','不能','不得','不伪造','不补造','待写入','生产','source-','来源文件')):return 'C→学术转述或迁移'
    if any(x in text for x in ('误差','不确定','尚未','失败','边界','有限','仅用于','无支持','未完成','不能','缺帧','局限')):return 'B：科学边界'
    return 'A：方法与事实'

def amend_tables(doc,writer):
    changes={
      (0,0,2):'时间与证据说明',(0,1,2):'外部激励参数，独立于AM刷新',
      (0,2,1):'20×21扫描；设计频率300 Hz',(0,2,2):'底层扫描设计，实测刷新另行核验',
      (0,3,2):'区分曝光、接收与容器时间',
      (1,1,1):'帧身份、时钟、任务上下文、Applied',(1,3,2):'观测质量筛选，置信尚未作正确率校准',
      (2,1,2):'一般一致性窗口确认',(2,3,2):'一般一致性窗口及无进展保护',(2,6,2):'可靠性标记，独立于五种运动状态',
      (3,0,1):'完整五状态算法初始配置',(3,4,1):'0.5 mm（标定域）',(3,6,1):'0.5 mm（标定域）',
      (3,7,2):'相同质量定义；模拟置信未作真实校准',(3,8,1):'初始参数；未完成实物适用性标定',(3,8,2):'冻结算法级仿真参数，单位pitch',
      (4,6,2):'完成或保护停止；无后续事务时无Applied',
      (5,3,2):'模拟执行与运动响应分别建模',(5,5,2):'观测可用延迟参数',(5,6,2):'半径扰动0.015 pitch；简化观测模型',
      (5,8,2):'评分参考，与算法输入隔离',
      (7,7,2):'参考到达与异常Mask共存；误拒代价未隔离',
      (7,9,2):'参考到达时的低质量观测与确认损失'
    }
    for (ti,ri,ci),new in changes.items():settext(doc.tables[ti].cell(ri,ci).paragraphs[0],new,writer)
    for ri,name in enumerate(CONDITION_NAMES,1):settext(doc.tables[7].cell(ri,0).paragraphs[0],name,writer)

def build():
    assert sha(V1)=='355990246bcb9e50ae2a119cedf8e1c076af69317fb26de2160f3b8769f12c16','v1 changed; inspect edits before applying indexed revisions'
    if V2.exists():raise FileExistsError('Refusing to overwrite v2')
    data=collect();doc=Document(V1);original=list(doc.paragraphs);assert len(original)==233
    oldform=body_signature(doc);oldcaps=numbered_captions(doc);oldheads=[ptext(p) for p in doc.paragraphs if p.style.name.startswith('Heading')]
    olddraw=figure_drawings(doc)
    writer=object.__new__(Builder);writer.doc=doc
    results,limits=result_paragraphs(data)
    pilot=data['pilot']
    pilottext=(f'Pilot结果中，Otsu的平均Dice为{float(pilot[0]["mean_dice"]):.4f}、IoU为{float(pilot[0]["mean_iou"]):.4f}，'
      f'空Mask为1/18；自适应阈值分别为{float(pilot[1]["mean_dice"]):.4f}和{float(pilot[1]["mean_iou"]):.4f}，空Mask为0/18。'
      '质心误差分别为1.4461 px（17幅有效预测）和0.7512 px（18幅），检测失败单列保留。该结果描述同轮所选开发图像，尚未提供跨采集置信区间或真实U-Net比较结论。')
    revisions=[];moved=[];original_snapshot=[dict(paragraph=i,style=p.style.name,text=ptext(p),category=category(ptext(p))) for i,p in enumerate(original)]
    # Preserve a paragraph-to-section mapping independently of Word page shifts.
    sections={};section='前置页'
    numbers=js(V1DIR/'QA/structure_verification.json')['heading_records'];hit=iter(numbers)
    for i,p in enumerate(original):
        if p.style.name.startswith('Heading'):section=next(hit)['number']
        sections[i]=section
    for i,new in REVISIONS.items():
        old=ptext(original[i]);p=original[i]
        if new is None:
            moved.append(dict(paragraph=i,section=sections[i],old=old));p._p.getparent().remove(p._p);newtexts=[]
        else:
            newtexts=results if new=='@S2_RESULTS' else limits if new=='@S2_LIMITS' else [pilottext] if new=='@PILOT_RESULTS' else [new]
            settext(p,newtexts[0],writer)
            if newtexts[0].startswith('（5）') or newtexts[0].startswith('（6）'):
                p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.keep_with_next=True
                for r in p.runs:r.bold=True
            for text in newtexts[1:]:
                p=paragraph_insert_after(p);writer.fill(p,text)
                p.paragraph_format.line_spacing=1.5;p.paragraph_format.first_line_indent=Pt(24)
        revisions.append(dict(paragraph=i,section=sections[i],category=category(old),old=old,new=newtexts))
    # Only the figure placeholders change; existing caption fields remain.
    assets={11:Path(data['assets']['s2a']),12:Path(data['assets']['s2b'])}
    for pi,n in ((205,11),(207,12)):
        old=ptext(original[pi]);add_image(original[pi],assets[n],doc)
        revisions.append(dict(paragraph=pi,section='2.5.3',category='C→图稿来源迁移',old=old,new=[f'原样插入已存在的图2-{n}，来源登记在独立索引']))
    # Keep original caption fields and bookmark spans; revise only titles.
    caption_replacements={
      '生产识别器的状态含义与确认逻辑':'完整五状态识别算法的状态含义与确认逻辑',
      '生产初始配置与S2研究配置的区别':'完整五状态算法初始配置与S2研究配置的区别',
      '真实液滴分割Pilot及算法对比位置':'真实液滴分割Pilot与算法比较',
      '当前算法仿真的基础参数与单位':'算法级仿真的基础参数与单位',
      '同一闭环trial的任务阶段与空间特征':'同一闭环运行的任务阶段与空间特征'
    }
    for p in doc.paragraphs:
        if p.style.name=='Caption':
            for t in p._p.xpath('.//w:t'):
                for a,b in caption_replacements.items():
                    if a in (t.text or ''):t.text=t.text.replace(a,b)
    amend_tables(doc,writer)
    doc.core_properties.subject='硕士学位论文第二章学术语言规范化工作初稿 v2'
    doc.core_properties.comments='2026-10-26；基于v1定向修订，补入冻结S2结果，科研原始数据未变。'
    assert body_signature(doc)==oldform,'Numbered equations changed'
    assert numbered_captions(doc)==oldcaps,'Caption identities or equation numbering changed'
    assert [ptext(p) for p in doc.paragraphs if p.style.name.startswith('Heading')]==oldheads
    assert figure_drawings(doc)[:2]==olddraw
    OUT.mkdir(parents=True,exist_ok=True);doc.save(V2)
    source=OUT/'source';source.mkdir(exist_ok=True)
    dump(source/'revision_records.json',revisions);dump(source/'moved_original_notes.json',moved)
    dump(source/'full_paragraph_classification.json',original_snapshot)
    dump(source/'evidence_snapshot.json',data)
    dump(source/'structural_baseline.json',dict(numbered_math=oldform,caption_identities=oldcaps,headings=oldheads,s1_drawings=olddraw))
    shutil.copy2(__file__,source/Path(__file__).name)
    shutil.copy2(REPO/'scripts/chapter2_thesis_evidence.py',source/'chapter2_thesis_evidence.py')
    shutil.copy2(REPO/'scripts/build_chapter2_thesis_draft.py',source/'build_chapter2_thesis_draft.py')
    supporting(revisions,moved,data)
    dump(OUT/'QA/pre_render_verification.json',dict(passed=True,revised_paragraphs=len(revisions),numbered_equations=len(oldform),headings=len(oldheads),figures=12,tables=9,
         s1_drawings_unchanged=True,v1_sha256=sha(V1),v2_sha256=sha(V2),research_runs=0))
    print('v2 written',V2,'revised paragraphs',len(revisions))

def supporting(revisions,moved,data):
    esc=lambda s:s.replace('|','\\|').replace('\n','<br>')
    report=['# 第二章论文语言修订对照表','','版本：2026-10-26；基于现有v1直接定向修订，另存v2。',
      '', '## 分类与术语','',
      '- A：研究方法、技术原理、公式与实验事实；保留技术定义和参数。',
      '- B：科学局限、模型假设与负面结果；转为客观叙述并保留在正文。',
      '- C：工作区路径、开发约束、写作提醒和待办；移至独立索引，必要事实转为技术表述。',
      '- 统一术语：完整五状态识别算法；S2纯到达判定算法；视觉闭环控制器；算法级仿真；实物控制模式。',
      '', '## 修订范围','',
      '章节顺序、19个标题、20个编号公式、图2-1至图2-12及原9张表的编号保持。S1两图图片字节和尺寸保留；S2-A/B取既有图稿原样插入。表述清理不改变数值参数或评分分母。',
      '', '## 逐段对照','', '|v1段落/章节|内容类别|原文|v2修订或迁移结果|','|---|---|---|---|']
    for r in sorted(revisions,key=lambda x:x['paragraph']):
        after='<br><br>'.join(esc(v) for v in r['new']) or '移出正文，原文保存在独立追溯记录。'
        report.append(f'|P{r["paragraph"]:03d} / {r["section"]}|{r["category"]}|{esc(r["old"])}|{after}|')
    report.extend(['','## S2证据分配','',
      '|证据|作用|正文安排|','|---|---|---|',
      '|正常与短时闪变|单帧提前、W增量|2.5.3结果主段|',
      '|短跳变、远端碎片|K/S各自增量|结果主段；配对率差与区间|',
      '|持续伪观测、高置信错误|结论边界|正文结果与失效机制|',
      '|jitter/dropout与晚确认|可靠性—时效边界|正文，不移除失败|',
      '|历史重建剩余失败|边界案例|正文机制；原始seed/帧索引在追溯清单|',
      '|D_tail_true_cost|误拒代价不可辨识|正文局限，未伪造成本结论|',
      '|13条件全部65组与诊断|完整记录|独立追溯清单完整表及冻结CSV|',
      '', '未改动段落主要为A类方法或数学公式。完整原始段落快照与修订记录保存在source中。未重新拟合、计算新置信区间、运行仿真或筛选seed。'])
    (OUT/'第二章_论文语言修订对照表.md').write_text('\n'.join(report),encoding='utf-8')

    todo=['# 第二章内部待办与证据追溯清单','','此文件承接正文移出的写作管理、路径和来源信息，不属于论文正文。',
      '', '## 内部待办','',
      '|ID|章节|事项|状态/材料|','|---|---|---|---|',
      '|T01|2.1、2.3.1|核对视觉闭环、Otsu、自适应阈值、U-Net原始文献并补引|正文未插入虚构引文；本地已下载PDF需逐条阅读|',
      '|T02|2.2.1|实物相机/镜头铭牌及装配条件|型号后缀冲突，详见学术事实清单F01|',
      '|T03|图2-1—2-6|插入既有研究原图；版式与技术关系不重绘|保留6处简短图位；来源如下|',
      '|T04|2.5.1、图2-7|整理Pilot原图/GT/预测图；补独立采集与真实U-Net训练评价|传统Pilot已有，正式深度学习结果缺|',
      '|T05|2.5.2、图2-8|插入既有预实验叠加/残差；最终装置重标定|预实验数字已写入；最终标定未完成|',
      '|T06|2.5.3|校阅新增S2结果与完整失败解释|只读冻结数据；本轮不改判据或误差定义|',
      '|T07|2.5.4|S3/S4公平接口及研究协议验收后再确定实验范围|未启动正式新批次|',
      '|T08|2.5.5|真实模型、最终标定、波形/扫描与实物闭环|未开展本轮实物试验|',
      '|T09|整章|获得可靠浙大硕士论文模板后套版|现为统一暂定工科格式|',
      '', '## 来源索引','', '|ID|资料|绝对路径|证据状态|','|---|---|---|---|']
    for r in data['evidence']:todo.append(f'|{r["id"]}|{r["name"]}|{r["path"]}|{r["status"]}|')
    todo.extend(['','## S1/S2图稿绑定','',
      '- 图2-9 / S1-A：normal:262000:F:end_to_end；图片原样保留，图内来源标识不作删除。',
      '- 图2-10 / S1-B：同一trial，距离/进展来源为模拟Mask质心；原图不重绘。',
      '- 图2-11 / S2-A：A_normal_263000；五方法同一冻结缓存，四强方法重叠照实显示。',
      '- 图2-12 / S2-B：六代表条件正文主图，完整13条件在下表和冻结CSV保留。',
      '', '## S2全部条件与五方法结果','',
      '每组计划20步。S为H内支持，P为提前，U为无参考支持，M为H漏确认，L为晚支持（M子集），N0为有参考但无预测。R=0时支持率NA，不将0写成支持率0%。',
      '', '|条件|方法|参考R|S/P/U/M|晚支持L|无预测N0|','|---|---|---:|---|---:|---:|'])
    for r in data['stats']:
        vals='/'.join(r[k] for k in ('supported_confirmations','premature_confirmations','unsupported_confirmations','missed_supported_confirmation'))
        todo.append(f'|{r["condition"]}|{r["method"]}|{r["reference_arrivals"]}|{vals}|{r["late_supported_confirmations"]}|{r["no_prediction_reference"]}|')
    todo.extend(['','## 已知失败的原始定位','',
      '- C_jump_short_263016 / F_arrival：frame16无Mask，frame17的missing_id重建历史；曝光窗口[0.858,1.108] s，事件1.161926817 s。该定位来自既有逐帧日志和审查报告，未改判据。',
      '- D_tail_true_cost：静态异常Mask从任务起始存在，BTQ在参考前已消费事件，因此无法隔离S额外误拒正确到达的成本。',
      '- 旧21缓存BTQ/F事件与时刻一致，保留历史记录，不与新S2版本合池。',
      '', '## 移出的原始管理备注',''])
    for r in moved:todo.append(f'- v1 P{r["paragraph"]:03d}（{r["section"]}）：{r["old"]}')
    todo.extend(['','## 文件与更新','',
      f'- v1保留：{V1}',f'- v2：{V2}',
      '- 本轮使用现有Word作为底稿，不从旧Markdown重新创建。source/revision_records.json记录段落修订，source/structural_baseline.json记录公式与编号保护。',
      '- v2后续人工编辑前另存版本；本修订脚本拒绝覆盖已有v2。Word增删内容后更新目录及字段。',
      '- 渲染PDF/PNG仅在QA中用于版式检查；不作为新的科研图稿。'])
    (OUT/'第二章_内部待办与证据追溯清单.md').write_text('\n'.join(todo),encoding='utf-8')

    facts='''# 第二章仍需核验的学术事实清单

本清单区分已知研究局限与材料缺口；不以语言润色替代事实验证。

|ID|章节|学术事实或主张|现有依据|仍需核验及正文处理|
|---|---|---|---|---|
|F01|2.2.1|实际相机、镜头及装配参数|配置中MV-CS200-10UC与MV-CS200-10UC-V5冲突；镜头字段MVL-KF2524M-25MP|需铭牌/序列号/实际高度、焦点、盖板记录；正文保留待核验标记而非任选型号|
|F02|2.2.2|300 Hz为实际AM刷新频率|PC/固件接口设计参数为300 Hz、20×21|本轮未检查实测波形，仅写设计频率；实物值需第一章对应测量记录|
|F03|2.2、2.4|真实曝光发生于APPLIED之后|可记录主机接收、SDK原始计数|曝光时钟映射及顺序尚未验证；保留因果不确定性|
|F04|2.3.2|Gerber轮廓与电极编号/电气关系|420几何及既定布局绑定；角点方向1/20/381/400|设计几何已明确；网络表、电气连通与制造尺寸未独立检验，正文不把绑定写成电气验证|
|F05|2.5.2|最终装置标定精度|单照片8fit/16check，RMSE1.968 px等|仅单图设计一致性；最终高度、盖板、畸变及跨装夹尚缺|
|F06|2.5.1|传统分割优于U-Net或跨采集泛化|18图传统方法Pilot，同轮采集组1|没有真实U-Net正式权重/训练和独立测试；Pilot仅作描述|
|F07|2.4、2.5.3|五状态实际识别准确率|规则实现与单次机制展示|缺独立人工五状态GT；不输出真实混淆矩阵|
|F08|2.5.3|S/K普遍改善到达识别|局部合成压力增量，所有有参考条件BTQ/F主支持一致；旧21缓存事件一致|限定条件内拒绝收益，真实误差分布与普遍优势未验证|
|F09|2.5.3|S独立误拒代价已被量化|D_tail_true_cost的BTQ已提前消费事件|现有条件不可辨识该代价，正文保留明确局限；需新预声明可辨别对照，不能回改正式批次|
|F10|2.5.3|K能拒绝任意跳变或持续伪Mask|缺帧重建后1/20余错；持续伪观测/高置信伪Mask失败|这是已知失效边界，不是待删除异常；真实频率尚缺|
|F11|2.5.4|完整策略差异全部来自S/K|既有Deviation/Recovery路径与保护输入差别|需到达门×保护桥接，完整系统收益尚未形成新S3正式证据|
|F12|2.5.5|实物闭环成功率及延迟|当前有软件接口与方案|未完成联合实物验证；正文仅给实验方法及短占位|
|F13|整章|正式文献支持|本地有下载材料，正文尚未逐条核对|需原文核对并插入真实引文；不生成虚构编号或DOI|

## 术语与数值核验边界

完整五状态识别算法与S2纯到达判定算法具有不同历史采样及输出语义。0.75/0.10、0.25 s等初始完整算法配置与0.85/0.08、pitch单位的S2配置分别保留。仿真Mask、质量置信和设计坐标不等同于真实U-Net输出、校准概率或实物毫米测量。

## 统计外推

S2每条件20配对seed；40基础模拟世界经13观测条件复用，260缓存及1300方法调用不是独立实物重复。报告的bootstrap区间来自冻结统计，不以P值措辞扩大结论；零事件或退化区间不表示物理风险为零。jitter/dropout的晚支持保留在H主漏确认分母内。
'''
    (OUT/'第二章_仍需核验的学术事实清单.md').write_text(facts,encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('protect','build','verify'));args=p.parse_args()
    if args.action=='protect':protect()
    elif args.action=='build':build()
    else:print(verify_protection())

if __name__=='__main__':main()
