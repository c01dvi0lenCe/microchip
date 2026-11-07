"""S2-A: read persisted inputs, gates, events and references; never run a model."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from dmf.experiment.mask_cache import load_cache
from .spec import METHODS


def figure_phase(study_root):
    path=Path(study_root)/'run_report.json'
    phase=json.loads(path.read_text(encoding='utf-8')).get('study_phase','development') if path.exists() else 'development'
    if phase not in ('development','confirmatory'):raise ValueError('unknown figure study phase')
    return phase


def load_figure_data(study_root,cache_id):
    root=Path(study_root)
    if Path(cache_id).name!=cache_id:raise ValueError('cache ID must be a directory name')
    cache=load_cache(root/'inputs'/cache_id)
    events={};traces={};sources={}
    for method in METHODS:
        folder=root/'predictions'/cache_id/method
        p=folder/'prediction_manifest.json';payload=p.read_bytes()
        report=json.loads(payload)
        if report['input_sha256']!=cache['input_sha256']:raise ValueError('figure methods do not share input')
        events[method]=report['events'];sources[str(p)]=hashlib.sha256(payload).hexdigest()
        p=folder/'gate_trace.csv'
        with p.open(encoding='utf-8',newline='') as handle:traces[method]=list(csv.DictReader(handle))
        sources[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    p=root/'scoring_side'/cache_id/'references.json'
    refs=json.loads(p.read_text(encoding='utf-8'));sources[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(cache_id=cache_id,input_sha256=cache['input_sha256'],task=cache['tasks'][0],
                events=events,traces=traces,reference=refs[0],source_sha256=sources)


def render_s2a(study_root,output,*,cache_id='A_normal_262000',qa_tools=None):
    import matplotlib as mpl
    mpl.use('Agg')
    import matplotlib.pyplot as plt
    data=load_figure_data(study_root,cache_id);output=Path(output)
    phase=figure_phase(study_root)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    tools=Path(qa_tools) if qa_tools else Path.home()/'.agents/skills/nature-figure/scripts'
    sys.path.insert(0,str(tools))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.titlesize':8,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':7,
        'axes.spines.right':False,'axes.spines.top':False,'svg.fonttype':'none','pdf.fonttype':42,
        'legend.fontsize':7,'legend.frameon':False})
    # Final physical size: 183 x 170 mm.
    fig,axes=plt.subplots(4,1,figsize=(7.2047244094,6.6929133858),sharex=True,
        gridspec_kw={'height_ratios':[1,1,1,1.3]})
    fig.subplots_adjust(left=.22,right=.97,top=.88,bottom=.17,hspace=.42)
    fig.suptitle('S2-A | Same-input arrival decisions — '+('DEVELOPMENT SIMULATION' if phase=='development' else 'SIMULATION'),y=.97,fontsize=10)
    ref=data['reference'];lower=ref.get('lower_s');upper=ref.get('upper_s')
    task=data['task'];applied=task['applied_s']
    subtitle=f"{cache_id} | fixed task {task['source']} → {task['target']} | Applied {applied:.2f} s"
    if upper is not None:subtitle+=f" | reference [{lower:.2f}, {upper:.2f}] s"
    fig.text(.5,.925,subtitle,ha='center',fontsize=7)
    rows=data['traces']['BTQ'];times=np.array([float(r['processing_s']) for r in rows])
    raw=[json.loads(r['raw']) if r.get('raw') else None for r in rows]
    eta_t=np.array([r['eta_target'] if r else np.nan for r in raw]);eta_s=np.array([r['eta_source'] if r else np.nan for r in raw])
    axes[0].plot(times,eta_t,'o-',ms=2,lw=1,color='#286696',label='Target eta')
    axes[0].plot(times,eta_s,'s-',ms=1.8,lw=.8,color='#b77c4a',label='Source eta')
    axes[0].axhline(.85,color='#286696',ls=':',lw=.8);axes[0].axhline(.08,color='#b77c4a',ls=':',lw=.8)
    axes[0].set(ylabel='Mask-area fraction',ylim=(-.05,1.08))
    axes[0].legend(loc='center right',bbox_to_anchor=(1,.55),ncol=2)
    source_rows=[]
    for j,gate in enumerate(('G','Q','S','K')):
        values=[]
        for r,q in zip(rows,raw):
            passed=None if q is None else ((q['eta_target']>=.85 and q['eta_source']<=.08) if gate=='G' else bool(q[gate]))
            values.append(passed)
        passed=np.array([v is True for v in values]);failed=np.array([v is False for v in values])
        axes[1].scatter(times[passed],np.full(passed.sum(),j),s=9,color='#286696',marker='s')
        axes[1].scatter(times[failed],np.full(failed.sum(),j),s=9,color='#c9875d',marker='x')
    missing=np.array([r is None for r in raw])
    axes[1].scatter(times[missing],np.full(missing.sum(),-.6),s=12,color='#777777',marker='x')
    axes[1].set(yticks=[-.6,0,1,2,3],yticklabels=['C0 unavailable','G','Q','S','K'],ylim=(-1,3.6),ylabel='Raw gates')
    colors=['#929aa0','#788e9f','#507a96','#16496c'];styles=['-','--',':','-.']
    for i,method in enumerate(METHODS[1:]):
        trace=data['traces'][method];event=data['events'][method]
        stop=event[0]['timestamp_s'] if event else float('inf')
        x=[float(r['processing_s']) for r in trace]
        y=[float(r['window_duration_s']) if r.get('window_duration_s') and float(r['processing_s'])<=stop else np.nan for r in trace]
        axes[2].plot(x,y,lw=1.3,color=colors[i],ls=styles[i],label=method)
    axes[2].axhline(.25,color='#777777',ls=':',lw=.7)
    axes[2].set(ylabel='Evidence span (s)',ylim=(-.025,.34))
    axes[2].legend(loc='center right',bbox_to_anchor=(1,.48),ncol=2)
    event_source=[]
    for j,method in enumerate(METHODS):
        y=4-j;events=data['events'][method]
        if events:
            for event in events:
                c=event['timestamp_s']
                axes[3].scatter([c],[y],s=28,marker='D',color='#16496c')
                event_source.append(dict(method=method,**event))
            axes[3].text(2.55,y,f"{events[0]['timestamp_s']:.3f} s",va='center',fontsize=7)
        else:axes[3].text(2.55,y,'No event',va='center',fontsize=7)
    axes[3].set(yticks=range(5),yticklabels=list(reversed(METHODS)),ylim=(-.6,4.6),
                ylabel='First confirmation',xlabel='Simulation availability / decision time (s)')
    for label,ax in zip('abcd',axes):
        ax.annotate(label,xy=(0,1),xycoords='axes fraction',xytext=(-12,5),textcoords='offset points',fontweight='bold',fontsize=9)
        ax.set_xlim(0,task['end_s']+.08);ax.axvline(applied,color='#aeb7bd',ls=':',lw=.8,zorder=0)
        if upper is not None:
            ax.axvspan(lower,upper,color='#dfaf62',alpha=.3,zorder=0)
            ax.axvline(upper,color='#c18a34',lw=.7,zorder=0)
            ax.axvline(upper+1.,color='#c18a34',ls='--',lw=.65,zorder=0)
        ax.tick_params(direction='out',length=2.5);ax.grid(False)
    fig.text(.22,.072,'Raw gates: squares = pass; crosses = reject / unavailable. No missing-mask imputation.',fontsize=7)
    fig.text(.22,.046,f'SIMULATION | n=1 {phase} cache | pitch | synthetic camera, NOT real U-Net.',fontsize=7)
    fig.text(.22,.020,'Gold: reference; dashed gold: H=1 s deadline. Evidence displayed until first event.',fontsize=7)
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=output/'S2-A.alignment.json',
        overlay_svg=output/'S2-A.alignment.svg',tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    stem=output/('S2-A_同输入到达时序_开发候选' if phase=='development' else 'S2-A_同输入到达时序_正式候选')
    for ext in ('svg','pdf'):fig.savefig(str(stem)+'.'+ext)
    fig.savefig(str(stem)+'.png',dpi=600)
    plt.close(fig)
    for r,q in zip(rows,raw):
        source_rows.append(dict(frame_id=r['frame_id'],available_s=r['processing_s'],
            C0_passed=r['C0_passed'],eta_source=q['eta_source'] if q else None,
            eta_target=q['eta_target'] if q else None,Q=q['Q'] if q else None,
            S=q['S'] if q else None,K=q['K'] if q else None))
    from ..batch import _write_csv,_write_json
    _write_csv(output/'S2-A_frame_source.csv',source_rows);_write_csv(output/'S2-A_event_source.csv',event_source)
    _write_json(output/'S2-A_sources.json',dict(cache_id=cache_id,input_sha256=data['input_sha256'],
        source_sha256=data['source_sha256'],reference=ref,events=data['events'],
        simulation=True,example_n=1,study_phase=phase,performance_conclusion=False))
    return dict(svg=str(stem)+'.svg',pdf=str(stem)+'.pdf',png=str(stem)+'.png')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--cache',default='A_normal_262000')
    parser.add_argument('--qa-tools');args=parser.parse_args()
    print(json.dumps(render_s2a(args.study,args.output,cache_id=args.cache,qa_tools=args.qa_tools),ensure_ascii=False))
