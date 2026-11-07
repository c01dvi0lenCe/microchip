"""Read-only source review and physical-page PDF assembly, no figure redraw."""
from pathlib import Path
import csv
import argparse
import hashlib
import html
import io
import json
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import chapter2_paper_figure_closeout as p

BASE=p.BASE
SOURCE=BASE/'2026-10-27_仿真论文图_学术整理候选_v2'
OUT=BASE/'2026-10-27_仿真图定稿前复核与版心预览_v3'
WORD=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/论文初稿/2026-10-26_第二章学术语言修订_v2/第二章_单液滴视觉闭环控制_硕士论文工作初稿_v2.docx')
G3=BASE/'2026-10-26_S3_G3协议冻结_v1/S3_正式冻结协议.json'
TITLES=(
    '单液滴迁移的空间观测','同一迁移任务中的空间特征演化','相同模拟视觉输入下的到达确认时序',
    '到达判据比较及失效边界','四种闭环策略的运动轨迹与空间覆盖特征',
    '四种闭环策略的状态记录与控制事件','闭环策略的路径完成、安全性及预算化时间代价')
LABELS=('S1-A','S1-B','S2-A','S2-B','S3-A1','S3-A2','S3-B')
SHORT=(
    'DEVELOPMENT / n=1。normal，seed262000。六个时刻、模拟内部位置、已处理Mask及world.active均为原日志；不是性能统计。',
    'DEVELOPMENT / n=1。与S1-A同一trial。目标距离与方向投影来自模拟Mask质心，空间单位pitch；任务三阶段不作独立样本。',
    'FORMAL S2 / n=1示例。A_normal_263000共同缓存。金色区为独立参考到达；四强方法确认时刻重合。',
    'FORMAL S2。M为model-generated，X为synthetic stress；NA不是0。提前/无支持为两类计数，晚确认是主窗漏确认的子集。完整13条件保留。',
    'FORMAL / n=1 per strategy。G4，deviation，seed265000，四主trial。预声明正常/偏离场景的首个正式seed；共同外生条件，各自闭环轨迹。',
    'FORMAL / n=1 per strategy。与S3-A1同源。P_B组的Unknown包含策略屏蔽的非到达状态，不直接表征物理运动状态未知。Retry、Recovery和resend均来自实际日志。',
    'FORMAL。每条件每组20个配对trial，3计划步不是独立样本。a/b为Wilson95%区间；c/d为均值及冻结bootstrap95%区间。非严格成功的24s为惩罚，不是实际失败耗时。dropout中A为14/20、BTQ/F各12/20。')

def sha(q):return hashlib.sha256(Path(q).read_bytes()).hexdigest()
def read(q):
    with Path(q).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def load(q):return json.loads(Path(q).read_text(encoding='utf-8'))
def write_json(q,x):Path(q).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def minimum_at_width(font,old_width,new_width):return font*new_width/old_width

