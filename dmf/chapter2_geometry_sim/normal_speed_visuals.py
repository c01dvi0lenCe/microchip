"""Read-only plots and one-timescale replay for the normal1.4mm/s example."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from .normal_speed import audit_normal_trial
from .audit import read_rows
from .render import (_decode_rows,_style,_save,_electrodes,_scene,_scene_legend,
                     select_keyframes,write_player,NAVY,TEAL,ORANGE,GRAY)


def load_normal(root):
    root=Path(root);audit=audit_normal_trial(root)
    if not audit['passed']:raise ValueError(audit['failures'])
    read=lambda name:json.loads((root/name).read_text(encoding='utf-8'))
    return dict(root=root,manifest=read('manifest.json'),world=_decode_rows(read_rows(root/'world.csv')),
                observations=_decode_rows(read_rows(root/'observations.csv')),
                events=_decode_rows(read_rows(root/'events.csv')),polygons=read('world_polygons.json'),
                raster=read('raster.json'),design=read('map_snapshot.json'),reference=read('reference.json'),audit=audit)


def figures(data,output):
    output=Path(output);output.mkdir(exist_ok=False);_style()
    keys=select_keyframes(data)
    fig,axes=plt.subplots(2,3,figsize=(9.6,5.9))
    fig.subplots_adjust(left=.025,right=.99,bottom=.07,top=.82,wspace=.13,hspace=.34)
    for ax,key in zip(axes.flat,keys):_scene(ax,data,key['tick_index'])
    for ax in list(axes.flat)[len(keys):]:ax.set_visible(False)
    fig.suptitle('SIMULATION',fontsize=11,y=.99);_scene_legend(fig)
    _save(fig,output/'movement_keyframes');plt.close(fig)
    (output/'keyframe_index.json').write_text(json.dumps(keys,indent=2),encoding='utf-8')
    world=data['world'];obs=data['observations'];duration=data['manifest']['config']['duration_s']
    tw=np.array([r['time_s'] for r in world]);to=np.array([r['exposure_start_s'] for r in obs])
    fig,axes=plt.subplots(3,1,sharex=True,figsize=(7.2,7.4))
    fig.subplots_adjust(left=.14,right=.97,bottom=.09,top=.88,hspace=.55)
    for name,color,marker in (('x_mm',NAVY,'o'),('y_mm',ORANGE,'s')):
        axes[0].plot(tw,[r[name] for r in world],color=color,lw=1.4,label='Internal '+name[0])
        axes[0].plot(to,[r[name] for r in obs],ls='none',marker=marker,mfc='none',mec=color,ms=3,label='Observed '+name[0])
    axes[0].set_ylabel('Position / mm')
    axes[0].legend(ncol=4,fontsize=8.5,loc='lower center',bbox_to_anchor=(.5,1.02))
    axes[1].plot(to,[r['rho_target'] for r in obs],color=NAVY,lw=1.5,label='Target electrode coverage')
    axes[1].plot(to,[r['eta_source'] for r in obs],color=ORANGE,lw=1.5,label='Source residual')
    axes[1].axhline(.9,color=NAVY,ls=':',lw=.9);axes[1].axhline(.08,color=ORANGE,ls=':',lw=.9)
    axes[1].set(ylabel='Area fraction',ylim=(-.05,1.07))
    axes[1].legend(ncol=2,fontsize=8.5,loc='lower center',bbox_to_anchor=(.5,1.02))
    axes[2].plot(tw,[r['speed_mm_s'] for r in world],color=NAVY,lw=1.5,label='Internal')
    axes[2].plot(to,[r['observed_speed_mm_s'] if r['observed_speed_mm_s'] is not None else np.nan for r in obs],
                 ls='none',marker='o',mfc='none',mec=TEAL,ms=3,label='Observed')
    axes[2].set(ylabel='Speed / (mm/s)',xlabel='Simulation time / s')
    axes[2].legend(ncol=2,fontsize=8.5,loc='lower center',bbox_to_anchor=(.5,1.02))
    for ax in axes:
        for t,color in ((.5,GRAY),(.54,GRAY),(data['reference']['confirmed_s'],TEAL)):
            if t is not None:ax.axvline(t,color=color,lw=.7,ls='--',alpha=.7)
        ax.set_xlim(0,duration)
    fig.suptitle('SIMULATION',fontsize=11);_save(fig,output/'feature_timeline');plt.close(fig)
    fig,ax=plt.subplots(figsize=(7.2,3.8));fig.subplots_adjust(left=.22,right=.96,bottom=.18,top=.9)
    names=('single_confirmation','window_confirmation','spatiotemporal_confirmation','independent_reference')
    labels=('Single frame','Continuous','Spatiotemporal','Reference');ref=data['reference']['confirmed_s']
    if ref is not None:
        ax.axvspan(ref,duration,color=TEAL,alpha=.07);ax.axvline(ref,color=TEAL,lw=1,ls='--')
    for y,(name,marker) in enumerate(zip(names,('o','s','^','D'))):
        ax.hlines(y,0,duration,color='#d7dfe5',lw=.8)
        event=next((r for r in data['events'] if r['event']==name),None)
        if event:
            t=event['time_s'];before=ref is not None and t<ref-1e-9;color=ORANGE if before else NAVY
            ax.plot(t,y,marker,color=color,ms=7)
            ax.text(t-.1 if before else t+.1,y+.28,f'{t:.2f} s',
                    ha='right' if before else 'left',va='center',fontsize=10,color=color)
    ax.set(yticks=range(4),yticklabels=labels,xlim=(0,duration),ylim=(3.45,-.45),xlabel='Simulation time / s')
    fig.suptitle('SIMULATION',fontsize=11);_save(fig,output/'arrival_timeline');plt.close(fig)
    return keys


def render_normal(root,output,ffmpeg,common_figures):
    data=load_normal(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    keys=figures(data,output/'figures')
    # Identical map/static geometry are copied byte-for-byte, not regenerated.
    copies=[]
    for old,new in (('map_full_clean','map_full'),('static_geometry','static_geometry')):
        for ext in ('.svg','.pdf','.png'):
            source=Path(common_figures)/(old+ext);target=output/'figures'/(new+ext)
            shutil.copyfile(source,target)
            copies.append(dict(source=str(source),target=str(target),sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    frames=output/'replay_frames';frames.mkdir()
    _style();fig,ax=plt.subplots(figsize=(9.6,5.4))
    fig.subplots_adjust(left=.02,right=.98,bottom=.05,top=.82)
    fig.suptitle('SIMULATION',fontsize=12);_scene_legend(fig)
    for i in range(len(data['world'])):
        ax.clear();_scene(ax,data,i);fig.savefig(frames/f'{i:04d}.png',dpi=120)
    plt.close(fig)
    html=output/'开始回放.html';write_player(data,html)
    # Default playback is real simulation timescale; unchanged original writer
    # exposes all persisted ticks and all controls, without interpolation.
    content=html.read_text(encoding='utf-8').replace('<option value="1">','<option value="1" selected>')
    html.write_text(content,encoding='utf-8')
    movie=output/'normal_speed.mp4';fps=round(1/data['manifest']['config']['dt_s'])
    subprocess.run([str(ffmpeg),'-nostdin','-v','error','-framerate',str(fps),'-i',str(frames/'%04d.png'),
                    '-c:v','h264_mf','-b:v','3500k','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)],
                   check=True,capture_output=True)
    cap=cv2.VideoCapture(str(movie));decoded=0
    while True:
        ok,_=cap.read()
        if not ok:break
        decoded+=1
    actual_fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
    if decoded!=len(data['world']) or abs(actual_fps-fps)>1e-6:raise ValueError('movie frame/timebase mismatch')
    manifest=dict(trial_id=data['manifest']['trial_id'],source_manifest_sha256=hashlib.sha256(Path(root,'manifest.json').read_bytes()).hexdigest(),
                  new_simulation_runs=0,visualization_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  keyframes=keys,common_figure_copies=copies,
                  movie=dict(path=str(movie),frames=decoded,fps=actual_fps,playback_seconds=decoded/actual_fps,
                             simulation_seconds=data['manifest']['config']['duration_s'],speed_factor=1.,
                             no_interpolation=True,terminal_tick_display_s=1/fps),
                  files={p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()})
    (output/'render_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest
