"""Persisted fault mechanisms only; no simulator, interpolated data or statistics."""
import argparse
import math
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.plot_geometry_exp2_mechanisms import setup, save, label, transaction_markers
from scripts.analyze_geometry_exp2_outcomes import load, read, sha, write_json

ORDER=('A_fixed','M1','M2','M3','early_M1','early_M2','stall_false_M2','stall_false_M3',
       'camera_gap_M2','late_duplicate_M2','applied_delay_M2','stall_timeout_M2','turn_early_M1','turn_early_M2')
PANEL_CASES=('early_M1','early_M2','stall_false_M2','stall_false_M3','turn_early_M1','turn_early_M2')


def event_time(value):
    if value in ('',None):return None
    result=float(value)
    if not math.isfinite(result) or result<0:raise ValueError('nonnegative finite event time required')
    return result


def real_markers(events):return transaction_markers(events)


def trajectories(data,output):
    fig,axes=plt.subplots(3,2,figsize=(183/25.4,195/25.4))
    fig.subplots_adjust(left=.11,right=.98,bottom=.075,top=.91,wspace=.30,hspace=.50)
    for index,(name,ax) in enumerate(zip(PANEL_CASES,axes.flat)):
        folder=data/name;world=read(folder/'world.csv');frames=read(folder/'frames.csv');events=read(folder/'events.csv')
        origin=np.array([float(world[0]['x_mm']),float(world[0]['y_mm'])])
        times=[float(w['time_s']) for w in world]
        ax.plot(times,[float(w['x_mm'])-origin[0] for w in world],color='#315f87',lw=1.1)
        ax.plot(times,[float(w['y_mm'])-origin[1] for w in world],color='#77818a',lw=1.,ls='--')
        observed_t=[float(f['processed_s']) for f in frames]
        ax.scatter(observed_t,[float(f['x_mm'])-origin[0] for f in frames],s=5,facecolors='none',edgecolors='#bc8255',linewidths=.35,alpha=.5)
        ax.scatter(observed_t,[float(f['y_mm'])-origin[1] for f in frames],s=4,marker='x',color='#7b9293',linewidths=.35,alpha=.4)
        for mark in real_markers(events):
            ax.plot(mark['time_s'],7.25 if mark['kind']=='request' else 7.75,marker='v' if mark['kind']=='request' else 's',mfc='white',mec='#596c7c',ms=3,ls='none',mew=.6)
        ax.set(xlim=(0,40),ylim=(-4,8.2),xticks=[0,10,20,30,40],yticks=[-3,0,3,6],xlabel='simulation time / s',ylabel='position / mm')
        label(ax,chr(97+index),name)
    handles=[Line2D([],[],color='#315f87',lw=1,label='World x'),Line2D([],[],color='#77818a',ls='--',lw=1,label='World y'),
        Line2D([],[],color='#bc8255',marker='o',mfc='white',ls='none',ms=3,label='Mask x'),
        Line2D([],[],color='#7b9293',marker='x',ls='none',ms=3,label='Mask y'),
        Line2D([],[],color='#596c7c',marker='v',mfc='white',ls='none',ms=3,label='Request'),
        Line2D([],[],color='#596c7c',marker='s',mfc='white',ls='none',ms=3,label='Applied')]
    fig.text(.015,.99,'SIMULATION',va='top',fontsize=9)
    fig.legend(handles=handles,ncol=3,loc='upper right',bbox_to_anchor=(.985,.995),columnspacing=1.,handlelength=1.5)
    save(fig,output/'Exp2_fault_1_causal_trajectories')


def outcomes(analysis,output):
    rows={r['trial']:r for r in read(analysis/'outcome_summary.csv')}
    if set(rows)!=set(ORDER):raise ValueError('all four normal and ten fault cases required')
    fig,axes=plt.subplots(1,2,figsize=(183/25.4,155/25.4))
    fig.subplots_adjust(left=.255,right=.98,bottom=.11,top=.88,wspace=.34)
    for i,name in enumerate(ORDER):
        row=rows[name];complete=event_time(row['workflow_complete_s']);reference=event_time(row['final_target_reference_first_s'])
        if complete is not None and reference is not None:axes[0].plot([complete,reference],[i-.12,i+.12],color='#b8c2ca',lw=.7)
        for value,marker,color,offset in ((complete,'o','#315f87',-.12),(reference,'D','#bc8255',.12)):
            axes[0].plot(46. if value is None else value,i+offset,marker='x' if value is None else marker,color=color,ls='none',ms=4,mfc='white')
        axes[1].plot(int(row['unsupported_update_requests']),i-.12,marker='v',color='#315f87',ls='none',ms=5,mfc='white')
        axes[1].plot(int(row['unsupported_update_applied']),i+.12,marker='s',color='#bc8255',ls='none',ms=4,mfc='white')
    axes[0].set(xlim=(-1,48),xticks=[0,10,20,30,40,46],xticklabels=['0','10','20','30','40','NA'],
        ylim=(len(ORDER)-.5,-.7),yticks=range(len(ORDER)),yticklabels=ORDER,xlabel='simulation time / s')
    axes[1].set(xlim=(-.3,2.3),xticks=[0,1,2],ylim=(len(ORDER)-.5,-.7),yticks=range(len(ORDER)),yticklabels=[],xlabel='unsupported Update / count')
    label(axes[0],'a','');label(axes[1],'b','')
    fig.legend(handles=[Line2D([],[],color='#315f87',marker='o',mfc='white',ls='none',ms=4,label='Complete'),
        Line2D([],[],color='#bc8255',marker='D',mfc='white',ls='none',ms=4,label='Reference')],loc='lower right')
    # Two outside legends leave all failure rows and markers unobscured.
    fig.legends[-1].set_bbox_to_anchor((.62,.995));fig.legends[-1].set_loc('upper right');fig.legends[-1].set_ncols(2)
    fig.legend(handles=[Line2D([],[],color='#315f87',marker='v',mfc='white',ls='none',ms=4,label='Request'),
        Line2D([],[],color='#bc8255',marker='s',mfc='white',ls='none',ms=4,label='Applied')],loc='upper right',bbox_to_anchor=(.985,.995),ncol=2)
    fig.text(.015,.985,'SIMULATION',va='top',fontsize=9)
    save(fig,output/'Exp2_fault_2_outcome_separation')


def plot(data,analysis,audit,output):
    data,analysis,audit,output=map(Path,(data,analysis,audit,output))
    if not load(audit/'independent_audit.json')['passed']:raise ValueError('saved-data audit required')
    output.mkdir(parents=True,exist_ok=False);setup();trajectories(data,output);outcomes(analysis,output)
    write_json(output/'figure_manifest.json',dict(source=str(Path(__file__).resolve()),source_sha256=sha(__file__),
        data=str(data.resolve()),analysis=str(analysis.resolve()),audit=str(audit.resolve()),new_simulation_runs=0,
        n='one deterministic case per row; no statistical aggregation or confidence interval',
        selected_process_panels=list(PANEL_CASES),all_outcome_rows=list(ORDER),
        world_origin='190 initial center; x/y in mm',observation_time='actual processed time',
        exports={p.name:sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('data','analysis','audit','output'):p.add_argument(key)
    a=p.parse_args();plot(a.data,a.analysis,a.audit,a.output)