def captions():
    return '''# 第二章仿真论文图正式图注草稿

以下S1/S2/S3标识沿用研究图管理编号，正式论文图号在Word全文编号时对应调整。全部为SIMULATION；空间单位pitch；模型为简化二维点运动与SyntheticCamera观测，不是CFD、物理电润湿动力学或真实U-Net推理。

## S1-A 单液滴迁移的空间观测

开发阶段normal场景、seed262000的单次闭环机制示例（DEVELOPMENT，n=1），路线为190→191→192→172，主图放大首段190→191。蓝点为模拟世界内部位置，橙色轮廓与叉号分别为实际已处理的模拟Mask及其质心，浅蓝、浅橙为首段源、目标电极，绿色边框为world.active。a—f对应0.50、0.81、1.06、1.46、1.92和1.96s的真实日志时刻：源准备确认、已观测运动、跨电极迁移、独立参考到达、算法确认并请求Update、下一任务模拟Applied。0.50s原记录为Moving/Start，不表示Stationary；独立参考区间为[1.45,1.46]s。1.96s已进入191→192任务，旧Mask被拒绝而内部位置仍保留。预测状态并非独立状态GT，n=1用于说明机制，不作性能推断。

## S1-B 同一迁移任务中的空间特征演化

与S1-A同一开发阶段trial（DEVELOPMENT，n=1）。a为模拟内部及已处理Mask观测质心的x/y；b为源区残留η_source与目标覆盖η_target，分母均为液滴Mask总面积；c为观测质心至当前目标中心的距离以及沿源—目标方向的有符号投影距离，两者单位均为pitch，方向投影不是无量纲进展。任务阶段按模拟Applied在0.54、1.96和3.05s切换，末段于4.11s终止。距离和方向投影由模拟Mask质心与任务地图计算，不读取World真值作为算法输入。缺失、丢帧及任务切换处断线，不插值。三个运输阶段属于同一trial，不能视作三个独立重复。

## S2-A 相同模拟视觉输入下的到达确认时序

正式S2共同缓存A_normal_263000的单次示例（FORMAL S2，n=1），固定教师任务为190→191，任务模拟Applied为0.04s。a为目标覆盖率与源区残留，b为原始G/Q/S/K门通过或拒绝记录，c为连续证据窗口时长，d为五方法首次确认时刻。蓝方块表示通过，叉号表示拒绝或缺测；金色区间为独立参考到达[0.940,0.950]s，金色虚线为参考上界加1s的主确认窗口终点。单帧覆盖法于0.711s确认；BTQ、BTQ+S、BTQ+K及F_arrival均于1.059s确认，四者窗口和事件在此缓存重合。五方法共享Mask、任务、时钟与参考，确认结果不反向改变该缓存。该示例不代表F相对BTQ的普遍优势。

## S2-B 到达判据比较及失效边界

正式S2的五方法共同输入对照。正文展示六个既定代表条件，完整13条件及全部失败保留于附表。M表示model-generated，X表示synthetic stress；后者不等同真实液滴形变。每条件每方法20个配对seed/trial。a为主窗口内支持确认数/独立参考到达数；NA表示无独立参考到达，比例不定义，不等于0。b每格按“提前确认数/无支持确认数”显示两类计数，斜线不是分母，每条件planned=20。c为F_arrival−BTQ的配对比例差与冻结的seed级配对bootstrap95%逐点区间。d分别显示主窗口漏确认与主窗口后晚支持确认数，均以参考到达为分母；晚支持是主窗口漏确认的子集，二者不相加。正常、短暂跳变、远端碎片、持续伪Mask、jitter及dropout均保留，不能据局部压力条件宣称真实场景普遍优势。

## S3-A1 四种闭环策略的运动轨迹与空间覆盖特征

G4正式批次的预声明过程案例（FORMAL，deviation，seed265000，每策略n=1），四组为A_fixed/P_B、B_single/P_B、BTQ/P_B及F_full/P_F。案例选择规则为正式配置预先指定normal/deviation场景的首个正式seed265000，不按性能挑选最佳trial。四组共享外生运动扰动、模拟相机随机数组及P0源准备前缀；控制动作各自反作用于运动世界，因而后续轨迹、Mask与终止时刻不同。a、b、e、f分别为四组内部位置细线与已处理Mask质心观测点；c、d、g、h为对应源区残留与目标覆盖，分母均为液滴Mask面积。内部x为深蓝实线、内部y为低饱和紫色虚线，观测x为空心圆、观测y为加号；金色点线为独立参考到达区间上界。缺测与任务切换断线，无插值。单位pitch；此图为过程机制证据，不代表多seed平均性能。

## S3-A2 四种闭环策略的状态记录与控制事件

与S3-A1严格相同的四个G4正式trial（FORMAL，deviation，seed265000，每策略n=1），使用相同方法顺序与时间轴。a—d分别对应A_fixed/P_B、B_single/P_B、BTQ/P_B及F_full/P_F。所有状态符号来自处理后的逐帧日志。P_B组的Unknown包含策略屏蔽的非到达状态，不直接表征物理运动状态未知；因此不能据A/B/BTQ与F的状态散点差异比较五状态识别准确率。丢帧以单独短竖线保留，不补造状态。请求与模拟Applied分行显示，Retry为普通同目标重试，Recovery为局部源区恢复，resend为恢复确认后返回目标的重新施加（原事件名仍为recovering阶段Retry）。F示例实际有3次Recovery与3次resend、0次普通Retry；B和BTQ各有3次普通Retry。Complete为终止推进事件，不附加不存在的电极Applied。金色点线为独立参考上界，独立参考仅用于评分；模拟Applied不是实物ACK或实际高压输出。未出现新请求的区间为Hold或pending，不新增事件。

## S3-B 闭环策略的路径完成、安全性及预算化时间代价

正式S3七场景、四主策略，每条件每组n=20个配对simulation trial（seed265000—265019），共560主trial。独立统计单位为配对seed/trial，同一trial的3个计划步及其图像帧不是独立样本。a为独立参考支持路径完成率，b为含至少一次无支持推进请求的trial比例；推进请求包括Update及Complete，分母保留全部20个计划trial及源准备失败。a、b点为二项比例，误差棒为双侧Wilson95%置信区间，0%/100%及相应区间均保留。c为预算化路径完成时间代价：严格独立参考支持路径成功采用实际模拟完成时间，其余trial按冻结协议赋24s；24s是指标惩罚值，不是实际失败耗时或RMST。点为20个计划trial的算术均值，误差棒为冻结的seed级2000次有放回bootstrap均值百分位95%逐点区间（分析SeedSequence[20261026,303]），本轮不重新bootstrap。d为deviation场景的到达门×保护策略桥接，各单元n=20，展示每trial额外控制动作实际模拟Applied次数的均值及同类bootstrap区间。普通Retry、Recovery及恢复后返回目标resend分别计数，不包括常规Prepare、Start或Update；P_B两单元20个trial均为3/0/0次，P_F两单元均为0/3/3次，因此该条件组内无变化、区间退化为点。保护差异不能归因于S/K到达门的独立收益。dropout条件中A_fixed支持路径14/20，BTQ及F_full各12/20，完整方法并非所有条件均最好；jitter与持续故障失败同样保留。所有区间为逐点描述，不是同时置信区间，未新增显著性检验或普遍优越性结论。
'''

