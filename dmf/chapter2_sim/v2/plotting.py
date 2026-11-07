"""Scientific process figures from persisted logs; never runs a model or policy."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle,Polygon,FancyArrowPatch
import numpy as np
from PIL import Image
import cv2

from ..batch import _write_csv,_write_json
from .persistence import sha256
from .replay import PersistedReplay

BLUE='#176EAA';ORANGE='#D77A20';GREEN='#17826D';PURPLE='#8061A7';INK='#203448';GRAY='#7B8793'
COLORS={'Unknown':'#A5ADB5','Stationary':'#768BA2','Moving':BLUE,'Partial':ORANGE,'Arrived':GREEN,'Deviation':'#B35064'}


def _style():
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','Arial','DejaVu Sans'],'font.size':10,
        'svg.fonttype':'none','pdf.fonttype':42,'text.color':INK,'axes.labelcolor':INK,'axes.edgecolor':'#BAC7D1',
        'xtick.color':GRAY,'ytick.color':GRAY,'axes.spines.right':False,'axes.spines.top':False,'legend.frameon':False})


def _save(fig,out,name):
    scripts=Path(os.environ.get('NATURE_FIGURE_SCRIPTS',str(Path.home()/'.agents/skills/nature-figure/scripts')))
    if not (scripts/'audit_panel_alignment.py').exists():raise RuntimeError('Set NATURE_FIGURE_SCRIPTS to scientific figure QA scripts')
    sys.path.insert(0,str(scripts))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=out/(name+'.alignment.json'),overlay_svg=out/(name+'.alignment.svg'),strict=True,tolerance_pt=1.5,gutter_tolerance_pt=1.5)
    fig.savefig(out/(name+'.svg'),facecolor='white');fig.savefig(out/(name+'.pdf'),facecolor='white')
    fig.savefig(out/(name+'.png'),dpi=600,facecolor='white')
    with Image.open(out/(name+'.png')) as im:im.thumbnail((1800,1200));im.save(out/(name+'.preview.png'))
    plt.close(fig)


def _heading(fig,title,sub):
    fig.text(.055,.97,title,fontsize=17,fontweight='bold',va='top')
    fig.text(.055,.912,sub,fontsize=9.5,color=GRAY,va='top')
    fig.text(.95,.97,'SIMULATION',fontsize=12,fontweight='bold',color=BLUE,ha='right',va='top')


def architecture(replay,out):
    fig,ax=plt.subplots(figsize=(15.5,6.15));fig.subplots_adjust(left=.015,right=.985,bottom=.035,top=.84)
    ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
    _heading(fig,'V2-Process-1  简化二维运动与视觉观测仿真','独立开发模式。复用原World/Camera与有界控制策略，不是COMSOL、CFD或真实电润湿动力学计算。')
    xs=[.015,.215,.415,.615,.815];w=.17;y=.45;h=.48
    blocks=[('DropletWorld','420模板，单位pitch\n点状态：位置p、速度v\n命令应用后延迟响应\n有限迁移速度与扰动\nworld.active / response_at'),
        ('SyntheticCamera','20 FPS，8 ms曝光标记\n圆形Mask＋位置/半径噪声\n丢帧与40–55 ms可用延迟\n实际Mask像素持久化\n帧号、epoch、曝光与处理戳'),
        ('观察与连续证据','C0完整性始终开启\n共同覆盖门＋同一W窗口\nS空间 / K运动 / Q质量\nraw gate先算，开关后组合\n源 / 目标 / Recovery分列'),
        ('状态与一次事件','F：五状态＋Unknown\nBTQ：覆盖率强基线\n两者窗口N/T完全相同\nStepContext绑定任务\nArrivalEvent一次性消费'),
        ('EventController','复用既有有界局部策略\nHold：保持当前目标\nUpdate：请求下一目标\nRetry：重施当前目标\nRecovery：回当前源区')]
    for x,(title,body) in zip(xs,blocks):
        ax.add_patch(Rectangle((x,y),w,h,fc='#EDF3F7',ec='#BDCFDD',lw=1))
        ax.text(x+w/2,y+h-.055,title,ha='center',va='top',fontsize=13.5,fontweight='bold',color=BLUE)
        ax.text(x+.012,y+h-.16,body,va='top',fontsize=10.2,linespacing=1.85)
    for a,b in zip(xs[:-1],xs[1:]):ax.add_patch(FancyArrowPatch((a+w+.003,.69),(b-.005,.69),arrowstyle='-|>',mutation_scale=12,lw=1.5,color=INK))
    ax.plot([.9,.9,.10,.10],[.45,.35,.35,.45],lw=1.6,color=BLUE)
    ax.add_patch(FancyArrowPatch((.10,.40),(.10,.45),arrowstyle='-|>',mutation_scale=12,color=BLUE))
    ax.text(.5,.375,'控制改变激活目标与运动响应，运动位置影响下一次模拟观测',ha='center',va='bottom',color=BLUE,fontsize=12)
    ax.add_patch(Rectangle((.02,.035),.39,.21,fc='#F5F1F8',ec='#D0C4DF'))
    ax.text(.035,.205,'内部真值只进入独立评价',fontsize=13,fontweight='bold',color=PURPLE,va='top')
    ax.text(.035,.15,'位置 / 真速度 / 独立驻留定义参考到达区间\n评分在控制循环之后执行，算法入口没有GT参数',fontsize=11,va='top',linespacing=1.6)
    ax.add_patch(Rectangle((.49,.035),.495,.21,fc='#F6F8FA',ec='#D7DFE5'))
    ax.text(.505,.205,'持久化记录与严格回放',fontsize=13,fontweight='bold',va='top')
    ax.text(.505,.15,'观察Mask / 特征 / gate / 事件与内部truth分目录\n逐tick回放，不补帧、不插值、不拼接其他trial',fontsize=11,va='top',linespacing=1.6)
    ax.add_patch(FancyArrowPatch((.414,.14),(.485,.14),arrowstyle='-|>',mutation_scale=12,color=PURPLE,linestyle='--'))
    _save(fig,out,'V2-Process-1_仿真架构')


def _map(ax,r,s,compact=False):
    t=s['truth'];source=int(t['source']);target=int(t['target']);active=t.get('world_active')
    for key,points in r.geometry['polygons'].items():
        a=np.asarray(points,float)
        if a[:,0].min()<9-1e-9 or a[:,0].max()>12+1e-9 or a[:,1].min()<8-1e-9 or a[:,1].max()>10+1e-9:continue
        i=int(key);fill='#F8FAFC';edge='#BCCBD6';lw=.7
        if i==source:fill='#DCEAF4';edge=BLUE
        if i==target:fill='#FBEBD9';edge=ORANGE
        if i==active:lw=2.2;edge=GREEN
        ax.add_patch(Polygon(a,closed=True,fc=fill,ec=edge,lw=lw))
        ax.text(a[:,0].mean(),a[:,1].min()+.14,str(i),fontsize=8 if compact else 10,ha='center',va='center',color='#6B7F8D')
    before=[q for q in r.truth if q['time_s']<=s['time_s']+1e-9]
    ax.plot([q['x'] for q in before],[q['y'] for q in before],color=BLUE,alpha=.25,lw=.8)
    ax.plot(t['x'],t['y'],'o',ms=6 if compact else 10,color=BLUE,zorder=6)
    if s['overlay_mask'] is not None:
        mask=s['overlay_mask'];lower=r.geometry['lower'];scale=r.geometry['scale']
        ax.contour(lower[0]+np.arange(mask.shape[1])/scale,lower[1]+np.arange(mask.shape[0])/scale,mask,levels=[127],colors=[ORANGE],linewidths=1.2,zorder=5)
        f=s['frame']
        if f.get('x') is not None:ax.plot(f['x'],f['y'],'x',ms=6 if compact else 10,mew=1.5,color=ORANGE,zorder=7)
    ax.set(xlim=(9,12),ylim=(10,8),xticks=[9,10,11,12],yticks=[8,9,10])
    ax.set_aspect('equal',adjustable='box');ax.tick_params(labelsize=8 if compact else 10)
    ax.set_xlabel('x / pitch',fontsize=8 if compact else 10,labelpad=2);ax.set_ylabel('y / pitch',fontsize=8 if compact else 10,labelpad=2)


def keyframes(r,out):
    keys=r.keyframes();n=len(keys)
    if not 1<=n<=6:raise ValueError('unsupported keyframe selection; do not invent missing phases')
    fig,axes=plt.subplots(2,3,figsize=(13.5,7.3));fig.subplots_adjust(left=.06,right=.97,bottom=.10,top=.82,wspace=.23,hspace=.5)
    _heading(fig,'V2-Process-2  同一trial的实际Mask与电极反馈',f'{r.trial_id}，n=1开发演示。蓝点是内部点状态，橙线是实际已处理Mask，不是实物液滴轮廓。')
    for i,ax in enumerate(axes.flat):
        if i>=n:ax.axis('off');continue
        k=keys[i];s=r.snapshot(k['time_s']);_map(ax,r,s,True)
        ax.set_title(f"{chr(97+i)}  {k['label']}\nt={k['time_s']:.2f} s   {s['state']} / {s['action']}",loc='left',fontsize=10,pad=8)
    fig.legend(handles=[Line2D([],[],marker='o',color=BLUE,ls='none',label='内部点位置'),Line2D([],[],color=ORANGE,label='已处理Mask轮廓'),Line2D([],[],color=GREEN,lw=2,label='world.active')],loc='lower center',bbox_to_anchor=(.5,.015),ncol=3,fontsize=10)
    _save(fig,out,'V2-Process-2_关键帧');_write_csv(out/'keyframe_sources.csv',keys)


def timeline(r,out):
    fig,axes=plt.subplots(5,1,figsize=(13.5,10.5),sharex=True)
    fig.subplots_adjust(left=.105,right=.97,bottom=.08,top=.86,hspace=.32)
    _heading(fig,'V2-Process-3  同一trial的证据、状态与Update时间线',f'{r.trial_id}。所有横轴为simulation时间，Mask特征按processing_s对齐，Unknown与空值保留。')
    for field,color,label in [('x',BLUE,'内部x'),('y','#65A9C9','内部y')]:
        axes[0].step(r.times,[t[field] for t in r.truth],where='post',color=color,lw=1.3,label=label)
    for field,color,marker,label in [('x',ORANGE,'x','观测x'),('y','#AD662A','+','观测y')]:
        rows=[f for f in r.processed if f.get(field) is not None]
        axes[0].plot([f['processing_s'] for f in rows],[f[field] for f in rows],ls='none',marker=marker,ms=3,color=color,label=label)
    axes[0].set_ylabel('位置 / pitch');axes[0].legend(loc='upper left',bbox_to_anchor=(0,1.32),ncol=4,fontsize=9)
    for step in range(3):
        rows=[f for f in r.processed if f.get('phase')=='transport' and f['step']==step]
        for field,color,label in [('eta_target',ORANGE,'目标覆盖率ηt'),('eta_source',BLUE,'源区残留ηs')]:
            axes[1].plot([f['processing_s'] for f in rows],[f[field] if f.get(field) is not None else np.nan for f in rows],color=color,lw=1.2,label=label if step==0 else None)
    axes[1].set(ylabel='覆盖率',ylim=(-.05,1.08),yticks=[0,.5,1]);axes[1].legend(loc='lower left',bbox_to_anchor=(0,1.01),ncol=2,fontsize=9)
    for field,color,label in [('window_count',BLUE,'帧数支持 n/N'),('window_duration_s',ORANGE,'时长支持 Δt/T')]:
        values=[]
        for g in r.gates:
            stage='target' if g['stage']=='target' else 'source' if g['stage']=='source' else 'recovery';w=r.config[stage]['window']
            values.append((g.get(field) or 0)/(w['frames'] if field=='window_count' else w['duration_s']))
        axes[2].step([g['processing_s'] for g in r.gates],values,where='post',color=color,lw=1.2,label=label)
    axes[2].axhline(1.,ls=':',color=GRAY,lw=.7);axes[2].set(ylabel='连续证据支持',ylim=(-.05,1.5),yticks=[0,1]);axes[2].legend(loc='lower left',bbox_to_anchor=(0,1.01),ncol=2,fontsize=9)
    order=['Unknown','Stationary','Moving','Partial','Arrived','Deviation'];snapshots=[r.snapshot(t) for t in r.times];begin=0
    for i in range(1,len(snapshots)+1):
        if i==len(snapshots) or snapshots[i]['state']!=snapshots[begin]['state']:
            end=r.times[-1] if i==len(snapshots) else r.times[i];state=snapshots[begin]['state']
            if end>r.times[begin]:axes[3].broken_barh([(r.times[begin],end-r.times[begin])],(order.index(state)-.32,.64),fc=COLORS[state])
            begin=i
    axes[3].plot(r.times[-1],order.index(snapshots[-1]['state']),'s',ms=4,color=COLORS[snapshots[-1]['state']])
    axes[3].set(ylim=(-.6,5.6),yticks=range(6),yticklabels=order,ylabel='预测状态');axes[3].tick_params(axis='y',labelsize=8)
    for ref in r.references:
        t=ref['upper_s'];axes[4].plot(t,3,'D',color=PURPLE,ms=4);axes[4].text(t,3.23,f'{t:.2f}',ha='center',va='bottom',fontsize=8,color=PURPLE)
    for e in r.events:
        kind=e['event'];t=e['time_s']
        if kind not in ('ArrivalEvent','Start','Update','Complete','Retry','Recovery','Applied'):continue
        yy=2 if kind=='ArrivalEvent' else 0 if kind=='Applied' else 1;color=GREEN if yy==2 else GRAY if yy==0 else INK
        axes[4].plot(t,yy,'o',color=color,ms=4)
        label=f'{t:.2f}' if kind in ('ArrivalEvent','Applied') else f'{kind} {t:.2f}'
        axes[4].text(t,yy+.23,label,ha='right' if t>r.times[-1]-.2 else 'center',va='bottom',fontsize=8,color=color)
    axes[4].set(ylim=(-.6,3.8),yticks=[0,1,2,3],yticklabels=['模拟Applied','控制请求','算法确认','独立参考']);axes[4].tick_params(axis='y',labelsize=9)
    axes[4].set_xlabel('simulation时间 / s')
    for i,ax in enumerate(axes):
        ax.set_xlim(-.05,r.times[-1]+.11);ax.text(-.09,1.01,chr(97+i),transform=ax.transAxes,fontsize=12,fontweight='bold',va='bottom')
        if i<4:
            ax.grid(axis='x',color='#E8EDF1',lw=.6)
            for e in r.events:
                if e['event']=='ArrivalEvent':ax.axvline(e['time_s'],ls='--',color=GREEN,lw=.6,alpha=.5)
    _save(fig,out,'V2-Process-3_联合时间线')


def _movie_frame(r,s,path):
    dpi=1280/16;fig=plt.figure(figsize=(16,9),dpi=dpi,facecolor='white')
    fig.text(.035,.955,'v2开发演示：实际Mask与事件反馈',fontsize=20,fontweight='bold')
    fig.text(.035,.91,'normal / seed262000 / F，逐tick日志，4倍慢放',fontsize=12,color=GRAY)
    fig.text(.96,.955,'SIMULATION',ha='right',fontsize=16,fontweight='bold',color=BLUE)
    ax=fig.add_axes([.045,.235,.45,.59]);_map(ax,r,s)
    fig.text(.05,.845,'蓝点：内部位置    橙线/十字：已处理Mask/质心',fontsize=11)
    camera=fig.add_axes([.535,.59,.165,.225]);camera.axis('off')
    if s['mask'] is not None:camera.imshow(s['mask'],cmap='gray',vmin=0,vmax=255,interpolation='nearest')
    else:camera.text(.5,.5,'无当前已处理帧',ha='center',va='center',fontsize=11,transform=camera.transAxes)
    camera.set_title('实际SyntheticCamera Mask',fontsize=10,pad=5)
    f=s['frame'];trace=s['trace'];t=s['truth'];req=s['last_request']
    if f:
        fig.text(.535,.55,f"帧 {f['frame_id']}  曝光结束 {f['exposure_s']:.3f} s\n可用 {f['available_s']:.3f} / 处理 {f['processing_s']:.3f} s",fontsize=9.5,linespacing=1.7)
        fig.text(.535,.47,'C0通过' if trace.get('C0_passed') else '拒绝：'+str(trace.get('C0_reason','')),fontsize=10,color=GREEN if trace.get('C0_passed') else GRAY)
    fig.text(.535,.4,f"world.active = {t.get('world_active')}\nresponse_at = "+('未设置' if t.get('world_response_at_s') is None else f"{t['world_response_at_s']:.2f} s"),fontsize=11,linespacing=1.8)
    fig.text(.535,.30,'模拟应用延迟 0.04 s\n正常响应延迟 0.18 s',fontsize=11,linespacing=1.8)
    x=.745
    fig.text(x,.82,f"t = {s['time_s']:.2f} s",fontsize=22,fontweight='bold',color=BLUE)
    fig.text(x,.75,f"step {t['step']+1}/3   epoch {t['epoch']}",fontsize=13)
    fig.text(x,.70,f"源 {t['source']}   目标 {t['target']}",fontsize=13)
    fig.text(x,.62,s['state'],fontsize=22,fontweight='bold',color=COLORS[s['state']])
    fig.text(x,.55,f"动作：{s['action']}",fontsize=16,fontweight='bold')
    if f:
        eta=lambda k:'未知' if f.get(k) is None else f'{f[k]:.3f}'
        fig.text(x,.48,f"ηs {eta('eta_source')}   ηt {eta('eta_target')}",fontsize=12)
    fig.text(x,.41,f"证据 {trace.get('window_count',0)} 帧 / {trace.get('window_duration_s',0):.2f} s\n阶段 {trace.get('stage','无观测')}",fontsize=12,linespacing=1.7)
    if req:fig.text(x,.31,f"最近请求 {req['event']}\n@ {req['time_s']:.2f} s",fontsize=11,linespacing=1.7)
    ref=s['reference'];confirm=s['confirmation']
    fig.text(x,.235,'独立参考：'+(f"{ref['upper_s']:.2f} s" if ref else '未发生'),fontsize=12,color=PURPLE)
    fig.text(x,.19,'算法确认：'+(f"{confirm['time_s']:.2f} s" if confirm else '未发生'),fontsize=12,color=GREEN)
    bar=fig.add_axes([.065,.125,.87,.022]);bar.set(xlim=(0,r.times[-1]),ylim=(0,1));bar.axis('off')
    bar.add_patch(Rectangle((0,0),r.times[-1],1,fc='#E7EEF3',ec='none'));bar.add_patch(Rectangle((0,0),s['time_s'],1,fc=BLUE,ec='none'))
    fig.text(.065,.073,'简化二维点运动＋圆形视觉Mask。不是实物、U-Net预测或流体求解，长度单位pitch。',fontsize=10.5,color=GRAY)
    fig.text(.065,.035,'每帧对应0.01 s已记录tick，无插值。仅已处理帧可显示；被C0拒绝的Mask不叠加到世界图。',fontsize=10.5,color=GRAY)
    fig.savefig(path,dpi=dpi);plt.close(fig)


def make_visualization(trial_dir,output,*,ffmpeg=None):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);figures=output/'figures';figures.mkdir();frames=output/'frames';frames.mkdir()
    _style();r=PersistedReplay(trial_dir)
    architecture(r,figures);keyframes(r,figures);timeline(r,figures)
    index=[];key_times={round(k['time_s'],8) for k in r.keyframes()};key_dir=output/'keyframes';key_dir.mkdir()
    for i,t in enumerate(r.times):
        s=r.snapshot(t);dest=frames/f'frame-{i:04d}.png';_movie_frame(r,s,dest)
        capture=s['capture'];f=s['frame']
        index.append(dict(video_frame=i,video_time_s=i/25,simulation_time_s=t,trial_id=r.trial_id,truth_csv_line=s['truth']['csv_line'],
            frame_id=f['frame_id'] if f else None,frame_csv_line=f['csv_line'] if f else None,processing_s=f['processing_s'] if f else None,
            mask_path=capture.get('mask_path') if capture else None,mask_sha256=capture.get('mask_sha256') if capture else None,
            state=s['state'],action=s['action'],epoch=s['truth']['epoch'],world_active=s['truth']['world_active'],
            world_response_at_s=s['truth']['world_response_at_s'],window_count=s['trace'].get('window_count'),window_duration_s=s['trace'].get('window_duration_s')))
        if round(t,8) in key_times:(key_dir/dest.name).write_bytes(dest.read_bytes())
        if i%100==0:print(f'Replay frame {i+1}/{len(r.times)}',flush=True)
    _write_csv(output/'frame_index.csv',index)
    ffmpeg=ffmpeg or os.environ.get('CHAPTER2_VIS_FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('H.264 encoder unavailable; use --ffmpeg. PNG frames preserved, not claimed as MP4')
    video=output/'normal_262000_F_v2_development.mp4'
    p=subprocess.run([str(ffmpeg),'-y','-framerate','25','-i',str(frames/'frame-%04d.png'),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
    cap=cv2.VideoCapture(str(video));count=0;shape=None;fps=cap.get(cv2.CAP_PROP_FPS)
    while True:
        ok,frame=cap.read()
        if not ok:break
        count+=1;shape=frame.shape[:2]
    cap.release()
    if count!=len(r.times) or shape!=(720,1280) or abs(fps-25)>1e-9:raise RuntimeError('MP4 decode verification failed')
    manifest=dict(simulation=True,purpose='single_development_trial_not_formal_result',trial_id=r.trial_id,source_trial=str(Path(trial_dir).resolve()),
        trial_manifest_sha256=sha256(Path(trial_dir)/'trial_manifest.json'),plotting_source_sha256=sha256(__file__),mask_origin='persisted_actual_camera_pixels',
        no_rerun=True,no_interpolation=True,decoded_frames=count,fps=fps,playback_duration_s=count/fps,simulation_end_s=r.times[-1],slow_motion_factor=4,
        physical_timing_validated=False,files={str(p.relative_to(output)):sha256(p) for p in output.rglob('*') if p.is_file()})
    _write_json(output/'visualization_manifest.json',manifest)
    return str(video)
