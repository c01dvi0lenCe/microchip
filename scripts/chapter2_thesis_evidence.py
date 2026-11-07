"""Read-only evidence inventory for the 2026-10-26 Chapter 2 Word draft.

No model, recognizer, scoring or controller is imported or executed.
"""
from pathlib import Path
import csv
import hashlib
import json
import subprocess

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(r'D:/Learn/ZJU/第二章 单液滴视觉闭环')
OUT = ROOT/'论文初稿/2026-10-26_第二章Word工作初稿_v1'
S1 = ROOT/'仿真结果/2026-10-25_S1两张核心图_定稿候选_v1'
S2 = ROOT/'仿真结果/2026-10-25_S2正式仿真_v1'
CLOSE = ROOT/'仿真结果/2026-10-26_S2收尾与S3方案_v1'
PILOT = ROOT/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认'
REG = ROOT/'图像—电极配准/2026-10-23_配准独立复核与最终标定准备_v1'
MAP = ROOT/'电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):h.update(block)
    return h.hexdigest()

def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def js(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def dump(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def collect():
    stats=rows(S2/'formal/statistics/condition_statistics.csv')
    scores=rows(S2/'formal/step_scores.csv')
    diagnostics=rows(S2/'formal/diagnostic_scores.csv')
    assert len(stats)==65 and len(scores)==1300 and len(diagnostics)==260
    assert len({(r['condition'],r['method']) for r in stats})==65
    assert all(int(r['planned_steps'])==20 for r in stats)
    summary=rows(PILOT/'summary.csv')
    detail=rows(PILOT/'per_image.csv')
    assert len(detail)==36
    for s in summary:
        selected=[r for r in detail if r['method']==s['method']]
        for field in ('dice','iou','precision','recall'):
            assert abs(sum(float(r[field]) for r in selected)/18-float(s['mean_'+field]))<1e-12
        assert sum(r['empty_mask']=='True' for r in selected)==int(s['empty_masks'])
    numeric=('reference_arrivals','supported_confirmations','premature_confirmations',
             'unsupported_confirmations','missed_supported_confirmation','unattempted_steps',
             'confirmation_right_censored','reference_right_censored','infrastructure_unknown')
    for group in stats:
        ss=[r for r in scores if r['condition']==group['condition'] and r['method']==group['method']]
        assert len(ss)==20
        for field in numeric:
            if field in ss[0]:
                total=sum(float(r[field]) for r in ss)
                assert abs(total-float(group[field]))<1e-12,(group['condition'],group['method'],field)
    reg=js(REG/'independent_registration_audit.json')
    errors=[p['error_px'] for p in reg['points']]
    assert len(errors)==16
    assert abs((sum(v*v for v in errors)/16)**.5-reg['summary']['rmse_px'])<1e-12
    assets={
        's1a':S1/'S1-A_六阶段空间观测.png',
        's1b':S1/'S1-B_分阶段空间特征.png',
        's2a':CLOSE/'figures/S2-A/S2-A_同输入到达时序_收尾候选.png',
        's2b':CLOSE/'figures/S2-B_main/S2-B_代表条件与失效边界_正文候选.png',
        'reg':REG/'final_figures_v3/residual_vectors.png',
    }
    if not assets['reg'].exists():assets['reg']=REG/'residual_vectors.png'
    assert all(p.is_file() for p in assets.values())
    files={
        'E01':('系统与模式接口','2.2、2.4',REPO/'docs/chapter2-experiment.md','软件实现；非实物验证'),
        'E02':('生产状态与控制配置','2.4',REPO/'configs/chapter2_experiment.yaml','初始软件参数；未实测标定'),
        'E03':('生产五状态识别','2.4.1–2.4.2',REPO/'dmf/experiment/perception.py','实际实现'),
        'E04':('连续证据与任务因果','2.4.1–2.4.3',REPO/'dmf/experiment/evidence.py','实际实现；物理曝光映射未验证'),
        'E05':('有界策略与异常保护','2.4.3',REPO/'dmf/experiment/policy.py','实际实现；非实物闭环成功证据'),
        'E06':('空间特征定义','2.3.3',REPO/'dmf/vision/features.py','实际实现；单位依标定域'),
        'E07':('相机MVS配置','2.2.1',REPO/'configs/camera_mvs.yaml','配置型号MV-CS200-10UC，非铭牌核实'),
        'E08':('默认相机配置','2.2.1',REPO/'configs/camera.yaml','型号后缀冲突；镜头配置非实物确认'),
        'E09':('真实设计地图','2.3.2',MAP/'electrode_design_map.json','420设计轮廓；用户确认编号；非电气连通验证'),
        'E10':('地图来源与绑定','2.3.2',MAP/'manifest.json','Gerber来源与单位可追溯'),
        'E11':('真实视频资源','2.5.1',ROOT/'真实分割研究/2026-10-21_第一阶段与Pilot_v1/video_inventory.csv','10段同轮视频；容器帧率未经曝光验证'),
        'E12':('18张审核Mask','2.3.1、2.5.1',PILOT/'reviewed_snapshot/samples.csv','人工审核Pilot；Unknown运动标签保留'),
        'E13':('真实Pilot逐图指标','2.5.1',PILOT/'per_image.csv','真实图像开发描述；非正式独立测试'),
        'E14':('真实Pilot汇总和时间','2.5.1',PILOT/'summary.csv','已核对36行；无跨批次泛化CI'),
        'E15':('配准独立复核','2.3.2、2.5.2',REG/'independent_registration_audit.json','单照片8fit/16check预实验'),
        'E16':('配准原始检查坐标','2.5.2',REG/'independent_points.csv','原始人工检查点及逐点残差'),
        'E17':('S1单位及可观测性核查','2.5.3',REPO/'docs/chapter2-s1-final-technical-review-2026-10-25.md','n=1机制；观测质心进展/pitch'),
        'E18':('S1-A定稿源图','2.5.3',assets['s1a'],'原样插入；禁止重绘'),
        'E19':('S1-B定稿源图','2.5.3',assets['s1b'],'原样插入；禁止重绘'),
        'E20':('v1历史正式仿真','2.5.4',REPO/'docs/chapter2-formal-simulation-implementation-2026-10-21.md','历史版本独立保留；不合池'),
        'E21':('v2 E0–E3审查','2.5.3–2.5.4',REPO/'docs/chapter2-v2-stage-acceptance-2026-10-24.md','开发seed机制验收；21共同缓存BTQ/F一致'),
        'E22':('S2冻结正式配置','2.5.3',REPO/'configs/chapter2_s2_confirmatory.yaml','13条件×20配对seed；非实物重复'),
        'E23':('S2正式逐步评分','2.5.3',S2/'formal/step_scores.csv','1300主评分，失败与漏确认保留'),
        'E24':('S2辅助BQ评分','2.5.3',S2/'formal/diagnostic_scores.csv','260诊断，不混入五主方法'),
        'E25':('S2正式65组统计','2.5.3',S2/'formal/statistics/condition_statistics.csv','本稿数值表唯一汇总来源'),
        'E26':('S2配对效应','2.5.3',S2/'formal/statistics/paired_contrasts.csv','按seed配对；2000次bootstrap'),
        'E27':('S2科学局限','2.5.3',REPO/'docs/chapter2-s2-limitations-2026-10-26.md','记录反例和不可归因部分'),
        'E28':('S2-A最新图稿','2.5.3',assets['s2a'],'冻结数据只读绘图'),
        'E29':('S2-B最新图稿','2.5.3',assets['s2b'],'6代表条件；完整13条件另表保留'),
        'E30':('S3待实施协议','2.5.4',REPO/'docs/chapter2-s3-study-design-2026-10-26.md','研究方案，尚无专项正式结果'),
        'E31':('S4与四组研究框架','2.5.4',REPO/'docs/chapter2-four-simulation-studies-2026-10-25.md','消融机制及规划，不预设性能优势'),
        'E32':('S2共同门实现','2.4、2.5.3',REPO/'dmf/chapter2_sim/v2/arrival.py','研究到达门，不是完整五状态控制器'),
        'E33':('S/K/Q原始特征','2.4、2.5.3',REPO/'dmf/chapter2_sim/v2/observation.py','raw历史；开关不改变采样'),
        'E34':('模拟运动世界','2.5.3–2.5.4',REPO/'dmf/chapter2_sim/world.py','二维点运动；非CFD'),
        'E35':('模拟视觉','2.5.3–2.5.4',REPO/'dmf/chapter2_sim/vision.py','圆形简化Mask；非U-Net'),
        'E36':('S2独立参考与评分','2.5.3',REPO/'dmf/chapter2_sim/s2/evaluation.py','独立内部位置/速度/驻留；算法不读GT'),
        'E37':('S2统计设计','2.5.3',S2/'formal/statistics/statistics_manifest.json','seed为单位；不跨条件任意合池'),
        'E38':('模拟地图来源','2.5.3',REPO/'dmf/chapter2_sim/geometry.py','默认420示例模板，非Gerber毫米地图'),
        'E39':('U-Net现有适配器','2.3.1',REPO/'dmf/experiment/segmenter.py','接口存在不代表权重或训练完成'),
    }
    # Discover exact adapter name without guessing a source that does not exist.
    if not files['E39'][2].exists():
        candidates=list((REPO/'dmf').rglob('*unet*.py'))
        if candidates:files['E39']=(*files['E39'][:2],candidates[0],files['E39'][3])
    orig=ROOT/'第二章ppt/2026-10-23_第二章汇报_内容初稿_原图保真_v1/交付/原图与可编辑源稿'
    for i,n in enumerate(('01','04','05','06','07','08'),1):
        files[f'F{i:02d}']=(f'Fig.2-{i}原有研究图','2.2–2.4',orig/f'source-{n}.png','可核实原图；本稿预留位置，未重绘')
    inventory=[]
    for key,(name,section,p,status) in files.items():
        inventory.append(dict(id=key,name=name,section=section,path=str(p),exists=p.is_file(),
                              sha256=sha(p) if p.is_file() else None,status=status))
    return dict(stats=stats,pilot=summary,pilot_images=detail,registration=reg,
                videos=rows(ROOT/'真实分割研究/2026-10-21_第一阶段与Pilot_v1/video_inventory.csv'),
                evidence=inventory,assets={k:str(v) for k,v in assets.items()},
                counts=dict(primary=len(scores),diagnostic=len(diagnostics),groups=len(stats)))

def protected_files():
    files=[]
    for root in (S1,S2):files.extend(p for p in root.rglob('*') if p.is_file())
    for folder in ('configs','dmf','controllers','simulation','validation','tests'):
        files.extend(p for p in (REPO/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.extend((REPO/name) for name in ('main.py','app_controller.py','CONTEXT.md','docs/implementation-status.md'))
    return sorted(set(files))

def protect():
    OUT.mkdir(parents=True,exist_ok=True)
    destination=OUT/'QA/protected_before.json'
    if destination.exists():raise FileExistsError('Protection baseline already exists; do not replace')
    dump(destination,{str(p):sha(p) for p in protected_files()})
    dump(OUT/'QA/git_status_before.json',dict(status=subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True)))

def verify():
    old=js(OUT/'QA/protected_before.json')
    changed=[p for p,h in old.items() if not Path(p).is_file() or sha(p)!=h]
    result=dict(protected_count=len(old),changed=changed,passed=not changed)
    dump(OUT/'QA/protection_verification.json',result)
    assert not changed,changed
    return result

if __name__=='__main__':
    import sys
    action=sys.argv[1]
    if action=='inventory':
        data=collect();dump(OUT/'source/evidence_snapshot.json',data)
        print(json.dumps(dict(counts=data['counts'],missing=[r['path'] for r in data['evidence'] if not r['exists']]),ensure_ascii=False))
    elif action=='protect':protect();print('read-only protection baseline saved')
    elif action=='verify':print(json.dumps(verify(),ensure_ascii=False))
