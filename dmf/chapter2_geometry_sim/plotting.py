"""Static design-geometry diagnostics; not measured accuracy or S1 figures."""
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as Patch, Circle
from matplotlib.lines import Line2D

from .model import coverage_at

SKILL_SCRIPTS=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0,str(SKILL_SCRIPTS))
from audit_panel_alignment import require_matplotlib_panel_alignment


def _style():
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
                         'font.size':11,'svg.fonttype':'none','pdf.fonttype':42,
                         'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7})


def _save(fig,path):
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(path)+'.alignment.json',tolerance_pt=1.5,strict=True)
    for suffix in ('svg','pdf','png'):
        fig.savefig(str(path)+'.'+suffix,dpi=600)
    plt.close(fig)


def draw_polygons(ax,geometry,source=None,target=None,ids=False):
    for eid,p in geometry.polygons.items():
        face=('#d4e4ef' if eid<=400 else '#d3dbd1')
        if eid==source: face='#b4cfdf'
        if eid==target: face='#efcba9'
        ax.add_patch(Patch(list(p.exterior.coords),facecolor=face,edgecolor='#628096',lw=.35))
        if ids:
            q=p.representative_point()
            ax.text(q.x,q.y,str(eid),ha='center',va='center',fontsize=7 if eid>400 else 5.8)


def export_geometry_figures(geometry,output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    _style()
    fig,ax=plt.subplots(figsize=(9.4,9.4));fig.subplots_adjust(left=.09,right=.97,bottom=.09,top=.94)
    draw_polygons(ax,geometry,190,191)
    for e in geometry.document['electrodes']:
        eid=e['control_id']
        if eid>400 or eid in (1,20,381,400,190,191,192,172):
            q=geometry.polygons[eid].representative_point()
            ax.text(q.x,q.y,str(eid),ha='center',va='center',fontsize=9,color='#173a53')
    route=[geometry.center(i) for i in (190,191,192,172)]
    ax.plot([p[0] for p in route],[p[1] for p in route],'-',color='#a96021',lw=1.5)
    x0,y0,x1,y1=geometry.bounds
    ax.set(xlim=(x0-3,x1+3),ylim=(y1+3,y0-3),xlabel='x / mm',ylabel='y / mm',title='SIMULATION MAP | FBC6-3 | 400 core + 20 peripheral')
    ax.set_aspect('equal')
    _save(fig,output/'420_electrode_map')

    fig,axes=plt.subplots(1,3,figsize=(12.6,4.9));fig.subplots_adjust(left=.05,right=.985,bottom=.22,top=.83,wspace=.22)
    source,target=190,191
    center=geometry.center(target)
    rows=[]
    for index,(ax,d) in enumerate(zip(axes,(3.6,3.8,4.0))):
        # The displayed electrode and droplet are in the same millimetre coordinates.
        draw_polygons(ax,geometry,source,target)
        ax.add_patch(Circle(center,d/2,facecolor='#2e83a2',alpha=.27,edgecolor='none'))
        ax.add_patch(Circle(center,d/2,fill=False,edgecolor='#174c64',lw=1.8))
        ax.plot(*center,'+',color='#174c64',ms=8,mew=1.6)
        row=coverage_at(geometry,d,source,target); rows.append(row)
        ax.set(xlim=(center[0]-3.9,center[0]+2.9),ylim=(center[1]+3.1,center[1]-3.1),xlabel='x / mm')
        ax.set_aspect('equal',adjustable='box')
        ax.set_title(f'({chr(97+index)}) SIMULATION | D = {d:.1f} mm',fontsize=12,pad=16)
        ax.text(.5,-.20,f'Target / droplet = {row["eta_target"]:.1%}',transform=ax.transAxes,ha='center',fontsize=13,color='#173a53')
    axes[0].set_ylabel('y / mm')
    fig.legend(handles=[Line2D([],[],color='#b4cfdf',lw=8,label='Source electrode'),Line2D([],[],color='#efcba9',lw=8,label='Target electrode'),Line2D([],[],color='#174c64',lw=1.8,label='Simulated droplet outline')],loc='upper center',bbox_to_anchor=(.5,.98),ncol=3,fontsize=11)
    _save(fig,output/'droplet_electrode_overlap')
    with (output/'coverage_geometry_check.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (output/'figure_contract.json').write_text(json.dumps(dict(
        claim='Declared circular droplet dimensions change the feasible electrode-overlap ratios.',
        evidence='Gerber design geometry plus user-declared nominal diameters, not video measurements.',
        archetype='quantitative grid',unit='mm',simulation=True,
        spacer_height_mm=.8,diameter_source='user_corrected_diameter_mm',
        uncertainties='No empirical error bars: deterministic assumed geometry, not repeated experiments.',
        map_sha256=geometry.sha256),indent=2),encoding='utf-8')
    return rows
