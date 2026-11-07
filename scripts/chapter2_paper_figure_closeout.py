"""Read-only SIMULATION figure styling. No model, prediction or scoring calls.

All statistics and uncertainty intervals come from frozen CSVs. Source images,
algorithms, trials and earlier plotting scripts are never edited.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import shutil
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
S1=BASE/'2026-10-25_S1两张核心图_定稿候选_v1'
S2=BASE/'2026-10-25_S2正式仿真_v1/formal'
S2FIG=BASE/'2026-10-26_S2收尾与S3方案_v1/figures/S2-A'
S3=BASE/'2026-10-26_S3正式仿真_v1'
S3FINAL=BASE/'2026-10-26_S3正式验收与论文图_v1'
OUT=BASE/'2026-10-27_仿真论文图_清晰版候选_v1'
WIDTH_MM=160
MIN_PT=8.5
METHODS=('A_fixed','B_single','BTQ','F_full')
SCENARIOS=('normal','delayed','partial_stall','jitter','dropout','deviation','failure')
S2METHODS=('B_single_frame','BTQ','BTQ+S','BTQ+K','F_arrival')
CONDITIONS=('A_normal','C_jump_short','D_tail_false','C_jump_persistent','F_jitter','F_dropout')
CONDITION_LABELS=('M 正常','X 短暂跳变','X 远端碎片','X 持续伪Mask','M 抖动','M 丢帧')
BLUE='#286696';PURPLE='#80649C';ORANGE='#B9783C';GREEN='#398B75';GOLD='#AD7F28'
COLORS=('#7D8790','#BD916E','#6597B0','#234E6B')
MARKERS=('s','v','o','D')
STATES=('Unknown','Stationary','Moving','Partial','Arrived','Deviation')
STATE_COLORS=('#A9ADB1','#788F9B',BLUE,'#D69A4D',GREEN,'#B16A61')
ACTION_COLORS={'Prepare':'#88929A','Start':'#648C9F','Update':'#234E6B','Retry':'#9D704D',
               'Recovery':'#AE665F','Complete':'#398B75','Stop':'#212B33'}
_USED={}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def remember(p):
    p=Path(p);_USED[str(p)]=sha(p);return p
def read(p):
    with remember(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def load(p):return json.loads(remember(p).read_text(encoding='utf-8'))
def write_json(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def value(r,k):return float(r[k]) if r.get(k) not in ('',None) else np.nan

def s2_cell(row):
    r,s,p,u,n=[int(row[k]) for k in ('reference_arrivals','supported_confirmations','premature_confirmations','unsupported_confirmations','planned_steps')]
    if n<=0 or not 0<=s<=r or p<0 or u<0:raise ValueError('invalid frozen counts')
    return s/r if r else np.nan,(p+u)/n,(f'{s}/{r}' if r else 'NA',f'{p}/{u}')

def interval_values(row):
    y,lo,hi=[float(row[k]) for k in ('mean','ci_low','ci_high')]
    if not np.isfinite([y,lo,hi]).all() or lo>y+1e-12 or hi<y-1e-12:raise ValueError('invalid frozen interval')
    return y,lo,hi

def observed_series(rows,field):
    ts=[];ys=[];prev=None
    for row in rows:
        good=row.get('processing_s') not in ('',None) and row.get(field) not in ('',None)
        context=(row['step'],row['epoch'])
        if not good or prev is not None and (int(row['frame_id'])!=prev[0]+1 or context!=prev[1]):
            ts.append(np.nan);ys.append(np.nan)
        if good:ts.append(float(row['processing_s']));ys.append(float(row[field]))
        prev=(int(row['frame_id']),context) if good else None
    return np.asarray(ts),np.asarray(ys)

def validate_summary(rows):
    main=[r for r in rows if r['cohort']=='main']
    if len(main)!=28:raise ValueError('all seven scenarios/four main methods required')
    for s in SCENARIOS:
        for m in METHODS:
            rs=[r for r in main if r['scenario']==s and r['method']==m]
            if len(rs)!=1 or int(rs[0]['planned_trials'])!=20:raise ValueError('complete planned denominator required')
    return main

def select_trials(rows):
    chosen=[]
    for method in METHODS:
        rs=[r for r in rows if r['cohort']=='main' and r['scenario']=='deviation' and r['seed']=='265000' and r['method']==method]
        if len(rs)!=1:raise ValueError('fixed four-strategy deviation/265000 trial identity required')
        chosen.append(rs[0])
    return chosen

def style():
    import matplotlib as mpl
    mpl.use('Agg')
    from matplotlib import font_manager
    for path in ('C:/Windows/Fonts/arial.ttf','C:/Windows/Fonts/simhei.ttf'):
        if Path(path).exists():font_manager.fontManager.addfont(path)
    mpl.rcParams.update({'font.family':['Arial','SimHei'],'font.size':9,'axes.labelsize':9,
        'axes.titlesize':10,'xtick.labelsize':9,'ytick.labelsize':9,'legend.fontsize':MIN_PT,
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,
        'legend.frameon':False,'svg.fonttype':'none','pdf.fonttype':42,'text.usetex':False})

def figure_header(fig,title):
    fig.text(.04,.987,title,fontsize=10.5,weight='bold',va='top')
    fig.text(.98,.987,'SIMULATION',fontsize=MIN_PT,ha='right',va='top',color='#526879')

def label(ax,text):
    ax.annotate(text,(0,1),xycoords='axes fraction',xytext=(-14,6),textcoords='offset points',
                weight='bold',fontsize=10,annotation_clip=False)

def save(fig,name):
    import matplotlib.pyplot as plt
    skill=Path.home()/'.agents/skills/nature-figure/scripts'
    if str(skill) not in sys.path:sys.path.insert(0,str(skill))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=OUT/'QA'/f'{name}.alignment.json',
        overlay_svg=OUT/'QA'/f'{name}.alignment.svg',tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(OUT/'figures'/f'{name}.svg')
    fig.savefig(OUT/'figures'/f'{name}.pdf')
    fig.savefig(OUT/'figures'/f'{name}.png',dpi=600)
    fig.savefig(OUT/'previews'/f'{name}.png',dpi=300)
    plt.close(fig)

def render_s2_a():
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    data=load(S2FIG/'source_manifest.json');rows=data['traces']['BTQ']
    times=np.asarray([float(r['processing_s']) for r in rows]);raw=[json.loads(r['raw']) if r.get('raw') else None for r in rows]
    ref=data['reference'];lo,hi=ref['lower_s'],ref['upper_s'];task=data['task']
    fig,axes=plt.subplots(4,1,figsize=(WIDTH_MM/25.4,175/25.4),sharex=True,
        gridspec_kw={'height_ratios':[1,1,1,1.35]})
    fig.subplots_adjust(left=.22,right=.975,top=.91,bottom=.09,hspace=.38)
    figure_header(fig,'到达判定时序')
    axes[0].plot(times,[r['eta_target'] if r else np.nan for r in raw],'-o',ms=2.1,lw=1.1,color=BLUE,label='目标覆盖')
    axes[0].plot(times,[r['eta_source'] if r else np.nan for r in raw],'--s',ms=1.8,lw=1,color=ORANGE,label='源区残留')
    axes[0].axhline(.85,color=BLUE,ls=':',lw=.7);axes[0].axhline(.08,color=ORANGE,ls=':',lw=.7)
    axes[0].set(ylabel='面积比例',ylim=(-.05,1.08));axes[0].legend(loc='center right')
    for j,g in enumerate(('G','Q','S','K')):
        vs=[None if r is None else r['eta_target']>=.85 and r['eta_source']<=.08 if g=='G' else bool(r[g]) for r in raw]
        passed=np.array([v is True for v in vs]);failed=np.array([v is False for v in vs])
        axes[1].scatter(times[passed],np.full(sum(passed),j),s=9,color=BLUE,marker='s')
        axes[1].scatter(times[failed],np.full(sum(failed),j),s=11,color=ORANGE,marker='x')
    missing=np.array([r is None for r in raw]);axes[1].scatter(times[missing],np.full(sum(missing),-.7),s=13,color='#777777',marker='x')
    axes[1].set(yticks=[-.7,0,1,2,3],yticklabels=['缺测','G','Q','S','K'],ylim=(-1.1,3.6),ylabel='原始门')
    for method,color,ls in zip(S2METHODS[1:],['#929aa0','#657e91','#447b9e','#16496c'],['-','--',':','-.']):
        trace=data['traces'][method];events=data['events'][method];stop=events[0]['timestamp_s'] if events else float('inf')
        x=[float(r['processing_s']) for r in trace]
        y=[float(r['window_duration_s']) if r.get('window_duration_s') and float(r['processing_s'])<=stop else np.nan for r in trace]
        axes[2].plot(x,y,color=color,ls=ls,lw=1.3)
    axes[2].axhline(.25,ls=':',color='#777777',lw=.7)
    axes[2].set(ylabel='证据时长 / s',ylim=(-.025,.34))
    axes[2].text(.98,.5,'BTQ / +S / +K / F',ha='right',va='center',transform=axes[2].transAxes,fontsize=MIN_PT)
    for j,method in enumerate(S2METHODS):
        events=data['events'][method];y=4-j
        for event in events:axes[3].scatter(event['timestamp_s'],y,marker='D',s=25,color='#16496c')
        axes[3].text(2.5,y,f"{events[0]['timestamp_s']:.3f} s" if events else '无确认',va='center',fontsize=MIN_PT)
    axes[3].set(yticks=range(5),yticklabels=['F','BTQ+K','BTQ+S','BTQ','单帧'],ylim=(-.6,4.6),
                ylabel='首次确认',xlabel='simulation时间 / s')
    for letter,ax in zip('abcd',axes):
        label(ax,letter);ax.set_xlim(0,task['end_s']+.08);ax.set_xticks([0,1,2,3,4])
        ax.axvline(task['applied_s'],ls=':',color='#aeb7bd',lw=.65,zorder=0)
        ax.axvspan(lo,hi,color='#D5AA55',alpha=.5,zorder=0)
        ax.axvline(hi,color=GOLD,lw=1,zorder=0);ax.axvline(hi+1,color=GOLD,ls='--',lw=.8,zorder=0)
        ax.tick_params(direction='out',length=3)
    fig.legend(handles=[Line2D([],[],color=GOLD,lw=1,label='参考到达'),Line2D([],[],color=GOLD,ls='--',label='主窗结束')],
               loc='upper center',bbox_to_anchor=(.6,.967),ncol=2,handlelength=1.6,fontsize=MIN_PT)
    save(fig,'S2-A_到达时序_论文候选')

def render_s2_b():
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D
    all_rows=read(S2/'statistics/condition_statistics.csv')
    if len(all_rows)!=65:raise ValueError('full 13-condition five-method table required')
    lookup={(r['condition'],r['method']):r for r in all_rows}
    paired=read(S2/'statistics/paired_contrasts.csv')
    contrasts={r['condition']:r for r in paired if r['baseline']=='BTQ' and r['comparison']=='F_arrival'}
    support=np.full((6,5),np.nan);errors=np.zeros((6,5));failure=np.full((6,4),np.nan)
    la=[];lb=[];ld=[]
    for i,c in enumerate(CONDITIONS):
        a=[];b=[];d=[]
        for j,m in enumerate(S2METHODS):
            support[i,j],errors[i,j],labels=s2_cell(lookup[c,m]);a.append(labels[0]);b.append(labels[1])
        for j,(m,k) in enumerate((('BTQ','missed_supported_confirmation'),('F_arrival','missed_supported_confirmation'),
                                  ('BTQ','late_supported_confirmations'),('F_arrival','late_supported_confirmations'))):
            r=lookup[c,m];n=int(r['reference_arrivals']);v=int(r[k]);failure[i,j]=v/n if n else np.nan
            d.append(f'{v}/{n}' if n else 'NA')
        la.append(a);lb.append(b);ld.append(d)
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,185/25.4))
    fig.subplots_adjust(left=.205,right=.98,top=.875,bottom=.10,wspace=.36,hspace=.62)
    figure_header(fig,'到达判据对比与失效边界')
    cmap=LinearSegmentedColormap.from_list('fractions',['#ffffff','#a9c4d3']);cmap.set_bad('#eeeeee')
    for ax,matrix,txt,title,ticks in ((axes[0,0],support,la,'主窗内支持确认',['单帧','BTQ','+S','+K','F']),
        (axes[0,1],errors,lb,'提前 / 无支持',['单帧','BTQ','+S','+K','F']),
        (axes[1,1],failure,ld,'漏确认 / 晚确认',['BTQ\n漏','F\n漏','BTQ\n晚','F\n晚'])):
        ax.imshow(matrix,aspect='auto',cmap=cmap,vmin=0,vmax=1,interpolation='none')
        for i in range(6):
            for j in range(len(ticks)):ax.text(j,i,txt[i][j],ha='center',va='center',fontsize=MIN_PT,color='#17384f')
        ax.set(yticks=range(6),yticklabels=CONDITION_LABELS if ax is axes[0,0] else [],xticks=range(len(ticks)),xticklabels=ticks,ylim=(5.5,-.5))
        ax.xaxis.tick_top();ax.tick_params(length=0,pad=5,labelsize=MIN_PT);ax.set_title(title,pad=30,fontsize=9.5)
        for spine in ax.spines.values():spine.set_visible(False)
    ax=axes[1,0];ax.axvline(0,color='#aab3b9',lw=.7,zorder=0)
    styles=(('support',BLUE,'o',-.17,'支持'),('premature',ORANGE,'s',0,'提前'),('unsupported','#666666','D',.17,'无支持'))
    for field,color,marker,offset,title in styles:
        for i,c in enumerate(CONDITIONS):
            r=contrasts[c]
            if not r[field+'_difference']:continue
            v,lo,hi=[float(r[field+'_difference'+s]) for s in ('','_lo','_hi')]
            ax.errorbar(v,i+offset,xerr=[[max(0,v-lo)],[max(0,hi-v)]],fmt=marker,ms=3.6,lw=.9,color=color,capsize=1.8)
    ax.legend(handles=[Line2D([],[],color=c,marker=m,lw=.8,ms=3.5,label=t) for _,c,m,_,t in styles],loc='center right',fontsize=MIN_PT,handlelength=1.2)
    ax.set(yticks=range(6),yticklabels=CONDITION_LABELS,ylim=(5.5,-.5),xlim=(-1.1,1.1),xticks=[-1,0,1],xlabel='F − BTQ 比例差值')
    ax.set_title('配对差值及95%区间',pad=30,fontsize=9.5)
    for letter,ax in zip('abcd',axes.flat):label(ax,letter)
    save(fig,'S2-B_判据对比_论文候选')

def trial_data():
    data=[]
    for row in select_trials(read(S3/'formal_trials.csv')):
        p=S3/row['relative_trial_path']
        data.append(dict(metric=row,path=p,truth=read(p/'evaluation/truth_ticks.csv'),
            frames=read(p/'observations/frames.csv'),refs=read(p/'evaluation/reference_intervals.csv'),
            events=read(p/'observations/events.csv')))
    return data

def references(ax,rows):
    for row in rows:
        if row['activation_target']==row['target'] and row['target'] in ('191','192','172'):
            ax.axvline(value(row,'upper_s'),color=GOLD,ls=':',lw=.7,zorder=0)

def render_s3_motion(data):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig,axes=plt.subplots(4,2,figsize=(WIDTH_MM/25.4,205/25.4),sharex=True)
    fig.subplots_adjust(left=.13,right=.975,top=.875,bottom=.075,wspace=.28,hspace=.43)
    figure_header(fig,'四策略运动与覆盖率')
    end=max(value(d['metric'],'execution_time_s') for d in data)
    positions=[value(t,k) for d in data for t in d['truth'] for k in ('x','y')]
    names=('A / P_B','B / P_B','BTQ / P_B','F / P_F')
    for i,d in enumerate(data):
        r=(i//2)*2;c=i%2;a,b=axes[r,c],axes[r+1,c]
        ts=[value(t,'time_s') for t in d['truth']]
        a.plot(ts,[value(t,'x') for t in d['truth']],color=BLUE,lw=1)
        a.plot(ts,[value(t,'y') for t in d['truth']],color=PURPLE,lw=1,ls='--')
        for k,color,marker in (('x',ORANGE,'x'),('y','#B9A16D','+')):
            x,y=observed_series(d['frames'],k);a.plot(x,y,lw=0,color=color,marker=marker,ms=2)
        a.set_title(names[i],fontsize=10,pad=9);a.set_ylim(min(positions)-.15,max(positions)+.15)
        a.set_ylabel('位置 / pitch' if c==0 else '')
        for k,color,ls in (('eta_target',GREEN,'-'),('eta_source',ORANGE,'--')):
            x,y=observed_series(d['frames'],k);b.plot(x,y,color=color,lw=1,ls=ls)
        b.set(ylim=(-.04,1.07),ylabel='面积比例' if c==0 else '',xlabel='simulation时间 / s')
        references(a,d['refs']);references(b,d['refs'])
    for letter,ax in zip('abcdefgh',axes.flat):
        label(ax,letter);ax.set_xlim(-.15,end+.15);ax.set_xticks([0,4,8,12])
    handles=[Line2D([],[],color=BLUE,label='内部x'),Line2D([],[],color=PURPLE,ls='--',label='内部y'),
        Line2D([],[],color=ORANGE,marker='x',lw=0,label='观测x'),Line2D([],[],color='#B9A16D',marker='+',lw=0,label='观测y'),
        Line2D([],[],color=ORANGE,ls='--',label='源区残留'),Line2D([],[],color=GREEN,label='目标覆盖'),Line2D([],[],color=GOLD,ls=':',label='参考到达')]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.53,.957),ncol=4,fontsize=MIN_PT,
               columnspacing=1,handlelength=1.5,handletextpad=.4)
    save(fig,'S3-A1_运动与覆盖_论文候选')

def render_s3_control(data):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,175/25.4),sharex=True)
    fig.subplots_adjust(left=.15,right=.975,top=.90,bottom=.25,wspace=.35,hspace=.38)
    figure_header(fig,'四策略状态与控制事件')
    end=max(value(d['metric'],'execution_time_s') for d in data)
    for i,(ax,d) in enumerate(zip(axes.flat,data)):
        for row in d['frames']:
            if row.get('processing_s'):
                j=STATES.index(row['state']);ax.scatter(value(row,'processing_s'),j,s=6,color=STATE_COLORS[j],lw=0)
            elif row.get('reason')=='CAMERA_DROPPED':ax.plot(value(row,'available_s'),0,'x',color='black',ms=2,mew=.6)
        for row in d['events']:
            if row['event']=='Applied':ax.plot(value(row,'time_s'),7,'|',color=GREEN,ms=6,mew=1)
            elif row['event'] in ACTION_COLORS:ax.plot(value(row,'time_s'),6,'v',color=ACTION_COLORS[row['event']],ms=4,mew=0)
        references(ax,d['refs'])
        ax.set_title(('A / P_B','B / P_B','BTQ / P_B','F / P_F')[i],pad=10,fontsize=10)
        ax.set_yticks(range(8),['未知','静止','运动','部分','到达','偏离','请求','施加'])
        ax.set(ylim=(-.4,7.6),xlim=(-.15,end+.15),xlabel='simulation时间 / s');ax.set_xticks([0,4,8,12]);label(ax,chr(97+i))
    zh=('准备','启动','更新','重试','恢复','完成','停止')
    handles=[Line2D([],[],color=c,marker='v',lw=0,label=t) for c,t in zip(ACTION_COLORS.values(),zh)]
    handles.extend([Line2D([],[],color=GREEN,marker='|',lw=0,label='模拟Applied'),Line2D([],[],color=GOLD,ls=':',label='参考到达')])
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.53,.035),ncol=3,fontsize=MIN_PT,
               handlelength=1.5,columnspacing=1.2,labelspacing=.6)
    save(fig,'S3-A2_状态与控制_论文候选')

def render_s3_b():
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    summary=validate_summary(read(S3/'formal_summary.csv'));intervals=read(S3FINAL/'tables/time_and_action_intervals.csv')
    fig,axes=plt.subplots(2,2,figsize=(WIDTH_MM/25.4,175/25.4))
    fig.subplots_adjust(left=.13,right=.98,top=.90,bottom=.13,hspace=.55,wspace=.36)
    figure_header(fig,'路径完成、安全性与执行代价')
    names=('正常','延迟','停滞','抖动','丢帧','偏离','故障');x=np.arange(7)
    for i,m in enumerate(METHODS):
        rows=[next(r for r in summary if r['scenario']==s and r['method']==m) for s in SCENARIOS]
        xx=x+(i-1.5)*.15
        for ax,key,low,high in ((axes[0,0],'path_rate','path_ci_low','path_ci_high'),(axes[0,1],'unsafe_rate','unsafe_ci_low','unsafe_ci_high')):
            y=np.array([value(r,key) for r in rows])*100;lo=np.array([value(r,low) for r in rows])*100;hi=np.array([value(r,high) for r in rows])*100
            ax.errorbar(xx,y,yerr=np.maximum(0,np.array([y-lo,hi-y])),fmt=MARKERS[i],ms=3.8,color=COLORS[i],elinewidth=.8,capsize=1.5,lw=0)
            ax.set_ylim(-4,105)
        rs=[next(r for r in intervals if r['cohort']=='main' and r['scenario']==s and r['method']==m and r['metric']=='budgetized_completion_s') for s in SCENARIOS]
        ys=np.asarray([interval_values(r) for r in rs]);y,lo,hi=ys.T
        axes[1,0].errorbar(xx,y,yerr=np.maximum(0,np.array([y-lo,hi-y])),fmt=MARKERS[i],ms=3.8,color=COLORS[i],elinewidth=.8,capsize=1.5,lw=0)
    for ax in (axes[0,0],axes[0,1],axes[1,0]):ax.set_xticks(x,names);ax.set_xlim(-.6,6.6);ax.tick_params(axis='x',labelsize=MIN_PT)
    axes[0,0].set_ylabel('路径完成率 / %');axes[0,1].set_ylabel('无支持请求trial / %')
    axes[1,0].set(ylabel='全计划时间代价 / s',ylim=(0,25.5))
    cells=(('BTQ','P_B'),('BTQ','P_F'),('F_full','P_B'),('F_full','P_F'))
    actions=(('retries',BLUE,'o','重试'),('recoveries','#AE665F','s','恢复'),('recovery_resends',ORANGE,'^','返回重发'))
    for j,(field,color,marker,_) in enumerate(actions):
        rs=[next(r for r in intervals if r['scenario']=='deviation' and r['method']==m and r['protection']==p and r['metric']==field) for m,p in cells]
        ys=np.asarray([interval_values(r) for r in rs]);y,lo,hi=ys.T
        axes[1,1].errorbar(np.arange(4)+(j-1)*.16,y,yerr=np.maximum(0,np.array([y-lo,hi-y])),fmt=marker,ms=4,color=color,elinewidth=.8,capsize=1.5,lw=0)
    axes[1,1].set_xticks(range(4),['BTQ\nP_B','BTQ\nP_F','F\nP_B','F\nP_F'])
    axes[1,1].set(ylabel='每trial施加次数',ylim=(-.15,5.3),xlim=(-.5,3.5))
    axes[1,1].legend(handles=[Line2D([],[],color=c,marker=m,lw=0,label=t) for _,c,m,t in actions],loc='upper center',fontsize=MIN_PT,handlelength=1)
    for letter,ax,title in zip('abcd',axes.flat,('参考支持路径','无支持请求风险','失败计入的时间代价','偏离场景保护桥接')):
        label(ax,letter);ax.set_title(title,loc='left',pad=12,fontsize=9.5)
    fig.legend(handles=[Line2D([],[],color=COLORS[i],marker=MARKERS[i],lw=0,label=n) for i,n in enumerate(('A','B','BTQ','F'))],
               loc='lower center',bbox_to_anchor=(.54,.025),ncol=4,fontsize=9)
    save(fig,'S3-B_控制性能_论文候选')

def captions():
    return '''# 图注与数据边界（正文图内不重复堆放）

本目录为待审查候选图，160mm宽。S1原样参照未修改。全部新图为SIMULATION；二维点运动、简化合成Mask、pitch单位，不是CFD或真实U-Net/实物结果。

## S2-A 到达判定时序

同一冻结缓存A_normal_263000，固定190→191任务，模拟Applied 0.04s，n=1机制示例。四层依次为源/目标Mask面积比例、原始G/Q/S/K、连续证据时长和五方法首次确认。G阈值为0.85/0.08，W时长0.25s；方块通过、叉号拒绝，缺测不补值。金色带为独立参考[0.940,0.950]s，金色虚线为参考上界+H（H=1s）。BTQ、BTQ+S、BTQ+K和F_arrival在该缓存的窗口及确认时间重合，如实保留。单帧0.711s，四强方法均1.059s；并非普遍F优势。

## S2-B 到达判据对比与失效边界

六个预先选定的代表条件，五方法；全部13条件65行保留在tables。M为model-generated，X为synthetic stress，不称真实液滴形变。单帧=B_single_frame；+S=BTQ+S；+K=BTQ+K；F=F_arrival。(a)主窗口H内支持确认/独立参考到达；(b)提前/无支持确认的精确计数，每条件planned=20；(c)F−BTQ配对比例差及冻结的2000次配对seed bootstrap 95%逐点区间；(d)漏确认与晚支持计数/参考到达。晚支持是主窗口漏确认的子集，不能相加。NA是无独立参考到达，不是0。完整Wilson区间、延迟和所有失败在表中，不根据本次绘图重新统计。

## S3-A1 四策略运动与覆盖率

固定deviation、seed265000，每策略n=1，均为原正式试验。A/B/BTQ采用P_B，F为F_arrival+P_F（代码F_full）。上/下两组分别A/B、BTQ/F，每组位置与覆盖率相邻显示；内部x/y为World记录，观测x/y为实际已处理Mask质心，二者严格分开。源/目标eta分母均为液滴Mask面积。金色点线为原独立参考完成上界；缺帧/epoch切换断线，不插值。各策略运动随控制分叉，不拼接为同一轨迹。

## S3-A2 四策略状态与控制事件

与S3-A1完全相同四trial和时间轴。点为已记录预测状态，Unknown为观测可靠性标记，不是第六种物理状态。黑叉为原日志丢帧；请求行用颜色区分准备/启动/更新/重试/恢复/完成/停止，绿色竖线为模拟Applied。未标新请求时为Hold或pending，不能补画不存在的事件。独立参考只用于评分；模拟Applied不是实物ACK或实际高压。

## S3-B 路径完成、安全性与执行代价

七场景、四主策略，每条件20个配对seed，共560主trial；桥接单独展示不合池。(a)独立参考支持路径完成率；(b)至少一次无支持请求的trial比例（不是请求事件比例）；两者为冻结Wilson95%区间。(c)全计划预算化代价：严格成功用实际完成时间，否则24s；该工程惩罚不是RMST。(d)偏离场景固定到达门/保护桥接的实际Applied动作次数，重试、恢复及返回目标重发分开；(c,d)使用既有seed bootstrap 95%逐点区间。失败、源准备失败和未尝试保留在planned分母，零错误请求不等于成功。BTQ/F同保护事件一致，不能据保护策略差异宣称S/K独立闭环收益；jitter/dropout和恢复时间代价均保留。
'''

def main():
    args=argparse.ArgumentParser();args.add_argument('--revise',action='store_true');ns=args.parse_args()
    if OUT.exists() and not ns.revise:raise FileExistsError(OUT)
    for name in ('figures','previews','QA','tables','S1_原样参照'): (OUT/name).mkdir(parents=True,exist_ok=True)
    # Preserve every existing source before plotting; no scientific code is imported.
    protected={}
    for folder in (S1,BASE/'2026-10-26_S2收尾与S3方案_v1/figures',S3FINAL/'figures'):
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix in ('.svg','.pdf','.png','.json','.csv') and 'original_trial' not in str(p):protected[str(p)]=sha(p)
    for p in S1.glob('*'):
        if p.is_file() and p.suffix in ('.svg','.pdf','.png'):shutil.copy2(p,OUT/'S1_原样参照'/p.name)
    style();render_s2_a();render_s2_b();data=trial_data();render_s3_motion(data);render_s3_control(data);render_s3_b()
    for p in (S2/'statistics').iterdir():
        if p.is_file():remember(p);shutil.copy2(p,OUT/'tables'/('S2_'+p.name))
    for p in (S3/'formal_summary.csv',S3/'paired_contrasts.csv',S3FINAL/'tables/time_and_action_intervals.csv',S3FINAL/'tables/bridge_control_identity.csv'):
        remember(p);shutil.copy2(p,OUT/'tables'/('S3_'+p.name))
    (OUT/'论文图注与说明.md').write_text(captions(),encoding='utf-8')
    import pymupdf as fitz
    combined=fitz.open()
    for p in sorted((OUT/'S1_原样参照').glob('*.pdf'))+sorted((OUT/'figures').glob('*.pdf')):
        with fitz.open(p) as document:combined.insert_pdf(document)
    combined.save(OUT/'第二章仿真论文图_候选预览.pdf');combined.close()
    changes=[name for name,h in {**protected,**_USED}.items() if sha(name)!=h]
    result=dict(simulation=True,status='candidate_not_user_final',width_mm=WIDTH_MM,min_source_font_pt=MIN_PT,
        source_files=_USED,protected_original_files=len(protected),protected_original_sha256=protected,
        changes=changes,new_trials=0,new_predictions=0,new_score_count=0,
        trial_ids=[d['metric']['trial_id'] for d in data],full_S2_conditions=13,full_S3_scenarios=7,
        script_sha256=sha(__file__))
    write_json(OUT/'source_manifest.json',result);assert not changes
    print(json.dumps(dict(figure_count=5,original_protected=len(protected),source_files=len(_USED),changes=changes,new_trials=0),ensure_ascii=False))

if __name__=='__main__':main()
