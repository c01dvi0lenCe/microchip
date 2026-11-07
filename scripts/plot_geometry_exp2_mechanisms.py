"""Render only actual persisted development trajectories, masks and events."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import fontManager
from matplotlib.lines import Line2D

SKILL=Path.home()/'.agents/skills/nature-figure/scripts'
sys.path.insert(0,str(SKILL))
from audit_panel_alignment import require_matplotlib_panel_alignment

WIDTH_MM=183
METHODS=('A_fixed','M1','M2','M3')
COLORS=('#77818a','#668e93','#315f87','#bc8255')


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transaction_markers(events):
    requests={r['request_id']:r for r in events if r['event']=='request'}
    result=[]
    for row in events:
        if row['event'] not in ('request','simulated_applied'):continue
        if row['event']=='simulated_applied':
            if row['request_id'] not in requests or requests[row['request_id']]['target']!=row['target']:
                raise ValueError('unmatched Applied cannot be plotted')
        result.append(dict(kind='request' if row['event']=='request' else 'applied',
                           time_s=float(row['time_s']),target=int(row['target']),action=row['action']))
    return result


def validate_steps(rows):
    if len(rows)!=3 or {int(r['step']) for r in rows}!={0,1,2}:raise ValueError('exactly3 planned steps required')
    return rows


def setup():
    for p in ['C:/Windows/Fonts/simsun.ttc','C:/Windows/Fonts/times.ttf']:fontManager.addfont(p)
    plt.rcParams.update({'font.family':['Times New Roman','SimSun','Arial'],'font.size':8.5,
        'axes.labelsize':8.5,'axes.titlesize':9,'legend.fontsize':8.5,'pdf.fonttype':42,
        'svg.fonttype':'none','axes.unicode_minus':False,'axes.spines.top':False,
        'axes.spines.right':False,'axes.linewidth':.6,'legend.frameon':False,
        'figure.facecolor':'white','axes.facecolor':'white'})


def label(ax,letter,title):
    ax.set_title(title,pad=6)
    ax.annotate(letter,xy=(0,1),xycoords='axes fraction',xytext=(-24,6),textcoords='offset points',
                fontsize=10,fontweight='bold',annotation_clip=False)


def save(fig,path):
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(path)+'.alignment.json',
        overlay_svg=str(path)+'.alignment.svg',strict=True,tolerance_pt=1.5,gutter_tolerance_pt=1.5)
    fig.savefig(str(path)+'.pdf');fig.savefig(str(path)+'.svg');fig.savefig(str(path)+'.png',dpi=600)
    plt.close(fig)


def geometry(path):
    doc=load(path);polys={e['control_id']:np.array(e['polygon_map_mm']) for e in doc['electrodes']}
    from shapely.geometry import Polygon
    centers={i:np.array(Polygon(poly).centroid.coords[0]) for i,poly in polys.items()}
    return polys,centers


def draw_map(ax,polys,centers,origin,ids):
    for i in ids:
        p=polys[i]-origin;ax.plot(p[:,0],p[:,1],color='#abb4bc',lw=.55,zorder=0)
        c=centers[i]-origin
        if i==172:
            ax.text(c[0]+2.12,c[1],str(i),ha='left',va='center',fontsize=8)
        else:
            ax.text(c[0],c[1]+2.15,str(i),ha='center',va='center',fontsize=8)
    c=np.array([centers[i]-origin for i in ids]);lo=c.min(axis=0)-2.8;hi=c.max(axis=0)+2.8
    bounds=ax.get_position();fig=ax.figure
    ratio=bounds.width*fig.get_figwidth()/(bounds.height*fig.get_figheight())
    span=hi-lo;mid=(lo+hi)/2
    if span[0]/span[1]<ratio:span[0]=span[1]*ratio
    else:span[1]=span[0]/ratio
    ax.set(xlim=(mid[0]-span[0]/2,mid[0]+span[0]/2),ylim=(mid[1]-span[1]/2,mid[1]+span[1]/2),xlabel='x / mm',ylabel='y / mm')
    ax.set_aspect('equal',adjustable='box')


def normal_figure(data,out):
    fig,axes=plt.subplots(4,2,figsize=(WIDTH_MM/25.4,225/25.4))
    fig.subplots_adjust(left=.11,right=.985,bottom=.065,top=.93,wspace=.35,hspace=.68)
    inputs=load(data/'M1/manifest.json')['inputs'];polys,centers=geometry(inputs['map_path']);origin=centers[190]
    for j,method in enumerate(METHODS):
        folder=data/method;world=read(folder/'world.csv');frames=read(folder/'frames.csv');events=read(folder/'events.csv')
        validate_steps(read(folder/'steps.csv'));left,right=axes[j]
        draw_map(left,polys,centers,origin,[190,191,192,172])
        xy=np.array([[float(r['x_mm']),float(r['y_mm'])] for r in world])-origin
        left.plot(xy[:,0],xy[:,1],color=COLORS[j],lw=1.3,label='World')
        observations=np.array([[float(r['x_mm']),float(r['y_mm'])] for r in frames if r.get('x_mm','')!=''])-origin
        if len(observations):left.scatter(observations[:,0],observations[:,1],s=5,edgecolors='#596c7c',facecolors='none',alpha=.45,linewidths=.35,label='Mask',zorder=4)
        ts=[float(r['processed_s']) for r in frames if r['phase']=='transport']
        rr=[r for r in frames if r['phase']=='transport']
        right.plot(ts,[float(r['rho_target']) for r in rr],color='#315f87',lw=.9)
        right.plot(ts,[float(r['eta_source']) for r in rr],color='#bc8255',lw=.9,ls='--')
        for mark in transaction_markers(events):
            right.plot(mark['time_s'],1.06 if mark['kind']=='request' else 1.14,
                marker='v' if mark['kind']=='request' else 's',color='#596c7c' if mark['kind']=='request' else COLORS[j],
                mfc='white',ms=3,ls='none',mew=.7)
        right.set(xlim=(0,40),ylim=(-.03,1.22),yticks=[0,.5,1],xlabel='simulation time / s',ylabel='覆盖率')
        label(left,chr(97+j*2),method);label(right,chr(98+j*2),method)
    fig.text(.015,.987,'SIMULATION',va='top',fontsize=9)
    handles=[Line2D([],[],color='#596c7c',lw=1,label='World'),Line2D([],[],color='#596c7c',marker='o',mfc='white',ms=3,ls='none',label='Mask'),
        Line2D([],[],color='#315f87',lw=1,label='ρ target'),Line2D([],[],color='#bc8255',lw=1,ls='--',label='η source'),
        Line2D([],[],color='#596c7c',marker='v',mfc='white',ms=3,ls='none',label='Request'),
        Line2D([],[],color='#596c7c',marker='s',mfc='white',ms=3,ls='none',label='Applied')]
    fig.legend(handles=handles,loc='upper right',bbox_to_anchor=(.985,.99),ncol=3,columnspacing=1,handlelength=1.5,labelspacing=.2)
    save(fig,out/'Exp2_mechanism_1_closed_loop')


def counterfactual_figure(folder,out,map_path):
    polys,centers=geometry(map_path);origin=centers[190]
    fig=plt.figure(figsize=(WIDTH_MM/25.4,135/25.4));gs=fig.add_gridspec(2,2,height_ratios=[1,1.1])
    axes=[fig.add_subplot(gs[0,0]),fig.add_subplot(gs[0,1]),fig.add_subplot(gs[1,:])]
    fig.subplots_adjust(left=.10,right=.98,bottom=.10,top=.90,wspace=.3,hspace=.54)
    for ax,name,color,title in zip(axes[:2],['early','late'],[COLORS[0],COLORS[2]],['0.80 s Request','8.00 s Request']):
        world=read(folder/name/'world.csv');events=load(folder/name/'events.json')
        draw_map(ax,polys,centers,origin,[190,191,192]);xy=np.array([[float(r['x_mm']),float(r['y_mm'])] for r in world])-origin
        ax.plot(xy[:,0],xy[:,1],color=color,lw=1.4)
        label(ax,'a' if name=='early' else 'b',title)
        axes[2].plot([float(r['time_s']) for r in world],xy[:,0],color=color,lw=1.2,label='Early' if name=='early' else 'Late')
        for e in events:
            if e['event']=='simulated_applied':axes[2].plot(float(e['time_s']),float(e['left_limit']['x_mm'])-origin[0],marker='s',mfc='white',color=color,ms=4)
    axes[2].set(xlim=(0,20),xlabel='simulation time / s',ylabel='x / mm');label(axes[2],'c','')
    axes[2].legend(loc='lower right');fig.text(.015,.985,'SIMULATION',va='top',fontsize=9)
    save(fig,out/'Exp2_mechanism_2_timing_counterfactual')


def plot(data,counterfactual,output):
    data,counterfactual,output=map(Path,(data,counterfactual,output))
    if output.exists():raise FileExistsError(output)
    if not load(data/'independent_audit.json')['passed']:raise ValueError('saved-data audit must pass')
    output.mkdir(parents=True);setup();normal_figure(data,output)
    counterfactual_figure(counterfactual,output,load(data/'M1/manifest.json')['inputs']['map_path'])
    (output/'figure_manifest.json').write_text(json.dumps(dict(source=str(Path(__file__).resolve()),source_sha256=sha(__file__),
        data=str(data.resolve()),counterfactual=str(counterfactual.resolve()),new_simulation_runs=0,
        axis_origin_electrode=190,observation_points='all processed observations, no row sampling',
        scope='deterministic mechanism n=1 per method, no performance inference',
        files={p.name:sha(p) for p in output.iterdir() if p.is_file()}),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('data','counterfactual','output'):p.add_argument(name)
    a=p.parse_args();plot(a.data,a.counterfactual,a.output)
