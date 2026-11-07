"""Single-image review plates; pending navigation is not calibration evidence."""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import numpy as np

from .design_registration import project
from .pilot_annotation import _json


def render_registration(workspace, design, image, result, output):
    """Export additive SVG/PDF/600dpi PNG, never alter image pixels on disk."""
    output=Path(output)
    pending=not workspace.get('fit_freeze')
    pre_experiment=workspace.get('use_scope')=='pre_experiment_only'
    photograph=workspace['source'].get('kind')=='real_industrial_camera_photo'
    matrix=np.array(workspace['initial_image_to_design_mm'] if pending else
                    workspace['fit_freeze']['image_to_design_mm'])
    inverse=np.linalg.inv(matrix)
    polygons=[np.array(project(e['polygon_map_mm'],inverse)) for e in design['electrodes']]
    height,width=image.shape[:2]
    config={'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
            'font.size':7,'svg.fonttype':'none','pdf.fonttype':42}
    with plt.rc_context(config):
        for stem, navigation in [('electrode_overlay',False),('point_navigation',True)]:
            width_inches=183/25.4
            height_inches=(183*height/width+20)/25.4
            fig=plt.figure(figsize=(width_inches,height_inches),facecolor='white')
            ax=fig.add_axes([.025,.08,.95,.83])
            ax.imshow(image[:,:,::-1],interpolation='nearest')
            ax.set_xlim(-.5,width-.5);ax.set_ylim(height-.5,-.5);ax.set_axis_off()
            if not navigation:
                lines=[np.vstack([p,p[0]]) for p in polygons]
                ax.add_collection(LineCollection(lines,colors='#66dcf0',linewidths=.28,alpha=.7))
                for electrode in design['electrodes']:
                    if electrode['control_id'] in (1,20,381,400,402,404,406,408,410,412,414,416):
                        u,v=project([electrode['label_point_map_mm']],inverse)[0]
                        if electrode['control_id'] in (1,20,381,400):
                            x,y=electrode['label_point_map_mm']
                            label=project([[(-13 if x<32 else 77),y]],inverse)[0]
                            label_color='#1f1f1f' if photograph else 'white'
                            ax.annotate(str(electrode['control_id']),(u,v),xytext=label,
                                color=label_color,fontsize=7,ha='center',va='center',clip_on=True,
                                arrowprops=dict(arrowstyle='-',color=label_color,linewidth=.5))
                        else:
                            ax.text(u,v,str(electrode['control_id']),color='white',fontsize=7,
                                    ha='center',va='center',clip_on=True)
            else:
                for point in workspace['points']:
                    actual=point['status']=='confirmed'
                    xy=point['observed_px'] if actual else point['suggested_px']
                    color='#66dcf0' if point['role']=='fit' else '#ffe08a'
                    ax.plot(*xy,marker='x' if actual else 'o',markersize=4,
                            markerfacecolor='none',markeredgecolor=color,markeredgewidth=.7)
                    ax.annotate(point['point_id'],xy,xytext=(5,4),textcoords='offset points',
                                color=color,fontsize=7,clip_on=True)
            title=('POINT NAVIGATION | Not observed reference points' if navigation else
                   ('PRELIMINARY | Navigation initialization' if photograph else
                    'PRELIMINARY | Legacy four-corner initialization')) if pending else (
                   'POINT REVIEW | Fit / held-out checks' if navigation else
                   'DESIGN OVERLAY | Frozen manual fit')
            if pre_experiment:title='PRE-EXPERIMENT | '+title
            source_label=('Real industrial-camera photograph' if photograph else
                          f'Real industrial-camera video frame {workspace["source"]["source_frame_id"]}')
            fig.text(.025,.975,title,fontsize=9,ha='left',va='top')
            fig.text(.025,.938,f'{source_label} '
                     f'| {width} × {height} px | 420 design polygons',fontsize=7,va='top')
            footer=('Hollow markers are projected search locations, not ground truth.' if navigation and pending else
                    'Independent check-point accuracy: PENDING. No physical accuracy claim.' if
                    result['rmse_px'] is None else
                    f'Independent checks: {result["check_confirmed"]}/{result["check_total"]}; '
                    'design-coordinate consistency only, not physical metrology.')
            if pre_experiment:
                footer='Pre-experiment only; final height not fixed. '+(
                    'Navigation is NOT ground truth.' if navigation else 'NOT approved as final calibration.')
            fig.text(.025,.026,footer,fontsize=7,va='bottom')
            fig.canvas.draw()
            _json(output/f'{stem}.alignment.json',dict(verdict='NOT APPLICABLE',
                reason='one image plot-area; no comparable multi-panel rectangles',
                axes_bounds=list(ax.get_position().bounds)))
            fig.savefig(output/f'{stem}.svg',facecolor='white')
            fig.savefig(output/f'{stem}.pdf',facecolor='white')
            fig.savefig(output/f'{stem}.png',dpi=600,facecolor='white')
            plt.close(fig)
    _json(output/'figure_integrity.json',dict(backend='Python/Matplotlib',
        archetype='single image review plate',claim='real design geometry projected for manual review',
        accuracy_status=result['status'],source_image_sha256=workspace['image_sha256'],
        source_frame_id=workspace['source'].get('source_frame_id'),
        source_kind=workspace['source'].get('kind','real_video_frame'),
        use_scope=workspace.get('use_scope','registration_review'),crop=None,
        brightness_contrast_gamma_adjustment=False,pseudocolor=False,stitching=False,
        resizing='display/export sampling only; original native PNG retained',
        physical_scale_bar=False,points_shown='navigation suggestions unless explicitly manually confirmed',
        independent_acquisition_groups=1,simulation=False,
        formal_thesis_accuracy_figure_ready=(not pre_experiment and result['status']=='checked_design_consistency')))
