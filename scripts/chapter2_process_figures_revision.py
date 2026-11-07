"""Read frozen logs, redraw scientific process figures. No simulation execution."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle,Polygon,FancyArrowPatch
import numpy as np
from PIL import Image

from dmf.chapter2_sim.v2.replay import PersistedReplay
from scripts.audit_chapter2_v2_stage import read_csv,write_csv,write_json

BLUE='#176EAA';ORANGE='#D77A20';GREEN='#17826D';PURPLE='#8061A7';INK='#203448';GRAY='#687D8D'
COLORS={'Unknown':'#BAC2C9','Moving':BLUE,'Partial':ORANGE,'Arrived':GREEN}
TRIAL='normal:262000:F:end_to_end:full'
QA=Path.home()/'.agents/skills/nature-figure/scripts'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load_plot_source(path):
    r=PersistedReplay(path)
    if r.trial_id!=TRIAL:raise ValueError('Only the approved single trial is in scope')
    return r
def panel_records(r):return r.keyframes()
def visible_states(r):return [s for s in COLORS if any(f['state']==s for f in r.frames)]


def style():
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','Arial','DejaVu Sans'],
        'svg.fonttype':'none','pdf.fonttype':42,'font.size':12,'text.color':INK,'axes.labelcolor':INK,
        'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#AABBC7','xtick.color':GRAY,'ytick.color':GRAY,
        'legend.frameon':False,'axes.unicode_minus':False})


def save(fig,out,name):
    sys.path.insert(0,str(QA))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=out/(name+'.alignment.json'),overlay_svg=out/(name+'.alignment.svg'),strict=True)
    for ext in ('svg','pdf'):fig.savefig(out/(name+'.'+ext),facecolor='white')
    fig.savefig(out/(name+'.png'),dpi=600,facecolor='white')
    with Image.open(out/(name+'.png')) as im:
        im.thumbnail((1920,1440));im.save(out/(name+'.preview.png'))
    plt.close(fig)


def heading(fig,title,paper=False):
    fig.text(.05,.965,title,fontsize=12 if paper else 23,fontweight='bold',va='top')
    fig.text(.95,.965,'SIMULATION',fontsize=9 if paper else 14,color=BLUE,fontweight='bold',ha='right',va='top')
    fig.text(.05,.91,TRIAL,fontsize=6.5 if paper else 11,color=GRAY,va='top')


def footer(fig,text,paper=False):
    fig.text(.05,.027,text,fontsize=6.2 if paper else 10.5,color=GRAY,va='bottom')


BLOCKS=[('运动世界','DropletWorld','点位置与速度\n延迟响应与扰动'),('模拟视觉','SyntheticCamera','实际模拟Mask\n帧号与模拟时间'),
        ('共同证据','C0 / Q / W','任务与有效性约束\n覆盖率和连续窗口'),('判定与事件','S / K + ArrivalEvent','BTQ与F共享窗口\n事件仅消费一次'),
        ('控制反馈','EventController','Hold / Update\n有界Retry与Recovery')]


def architecture(out):
    fig,ax=plt.subplots(figsize=(13.333,7.5));fig.subplots_adjust(left=.035,right=.965,bottom=.12,top=.83)
    heading(fig,'简化二维视觉闭环仿真架构');ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
    xs=np.linspace(.012,.812,5);w=.176
    for x,(title,sub,body) in zip(xs,BLOCKS):
        ax.add_patch(Rectangle((x,.47),w,.40,fc='#EDF3F7',ec='#B9CDDD',lw=1))
        ax.text(x+.014,.82,title,fontsize=18,fontweight='bold',va='top',color=BLUE)
        ax.text(x+.014,.70,sub,fontsize=11.5,va='top')
        ax.text(x+.014,.61,body,fontsize=13,va='top',linespacing=1.65)
    for a,b in zip(xs[:-1],xs[1:]):ax.add_patch(FancyArrowPatch((a+w+.003,.68),(b-.004,.68),arrowstyle='-|>',mutation_scale=13,lw=1.5,color=INK))
    ax.plot([.90,.90,.10,.10],[.47,.35,.35,.47],lw=1.8,color=BLUE)
    ax.add_patch(FancyArrowPatch((.10,.40),(.10,.47),arrowstyle='-|>',mutation_scale=14,color=BLUE))
    ax.text(.5,.375,'控制动作改变目标电极及后续运动',ha='center',va='bottom',fontsize=15,color=BLUE)
    ax.add_patch(Rectangle((.12,.05),.76,.16,fc='#F6F2F8',ec='#D3C7E0'))
    ax.text(.15,.16,'独立评分支路',fontsize=14,fontweight='bold',color=PURPLE,va='center')
    ax.text(.39,.16,'内部位置与真实速度  ·  独立驻留参考',fontsize=13,va='center')
    ax.text(.15,.095,'评分读取内部真值，算法只读取模拟观测',fontsize=12,va='center')
    ax.add_patch(FancyArrowPatch((.10,.47),(.10,.13),arrowstyle='-',linestyle='--',color=PURPLE))
    ax.add_patch(FancyArrowPatch((.10,.13),(.12,.13),arrowstyle='-|>',mutation_scale=12,color=PURPLE))
    footer(fig,'420示例模板，单位pitch。二维点运动与圆形Mask。保留真实日志，不代表流体求解或实物验证。')
    save(fig,out,'V2-Process-1_PPT_简化架构')


def local_map(ax,r,s):
    for i,color in ((190,'#DFEDF6'),(191,'#FAEAD9')):
        p=np.asarray(r.geometry['polygons'][str(i)],float)
        ax.add_patch(Polygon(p,fc=color,ec='#A8BDCD',lw=1.1))
        ax.text(p[:,0].mean(),9.11,str(i),ha='center',va='center',fontsize=14,color=GRAY)
        if i==s['truth']['world_active']:ax.add_patch(Polygon(p,fc='none',ec=GREEN,lw=2.2))
    t=s['truth'];ax.plot(t['x'],t['y'],'o',ms=7,color=BLUE,zorder=8)
    if s['overlay_mask'] is not None:
        mask=s['overlay_mask'];lo=r.geometry['lower'];scale=r.geometry['scale']
        ax.contour(lo[0]+np.arange(mask.shape[1])/scale,lo[1]+np.arange(mask.shape[0])/scale,mask,levels=[127],colors=[ORANGE],linewidths=1.6)
        f=s['frame'];ax.plot(f['x'],f['y'],'x',ms=7,color=ORANGE,mew=1.7)
    ax.set(xlim=(8.95,11.05),ylim=(10.02,8.98),xticks=[],yticks=[])
    ax.set_aspect('equal',adjustable='box')
    for spine in ax.spines.values():spine.set_visible(False)


def keyframes(r,out):
    fig,axes=plt.subplots(2,3,figsize=(13.333,7.5));fig.subplots_adjust(left=.045,right=.955,bottom=.24,top=.80,wspace=.18,hspace=.65)
    heading(fig,'190至191：独立参考、视觉确认与模拟应用')
    titles=['源区确认','开始运动','跨电极观测','独立参考到达','算法确认与Update','下一目标模拟Applied']
    records=panel_records(r)
    for i,(ax,row) in enumerate(zip(axes.flat,records)):
        s=r.snapshot(row['time_s']);local_map(ax,r,s)
        ax.set_title(f"{chr(97+i)}  {titles[i]}\n{row['time_s']:.2f} s",fontsize=15,loc='left',pad=9,color=PURPLE if i==3 else GREEN if i==4 else BLUE if i==5 else INK)
        text=f"{s['state']} / {s['action']}"
        if i==5:text+='\n任务目标192，当前active191；旧Mask拒绝'
        elif i==3:text+='\n参考区间 [1.45, 1.46] s'
        ax.text(0,-.09,text,transform=ax.transAxes,fontsize=10.5,va='top',linespacing=1.5)
    fig.legend(handles=[Line2D([],[],marker='o',color=BLUE,ls='none',label='内部真实模拟位置'),Line2D([],[],color=ORANGE,lw=1.8,label='已处理有效Mask'),Line2D([],[],marker='x',color=ORANGE,ls='none',label='观测质心'),Line2D([],[],color=GREEN,lw=2,label='world.active')],loc='lower center',bbox_to_anchor=(.5,.075),ncol=4,fontsize=11)
    footer(fig,'固定观察190与191，单位pitch。预测状态不是GT。本trial未出现Stationary、Deviation、Retry或Recovery。')
    save(fig,out,'V2-Process-2_六阶段放大')
    return records


def position(ax,r,size):
    for k,c,label in (('x',BLUE,'内部x'),('y','#63A6C5','内部y')):
        ax.step(r.times,[v[k] for v in r.truth],where='post',color=c,lw=1.2,label=label)
    for k,c,label in (('x',ORANGE,'观测x'),('y','#9F5B21','观测y')):
        rows=[f for f in r.processed if f.get(k) is not None]
        ax.plot([f['processing_s'] for f in rows],[f[k] for f in rows],ls='none',marker='x',ms=3,color=c,label=label)
    ax.set_ylabel('位置 / pitch');ax.legend(loc='upper left',ncol=4,fontsize=size,bbox_to_anchor=(0,1.27))


def coverage(ax,r,size):
    for k,c,label in (('eta_target',ORANGE,'目标覆盖率'),('eta_source',BLUE,'源区残留')):
        ts=[];vs=[];last=None
        for f in r.processed:
            if last is not None and (f['epoch']!=last['epoch'] or f['frame_id']!=last['frame_id']+1):ts.append(float('nan'));vs.append(float('nan'))
            ts.append(f['processing_s']);vs.append(f.get(k) if f.get(k) is not None else float('nan'));last=f
        ax.plot(ts,vs,color=c,lw=1.1,marker='.',ms=2,label=label)
    ax.set(ylim=(-.04,1.07),yticks=[0,.5,1],ylabel='面积比例');ax.legend(loc='upper left',ncol=2,fontsize=size,bbox_to_anchor=(0,1.25))


def evidence(ax,r,size):
    for key,c,label,scale in (('window_count',BLUE,'帧数支持 N/5',5),('window_duration_s',ORANGE,'时长支持 T/0.25s',.25)):
        ax.step([g['processing_s'] for g in r.gates],[g.get(key,0)/scale for g in r.gates],where='post',color=c,lw=1.15,label=label)
    ax.axhline(1,color=GRAY,lw=.65,ls=':');ax.set(ylim=(-.04,1.35),yticks=[0,1],ylabel='连续证据支持')
    ax.legend(loc='upper left',ncol=2,fontsize=size,bbox_to_anchor=(0,1.25))


def states(ax,r,size):
    names=visible_states(r);snap=[r.snapshot(t)['state'] for t in r.times];begin=0
    for i in range(1,len(snap)+1):
        if i==len(snap) or snap[i]!=snap[begin]:
            end=r.times[-1] if i==len(snap) else r.times[i]
            if end>r.times[begin]:ax.broken_barh([(r.times[begin],end-r.times[begin])],(names.index(snap[begin])-.30,.60),fc=COLORS[snap[begin]])
            begin=i
    ax.plot(r.times[-1],names.index(snap[-1]),'s',ms=3,color=COLORS[snap[-1]])
    ax.set(yticks=range(len(names)),yticklabels=names,ylim=(-.6,len(names)-.4),ylabel='预测状态')
    ax.tick_params(axis='y',labelsize=size)


def events(ax,r,size):
    for ref in r.references:
        t=ref['upper_s'];ax.plot(t,3,'D',color=PURPLE,ms=4);ax.annotate(f'{t:.2f}',(t,3),xytext=(0,6),textcoords='offset points',ha='center',va='bottom',fontsize=size,color=PURPLE)
    for e in r.events:
        kind=e['event'];t=e['time_s']
        if kind not in ('ArrivalEvent','Start','Update','Complete','Applied'):continue
        y=2 if kind=='ArrivalEvent' else 0 if kind=='Applied' else 1;c=GREEN if y==2 else GRAY if y==0 else INK
        ax.plot(t,y,'o',ms=3.5,color=c)
        label=f'{t:.2f}' if y!=1 else f'{kind} {t:.2f}'
        ax.text(t,y+.16,label,fontsize=size,ha='right' if t>4 else 'center',va='bottom',color=c)
    ax.set(yticks=[0,1,2,3],yticklabels=['模拟Applied','控制请求','算法确认','独立参考'],ylim=(-.5,4.2),ylabel='日志事件')
    ax.tick_params(axis='y',labelsize=size)


def finish_axes(axes,r,size):
    for i,ax in enumerate(axes):
        ax.set_xlim(-.06,r.times[-1]+.12);ax.tick_params(labelsize=size)
        if ax.get_ylabel()!='日志事件':ax.grid(axis='x',color='#E7EDF2',lw=.5)
        ax.text(-.11,1.02,chr(97+i),transform=ax.transAxes,fontsize=size+1,fontweight='bold',va='bottom')
    axes[-1].set_xlabel('simulation时间 / s')


def timelines(r,out):
    fig,axes=plt.subplots(5,1,figsize=(7.2,7.8),sharex=True)
    fig.subplots_adjust(left=.15,right=.97,bottom=.11,top=.80,hspace=.50)
    heading(fig,'同一trial的运动、证据与控制事件',paper=True)
    with plt.rc_context({'font.size':7.5,'axes.labelsize':7.5}):
        position(axes[0],r,7);coverage(axes[1],r,7);evidence(axes[2],r,7);states(axes[3],r,7);events(axes[4],r,6.5);finish_axes(axes,r,7)
    footer(fig,'完整4.11s日志。状态为最近已处理帧显示。无Stationary/Deviation/Retry/Recovery。',True)
    save(fig,out,'V2-Process-3_论文完整版')
    for part,functions,title in [(1,[position,coverage],'模拟运动与视觉覆盖'),(2,[evidence,states,events],'连续证据、预测状态与控制事件')]:
        fig,axes=plt.subplots(len(functions),1,figsize=(13.333,7.5),sharex=True)
        fig.subplots_adjust(left=.13,right=.955,bottom=.13,top=.79,hspace=.55 if part==1 else .48)
        heading(fig,title)
        with plt.rc_context({'font.size':12,'axes.labelsize':12}):
            for ax,fn in zip(axes,functions):fn(ax,r,11)
            finish_axes(axes,r,11)
        footer(fig,'源/目标定义随步骤切换。全部为同一trial，单位pitch；观测点按处理时间显示。' if part==1 else '全部为同一trial。1.46s参考到达，1.92s算法确认，1.96s模拟Applied。未发生的状态与动作不补画。')
        save(fig,out,f'V2-Process-3_PPT-{part}_'+('运动与覆盖' if part==1 else '证据与事件'))


def summarize_existing(study,out):
    rows=[]
    for condition in sorted((study/'research_predictions').iterdir()):
        b=json.loads((condition/'BTQ/prediction_manifest.json').read_text(encoding='utf-8'));f=json.loads((condition/'F/prediction_manifest.json').read_text(encoding='utf-8'))
        signature=lambda m:[(e['step_id'],e['timestamp_s']) for e in m['events']]
        counts=Counter()
        for g in read_csv(condition/'F/gate_trace.csv'):
            raw=g.get('raw')
            if not isinstance(raw,dict) or not {'S','K','Q'}<=set(raw):continue
            counts['parsed']+=1;counts['Q_rejected']+=not raw['Q'];counts['K_rejected']+=not raw['K']
            counts['S_only_candidate_reject']+=bool(g['coverage_passed'] and raw['Q'] and raw['K'] and not raw['S'])
            counts['K_only_candidate_reject']+=bool(g['coverage_passed'] and raw['Q'] and raw['S'] and not raw['K'])
            counts['W_eligible_but_unconfirmed']+=bool(g['eligible'] and not g['confirmed'])
        rows.append(dict(condition=condition.name,input_same=b['input_sha256']==f['input_sha256'],events_identical=signature(b)==signature(f),**counts))
    write_csv(out/'existing_21_cache_diagnostics.csv',rows)
    probes=[]
    for case in sorted((study/'mechanism_predictions').iterdir()):
        gs=read_csv(case/'F/gate_trace.csv');raw=[g['raw'] for g in gs if isinstance(g.get('raw'),dict) and g['raw']]
        probes.append(dict(case=case.name,frames=len(gs),S_fail=sum(not g['S'] for g in raw),K_fail=sum(not g['K'] for g in raw),Q_fail=sum(not g['Q'] for g in raw),
            W_eligible_unconfirmed=sum(bool(g['eligible'] and not g['confirmed']) for g in gs),F_events=len(json.loads((case/'F/prediction_manifest.json').read_text(encoding='utf-8'))['events'])))
    write_csv(out/'mechanism_trigger_counts.csv',probes)


def main(trial,study,output):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);figures=output/'figures';data=output/'source_data';figures.mkdir();data.mkdir()
    r=load_plot_source(trial);style();architecture(figures);panels=keyframes(r,figures);timelines(r,figures)
    write_csv(data/'panel_sources.csv',panels);summarize_existing(study,data)
    sources={}
    for p in trial.rglob('*'):
        if p.is_file():sources[str(p)]=sha(p)
    for p in [study/'study_manifest.json',study/'method_contracts.json']:
        sources[str(p)]=sha(p)
    for parent in ['research_predictions','mechanism_predictions']:
        for p in (study/parent).rglob('*'):
            if p.is_file() and p.name in {'prediction_manifest.json','gate_trace.csv'}:sources[str(p)]=sha(p)
    for relative in ['observations/frames.csv','observations/gate_trace.csv','observations/events.csv','evaluation/truth_ticks.csv','evaluation/reference_intervals.csv','config_snapshot.json','electrode_map_snapshot.json']:
        p=trial/relative;shutil.copy2(p,data/Path(relative).name)
    write_json(data/'input_sha256.json',sources)
    write_json(output/'figure_manifest.json',dict(simulation=True,trial_id=r.trial_id,source_trial=str(trial),source_hashes=sources,new_simulation_runs=0,
        crop=dict(electrodes=[190,191],x=[8.95,11.05],y=[8.98,10.02],unit='pitch'),
        observed_states=visible_states(r),absent=['Stationary','Deviation','Retry','Recovery'],keyframes=panels,
        source_code_sha256=sha(__file__),figures=[p.name for p in figures.glob('*.pdf')],input_changes=[p for p,h in sources.items() if sha(p)!=h]))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--study',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.trial,a.study,a.output)
