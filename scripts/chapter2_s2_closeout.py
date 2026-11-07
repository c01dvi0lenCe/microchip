"""Read-only S2 closeout figures; never generates motion, predictions or scores."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_sim.s2.spec import CONDITIONS,METHODS,MODEL_GENERATED
from dmf.chapter2_sim.s2.plotting import load_figure_data

OLD=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-25_S2正式仿真_v1')
MAIN=('A_normal','C_jump_short','D_tail_false','C_jump_persistent','F_jitter','F_dropout')
LABELS=('Normal','Short jump','Remote fragments','Persistent false mask','Jitter','Dropout')


def read_csv(path):
    with Path(path).open(encoding='utf-8',newline='') as handle:return list(csv.DictReader(handle))


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def write_csv(path,rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=keys);writer.writeheader();writer.writerows(rows)


def inventory():
    result={}
    for p in OLD.rglob('*'):
        if p.is_file():result['S2/'+p.relative_to(OLD).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for folder in ('dmf','controllers','configs','simulation','validation'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.yaml','.json'):
                result['code/'+p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for p in list(ROOT.glob('run*.py'))+[ROOT/'main.py',ROOT/'app_controller.py']:
        result['code/'+p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def initialize(output):
    out=Path(output)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True);(out/'QA').mkdir();(out/'source_data').mkdir()
    items=inventory();write_json(out/'source_data/frozen_inventory_before.json',items)
    write_json(out/'S2_freeze_index.json',dict(version='chapter2_s2_single_task_confirmatory_v1',
        source_root=str(OLD),file_count=sum(k.startswith('S2/') for k in items),
        inventory_sha256=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest(),
        policy='full content hash, original files and attributes not changed',simulation=True))


def verify(output):
    out=Path(output);before=json.loads((out/'source_data/frozen_inventory_before.json').read_text(encoding='utf-8'))
    after=inventory();changed=[k for k in set(before)|set(after) if before.get(k)!=after.get(k)]
    result=dict(unchanged=not changed,checked_files=len(before),changed=changed,new_simulation_trials=0,
                new_predictions=0,new_scoring_runs=0)
    write_json(out/'QA/frozen_integrity_after.json',result)
    if changed:raise ValueError('frozen inputs changed: '+str(changed[:5]))
    return result


def failure_counts(row):
    return tuple(int(row[k]) for k in ('missed_supported_confirmation','late_supported_confirmations','reference_arrivals'))


def matrices(rows):
    if Counter((r['condition'],r['method']) for r in rows)!=Counter((c,m) for c in CONDITIONS for m in METHODS):
        raise ValueError('all 13 conditions and five methods required')
    lookup={(r['condition'],r['method']):r for r in rows}
    support=np.full((6,5),np.nan);errors=np.zeros((6,5));fail=np.full((6,4),np.nan)
    la=[];lb=[];ld=[]
    for i,c in enumerate(MAIN):
        a=[];b=[];d=[]
        for j,m in enumerate(METHODS):
            row=lookup[c,m];r=int(row['reference_arrivals']);s=int(row['supported_confirmations'])
            p=int(row['premature_confirmations']);u=int(row['unsupported_confirmations']);n=int(row['planned_steps'])
            if r:support[i,j]=s/r
            errors[i,j]=(p+u)/n;a.append(f'{s}/{r}' if r else 'NA');b.append(f'{p}/{u}')
        for j,(method,field) in enumerate((('BTQ','missed_supported_confirmation'),('F_arrival','missed_supported_confirmation'),
                ('BTQ','late_supported_confirmations'),('F_arrival','late_supported_confirmations'))):
            row=lookup[c,method];r=int(row['reference_arrivals']);value=int(row[field])
            if r:fail[i,j]=value/r
            d.append(f'{value}/{r}' if r else 'NA')
        la.append(a);lb.append(b);ld.append(d)
    return dict(support=support,errors=errors,failure=fail,labels_a=la,labels_b=lb,labels_d=ld,all_rows=rows)


def style():
    import matplotlib as mpl
    mpl.use('Agg')
    mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.titlesize':8,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':7,
        'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none','pdf.fonttype':42,
        'legend.fontsize':7,'legend.frameon':False})


def save(fig,folder,name):
    folder=Path(folder);folder.mkdir(parents=True)
    sys.path.insert(0,str(Path.home()/'.agents/skills/nature-figure/scripts'))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=folder/(name+'.alignment.json'),
        overlay_svg=folder/(name+'.alignment.svg'),tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(folder/(name+'.svg'))
    fig.savefig(folder/(name+'.pdf'))
    fig.savefig(folder/(name+'.png'),dpi=600)


def render_a(output):
    style();import matplotlib.pyplot as plt
    out=Path(output)/'figures/S2-A';data=load_figure_data(OLD/'formal','A_normal_263000')
    rows=data['traces']['BTQ'];times=np.array([float(r['processing_s']) for r in rows])
    raw=[json.loads(r['raw']) if r.get('raw') else None for r in rows]
    ref=data['reference'];l,u=ref['lower_s'],ref['upper_s'];task=data['task']
    fig,axes=plt.subplots(4,1,figsize=(7.2047244094,6.6929133858),sharex=True,gridspec_kw={'height_ratios':[1,1,1,1.3]})
    fig.subplots_adjust(left=.22,right=.97,top=.86,bottom=.17,hspace=.42)
    fig.suptitle('S2-A | Same-input arrival decisions — SIMULATION',y=.98,fontsize=10)
    fig.text(.5,.94,f"A_normal_263000 | fixed task 190 → 191 | Applied {task['applied_s']:.2f} s",ha='center',fontsize=7)
    fig.text(.5,.905,f'Independent dwell-completion reference [{l:.3f}, {u:.3f}] s (true-scale interval)',ha='center',fontsize=7,color='#805a18')
    axes[0].plot(times,[q['eta_target'] if q else np.nan for q in raw],'-o',ms=2.3,lw=1.2,color='#286696',label='Target eta (Mask fraction)')
    axes[0].plot(times,[q['eta_source'] if q else np.nan for q in raw],'--s',ms=2,lw=1,color='#a06d3d',label='Source eta (Mask fraction)')
    axes[0].axhline(.85,color='#286696',ls=':',lw=.75);axes[0].axhline(.08,color='#a06d3d',ls=':',lw=.75)
    axes[0].set(ylabel='Mask-area fraction',ylim=(-.05,1.08));axes[0].legend(loc='center right',ncol=1)
    for j,gate in enumerate(('G','Q','S','K')):
        values=[None if q is None else q['eta_target']>=.85 and q['eta_source']<=.08 if gate=='G' else bool(q[gate]) if q is not None else None for q in raw]
        passed=np.array([v is True for v in values]);failed=np.array([v is False for v in values])
        axes[1].scatter(times[passed],np.full(sum(passed),j),s=9,color='#286696',marker='s')
        axes[1].scatter(times[failed],np.full(sum(failed),j),s=10,color='#aa7046',marker='x')
    missing=np.array([q is None for q in raw]);axes[1].scatter(times[missing],np.full(sum(missing),-.6),s=12,color='#777777',marker='x')
    axes[1].set(yticks=[-.6,0,1,2,3],yticklabels=['C0 unavailable','G','Q','S','K'],ylim=(-1,3.6),ylabel='Raw gates')
    for method,color,ls in zip(METHODS[1:],['#929aa0','#657e91','#447b9e','#16496c'],['-','--',':','-.']):
        trace=data['traces'][method];events=data['events'][method];stop=events[0]['timestamp_s'] if events else float('inf')
        x=[float(r['processing_s']) for r in trace];y=[float(r['window_duration_s']) if r.get('window_duration_s') and float(r['processing_s'])<=stop else np.nan for r in trace]
        axes[2].plot(x,y,color=color,ls=ls,lw=1.5,label=method)
    axes[2].axhline(.25,ls=':',color='#777777',lw=.75);axes[2].set(ylabel='Evidence span (s)',ylim=(-.025,.34))
    axes[2].legend(loc='center right',ncol=2)
    events=[]
    for j,method in enumerate(METHODS):
        ee=data['events'][method];y=4-j
        for e in ee:axes[3].scatter(e['timestamp_s'],y,marker='D',s=28,color='#16496c');events.append(dict(method=method,**e))
        axes[3].text(2.55,y,f"{ee[0]['timestamp_s']:.3f} s" if ee else 'No event',va='center',fontsize=7)
    axes[3].set(yticks=range(5),yticklabels=list(reversed(METHODS)),ylim=(-.6,4.6),ylabel='First confirmation',xlabel='Simulation availability / decision time (s)')
    for label,ax in zip('abcd',axes):
        ax.annotate(label,(0,1),xycoords='axes fraction',xytext=(-12,5),textcoords='offset points',fontweight='bold',fontsize=9)
        ax.set_xlim(0,task['end_s']+.08);ax.axvline(task['applied_s'],ls=':',color='#aeb7bd',lw=.7,zorder=0)
        ax.axvspan(l,u,color='#dca847',alpha=.5,zorder=0);ax.axvline(l,color='#b17a20',lw=.7,zorder=0)
        ax.axvline(u,color='#b17a20',lw=1.1,zorder=0);ax.axvline(u+1,ls='--',color='#b17a20',lw=.8,zorder=0)
        ax.grid(False);ax.tick_params(direction='out',length=2.5)
    fig.text(.22,.072,'Squares = gate pass; crosses = reject / unavailable. Missing Mask is not imputed.',fontsize=7)
    fig.text(.22,.046,'Gold band = [l,u]; gold dashed = u+H, H=1 s. Four strong-method traces overlap.',fontsize=7)
    fig.text(.22,.020,'SIMULATION | n=1 | pitch | synthetic observations, NOT real U-Net. Source: frozen S2 v1.',fontsize=7)
    save(fig,out,'S2-A_同输入到达时序_收尾候选');plt.close(fig)
    write_json(out/'source_manifest.json',data)
    write_csv(out/'event_source.csv',events);write_csv(out/'frame_source.csv',rows)


def render_b(output):
    style();import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D
    out=Path(output)/'figures/S2-B_main'
    all_rows=read_csv(OLD/'formal/statistics/condition_statistics.csv');data=matrices(all_rows)
    paired=read_csv(OLD/'formal/statistics/paired_contrasts.csv')
    contrasts={r['condition']:r for r in paired if r['baseline']=='BTQ' and r['comparison']=='F_arrival'}
    fig,axes=plt.subplots(2,2,figsize=(7.2047244094,7.35))
    fig.subplots_adjust(left=.235,right=.975,top=.84,bottom=.20,wspace=.23,hspace=.47)
    fig.suptitle('S2-B | Conditional benefits and failure boundaries — SIMULATION',y=.98,fontsize=10)
    fig.text(.5,.944,'Six representative conditions; full 13-condition / five-method results in supplementary tables.',ha='center',fontsize=7)
    fig.text(.5,.918,'20 paired seeds per condition | H=1 s | no pooled accuracy or real-droplet claim',ha='center',fontsize=7)
    labels=[('[M] ' if c in MODEL_GENERATED else '[X] ')+name for c,name in zip(MAIN,LABELS)]
    cmap=LinearSegmentedColormap.from_list('fractions',['#ffffff','#a9c4d3']);cmap.set_bad('#eeeeee')
    for ax,values,text,title,ticks in [(axes[0,0],data['support'],data['labels_a'],'H-supported / reference',['B','BTQ','+S','+K','F']),
        (axes[0,1],data['errors'],data['labels_b'],'Premature / unsupported counts',['B','BTQ','+S','+K','F']),
        (axes[1,1],data['failure'],data['labels_d'],'Main misses and late support / R',['BTQ\nMiss','F\nMiss','BTQ\nLate','F\nLate'])]:
        ax.imshow(values,aspect='auto',cmap=cmap,vmin=0,vmax=1,interpolation='none')
        for i in range(6):
            for j in range(len(ticks)):ax.text(j,i,text[i][j],ha='center',va='center',fontsize=6.8,color='#15344b')
        ax.set(yticks=np.arange(6),yticklabels=labels if ax is axes[0,0] else [],xticks=np.arange(len(ticks)),xticklabels=ticks,ylim=(5.5,-.5))
        ax.xaxis.tick_top();ax.tick_params(length=0,pad=4);ax.set_title(title,pad=31)
        for spine in ax.spines.values():spine.set_visible(False)
    ax=axes[1,0];ax.axvline(0,color='#aab3b9',lw=.7,zorder=0)
    styles=[('support','#286696','o',-.17,'Supported / R'),('premature','#b77c4a','s',0,'Premature / planned'),('unsupported','#666666','D',.17,'Unsupported / planned')]
    for field,color,marker,offset,label in styles:
        for i,c in enumerate(MAIN):
            row=contrasts[c]
            if row[field+'_difference']=='':continue
            value,lo,hi=[float(row[field+'_difference'+suffix]) for suffix in ('','_lo','_hi')]
            ax.errorbar(value,i+offset,xerr=[[max(0,value-lo)],[max(0,hi-value)]],fmt=marker,ms=3.2,lw=.9,color=color,capsize=1.5)
    ax.legend(handles=[Line2D([],[],color=color,marker=marker,lw=.8,ms=3,label=label) for field,color,marker,offset,label in styles],loc='upper left',bbox_to_anchor=(-.05,1.27),handlelength=1.3,labelspacing=.25,fontsize=6.5)
    ax.set(yticks=np.arange(6),yticklabels=labels,ylim=(5.5,-.5),xlim=(-1.1,1.1),xticks=[-1,-.5,0,.5,1],xlabel='F − BTQ paired rate difference')
    for label,ax in zip('abcd',axes.flat):
        ax.annotate(label,(0,1),xycoords='axes fraction',xytext=(-12,5),textcoords='offset points',fontweight='bold',fontsize=9);ax.grid(False)
    notes=['SIMULATION | pitch / simulation seconds | synthetic camera, NOT real U-Net or CFD.',
        '[M] model-generated; [X] synthetic stress. NA: no independent reference arrival (R=0).',
        '(a,b,d) exact counts; all planned n=20. Wilson 95% CI and full delay data in tables.',
        '(c) paired-seed bootstrap 95% CI, 2000 resamples; no significance claims.',
        '(d) Late support is retained within main misses; these columns must not be added.',
        'B=B_single_frame; +S=BTQ+S; +K=BTQ+K; F=F_arrival. All 13 conditions preserved.']
    for j,note in enumerate(notes):fig.text(.235,.13-j*.019,note,fontsize=6.3)
    save(fig,out,'S2-B_代表条件与失效边界_正文候选');plt.close(fig)
    write_csv(out/'main_condition_source.csv',[r for r in all_rows if r['condition'] in MAIN])
    write_csv(out/'main_paired_source.csv',[r for r in paired if r['condition'] in MAIN])
    write_json(out/'display_contract.json',dict(representative_conditions=MAIN,all_conditions=CONDITIONS,
        exclusion_from_supplement=False,count_panels='exact counts, marginal Wilson intervals in supplement',
        interval_panel='frozen 2000-resample paired bootstrap',no_new_statistics=True))


def figures(output):
    out=Path(output)
    if (out/'figures').exists():raise FileExistsError(out/'figures')
    verify(out);render_a(out);render_b(out)
    tables=out/'tables';tables.mkdir()
    for name in ('condition_statistics.csv','paired_contrasts.csv','diagnostic_contrasts.csv','statistics_manifest.json'):
        shutil.copyfile(OLD/'formal/statistics'/name,tables/name)
    for name in ('step_scores.csv','diagnostic_scores.csv','plan.csv','run_report.json'):
        shutil.copyfile(OLD/'formal'/name,tables/name)
    mapping={str(p.relative_to(OLD)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (OLD/'formal/statistics').iterdir() if p.is_file()}
    write_json(tables/'source_hashes.json',mapping);verify(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('init','figures','verify'));parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result={'init':initialize,'figures':figures,'verify':verify}[args.action](args.output)
    print(json.dumps(result,ensure_ascii=False))
