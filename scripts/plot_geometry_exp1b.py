"""Mechanism figures from saved data, not random-performance statistics."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b.audit import read,load,sha
from dmf.chapter2_geometry_sim.render import _style
from dmf.chapter2_geometry_sim.sdf_trial import js
sys.path.insert(0,"C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
from audit_panel_alignment import require_matplotlib_panel_alignment


def _save(fig,path):
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(path)+'.alignment.json',tolerance_pt=1.5,
        gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(str(path)+'.svg')
    fig.savefig(str(path)+'.pdf')
    fig.savefig(str(path)+'.png',dpi=600)


def plot(root,output):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    audit=load(root/'independent_audit.json')
    if not audit['passed']:raise ValueError('source audit failed')
    config=load(root/'config.json');results=read(root/'planned_method_results.csv');counts=read(root/'gate_trigger_counts.csv')
    cases=[r['name'] for r in config['cases']];methods=[r['name'] for r in config['methods']]
    labels={'M1':'M1','GQ':'GQ','M2':'M2','M2_S':'M2+S','M2_K':'M2+K','M3':'M3'}
    index={(r['case_id'],r['method']):r for r in results}
    _style();plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':10,'pdf.fonttype':42,'svg.fonttype':'none'})
    categories=['supported','premature','unsupported','unconfirmed','unattempted']
    colors=['#4b979d','#c88b47','#a45b61','#b3bdc6','#eeeeee']
    display=['Supported','Premature','Unsupported','No event','Not run']
    matrix=[]
    for method in methods:
        matrix.append([categories.index(index[c,method]['category'] if index[c,method]['status']=='executed' else 'unattempted') for c in cases])
    fig,ax=plt.subplots(figsize=(8.6,4.4));fig.subplots_adjust(left=.13,right=.98,bottom=.16,top=.72)
    ax.imshow(matrix,cmap=ListedColormap(colors),vmin=-.5,vmax=4.5,aspect='auto',interpolation='nearest')
    ax.set(xticks=range(16),xticklabels=cases,yticks=range(6),yticklabels=[labels[m] for m in methods],xlabel='Case')
    ax.set_xticks(np.arange(-.5,16,1),minor=True);ax.set_yticks(np.arange(-.5,6,1),minor=True)
    ax.grid(which='minor',color='white',lw=1.3);ax.tick_params(which='minor',bottom=False,left=False)
    for j in range(6):ax.plot(1,j,marker='x',color='#54616b',ms=5,mew=1)
    fig.suptitle('SIMULATION',fontsize=11,y=.99)
    fig.legend(handles=[Patch(color=c,label=t) for c,t in zip(colors,display)],loc='upper center',
        bbox_to_anchor=(.5,.91),ncol=3,fontsize=9,frameon=False)
    _save(fig,output/'Exp1B_1_event_outcomes');plt.close(fig)
    # Only main methods; all exclusions (no reference/no execution) remain visible in Figure1 and CSV.
    method_colors={'M1':'#9b8e7d','M2':'#4b979d','M3':'#193d58'}
    markers={'M1':'o','M2':'s','M3':'^'}
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(8.6,6.4));fig.subplots_adjust(left=.13,right=.98,bottom=.12,top=.86,hspace=.42)
    for j,method in enumerate(('M1','M2','M3')):
        valid=[(i,index[c,method]) for i,c in enumerate(cases) if index[c,method].get('signed_deviation_s','')!='']
        axes[0].scatter([i+(j-1)*.19 for i,r in valid],[float(r['signed_deviation_s']) for i,r in valid],
            marker=markers[method],color=method_colors[method],s=30,label=method)
        supported=[(i,index[c,method]) for i,c in enumerate(cases) if index[c,method].get('latency_s','')!='']
        axes[1].scatter([i+(j-1)*.19 for i,r in supported],[float(r['latency_s']) for i,r in supported],
            marker=markers[method],color=method_colors[method],s=30)
    axes[0].axhline(0,color='#a4acb3',ls='--',lw=.8);axes[1].axhline(0,color='#a4acb3',ls='--',lw=.8)
    axes[0].set_ylabel('Decision − reference / s');axes[1].set_ylabel('Supported latency / s')
    axes[1].set(xticks=range(16),xticklabels=cases,xlabel='Case',xlim=(-.6,15.6),ylim=(-.02,.35))
    for ax,label in zip(axes,('a','b')):ax.annotate(label,xy=(0,1),xycoords='axes fraction',xytext=(-24,8),textcoords='offset points',fontweight='bold',fontsize=11)
    for ax in axes:
        ax.axvspan(.55,1.45,facecolor='#eeeeee',edgecolor='#c1c8ce',hatch='///',lw=0,zorder=-2)
        ax.axvspan(2.55,3.45,facecolor='#f4f6f8',lw=0,zorder=-2)
    fig.suptitle('SIMULATION',fontsize=11,y=.99)
    fig.legend(handles=[Line2D([],[],ls='none',marker=markers[m],color=method_colors[m],label=m) for m in method_colors],
        loc='upper center',bbox_to_anchor=(.5,.945),ncol=3,fontsize=10,frameon=False)
    _save(fig,output/'Exp1B_2_timing_tradeoff');plt.close(fig)
    # Raw failures versus conditional added rejection: mechanism counts, not independent samples.
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(8.6,6.5));fig.subplots_adjust(left=.13,right=.98,bottom=.12,top=.84,hspace=.42)
    for j,(key,color) in enumerate([('Q','#999f80'),('S','#7d96b2'),('K','#193d58')]):
        valid=[(i,r) for i,r in enumerate(counts) if r.get(key+'_failed','')!='']
        axes[0].bar([i+(j-1)*.24 for i,r in valid],[float(r[key+'_failed']) for i,r in valid],
            width=.22,color=color,label=key)
    for j,(key,color) in enumerate([('S','#7d96b2'),('K','#193d58')]):
        valid=[(i,r) for i,r in enumerate(counts) if r.get(key+'_extra_on_GQ','')!='']
        axes[1].bar([i+(j-.5)*.26 for i,r in valid],[float(r[key+'_extra_on_GQ']) for i,r in valid],width=.24,color=color)
    axes[0].set_ylabel('Raw rejection count');axes[1].set_ylabel('Added rejections on GQ')
    axes[1].set(xticks=range(16),xticklabels=cases,xlabel='Case',xlim=(-.6,15.6),yticks=[0,1,2],ylim=(0,2.2))
    for ax,label in zip(axes,('a','b')):ax.annotate(label,xy=(0,1),xycoords='axes fraction',xytext=(-24,8),textcoords='offset points',fontweight='bold',fontsize=11)
    for ax in axes:ax.axvspan(.55,1.45,facecolor='#eeeeee',edgecolor='#c1c8ce',hatch='///',lw=0,zorder=-2)
    fig.suptitle('SIMULATION',fontsize=11,y=.99)
    fig.legend(handles=[Patch(color=c,label=k) for k,c in [('Q','#999f80'),('S','#7d96b2'),('K','#193d58')]],
        loc='upper center',bbox_to_anchor=(.5,.945),ncol=3,fontsize=10,frameon=False)
    _save(fig,output/'Exp1B_3_gate_overlap');plt.close(fig)
    js(output/'figure_manifest.json',dict(source_results_sha256=sha(root/'planned_method_results.csv'),
        source_gate_counts_sha256=sha(root/'gate_trigger_counts.csv'),source_audit_sha256=sha(root/'independent_audit.json'),
        plot_script_sha256=sha(__file__),new_simulation_runs=0,
        figure1='All96 planned cells; B1 unattempted; event categories not probabilities',
        figure2=dict(main_methods=['M1','M2','M3'],signed_points=sum(bool(r.get('signed_deviation_s')) for r in results if r['method'] in ('M1','M2','M3')),
            missing_rule='No reference/no decision/not run omitted only from numeric y; retained in Fig1 and source CSV',
            supported_latency_only=True,CI='not applicable: deterministic mechanism fixtures'),
        files={p.name:sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root');parser.add_argument('output')
    args=parser.parse_args();plot(args.root,args.output)
