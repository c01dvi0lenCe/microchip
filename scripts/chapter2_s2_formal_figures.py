"""Read-only formal S2 figure assembly from persisted tables and traces."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_sim.s2.spec import CONDITIONS,METHODS,MODEL_GENERATED
from dmf.chapter2_sim.s2.study import _rows
from dmf.chapter2_sim.batch import _write_csv,_write_json

DISPLAY=['Normal','Flash short','Flash window','Jump short','Jump persistent',
         'Tail false','Tail true boundary','Low-conf false','Low-conf true','High-conf false',
         'Jitter','Dropout','Gap']


def figure_matrices(rows):
    expected=Counter((c,m) for c in CONDITIONS for m in METHODS)
    if Counter((r['condition'],r['method']) for r in rows)!=expected:
        raise ValueError('figure requires all 65 unique condition/method summaries')
    lookup={(r['condition'],r['method']):r for r in rows}
    support=np.full((13,5),np.nan);errors=np.zeros((13,5))
    labels_a=[];labels_b=[]
    for i,c in enumerate(CONDITIONS):
        la=[];lb=[]
        for j,m in enumerate(METHODS):
            r=lookup[c,m];n=int(r['planned_steps']);ref=int(r['reference_arrivals'])
            s=int(r['supported_confirmations']);miss=int(r['missed_supported_confirmation'])
            p=int(r['premature_confirmations']);u=int(r['unsupported_confirmations'])
            if ref:support[i,j]=s/ref
            errors[i,j]=(p+u)/n
            la.append(f'{s}/{ref}; m{miss}' if ref else 'NA (R=0)')
            lb.append(f'P{p} / U{u}')
        labels_a.append(la);labels_b.append(lb)
    return dict(support=support,errors=errors,labels_a=labels_a,labels_b=labels_b)


def render(study,output):
    import matplotlib as mpl
    mpl.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from dmf.chapter2_sim.s2.confirmatory import audit_confirmatory
    audit_confirmatory(study)
    root=Path(study);out=Path(output)
    if out.exists():raise FileExistsError(out)
    rows=_rows(root/'statistics/condition_statistics.csv');data=figure_matrices(rows)
    contrasts=_rows(root/'statistics/paired_contrasts.csv')
    contrast={r['condition']:r for r in contrasts if r['baseline']=='BTQ' and r['comparison']=='F_arrival'}
    if set(contrast)!=set(CONDITIONS):raise ValueError('incomplete paired contrasts')
    out.mkdir(parents=True)
    mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':7,'axes.titlesize':8,'axes.labelsize':7,'xtick.labelsize':6,'ytick.labelsize':6,
        'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'svg.fonttype':'none',
        'legend.fontsize':6,'legend.frameon':False})
    fig,axes=plt.subplots(2,2,figsize=(7.2047244094,8.66))
    fig.subplots_adjust(left=.19,right=.965,top=.86,bottom=.19,wspace=.24,hspace=.42)
    fig.suptitle('S2-B | Arrival decisions under matched inputs — SIMULATION',y=.98,fontsize=10)
    fig.text(.5,.952,'Five primary methods | 13 fixed conditions | 20 paired seeds per condition',ha='center',fontsize=7)
    fig.text(.5,.932,'Counts include all planned steps; H = 1 s. No pooled overall accuracy.',ha='center',fontsize=7)
    ylabels=[('[M] ' if c in MODEL_GENERATED else '[X] ')+d for c,d in zip(CONDITIONS,DISPLAY)]
    for ax,matrix,labels,title in [(axes[0,0],data['support'],data['labels_a'],'H-supported / reference; m = missed'),
            (axes[0,1],data['errors'],data['labels_b'],'Premature (P) / unsupported (U) counts')]:
        cmap=LinearSegmentedColormap.from_list('fraction',['#ffffff','#a9c4d3']);cmap.set_bad('#eeeeee')
        ax.imshow(matrix,aspect='auto',vmin=0,vmax=1,cmap=cmap,interpolation='none')
        for i in range(13):
            for j in range(5):ax.text(j,i,labels[i][j],ha='center',va='center',fontsize=5.2,color='#15344b')
        ax.set(yticks=np.arange(13),yticklabels=ylabels if ax is axes[0,0] else [],
            xticks=np.arange(5),xticklabels=['B','BTQ','+S','+K','F'],ylim=(12.5,-.5))
        ax.xaxis.tick_top();ax.tick_params(length=0,pad=4)
        ax.set_title(title,pad=24)
        for spine in ax.spines.values():spine.set_visible(False)
    ax=axes[1,0];ax.axvline(0,color='#aab3b9',lw=.7,zorder=0)
    styles=[('support','#286696','o',-.20,'Supported / R'),
            ('premature','#b77c4a','s',0,'Premature / planned'),
            ('unsupported','#666666','D',.20,'Unsupported / planned')]
    for field,color,marker,offset,label in styles:
        for i,c in enumerate(CONDITIONS):
            row=contrast[c];value=row[field+'_difference']
            if value=='':continue
            value=float(value);lo=float(row[field+'_difference_lo']);hi=float(row[field+'_difference_hi'])
            ax.errorbar(value,i+offset,xerr=[[max(0.,value-lo)],[max(0.,hi-value)]],
                fmt=marker,ms=3,lw=.8,color=color,capsize=1.5,label=label if i==0 else None)
    # Explicit handles include metrics undefined in the first condition.
    from matplotlib.lines import Line2D
    handles=[Line2D([],[],color=color,marker=marker,lw=.8,ms=3,label=label)
             for field,color,marker,offset,label in styles]
    ax.legend(handles=handles,loc='upper left',bbox_to_anchor=(-.05,1.20),ncol=1,handlelength=1.3,labelspacing=.25)
    ax.set(yticks=np.arange(13),yticklabels=ylabels,ylim=(12.6,-.6),xlim=(-1.1,1.1),
        xticks=[-1,-.5,0,.5,1],xlabel='F − BTQ paired rate difference')
    ax=axes[1,1];ax.axvline(0,color='#aab3b9',lw=.7,zorder=0)
    allbounds=[]
    for i,c in enumerate(CONDITIONS):
        row=contrast[c];n=int(row['dual_supported_n'])
        if n:
            value=float(row['latency_difference_s']);lo=float(row['latency_difference_s_lo']);hi=float(row['latency_difference_s_hi'])
            ax.errorbar(value,i,xerr=[[max(0.,value-lo)],[max(0.,hi-value)]],fmt='o',ms=3,lw=.8,color='#286696',capsize=1.5)
            allbounds.extend([lo,hi])
        ax.text(.98,i,f'n={n}/20',transform=ax.get_yaxis_transform(),ha='right',va='center',fontsize=5.5)
    bound=max([abs(v) for v in allbounds]+[.05])*1.2
    ax.set(yticks=np.arange(13),yticklabels=[],ylim=(12.6,-.6),xlim=(-bound,bound),
           xlabel='F − BTQ conditional latency (s)')
    ax.set_title('Dual H-supported pairs only',pad=24)
    for label,ax in zip('abcd',axes.flat):
        ax.annotate(label,(0,1),xycoords='axes fraction',xytext=(-12,5),textcoords='offset points',fontweight='bold',fontsize=9)
        ax.grid(False);ax.tick_params(direction='out')
    lines=['SIMULATION | units pitch and simulation seconds | synthetic masks, NOT U-Net or CFD.',
           '[M] model-generated; [X] synthetic stress. R=0: support is NA, not zero accuracy.',
           '(a,b) descriptive counts (each planned n=20); Wilson 95% intervals in source table.',
           '(c,d) paired-seed percentile bootstrap 95% CI, 2000 resamples; no significance stars.',
           '(d) excludes pairs lacking two H-supported events; failures remain in (a-c) denominators.',
           'B = B_single_frame; +S = BTQ+S; +K = BTQ+K; F = F_arrival.']
    for j,line in enumerate(lines):fig.text(.19,.115-j*.017,line,fontsize=6)
    sys.path.insert(0,str(Path.home()/'.agents/skills/nature-figure/scripts'))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=out/'S2-B.alignment.json',
        overlay_svg=out/'S2-B.alignment.svg',tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    stem=out/'S2-B_到达事件配对比较_正式候选'
    for ext in ('svg','pdf'):fig.savefig(str(stem)+'.'+ext)
    fig.savefig(str(stem)+'.png',dpi=600);plt.close(fig)
    _write_csv(out/'S2-B_condition_source.csv',rows);_write_csv(out/'S2-B_paired_source.csv',contrasts)
    paths=[root/'step_scores.csv',root/'diagnostic_scores.csv',root/'statistics/condition_statistics.csv',
        root/'statistics/paired_contrasts.csv',root/'configuration_manifest.json',Path(__file__)]
    _write_json(out/'S2-B_sources.json',dict(simulation=True,planned_primary=1300,conditions=13,
        seeds_per_condition=20,figure_question='Conditional incremental information and failure boundaries, not universal superiority',
        source_sha256={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        count_panel_interval_exemption='Exact counts; marginal Wilson intervals supplied in source CSV; paired uncertainty shown in c,d'))
    return dict(svg=str(stem)+'.svg',pdf=str(stem)+'.pdf',png=str(stem)+'.png')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(render(args.study,args.output),ensure_ascii=False))
