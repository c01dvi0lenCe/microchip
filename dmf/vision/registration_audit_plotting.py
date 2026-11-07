"""Single-panel real-coordinate residual diagnostics; no physical accuracy claim."""
from pathlib import Path
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
import numpy as np


COLORS={'core_center':'#0072b2','core_edge':'#d17a22','peripheral':'#666666'}
LABELS={'core_center':'Core center','core_edge':'Core edge','peripheral':'Peripheral'}


def _save(fig, ax, output, stem):
    fig.canvas.draw()
    (output/f'{stem}.alignment.json').write_text(json.dumps(dict(verdict='NOT APPLICABLE',
        reason='single plot area', axes_bounds=list(ax.get_position().bounds))),encoding='utf-8')
    fig.savefig(output/f'{stem}.svg',facecolor='white')
    fig.savefig(output/f'{stem}.pdf',facecolor='white')
    fig.savefig(output/f'{stem}.png',dpi=600,facecolor='white')
    plt.close(fig)


def _place_point_labels(fig, ax, rows, gain):
    """Pick fixed-point offsets against rendered labels/arrow extents, not data edits."""
    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
    obstacles=[]
    for r in rows:
        a=ax.transData.transform([r['observed_u'],r['observed_v']])
        b=ax.transData.transform([r['observed_u']+gain*r['du_px'],r['observed_v']+gain*r['dv_px']])
        obstacles.append(Bbox.from_extents(min(a[0],b[0])-2,min(a[1],b[1])-2,
                                           max(a[0],b[0])+2,max(a[1],b[1])+2))
    placed=[]
    offsets=((7,7),(-7,7),(7,-11),(-7,-11),(13,0),(-13,0),(0,15),(0,-18))
    for r in rows:
        text=ax.annotate(r['point_id'],(r['observed_u'],r['observed_v']),
                         xytext=(7,7),textcoords='offset points',fontsize=7)
        best=None
        for offset in offsets:
            text.set_position(offset)
            text.set_ha('right' if offset[0]<0 else 'left' if offset[0]>0 else 'center')
            bbox=text.get_window_extent(renderer).expanded(1.1,1.15)
            intersections=[Bbox.intersection(bbox,other) for other in obstacles+placed]
            score=sum(p.width*p.height for p in intersections if p is not None)
            if best is None or score<best[0]:best=(score,offset,bbox)
            if score==0:break
        _,offset,bbox=best; text.set_position(offset)
        text.set_ha('right' if offset[0]<0 else 'left' if offset[0]>0 else 'center')
        placed.append(bbox)


def render_audit(result, output, *, image_size):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    rows=result['points']; gain=80
    if not rows: raise ValueError('reviewed checks required for figure')
    with plt.rc_context({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
                         'font.size':7,'svg.fonttype':'none','pdf.fonttype':42,
                         'axes.spines.top':False,'axes.spines.right':False}):
        fig,ax=plt.subplots(figsize=(183/25.4,145/25.4)); fig.subplots_adjust(left=.11,right=.96,bottom=.17,top=.82)
        for name in COLORS:
            group=[r for r in rows if r['region']==name]
            if not group:continue
            u=np.array([r['observed_u'] for r in group]); v=np.array([r['observed_v'] for r in group])
            ax.scatter(u,v,s=13,color=COLORS[name],label=f'{LABELS[name]} (n={len(group)})',zorder=3)
            ax.quiver(u,v,np.array([r['du_px'] for r in group])*gain,
                np.array([r['dv_px'] for r in group])*gain,angles='xy',scale_units='xy',scale=1,
                width=.003,color=COLORS[name],zorder=2)
        width,height=image_size
        ax.set(xlim=(0,width),ylim=(height,0),xlabel='Image u (px; right)',ylabel='Image v (px; down)')
        ax.set_aspect('equal',adjustable='box'); ax.legend(loc='lower center',bbox_to_anchor=(.5,1.03),
            ncol=3,frameon=False,handletextpad=.4,columnspacing=1)
        fig.text(.11,.97,'PRE-EXPERIMENT | Held-out check-point residuals',fontsize=9,va='top')
        fig.text(.11,.92,f'{len(rows)} checks; arrows enlarged ×80; residual = projected design − manual pixel',fontsize=7,va='top')
        fig.text(.11,.055,'Single image; descriptive only. No independent physical accuracy or distortion clearance.',fontsize=7)
        fig.text(.11,.025,'Source data: independent_points.csv | Arrow length 160 image-coordinate units = 2 px residual',fontsize=7)
        _place_point_labels(fig,ax,rows,gain)
        _save(fig,ax,output,'residual_vectors')
        diagnostics=[('observed_u','du_px','Image u (px)','Signed horizontal residual (px)','horizontal_position'),
            ('observed_v','dv_px','Image v (px)','Signed vertical residual (px)','vertical_position'),
            ('radius_from_image_center_px','error_px','Radius from image geometric center (px)',
             'Residual magnitude (px)','radius_magnitude')]
        for x,y,xlabel,ylabel,stem in diagnostics:
            fig,ax=plt.subplots(figsize=(130/25.4,100/25.4)); fig.subplots_adjust(left=.16,right=.96,bottom=.22,top=.80)
            for name in COLORS:
                group=[r for r in rows if r['region']==name]
                ax.scatter([r[x] for r in group],[r[y] for r in group],s=18,
                           color=COLORS[name],label=LABELS[name])
            ax.set(xlabel=xlabel,ylabel=ylabel)
            fig.text(.16,.96,'PRE-EXPERIMENT | Residual trend diagnostic',fontsize=9,va='top')
            fig.text(.16,.89,f'n={len(rows)} points in one image; no fitted distortion model',fontsize=7,va='top')
            fig.text(.16,.05,'Image center is NOT measured lens principal point. No significance test.',fontsize=7)
            _save(fig,ax,output,stem)
    (output/'figure_integrity.json').write_text(json.dumps(dict(
        backend='Python/Matplotlib',archetype='single quantitative residual diagnostics',
        simulation=False,check_points_plotted=len(rows),arrow_gain=gain,
        raw_pixel_image_modified=False,physical_accuracy_claim=False,
        independent_acquisition_groups=1,source_data='independent_points.csv',
        statistics='descriptive; no CI or p value; repeated points are not independent acquisitions'),indent=2),encoding='utf-8')