def paragraph_text(text):
    escaped=html.escape(text)
    return re.sub(r'([A-Za-z0-9][A-Za-z0-9 /_=.,:%+;\[\]-]*)',r'<font name="ThesisLatin">\1</font>',escaped)

def make_preview(files,geometry,width,path):
    import pymupdf
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont('ThesisChinese','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('ThesisLatin','C:/Windows/Fonts/times.ttf'))
    mm=72/25.4;page_w=geometry['page_width_mm']*mm;page_h=geometry['page_height_mm']*mm
    left=geometry['left_mm']*mm;top=geometry['top_mm']*mm;body=geometry['body_width_mm']*mm
    bottom=page_h-geometry['bottom_mm']*mm
    buffer=io.BytesIO();c=canvas.Canvas(buffer,pagesize=(page_w,page_h))
    positions=[]
    def draw_block(text,x,top,width):
        size=10.5;leading=15.;lines=[];line='';used=0.
        def font(ch):return 'ThesisLatin' if ord(ch)<128 else 'ThesisChinese'
        for token in re.findall(r'[A-Za-z0-9_:.=/+\-]+|\s+|.',text):
            tw=sum(pdfmetrics.stringWidth(ch,font(ch),size) for ch in token)
            if line and used+tw>width:lines.append(line.rstrip());line='';used=0.
            line+=token;used+=tw
        if line:lines.append(line.rstrip())
        for n,line in enumerate(lines):
            runs=[]
            for ch in line:
                f=font(ch)
                if runs and runs[-1][0]==f:runs[-1][1]+=ch
                else:runs.append([f,ch])
            xx=x;baseline=page_h-top-size-n*leading
            for f,run in runs:
                c.setFont(f,size);c.drawString(xx,baseline,run);xx+=pdfmetrics.stringWidth(run,f,size)
        return len(lines)*leading
    for i,source in enumerate(files):
        with pymupdf.open(source) as original:r=original[0].rect
        w=width*mm;h=w*r.height/r.width;x=left+(body-w)/2;y=top
        c.setStrokeColorRGB(.78,.8,.82);c.setLineWidth(.35)
        c.rect(left,page_h-bottom,body,bottom-top,stroke=1,fill=0)
        c.setFont('ThesisChinese',10);c.setFillColorRGB(.25,.3,.35)
        c.drawString(left,page_h-14*mm,f'版心核对  图宽{width:.2f}mm  非Word引擎导出')
        th=draw_block(f'{LABELS[i]}  {TITLES[i]}',left,y+h+4*mm,body)
        sh=draw_block(SHORT[i],left,y+h+4*mm+th+2*mm,body)
        caption_bottom=y+h+4*mm+th+2*mm+sh
        assert caption_bottom<=bottom+1e-4,(i,caption_bottom,bottom)
        c.setFont('ThesisChinese',9);c.setFillColorRGB(.35,.38,.4)
        c.drawString(left,11*mm,f'{i+1}/7  按现有Word页面几何等比例拼版  正式完整图注另附')
        positions.append((x,y,x+w,y+h));c.showPage()
    c.save();buffer.seek(0);doc=pymupdf.open(stream=buffer.getvalue(),filetype='pdf')
    measurements=[]
    for i,(page,source,rect) in enumerate(zip(doc,files,positions)):
        with pymupdf.open(source) as original:
            r=original[0].rect
            spans=[s for b in original[0].get_text('dict')['blocks'] if 'lines' in b for ln in b['lines'] for s in ln['spans'] if s['text'].strip()]
            minimum=min(s['size'] for s in spans);old_width=r.width/72*25.4
            page.show_pdf_page(pymupdf.Rect(rect),original,0)
        measurements.append(dict(page=i+1,figure=LABELS[i],source_width_mm=old_width,insert_width_mm=width,
            min_source_font_pt=minimum,transformed_min_font_pt=minimum_at_width(minimum,old_width,width),rectangle_pt=list(rect)))
        page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False).save(OUT/'QA'/f'{path.stem}_page_{i+1:02}.png')
    doc.save(path);doc.close();return measurements

