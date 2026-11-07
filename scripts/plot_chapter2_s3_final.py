"""Read-only S3-A/S3-B formal SIMULATION figures from saved evidence."""
from pathlib import Path
import csv
import hashlib
import json
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
DATA=BASE/'2026-10-26_S3正式仿真_v1';OUT=BASE/'2026-10-26_S3正式验收与论文图_v1'
FIG=OUT/'figures';SKILL=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
sys.path.insert(0,str(SKILL));from audit_panel_alignment import require_matplotlib_panel_alignment
METHODS=('A_fixed','B_single','BTQ','F_full');LABELS=('A fixed','B single','BTQ','F full')
SCENARIOS=('normal','delayed','partial_stall','jitter','dropout','deviation','failure')
NAMES=('Normal','Delayed','Stall','Jitter','Dropout','Deviation','Failure')
COLORS=('#8E979F','#BD916E','#6C9DB5','#255C7A');MARKERS=('s','v','o','D')
BLUE='#437C9A';ORANGE='#D18D43';GREEN='#398B75';GOLD='#B58B30'
STATES=('Unknown','Stationary','Moving','Partial','Arrived','Deviation')
STATE_COLORS=('#A9ADB1','#788F9B',BLUE,'#D69A4D',GREEN,'#B16A61')

def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def val(r,k):return float(r[k]) if r.get(k) not in ('',None) else np.nan
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def decode(v):return json.loads(v) if isinstance(v,str) else v
def save(fig,name):
    fig.canvas.draw();require_matplotlib_panel_alignment(fig,json_out=FIG/(name+'.alignment.json'),overlay_svg=FIG/(name+'.alignment.svg'),
        tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(FIG/(name+'.svg'));fig.savefig(FIG/(name+'.pdf'));fig.savefig(FIG/(name+'.png'),dpi=600)
    fig.savefig(FIG/(name+'.preview.png'),dpi=300);plt.close(fig)

def observed(ax,frames,field,**kwargs):
    ts=[];ys=[];prev=None
    for f in frames:
        valid=f.get('processing_s') and f.get(field);context=f['step'],f['epoch']
        if not valid or prev is not None and (int(f['frame_id'])!=prev[0]+1 or context!=prev[1]):ts.append(np.nan);ys.append(np.nan)
        if valid:ts.append(val(f,'processing_s'));ys.append(val(f,field))
        prev=(int(f['frame_id']),context) if valid else None
    ax.plot(ts,ys,**kwargs)

def timeline(scenario,name):
    ms=read(DATA/'formal_trials.csv');trials=[next(r for r in ms if r['cohort']=='main' and r['scenario']==scenario and r['seed']=='265000' and r['method']==m) for m in METHODS]
    ds=[]
    for r in trials:
        p=DATA/r['relative_trial_path'];ds.append(dict(metric=r,path=p,truth=read(p/'evaluation/truth_ticks.csv'),frames=read(p/'observations/frames.csv'),
            refs=read(p/'evaluation/reference_intervals.csv'),events=read(p/'observations/events.csv')))
    fig,axes=plt.subplots(3,4,figsize=(9.6,6.4),sharex=True)
    fig.subplots_adjust(left=.075,right=.985,top=.84,bottom=.20,wspace=.29,hspace=.30)
    fig.text(.075,.974,'Closed-loop trajectories, independent reference and control',fontsize=11,weight='bold',va='top')
    fig.text(.075,.93,f'SIMULATION | {scenario} | paired seed 265000 | n=1 per strategy | chapter2_s3_confirmatory_v1',fontsize=7,color='#66717B',va='top')
    end=max(val(r,'execution_time_s') for r in trials)
    positions=[val(t,k) for d in ds for t in d['truth'] for k in ('x','y')]
    action_colors={'Prepare':'#88929A','Start':'#648C9F','Update':'#255C7A','Retry':'#9D704D','Recovery':'#AE665F','Complete':'#398B75','Stop':'#212B33'}
    for col,d in enumerate(ds):
        a,b,c=axes[:,col];ts=[val(t,'time_s') for t in d['truth']]
        a.plot(ts,[val(t,'x') for t in d['truth']],color=BLUE,lw=.85)
        a.plot(ts,[val(t,'y') for t in d['truth']],color='#7B6D9E',lw=.85,ls='--')
        observed(a,d['frames'],'x',color=BLUE,lw=0,marker='x',ms=1.8)
        observed(a,d['frames'],'y',color='#7B6D9E',lw=0,marker='+',ms=1.8)
        a.set_ylim(min(positions)-.15,max(positions)+.15)
        observed(b,d['frames'],'eta_target',color=BLUE,lw=.85)
        observed(b,d['frames'],'eta_source',color=ORANGE,lw=.85,ls='--');b.set_ylim(-.04,1.07)
        for f in d['frames']:
            if f.get('processing_s'):c.scatter(val(f,'processing_s'),STATES.index(f['state']),s=5,color=STATE_COLORS[STATES.index(f['state'])],lw=0)
            elif f.get('reason')=='CAMERA_DROPPED':c.plot(val(f,'available_s'),0,'x',color='black',ms=2,mew=.5)
        for r in d['refs']:
            if r['activation_target']!=r['target'] or r['target'] not in ('191','192','172'):continue
            for ax in (a,b):ax.axvline(val(r,'upper_s'),color=GOLD,ls=':',lw=.65)
            c.vlines(val(r,'upper_s'),-.35,5.4,color=GOLD,ls=':',lw=.65)
        for e in d['events']:
            if e['event']=='Applied':c.plot(val(e,'time_s'),7,'|',color=GREEN,ms=5,mew=.8)
            elif e['event'] in action_colors:c.plot(val(e,'time_s'),6,'v',color=action_colors[e['event']],ms=3.4,mew=0)
        a.set_title(LABELS[col]+' / '+d['metric']['protection'],fontsize=8,weight='bold')
        for row,ax in enumerate((a,b,c)):
            ax.set_xlim(-.20,end+.20);ax.text(-.075,1.04,chr(97+row*4+col),transform=ax.transAxes,fontsize=8,weight='bold',va='bottom')
            ax.tick_params(labelsize=7)
        a.set_ylabel('Position / pitch' if col==0 else '',fontsize=7)
        b.set_ylabel('Mask fraction' if col==0 else '',fontsize=7)
        c.set_yticks(range(8),['Unk','Sta','Mov','Par','Arr','Dev','Req','App'] if col==0 else ['']*8)
        c.set_ylim(-.35,7.5);c.set_xlabel('Simulation time / s',fontsize=7)
    handles=[Line2D([],[],color=BLUE,label='Internal x / target eta'),Line2D([],[],color='#7B6D9E',ls='--',label='Internal y'),
             Line2D([],[],color=ORANGE,ls='--',label='Source eta'),Line2D([],[],color=GOLD,ls=':',label='Independent reference'),
             Line2D([],[],color=GREEN,marker='|',lw=0,label='Simulated Applied')]
    handles += [Line2D([],[],color=v,marker='v',lw=0,label=k) for k,v in action_colors.items()]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.52,.075),ncol=4,fontsize=6.5,frameon=False)
    fig.text(.075,.025,'Observed x/y: cross markers; states are discrete logged predictions. Unknown and missing observations are retained.\nUnmarked intervals are Hold or pending; no invented events. Independent truth is scoring-only. Simplified 2D, synthetic Mask; not CFD or real U-Net.',fontsize=6.5,color='#66717B')
    save(fig,name)
    return [dict(trial_id=r['trial_id'],path=r['relative_trial_path']) for r in trials]

