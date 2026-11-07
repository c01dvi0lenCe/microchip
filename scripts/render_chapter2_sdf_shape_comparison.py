"""Saved-log shape sensitivity figures; modeling nodes are not holdout GT."""
import json
from pathlib import Path
import subprocess
import sys

import cv2
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from shapely.geometry import Polygon
from shapely.affinity import translate

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.sdf_trial import OUT,BASE,sha,js,audit_empirical
from dmf.chapter2_geometry_sim.shape_sequence import SDFShapeSequence,shape_metrics,width_at_fraction
from dmf.chapter2_geometry_sim.normal_speed_visuals import load_normal,figures
from dmf.chapter2_geometry_sim.render import _decode_rows,_style,_save,_electrodes,_scene,_scene_legend,write_player,NAVY,TEAL,ORANGE,GRAY
from dmf.chapter2_geometry_sim.audit import read_rows
from dmf.chapter2_geometry_sim.single_step import write_csv


def load_sdf():
    root=OUT/'trial';audit=audit_empirical(root)
    if not audit['passed']:raise ValueError(audit)
    load=lambda name:json.loads((root/name).read_text(encoding='utf-8'))
    return dict(root=root,manifest=load('manifest.json'),world=_decode_rows(read_rows(root/'world.csv')),
        observations=_decode_rows(read_rows(root/'observations.csv')),events=_decode_rows(read_rows(root/'events.csv')),
        polygons=load('world_polygons.json'),raster=load('raster.json'),design=load('map_snapshot.json'),reference=load('reference.json'),audit=audit)


