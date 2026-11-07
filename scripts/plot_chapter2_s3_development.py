"""Read-only development plates from persisted S3 CSV and actual Mask PNGs.

SIMULATION. No model, camera, predictor or scorer is imported or executed.
"""
from pathlib import Path
import csv
import hashlib
import json
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon,Patch
from matplotlib.lines import Line2D

BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1')
DATA=BASE/'development_smoke';OUT=BASE/'figures'
QA=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
sys.path.insert(0,str(QA))
from audit_panel_alignment import require_matplotlib_panel_alignment

METHODS=('A_fixed','B_single','BTQ','F_full')
SCENARIOS=('normal','delayed','partial_stall','jitter','dropout','deviation','failure')
STATE_ORDER=('Unknown','Stationary','Moving','Partial','Arrived','Deviation')
STATE_COLORS=('#A9ADB1','#788F9B','#437C9A','#D69A4D','#398B75','#B16A61')
BLUE='#437C9A';ORANGE='#D18D43';GREEN='#398B75';GRAY='#787F86';GOLD='#B58B30'

def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def js(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def num(row,key):return float(row[key]) if row.get(key) not in (None,'') else np.nan
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(metric):
    p=DATA/metric['relative_trial_path']
    return dict(path=p,metric=metric,frames=rows(p/'observations/frames.csv'),captures=rows(p/'observations/captures.csv'),
                truth=rows(p/'evaluation/truth_ticks.csv'),events=rows(p/'observations/events.csv'),
                refs=rows(p/'evaluation/reference_intervals.csv'),geometry=js(p/'electrode_map_snapshot.json'))
def chosen(scenario):
    values=[m for m in rows(DATA/'development_trials.csv') if m['cohort']=='main' and m['scenario']==scenario and m['seed']=='264000']
    return [load(next(m for m in values if m['method']==method)) for method in METHODS]

def header(fig,title,subtitle):
    fig.text(.07,.97,title,weight='bold',fontsize=11,va='top')
    fig.text(.07,.93,subtitle,fontsize=7.5,va='top',color=GRAY)
def footer(fig,text):
    fig.text(.07,.035,text,fontsize=7,va='bottom',color=GRAY)
def export(fig,name,*,excluded=()):
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=OUT/(name+'.alignment.json'),overlay_svg=OUT/(name+'.alignment.svg'),
        exclude_axes=excluded,tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(OUT/(name+'.svg'));fig.savefig(OUT/(name+'.pdf'));fig.savefig(OUT/(name+'.png'),dpi=600)
    fig.savefig(OUT/(name+'.preview.png'),dpi=300)
    plt.close(fig)

def trajectory(scenario):
    trials=chosen(scenario);fig,axes=plt.subplots(2,2,figsize=(7.2,6.6))
    fig.subplots_adjust(left=.09,right=.98,bottom=.19,top=.85,wspace=.26,hspace=.32)
    header(fig,'S3 development | Droplet motion and processed Masks',f'SIMULATION | {scenario} | seed 264000 | chapter2_s3_g0_g2_dev1 | n=1 per strategy')
    panels=[]
    for k,(ax,r) in enumerate(zip(axes.flat,trials)):
        g=r['geometry'];polygons=g['polygons'];route=[190,191,192,172]
        ax.set_xlim(8.55,12.5);ax.set_ylim(11.0,8.0);ax.set_aspect('equal',adjustable='box')
        for identity in route:
            poly=np.array(polygons[str(identity)]);center=poly.mean(axis=0)
            ax.add_patch(Polygon(poly,facecolor='#DDE7EE' if identity==190 else '#F4E5D3',edgecolor='#A2ACB5',linewidth=.6))
            ax.text(poly[:,0].min()+.08,poly[:,1].min()+.20,str(identity),ha='left',fontsize=7,color=GRAY)
        tx=[num(t,'x') for t in r['truth']];ty=[num(t,'y') for t in r['truth']]
        ax.plot(tx,ty,color=BLUE,lw=1.15,zorder=3)
        fs=[f for f in r['frames'] if f.get('processing_s') and f.get('x') and f.get('y')]
        ax.scatter([num(f,'x') for f in fs],[num(f,'y') for f in fs],color=ORANGE,marker='x',s=7,lw=.45,zorder=4)
        start=next((f for f in fs if f['action']=='Start'),None)
        intervention=next((f for f in fs if f['action'] in ('Retry','Recovery')),None)
        first_update=next((f for f in fs if f['action']=='Update'),None)
        picks=[]
        for f in (start,intervention or first_update,fs[-1] if fs else None):
            if f is not None and f['frame_id'] not in [x['frame_id'] for x in picks]:picks.append(f)
        captures={c['frame_id']:c for c in r['captures']};lower=np.array(g['lower']);scale=g['scale']
        for f in picks:
            c=captures[f['frame_id']];mask=np.array(Image.open(r['path']/c['mask_path']))
            xp=np.arange(mask.shape[1])/scale+lower[0];yp=np.arange(mask.shape[0])/scale+lower[1]
            ax.contour(xp,yp,mask,levels=[127.5],colors=[ORANGE],linewidths=.8,zorder=5)
        ax.text(.03,.04,'Mask times: '+', '.join(f"{num(f,'processing_s'):.2f}" for f in picks)+' s',
                transform=ax.transAxes,fontsize=6.5,color=ORANGE)
        active=int(r['truth'][-1]['world_active'])
        if str(active) in polygons:ax.add_patch(Polygon(polygons[str(active)],fill=False,edgecolor=GREEN,linewidth=1.4))
        ax.set_xlabel('x / pitch',fontsize=8);ax.set_ylabel('y / pitch',fontsize=8)
        ax.set_title(f"{chr(97+k)}  {r['metric']['method']} / {r['metric']['protection']}",loc='left',weight='bold',fontsize=8.5)
        panels.append(dict(trial_id=r['metric']['trial_id'],mask_frame_ids=[int(f['frame_id']) for f in picks],
                           mask_processing_s=[num(f,'processing_s') for f in picks],world_active_final=active))
    handles=[Line2D([],[],color=BLUE,lw=1.2,label='Internal position trajectory'),Line2D([],[],color=ORANGE,marker='x',lw=0,label='Processed Mask centroid'),
        Line2D([],[],color=ORANGE,lw=.8,label='Actual processed Mask snapshots'),Patch(facecolor='#DDE7EE',label='Initial source 190'),
        Patch(facecolor='#F4E5D3',label='Route targets'),Patch(facecolor='none',edgecolor=GREEN,label='Final world.active')]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.52,.075),ncol=3,fontsize=7,frameon=False)
    footer(fig,'Route ROI of the 420-electrode example template. 2D point motion + synthetic circular Masks; pitch units.\nNot CFD, physical EWOD, or real U-Net. All curves/snapshots are logged samples; no invented state/event.')
    export(fig,f'S3-dev-motion_{scenario}_264000');return panels

def observed(ax,frames,field,**kwargs):
    xx=[];yy=[];previous=None
    for f in sorted(frames,key=lambda x:int(x['frame_id'])):
        valid=f.get('processing_s') and f.get(field)
        context=(f.get('step'),f.get('epoch'))
        if not valid or previous is not None and (int(f['frame_id'])!=previous[0]+1 or context!=previous[1]):
            xx.append(np.nan);yy.append(np.nan)
        if valid:xx.append(num(f,'processing_s'));yy.append(num(f,field))
        previous=(int(f['frame_id']),context) if valid else None
    ax.plot(xx,yy,**kwargs)

def timeline(scenario):
    trials=chosen(scenario);fig,axes=plt.subplots(3,4,figsize=(10.8,7.3),sharex=True)
    fig.subplots_adjust(left=.07,right=.985,bottom=.19,top=.84,wspace=.28,hspace=.30)
    header(fig,'S3 development | State, reference and control timing',f'SIMULATION | {scenario} | paired seed 264000 | chapter2_s3_g0_g2_dev1 | n=1 per strategy')
    end=max(float(r['metric']['execution_time_s']) for r in trials)
    position_values=[num(t,k) for r in trials for t in r['truth'] for k in ('x','y')]
    position_limits=(min(position_values)-.15,max(position_values)+.15)
    for col,r in enumerate(trials):
        ts=np.array([num(t,'time_s') for t in r['truth']]);xs=[num(t,'x') for t in r['truth']];ys=[num(t,'y') for t in r['truth']]
        a,b,c=axes[:,col]
        a.plot(ts,xs,color=BLUE,lw=.9);a.plot(ts,ys,color='#7B6D9E',lw=.9,ls='--')
        observed(a,r['frames'],'x',color=BLUE,lw=0,marker='x',ms=2);observed(a,r['frames'],'y',color='#7B6D9E',lw=0,marker='+',ms=2)
        observed(b,r['frames'],'eta_target',color=BLUE,lw=.9);observed(b,r['frames'],'eta_source',color=ORANGE,lw=.9,ls='--')
        b.set_ylim(-.05,1.08);a.set_ylim(*position_limits)
        for f in r['frames']:
            if f.get('processing_s'):
                state=STATE_ORDER.index(f['state']);c.scatter(num(f,'processing_s'),state,s=6,color=STATE_COLORS[state],linewidths=0)
            elif f.get('reason')=='CAMERA_DROPPED':c.scatter(num(f,'available_s'),0,s=9,color='black',marker='x',lw=.6)
        for ref in r['refs']:
            target=int(ref['target'])
            if target not in (191,192,172) or ref['activation_target']!=ref['target']:continue
            for ax in (a,b):ax.axvline(num(ref,'upper_s'),color=GOLD,lw=.7,ls=':')
            c.vlines(num(ref,'upper_s'),-.4,5.5,color=GOLD,lw=.7,ls=':')
        for e in r['events']:
            t=num(e,'time_s');name=e['event']
            if name=='Applied':c.plot(t,7.1,'|',color=GREEN,ms=6,mew=1)
            elif name in ('Prepare','Start','Update','Retry','Recovery','Complete','Stop'):
                char={'Prepare':'P','Start':'S','Update':'U','Retry':'T','Recovery':'R','Complete':'C','Stop':'X'}[name]
                c.plot(t,6.05,'v',color='#334A5E',ms=3);c.text(t,6.4,char,fontsize=6,ha='center')
        a.set_title(r['metric']['method']+' / '+r['metric']['protection'],fontsize=8.5,weight='bold')
        for row,ax in enumerate((a,b,c)):
            ax.set_xlim(-.2,end+.2);ax.text(-.07,1.04,chr(97+row*4+col),transform=ax.transAxes,fontsize=8,weight='bold',va='bottom')
        a.set_ylabel('Position / pitch' if col==0 else '',fontsize=8)
        b.set_ylabel('Mask fraction' if col==0 else '',fontsize=8)
        c.set_yticks(range(8),['Unk','Sta','Mov','Par','Arr','Dev','Req','App'] if col==0 else ['']*8)
        c.set_ylim(-.4,7.6);c.set_xlabel('Simulation time / s',fontsize=8)
    handles=[Line2D([],[],color=BLUE,label='Internal x / target eta'),Line2D([],[],color='#7B6D9E',ls='--',label='Internal y'),
             Line2D([],[],color=ORANGE,ls='--',label='Source eta'),Line2D([],[],color=GOLD,ls=':',label='Independent reference completion'),
             Line2D([],[],marker='x',color='black',lw=0,label='Missing Mask'),Line2D([],[],marker='|',color=GREEN,lw=0,label='Simulated Applied')]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.52,.075),ncol=3,fontsize=7,frameon=False)
    footer(fig,'Discrete processed states; gaps and Unknown retained. No event marker = Hold. P Prepare, S Start, U Update, T Retry, R Recovery, C Complete, X Stop.\nObserved x/y: cross markers; internal x/y: lines. Gold lines use independent internal reference, not algorithm input. Simplified 2D simulation, not CFD or real U-Net.')
    export(fig,f'S3-dev-timeline_{scenario}_264000')