def comparison():
    summary=read(DATA/'formal_summary.csv');intervals=read(OUT/'tables/time_and_action_intervals.csv')
    fig,axes=plt.subplots(2,2,figsize=(7.2,6.8));fig.subplots_adjust(left=.11,right=.98,top=.82,bottom=.17,hspace=.47,wspace=.32)
    fig.text(.08,.974,'Path support, safety and execution cost',fontsize=12,weight='bold',va='top')
    fig.text(.08,.93,'SIMULATION | 7 scenarios | 20 paired seeds per condition and method | 560 main trials',fontsize=7,color='#66717B')
    fig.text(.08,.89,'No pooled overall accuracy; all planned failures and unattempted steps remain in denominators.',fontsize=6.5,color='#66717B')
    x=np.arange(7)
    for mi,m in enumerate(METHODS):
        rs=[next(r for r in summary if r['cohort']=='main' and r['scenario']==s and r['method']==m) for s in SCENARIOS]
        xx=x+(mi-1.5)*.15
        for ax,field,lo,hi in ((axes[0,0],'path_rate','path_ci_low','path_ci_high'),(axes[0,1],'unsafe_rate','unsafe_ci_low','unsafe_ci_high')):
            y=np.array([val(r,field) for r in rs])*100;low=np.array([val(r,lo) for r in rs])*100;high=np.array([val(r,hi) for r in rs])*100
            ax.errorbar(xx,y,yerr=np.maximum(0,np.array([y-low,high-y])),fmt=MARKERS[mi],ms=3.5,color=COLORS[mi],elinewidth=.7,capsize=1.5,lw=0)
            ax.set_ylim(-4,105)
        ts=[next(r for r in intervals if r['cohort']=='main' and r['scenario']==s and r['method']==m and r['metric']=='budgetized_completion_s') for s in SCENARIOS]
        y=np.array([val(r,'mean') for r in ts]);lo=np.array([val(r,'ci_low') for r in ts]);hi=np.array([val(r,'ci_high') for r in ts])
        axes[1,0].errorbar(xx,y,yerr=np.maximum(0,np.array([y-lo,hi-y])),fmt=MARKERS[mi],ms=3.5,color=COLORS[mi],elinewidth=.7,capsize=1.5,lw=0)
    for ax in (axes[0,0],axes[0,1],axes[1,0]):
        ax.set_xticks(x,NAMES,rotation=35,ha='right',rotation_mode='anchor',fontsize=6.5);ax.set_xlim(-.6,6.6)
    axes[0,0].set_ylabel('Reference-supported paths / %',fontsize=7)
    axes[0,1].set_ylabel('Trials with unsupported requests / %',fontsize=7)
    axes[1,0].set_ylabel('All-planned budgetized time / s',fontsize=7);axes[1,0].set_ylim(0,25.5)
    cells=[('BTQ','P_B'),('BTQ','P_F'),('F_full','P_B'),('F_full','P_F')]
    action_upper=0.
    for j,(field,color,marker) in enumerate((('retries',BLUE,'o'),('recoveries','#AE665F','s'),('recovery_resends',ORANGE,'^'))):
        rs=[next(r for r in intervals if r['scenario']=='deviation' and r['method']==m and r['protection']==p and r['metric']==field) for m,p in cells]
        y=np.array([val(r,'mean') for r in rs]);lo=np.array([val(r,'ci_low') for r in rs]);hi=np.array([val(r,'ci_high') for r in rs])
        action_upper=max(action_upper,float(np.max(hi)))
        axes[1,1].errorbar(np.arange(4)+(j-1)*.16,y,yerr=np.maximum(0,np.array([y-lo,hi-y])),fmt=marker,ms=3.7,color=color,elinewidth=.8,capsize=2,lw=0)
    axes[1,1].set_xticks(range(4),['BTQ/P_B','BTQ/P_F','F/P_B','F/P_F'],rotation=25,ha='right',rotation_mode='anchor',fontsize=6.5)
    axes[1,1].set_ylabel('Applied actions per planned trial',fontsize=7);axes[1,1].set_xlim(-.5,3.5)
    axes[1,1].set_ylim(-.15,action_upper*1.5+.5)
    axes[1,1].legend(handles=[Line2D([],[],color=c,marker=mk,lw=0,label=l) for c,mk,l in ((BLUE,'o','Retry'),('#AE665F','s','Recovery'),(ORANGE,'^','Return resend'))],loc='upper center',bbox_to_anchor=(.5,1.02),ncol=1,fontsize=6,frameon=False)
    for i,(ax,title) in enumerate(zip(axes.flat,('Supported completion','Unsafe request risk','Failure-aware execution cost','Deviation: protection bridge'))):
        ax.set_title(chr(97+i)+'  '+title,loc='left',fontsize=8,weight='bold',pad=10);ax.tick_params(labelsize=7)
    fig.legend(handles=[Line2D([],[],color=COLORS[i],marker=MARKERS[i],lw=0,label=LABELS[i]) for i in range(4)],
               loc='lower center',bbox_to_anchor=(.53,.065),ncol=4,fontsize=7,frameon=False)
    fig.text(.08,.012,'a,b: Wilson 95% intervals, N=20 planned trials. c,d: seed-bootstrap 95% pointwise intervals (2,000 draws).\nc: supported success uses execution time; otherwise 24 s. d: fixed arrival gate × protection; no independent S/K gain implied.\nb includes source failures: zero unsafe requests does not imply successful transport. Simplified 2D, pitch units; not physical EWOD.',fontsize=6,color='#66717B')
    save(fig,'S3-B_formal_performance')