def main():
    args=argparse.ArgumentParser();args.add_argument('--revise',action='store_true');ns=args.parse_args()
    if OUT.exists() and not ns.revise:raise FileExistsError(OUT)
    OUT.mkdir(exist_ok=True);(OUT/'QA').mkdir(exist_ok=True);(OUT/'来源').mkdir(exist_ok=True)
    from docx import Document
    d=Document(WORD);section=d.sections[0]
    geometry={k:v/36000 for k,v in dict(page_width_mm=section.page_width,page_height_mm=section.page_height,
        left_mm=section.left_margin,right_mm=section.right_margin,top_mm=section.top_margin,bottom_mm=section.bottom_margin).items()}
    geometry['body_width_mm']=geometry['page_width_mm']-geometry['left_mm']-geometry['right_mm']
    original_hashes={str(q):sha(q) for q in SOURCE.rglob('*') if q.is_file()}
    sources={str(WORD):sha(WORD),str(G3):sha(G3)}
    for q in ('config_manifest.json','planned_trials.json','completion_manifest.json','formal_trials.csv','formal_summary.csv'):
        sources[str(p.S3/q)]=sha(p.S3/q)
    config=load(p.S3/'config_manifest.json');plan=load(p.S3/'planned_trials.json')
    assert dict(scenario='deviation',seed=265000) in config['examples']
    formal=read(p.S3/'formal_trials.csv');index=load(SOURCE/'每图正式来源与hash索引.json');trials=index['S3-A1']['trials']
    assert trials==index['S3-A2']['trials']
    trace=[]
    for item in trials:
        tid=item['trial_id'];row=next(r for r in formal if r['trial_id']==tid and r['cohort']=='main')
        assert row['scenario']=='deviation' and row['seed']=='265000'
        assert any(r['scenario']=='deviation' and r['seed']==265000 and r['cohort']=='main' and r['method']==row['method'] for r in plan)
        manifest_path=next(r['path'] for r in item['files'] if Path(r['path']).name=='trial_manifest.json')
        manifest=load(manifest_path);assert manifest['schema']=='chapter2_s3_confirmatory_v1' and manifest['formal_seed_runs']==1
        assert manifest['purpose']=='formal_prespecified_SIMULATION_not_physical_experiment'
        assert manifest['G3_contract_sha256']==sha(G3)
        frozen=Path(manifest_path).parent/'source_code/dmf/chapter2_sim/s3_final/study.py'
        assert sha(frozen)==manifest['source_hashes']['dmf/chapter2_sim/s3_final/study.py']
        text=frozen.read_text(encoding='utf-8')
        assert text.index("examples=[dict(scenario=s,seed=265000)")<text.index('for i,item in enumerate(plan)')
        sources[str(frozen)]=sha(frozen);sources[str(manifest_path)]=sha(manifest_path)
        for src in item['files']:
            assert sha(src['path'])==src['sha256'];sources[src['path']]=src['sha256']
        trace.append(dict(figure='S3-A1 / S3-A2',stage='FORMAL G4',sample='n=1 per strategy',trial_id=tid,
            method=row['method'],protection=row['protection'],data_directory=str(Path(manifest_path).parent),
            manifest_sha256=sha(manifest_path),selection='prespecified normal/deviation first formal seed265000',
            selection_config_sha256=sha(p.S3/'config_manifest.json')))
    summary=read(p.S3/'formal_summary.csv')
    dropout={r['method']:int(r['path_complete']) for r in summary if r['cohort']=='main' and r['scenario']=='dropout'}
    assert dropout==dict(A_fixed=14,B_single=0,BTQ=12,F_full=12)
    files=sorted((SOURCE/'figures').glob('*.pdf'));assert len(files)==7
    (OUT/'每图正式caption草稿.md').write_text(captions(),encoding='utf-8')
    rows=[]
    for i,q in enumerate(files):
        rows.append(dict(page=i+1,figure=LABELS[i],source_pdf=str(q),source_sha256=sha(q),
            phase=('DEVELOPMENT n=1' if i<2 else 'FORMAL S2' if i<4 else 'FORMAL G4 n=1 per strategy' if i<6 else 'FORMAL G4 n=20 paired trial per cell'),
            figure_source_index=str(SOURCE/'每图正式来源与hash索引.json'),source_index_sha256=sha(SOURCE/'每图正式来源与hash索引.json')))
    for name,data in (('每图来源追溯表.csv',rows),('S3过程案例正式身份.csv',trace)):
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    (OUT/'来源/上一版每图来源与hash索引.json').write_bytes((SOURCE/'每图正式来源与hash索引.json').read_bytes())
    preview=[]
    for width,name in ((geometry['body_width_mm'],'当前Word版心160mm'),(150.,'保守图宽150mm')):
        preview.extend(make_preview(files,geometry,width,OUT/f'七图_{name}_A4尺寸核对.pdf'))
    changes=[q for q,h in original_hashes.items() if sha(q)!=h]
    assert not changes
    write_json(OUT/'QA/版心与来源复核.json',dict(passed_source_identity=True,figure_redraws=0,new_trials=0,new_predictions=0,
        bootstrap_rerun=False,source_v2_files_unchanged=len(original_hashes),changes=changes,word_geometry=geometry,
        word_file=str(WORD),word_sha256=sha(WORD),word_engine_rendered=False,
        preview_kind='physical vector A4 assembly using existing Word section geometry; not Word engine export',
        dropout_supported_paths=dropout,preview_measurements=preview))
    write_json(OUT/'来源/完整来源hash索引.json',dict(inputs=sources,protected_v2=original_hashes,
        caption_source_index=rows,script_sha256=sha(__file__)))
    print(json.dumps(dict(figures_redrawn=0,source_v2_files_unchanged=len(original_hashes),body_width_mm=geometry['body_width_mm'],formal_examples=4),ensure_ascii=False))

if __name__=='__main__':main()