def stages():
    summary=[r for r in rows(DATA/'development_summary.csv') if r['cohort']=='main']
    ordered=[next(r for r in summary if r['scenario']==s and r['method']==m) for s in SCENARIOS for m in METHODS]
    fig,axes=plt.subplots(1,2,figsize=(10.2,8.8),sharey=True)
    fig.subplots_adjust(left=.18,right=.98,bottom=.12,top=.79,wspace=.30)
    header(fig,'S3 development | Termination and control budgets','SIMULATION | 7 scenarios × 4 methods × 3 development seeds | raw counts only; not formal performance evidence')
    y=np.arange(len(ordered));left=np.zeros(len(ordered))
    categories=('source_preparation_failed','transport_aborted','workflow_complete_without_supported_path','reference_supported_path_complete','infrastructure_invalid')
    colors=('#BCC2C7','#C89585','#E2BC7F','#648C9F','#4E5961')
    labels=('Source preparation failed','Transport aborted','Workflow only / unsupported path','Reference-supported path','Infrastructure invalid')
    for field,color,label in zip(categories,colors,labels):
        values=np.array([int(r[field]) for r in ordered]);axes[0].barh(y,values,left=left,color=color,height=.70,label=label)
        for yy,v,start in zip(y,values,left):
            if v:axes[0].text(start+v/2,yy,str(v),ha='center',va='center',fontsize=7)
        left+=values
    axes[0].set_xlim(0,3);axes[0].set_xticks([0,1,2,3]);axes[0].set_xlabel('Trials / 3 planned per condition and method')
    axes[0].set_yticks(y,[r['scenario']+' / '+r['method'] for r in ordered],fontsize=7.5)
    left=np.zeros(len(ordered))
    for field,color,label in (('retries',BLUE,'Regular target Retry'),('recoveries','#C89585','Recovery command'),('recovery_resends',ORANGE,'Post-Recovery resend')):
        values=np.array([int(r[field]) for r in ordered]);axes[1].barh(y,values,left=left,color=color,height=.7,label=label);left+=values
    axes[1].set_xlabel('Applied actions / 3 planned trials');axes[1].set_xlim(0,max(left)+1)
    for ax in axes:
        ax.invert_yaxis();ax.set_ylim(len(ordered)-.3,-.7)
        for boundary in (3.5,7.5,11.5,15.5,19.5,23.5):ax.axhline(boundary,color='#E7EAEC',lw=.6)
    axes[0].set_title('a  Mutually exclusive trial terminals',loc='left',fontsize=9,weight='bold')
    axes[1].set_title('b  Retry / Recovery accounting',loc='left',fontsize=9,weight='bold')
    handles0,labels0=axes[0].get_legend_handles_labels();handles1,labels1=axes[1].get_legend_handles_labels()
    fig.legend(handles0+handles1,labels0+labels1,loc='upper center',bbox_to_anchor=(.54,.91),ncol=3,fontsize=7,frameon=False)
    footer(fig,'Each bar retains all 3 planned development seeds. Workflow completion is not path success. Retry and Recovery do not create extra planned steps.\nMain end-to-end cohort only; 12 bridge and 24 controlled transport records remain in separate CSV tables. No pooled accuracy, confidence interval, or superiority claim.')
    export(fig,'S3-dev-stage_and_budget_counts')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'Arial','font.size':8,'axes.spines.top':False,'axes.spines.right':False,
        'axes.linewidth':.6,'svg.fonttype':'none','pdf.fonttype':42,'legend.frameon':False})
    panels={}
    for scenario in ('normal','deviation'):
        panels[scenario]=trajectory(scenario);timeline(scenario)
    stages()
    manifest=dict(simulation=True,purpose='G2 development visualization, not formal performance',seed=264000,
        method_version='chapter2_s3_g0_g2_dev1',panels=panels,source_files={str(p.relative_to(DATA)):digest(p) for p in
          DATA.rglob('*.csv') if p.name in ('development_trials.csv','development_summary.csv','frames.csv','events.csv','captures.csv','truth_ticks.csv','reference_intervals.csv')},
        no_research_execution=True,mask_origin='persisted actual SyntheticCamera PNG output; contour only, no reconstruction or interpolation')
    (OUT/'figure_sources.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('exported 5 development figures from persisted logs')
if __name__=='__main__':main()
