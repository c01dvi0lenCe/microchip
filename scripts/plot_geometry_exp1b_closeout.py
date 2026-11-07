"""Reference-relative mechanism figures, not physical safety or performance rates."""
import argparse
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
sys.path.insert(0,"C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
from audit_panel_alignment import require_matplotlib_panel_alignment
from dmf.chapter2_geometry_sim.exp1b.audit import read,load,sha
from dmf.chapter2_geometry_sim.sdf_trial import js


def save(fig,path):
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(path)+'.alignment.json',strict=True,tolerance_pt=1.5,gutter_tolerance_pt=1.5)
    fig.savefig(str(path)+'.pdf');fig.savefig(str(path)+'.svg');fig.savefig(str(path)+'.png',dpi=600)


def plot(root,output):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    if not load(root/'closeout_audit.json')['passed']:raise ValueError('source audit failed')
    results=read(root/'planned_method_results.csv');outcomes=read(root/'exclusive_step_outcomes.csv')
    config=load(root/'config.json');counts=read(root/'gate_trigger_counts.csv')
    cases=[c['name'] for c in config['cases']];methods=[m['name'] for m in config['methods']]
    index={(r['case_id'],r['method']):r for r in results};primary={(r['case_id'],r['method']):r for r in outcomes}
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],'font.size':10,
        'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,
        'axes.linewidth':.8,'legend.frameon':False,'figure.facecolor':'white','axes.facecolor':'white'})
    labels={'M2_S':'M2+S','M2_K':'M2+K'}
    categories=['reference_supported','before_reference','no_reference_confirmation','reference_not_confirmed',
        'no_reference_no_confirmation','outside_reference_support','censored','unattempted']
    colors=['#4b979d','#c88b47','#a45b61','#a3afbd','#d4dbe0','#ab8494','#bbb6a4','#eeeeee']
    matrix=[[categories.index(primary[c,m]['primary_outcome']) for c in cases] for m in methods]
    fig,ax=plt.subplots(figsize=(8.6,4.4));fig.subplots_adjust(left=.13,right=.98,bottom=.16,top=.77)
    ax.imshow(matrix,cmap=ListedColormap(colors),vmin=-.5,vmax=7.5,aspect='auto',interpolation='nearest')
    ax.set(xticks=range(16),xticklabels=cases,yticks=range(6),yticklabels=[labels.get(m,m) for m in methods],xlabel='Case')
    ax.set_xticks(np.arange(-.5,16,1),minor=True);ax.set_yticks(np.arange(-.5,6,1),minor=True)
    ax.grid(which='minor',color='white',lw=1.2);ax.tick_params(which='minor',bottom=False,left=False)
    fig.suptitle('SIMULATION',y=.99,fontsize=11)
    fig.legend(handles=[Patch(color=colors[i],label=label) for i,label in
        [(0,'Reference supported'),(1,'Before reference'),(4,'No reference / no event')]],
        loc='upper center',bbox_to_anchor=(.5,.92),ncol=3,fontsize=9)
    save(fig,output/'Exp1B_closeout_1_exclusive_outcomes');plt.close(fig)
    colors_m={'M1':'#9b8e7d','M2':'#4b979d','M3':'#193d58'};markers={'M1':'o','M2':'s','M3':'^'}
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(8.6,6.4));fig.subplots_adjust(left=.13,right=.98,bottom=.12,top=.86,hspace=.42)
    for j,m in enumerate(colors_m):
        for ax,key in zip(axes,('signed_deviation_s','latency_s')):
            available=[(i,index[c,m]) for i,c in enumerate(cases) if index[c,m].get(key,'')!='']
            ax.scatter([i+(j-1)*.19 for i,r in available],[float(r[key]) for i,r in available],
                color=colors_m[m],marker=markers[m],s=30)
    for ax,label in zip(axes,('a','b')):
        ax.axhline(0,color='#a4acb3',ls='--',lw=.8)
        ax.axvspan(2.55,3.45,facecolor='#f4f6f8',lw=0,zorder=-2)
        ax.annotate(label,xy=(0,1),xycoords='axes fraction',xytext=(-24,8),textcoords='offset points',fontweight='bold',fontsize=11)
    axes[0].set_ylabel('Decision − reference / s');axes[1].set_ylabel('Reference-supported latency / s')
    axes[1].set(xticks=range(16),xticklabels=cases,xlabel='Case',xlim=(-.6,15.6),ylim=(-.02,.35))
    fig.suptitle('SIMULATION',fontsize=11,y=.99)
    fig.legend(handles=[Line2D([],[],ls='none',marker=markers[m],color=colors_m[m],label=m) for m in colors_m],
        loc='upper center',bbox_to_anchor=(.5,.945),ncol=3,fontsize=10)
    save(fig,output/'Exp1B_closeout_2_reference_timing');plt.close(fig)
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(8.6,6.5));fig.subplots_adjust(left=.13,right=.98,bottom=.12,top=.84,hspace=.42)
    for j,(key,color) in enumerate([('Q','#999f80'),('S','#7d96b2'),('K','#193d58')]):
        axes[0].bar(np.arange(16)+(j-1)*.24,[int(r[key+'_failed']) for r in counts],width=.22,color=color)
    for j,(key,color) in enumerate([('S','#7d96b2'),('K','#193d58')]):
        axes[1].bar(np.arange(16)+(j-.5)*.26,[int(r[key+'_extra_on_GQ']) for r in counts],width=.24,color=color)
    axes[0].set_ylabel('Raw rejection count');axes[1].set_ylabel('Added rejections on GQ')
    axes[1].set(xticks=range(16),xticklabels=cases,xlabel='Case',xlim=(-.6,15.6),yticks=[0,1,2],ylim=(0,2.2))
    for ax,label in zip(axes,('a','b')):ax.annotate(label,xy=(0,1),xycoords='axes fraction',xytext=(-24,8),textcoords='offset points',fontweight='bold',fontsize=11)
    fig.suptitle('SIMULATION',fontsize=11,y=.99)
    fig.legend(handles=[Patch(color=c,label=k) for k,c in [('Q','#999f80'),('S','#7d96b2'),('K','#193d58')]],
        loc='upper center',bbox_to_anchor=(.5,.945),ncol=3,fontsize=10)
    save(fig,output/'Exp1B_closeout_3_gate_overlap');plt.close(fig)
    js(output/'figure_manifest.json',dict(source_results_sha256=sha(root/'planned_method_results.csv'),
        source_exclusive_outcomes_sha256=sha(root/'exclusive_step_outcomes.csv'),
        source_gate_counts_sha256=sha(root/'gate_trigger_counts.csv'),source_audit_sha256=sha(root/'closeout_audit.json'),
        plot_script_sha256=sha(__file__),new_simulation_runs=0,CI='not applicable: deterministic mechanisms',
        omitted_numeric_points='No reference/no decision retained in outcome matrix and full CSV; not assigned zero latency',
        physical_wrong_advance_measured=False,files={p.name:sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');p.add_argument('output');a=p.parse_args();plot(a.root,a.output)