def render():
    data=load_sdf();old=load_normal(BASE)
    visual=OUT/'visualization';visual.mkdir(exist_ok=False)
    keys=figures(data,visual/'figures');_style()
    library=json.loads((OUT/'shape_inputs/shape_library.json').read_text(encoding='utf-8'))
    fig,axes=plt.subplots(2,4,figsize=(12.4,5.5));fig.subplots_adjust(left=.02,right=.99,bottom=.04,top=.9,wspace=.08,hspace=.25)
    for ax,r in zip(axes.flat,library['inputs']):
        image=cv2.imdecode(np.fromfile(OUT/'shape_inputs'/r['image_path'],np.uint8),cv2.IMREAD_COLOR)
        mask=cv2.imdecode(np.fromfile(OUT/'shape_inputs'/r['mask_path'],np.uint8),0)
        ax.imshow(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
        for c in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            xy=c[:,0,:];ax.plot(xy[:,0],xy[:,1],color='#45d5dc',lw=1)
        ax.set_title(f"Frame {r['source_frame_id']}",fontsize=11);ax.set_axis_off()
    fig.suptitle('REAL VIDEO | MODEL INPUT',fontsize=11)
    _save(fig,visual/'figures/real_shape_sequence');plt.close(fig)
    source=np.array([old['world'][0]['x_mm'],old['world'][0]['y_mm']])
    target=np.array(next(e['center_map_mm'] for e in old['design']['electrodes'] if e['control_id']==191))
    unit=(target-source)/np.linalg.norm(target-source)
    phases=np.array([(np.array([r['x_mm'],r['y_mm']])-source)@unit/np.linalg.norm(target-source) for r in old['world']])
    selected=[50]+[int(np.flatnonzero(phases>=q)[0]) for q in (.1,.3,.5,.8,1-1e-9)]
    fig,axes=plt.subplots(2,3,figsize=(9.6,5.9));fig.subplots_adjust(left=.025,right=.99,bottom=.07,top=.82,wspace=.13,hspace=.34)
    for ax,i in zip(axes.flat,selected):
        _electrodes(ax,data)
        for dataset,color,ls in ((old,GRAY,'--'),(data,NAVY,'-')):
            points=np.array(dataset['polygons'][i]['polygon_mm'])
            ax.plot(points[:,0],points[:,1],color=color,ls=ls,lw=1.5)
        row=data['world'][i];ax.plot(row['x_mm'],row['y_mm'],'+',color=TEAL,ms=7)
        ax.set_title(f"t = {row['time_s']:.2f} s",fontsize=11);ax.set_xticks([]);ax.set_yticks([])
    fig.suptitle('SIMULATION',fontsize=11,y=.99)
    fig.legend(handles=[Line2D([],[],color=GRAY,ls='--',label='Affine'),Line2D([],[],color=NAVY,label='Empirical SDF'),
         Line2D([],[],color=TEAL,marker='+',ls='none',label='Shared centroid')],loc='upper center',ncol=3,bbox_to_anchor=(.5,.965),fontsize=10)
    _save(fig,visual/'figures/two_models_same_trajectory');plt.close(fig)
    # Metrics at modeling nodes are reconstruction descriptors by construction.
    errors=[]
    sequence=SDFShapeSequence([r['phase'] for r in library['inputs']],[Polygon(r['normalized_polygon_mm']) for r in library['inputs']])
    for r in library['inputs']:
        q=r['phase'];i=int(np.argmin(abs(phases-q)))
        affine=Polygon(old['polygons'][i]['polygon_mm'])
        affine=translate(affine,-affine.centroid.x,-affine.centroid.y)
        reference=Polygon(r['normalized_polygon_mm']);empirical=sequence.polygon(q)
        metric=shape_metrics(reference)
        for name,p in [('Affine',affine),('Empirical_SDF',empirical)]:
            measure=shape_metrics(p);ref_neck=metric['neck_width_mm'];pred_neck=None
            if ref_neck is not None:pred_neck=width_at_fraction(p,metric['neck_fraction'])
            errors.append(dict(source_frame_id=r['source_frame_id'],method=name,
                evaluation_role='modeling_node_reconstruction_NOT_independent_validation',
                original_gui_mask_reviewed=r['original_gui_mask_reviewed'],
                shape_phase=q,affine_nearest_tick_s=old['world'][i]['time_s'],affine_phase_mismatch=float(phases[i]-q),
                normalized_shape_iou=p.intersection(reference).area/p.union(reference).area,
                aspect_ratio_reference=metric['aspect_ratio'],aspect_ratio_predicted=measure['aspect_ratio'],
                aspect_ratio_absolute_error=abs(measure['aspect_ratio']-metric['aspect_ratio']),
                reference_neck_width_mm=ref_neck,predicted_width_at_reference_neck_mm=pred_neck,
                neck_width_absolute_error_mm=None if ref_neck is None else abs(pred_neck-ref_neck),
                normalized_area_relative_error=abs(p.area/reference.area-1),
                real_electrode_coverage_error=None,heldout_shape_iou=None,
                missing_real_coverage_reason='no_valid_video_Gerber_binding',missing_holdout_reason='no_independent_reviewed_migration'))
    write_csv(OUT/'modeling_node_shape_descriptors.csv',errors)
    comparison=[]
    for a,b in zip(old['observations'],data['observations']):
        if a['frame_id']!=b['frame_id'] or a['exposure_start_s']!=b['exposure_start_s']:raise ValueError('camera pairing mismatch')
        comparison.append(dict(frame_id=int(a['frame_id']),exposure_start_s=a['exposure_start_s'],
            affine_rho_target=a['rho_target'],sdf_rho_target=b['rho_target'],
            affine_eta_source=a['eta_source'],sdf_eta_source=b['eta_source'],
            affine_distance_mm=a['distance_mm'],sdf_distance_mm=b['distance_mm']))
    write_csv(OUT/'paired_observed_features.csv',comparison)
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(7.2,5.7));fig.subplots_adjust(left=.14,right=.97,bottom=.12,top=.86,hspace=.42)
    t=[r['exposure_start_s'] for r in comparison]
    for ax,key,threshold,label in [(axes[0],'rho_target',.9,'Target electrode coverage'),(axes[1],'eta_source',.08,'Source residual')]:
        ax.plot(t,[r['affine_'+key] for r in comparison],color=GRAY,ls='--',lw=1.5,label='Affine')
        ax.plot(t,[r['sdf_'+key] for r in comparison],color=NAVY,lw=1.5,label='Empirical SDF')
        ax.axhline(threshold,color=ORANGE,ls=':',lw=1)
        ax.set(ylabel=label,ylim=(-.05,1.05),xlim=(0,6));ax.legend(ncol=2,loc='lower center',bbox_to_anchor=(.5,1.02),fontsize=9.5)
    axes[-1].set_xlabel('Simulation time / s');fig.suptitle('SIMULATION',fontsize=11)
    _save(fig,visual/'figures/paired_coverage_features');plt.close(fig)
    frames=visual/'replay_frames';frames.mkdir()
    fig,axes=plt.subplots(1,2,figsize=(12.8,4.5));fig.subplots_adjust(left=.02,right=.99,bottom=.1,top=.78,wspace=.1)
    fig.suptitle('SIMULATION',fontsize=12,y=.99);_scene_legend(fig)
    for i in range(len(data['world'])):
        for ax,d,label in zip(axes,(old,data),('Affine','Empirical SDF')):
            ax.clear();_scene(ax,d,i);ax.set_title(f"{label} | t = {d['world'][i]['time_s']:.2f} s",fontsize=11)
        fig.savefig(frames/f'{i:04d}.png',dpi=120)
    plt.close(fig)
    player=visual/'开始回放.html';write_player(data,player)
    content=player.read_text(encoding='utf-8').replace('<option value="1">','<option value="1" selected>')
    content=content.replace('SIMULATION · 190 → 191','SIMULATION · 仿射（左） / SDF（右）')
    content=content.replace('<b>液滴／观测</b>','<b>右侧SDF观测与事件</b>')
    player.write_text(content,encoding='utf-8')
    ffmpeg=Path('E:/Apps/Jianying/JianyingPro/11.6.0.14552/ffmpeg.exe');movie=visual/'affine_vs_sdf.mp4'
    subprocess.run([str(ffmpeg),'-nostdin','-v','error','-framerate','100','-i',str(frames/'%04d.png'),
       '-c:v','h264_mf','-b:v','5000k','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)],check=True,capture_output=True)
    capture=cv2.VideoCapture(str(movie));count=0
    while True:
        ok,_=capture.read()
        if not ok:break
        count+=1
    fps=capture.get(cv2.CAP_PROP_FPS);capture.release()
    if count!=601 or fps!=100:raise ValueError('encoded movie frame/time mismatch')
    js(visual/'render_manifest.json',dict(trial_id=data['manifest']['trial_id'],new_simulation_runs=0,
       plot_script_sha256=sha(__file__),keyframes=keys,comparison_tick_indices=selected,
       movie=dict(frames=count,fps=fps,seconds=count/fps,speed_factor=1,no_interpolation=True),
       input_manifest_sha256=sha(OUT/'trial/manifest.json'),
       files={p.relative_to(visual).as_posix():sha(p) for p in visual.rglob('*') if p.is_file()}))
    print('rendered',visual,flush=True)


if __name__=='__main__':render()