def main():
    FIG.mkdir(parents=True,exist_ok=True)
    audit=json.loads((OUT/'QA/independent_final_audit.json').read_text(encoding='utf-8'))
    if not audit['passed']:raise ValueError('independent G5 audit not passed')
    plt.rcParams.update({'font.family':'Arial','font.size':7,'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.6,'svg.fonttype':'none','pdf.fonttype':42})
    examples={s:timeline(s,'S3-A_formal_process' if s=='deviation' else 'S3-A_supplement_normal') for s in ('deviation','normal')}
    comparison()
    (FIG/'figure_sources.json').write_text(json.dumps(dict(simulation=True,method_version='chapter2_s3_confirmatory_v1',examples=examples,
        source_files={p.relative_to(DATA).as_posix():sha(p) for p in DATA.glob('*.csv')},no_simulation_execution=True,
        tables={p.name:sha(p) for p in (OUT/'tables').glob('*.csv')},plot_script_sha256=sha(Path(__file__)),
        trial_files={str((Path(e['path'])/name).as_posix()):sha(DATA/e['path']/name) for es in examples.values() for e in es
                     for name in ('observations/frames.csv','observations/events.csv','evaluation/truth_ticks.csv','evaluation/reference_intervals.csv','trial_manifest.json')},
        main_A='prespecified deviation seed265000, n=1 per strategy',main_B='all seven main scenarios and prespecified deviation bridge; N=20 paired seeds'),ensure_ascii=False,indent=2),encoding='utf-8')
    print('S3-A, S3-B and normal supplement exported')

if __name__=='__main__':main()
