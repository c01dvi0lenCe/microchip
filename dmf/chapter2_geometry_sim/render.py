"""Read-only scientific rendering and frame replay from persisted artifacts."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as Patch
from shapely.geometry import Polygon as ShapePolygon,box

from .audit import audit_trial,read_rows

SKILL=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")
if str(SKILL) not in sys.path:sys.path.insert(0,str(SKILL))
from audit_panel_alignment import require_matplotlib_panel_alignment

NAVY='#173a53';TEAL='#238da5';ORANGE='#c28140';GRAY='#8998a4'


def _decode_rows(rows):
    result=[]
    for row in rows:
        decoded={}
        for key,value in row.items():
            if value=='True':decoded[key]=True
            elif value=='False':decoded[key]=False
            elif value=='':decoded[key]=None
            else:
                try:decoded[key]=float(value)
                except ValueError:decoded[key]=value
        result.append(decoded)
    return result


def load_trial(root):
    root=Path(root)
    audit=audit_trial(root)
    if not audit['passed']:raise ValueError(audit['failures'])
    return dict(root=root,manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8')),
                world=_decode_rows(read_rows(root/'world.csv')),
                observations=_decode_rows(read_rows(root/'observations.csv')),
                events=_decode_rows(read_rows(root/'events.csv')),
                polygons=json.loads((root/'world_polygons.json').read_text(encoding='utf-8')),
                raster=json.loads((root/'raster.json').read_text(encoding='utf-8')),
                design=json.loads((root/'map_snapshot.json').read_text(encoding='utf-8')),
                reference=json.loads((root/'reference.json').read_text(encoding='utf-8')),audit=audit)


def select_keyframes(data):
    world=data['world'];times=np.array([r['time_s'] for r in world])
    source=np.array([world[0]['x_mm'],world[0]['y_mm']])
    target=np.array(next(e['center_map_mm'] for e in data['design']['electrodes'] if e['control_id']==191))
    length=np.linalg.norm(target-source);unit=(target-source)/length
    q=np.array([(np.array([r['x_mm'],r['y_mm']])-source)@unit/length for r in world])
    choices=[('source',.5)]
    for fraction in (.25,.5):
        ids=np.flatnonzero(q>=fraction)
        if len(ids):choices.append((f'progress_{fraction}',times[ids[0]]))
    for event in ('single_confirmation','independent_reference','window_confirmation','spatiotemporal_confirmation'):
        matching=[r for r in data['events'] if r['event']==event]
        if matching:choices.append((event,matching[0]['time_s']))
    by_index={}
    for stage,time in choices:
        i=int(np.argmin(abs(times-time)))
        if i not in by_index:by_index[i]=dict(tick_index=i,time_s=float(times[i]),stages=[])
        by_index[i]['stages'].append(stage)
    return [by_index[i] for i in sorted(by_index)][:6]


def _style():
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':10.5,'axes.labelsize':11,'axes.spines.right':False,'axes.spines.top':False,
        'axes.linewidth':.65,'svg.fonttype':'none','pdf.fonttype':42,'legend.frameon':False})


def _save(fig,path):
    for ext in ('svg','pdf','png'):
        if path.with_suffix('.'+ext).exists():raise FileExistsError(path.with_suffix('.'+ext))
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=str(path)+'.alignment.json',strict=True,tolerance_pt=1.5)
    fig.savefig(path.with_suffix('.svg'))
    fig.savefig(path.with_suffix('.pdf'))
    fig.savefig(path.with_suffix('.png'),dpi=600)


def _electrodes(ax,data,full=False):
    clip=box(27.3,27.25,36.7,33.55)
    for e in data['design']['electrodes']:
        p=np.array(e['polygon_map_mm']);eid=e['control_id']
        if not full and (p[:,0].max()<27 or p[:,0].min()>37 or p[:,1].max()<27 or p[:,1].min()>34):continue
        color='#dbe7ef' if eid==190 else '#efd3b4' if eid==191 else '#f2f5f7'
        display=ShapePolygon(p) if full else ShapePolygon(p).intersection(clip)
        if display.is_empty:continue
        parts=list(display.geoms) if display.geom_type=='MultiPolygon' else [display]
        for part in parts:
            ax.add_patch(Patch(np.array(part.exterior.coords),facecolor=color,edgecolor='#9bacb7',lw=.45))
        if (not full and eid in (190,191)) or (full and (eid>400 or eid in (1,20,381,400))):
            x,y=e['label_point_map_mm']
            if full:
                if eid==190:y-=.6
                elif eid==191:y+=.6
                ax.text(x,y,str(eid),ha='center',va='center',fontsize=8 if eid in (190,191) else 9,color=NAVY)
            else:ax.text(x,-.04,str(eid),transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=10,color=NAVY)
    if full:
        points=np.concatenate([np.array(e['polygon_map_mm']) for e in data['design']['electrodes']])
        lo=points.min(axis=0)-3;hi=points.max(axis=0)+3
        ax.set(xlim=(lo[0],hi[0]),ylim=(hi[1],lo[1]),xlabel='x / mm',ylabel='y / mm')
    else:ax.set(xlim=(27.3,36.7),ylim=(33.55,27.25))
    ax.set_aspect('equal',adjustable='box')


def _latest_observation(data,t):
    rows=[r for r in data['observations'] if r['processed_at_s']<=t+1e-9]
    return rows[-1] if rows else None


def _observed_layer(ax,data,row):
    if row is None:return
    mask=cv2.imdecode(np.frombuffer((data['root']/row['mask_path']).read_bytes(),np.uint8),0)
    raster=data['raster'];lo=raster['lower_mm'];hi=raster['upper_mm']
    scale=raster['pixels_per_mm']
    x0=int(round((27.3-lo[0])*scale));x1=int(round((36.7-lo[0])*scale))
    y0=int(round((27.25-lo[1])*scale));y1=int(round((33.55-lo[1])*scale))
    cropped=mask[y0:y1,x0:x1]
    rgba=np.zeros((*cropped.shape,4),float);rgba[:,:,:3]=np.array([35,141,165])/255.;rgba[:,:,3]=(cropped>0)*.28
    ax.imshow(rgba,extent=(lo[0]+x0/scale,lo[0]+x1/scale,lo[1]+y1/scale,lo[1]+y0/scale),origin='upper',interpolation='none',zorder=2)
    ax.plot(row['x_mm'],row['y_mm'],'+',color=TEAL,ms=7,mew=1.6,zorder=5)


def _scene(ax,data,index):
    row=data['world'][index];_electrodes(ax,data)
    observed=_latest_observation(data,row['time_s']);_observed_layer(ax,data,observed)
    p=np.array(data['polygons'][index]['polygon_mm'])
    ax.plot(p[:,0],p[:,1],color=NAVY,lw=1.5,zorder=4)
    ax.plot(row['x_mm'],row['y_mm'],'o',mfc='white',mec=NAVY,ms=3.5,zorder=6)
    ax.set_xticks([]);ax.set_yticks([])
    ax.set_title(f't = {row["time_s"]:.2f} s',fontsize=11,pad=7)


def _scene_legend(fig):
    fig.legend(handles=[Line2D([],[],color=NAVY,lw=1.5,label='Internal outline'),
                        Line2D([],[],color=TEAL,lw=6,alpha=.35,label='Observed mask'),
                        Line2D([],[],color=TEAL,marker='+',ls='none',label='Observed centroid')],
               loc='upper center',ncol=3,bbox_to_anchor=(.5,.965),fontsize=10)


def make_figures(data,output,preflight):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);_style()
    fig,ax=plt.subplots(figsize=(8,8));fig.subplots_adjust(left=.1,right=.97,bottom=.09,top=.94)
    _electrodes(ax,data,full=True);fig.suptitle('SIMULATION',fontsize=11)
    _save(fig,output/'map_full');plt.close(fig)
    fig,axes=plt.subplots(1,5,figsize=(12.8,3.5));fig.subplots_adjust(left=.025,right=.99,bottom=.1,top=.78,wspace=.13)
    for ax,row in zip(axes,preflight['rows']):
        _electrodes(ax,data);p=np.array(row['polygon_mm']);ax.plot(p[:,0],p[:,1],color=NAVY,lw=1.6)
        ax.plot(row['x_mm'],row['y_mm'],'+',color=NAVY,ms=7)
        ax.set_title(f'{row["fraction"]:.0%}',fontsize=12);ax.set_xticks([]);ax.set_yticks([])
    fig.suptitle('SIMULATION',fontsize=11)
    _save(fig,output/'static_geometry');plt.close(fig)

    keys=select_keyframes(data)
    fig,axes=plt.subplots(2,3,figsize=(9.6,5.9));fig.subplots_adjust(left=.025,right=.99,bottom=.07,top=.82,wspace=.13,hspace=.34)
    for ax,key in zip(axes.flat,keys):_scene(ax,data,key['tick_index'])
    for ax in list(axes.flat)[len(keys):]:ax.set_visible(False)
    fig.suptitle('SIMULATION',fontsize=11,y=.99);_scene_legend(fig)
    _save(fig,output/'movement_keyframes');plt.close(fig)
    (output/'keyframe_index.json').write_text(json.dumps(keys,indent=2),encoding='utf-8')

    w=data['world'];o=data['observations'];tw=np.array([r['time_s'] for r in w]);to=np.array([r['exposure_start_s'] for r in o])
    fig,axes=plt.subplots(3,1,sharex=True,figsize=(7.2,7.4));fig.subplots_adjust(left=.14,right=.97,bottom=.09,top=.88,hspace=.55)
    ax=axes[0]
    for name,color,marker in (('x_mm',NAVY,'o'),('y_mm',ORANGE,'s')):
        ax.plot(tw,[r[name] for r in w],color=color,lw=1.4,label='Internal '+name[0])
        ax.plot(to,[r[name] for r in o],ls='none',marker=marker,mfc='none',mec=color,ms=3,label='Observed '+name[0])
    ax.set_ylabel('Position / mm');ax.legend(ncol=4,fontsize=8.5,loc='lower center',bbox_to_anchor=(.5,1.02))
    ax=axes[1]
    ax.plot(to,[r['rho_target'] for r in o],color=NAVY,label='Target electrode coverage',lw=1.5)
    ax.plot(to,[r['eta_source'] for r in o],color=ORANGE,label='Source residual',lw=1.5)
    ax.axhline(.9,color=NAVY,ls=':',lw=.9);ax.axhline(.08,color=ORANGE,ls=':',lw=.9)
    ax.set_ylabel('Area fraction');ax.set_ylim(-.05,1.07);ax.legend(ncol=2,fontsize=8.5,loc='lower center',bbox_to_anchor=(.5,1.02))
    ax=axes[2]
    ax.plot(tw,[r['speed_mm_s'] for r in w],color=NAVY,label='Internal',lw=1.5)
    ax.plot(to,[r['observed_speed_mm_s'] if r['observed_speed_mm_s'] is not None else np.nan for r in o],ls='none',marker='o',mfc='none',mec=TEAL,ms=3,label='Observed')
    ax.set_ylabel('Speed / (mm/s)');ax.set_xlabel('Simulation time / s');ax.legend(ncol=2,fontsize=8.5,loc='lower center',bbox_to_anchor=(.5,1.02))
    for ax in axes:
        for t,color in ((.5,GRAY),(.54,GRAY),(data['reference']['confirmed_s'],TEAL)):
            if t is not None:ax.axvline(t,color=color,lw=.7,ls='--',alpha=.7)
        ax.set_xlim(0,3)
    fig.suptitle('SIMULATION',fontsize=11)
    _save(fig,output/'feature_timeline');plt.close(fig)

    fig,ax=plt.subplots(figsize=(7.2,3.8));fig.subplots_adjust(left=.22,right=.96,bottom=.18,top=.9)
    names=('single_confirmation','window_confirmation','spatiotemporal_confirmation','independent_reference')
    labels=('Single frame','Continuous','Spatiotemporal','Reference')
    markers=('o','s','^','D');ref=data['reference']['confirmed_s']
    if ref is not None:ax.axvspan(ref,3,color=TEAL,alpha=.07);ax.axvline(ref,color=TEAL,lw=1,ls='--')
    for y,(name,marker) in enumerate(zip(names,markers)):
        ax.hlines(y,0,3,color='#d7dfe5',lw=.8)
        event=next((r for r in data['events'] if r['event']==name),None)
        if event:
            t=event['time_s'];color=ORANGE if ref is None or t<ref-1e-9 else NAVY
            ax.plot(t,y,marker,color=color,ms=7)
            before=ref is not None and t<ref-1e-9
            ax.text(t-.07 if before else t+.07,y+.28,f'{t:.2f} s',ha='right' if before else 'left',va='center',fontsize=10,color=color)
    ax.set(yticks=range(4),yticklabels=labels,xlim=(0,3),ylim=(3.45,-.45),xlabel='Simulation time / s')
    fig.suptitle('SIMULATION',fontsize=11)
    _save(fig,output/'arrival_timeline');plt.close(fig)
    return keys


def write_player(data,path,figure_directory='figures',map_filename='map_full.pdf'):
    path=Path(path)
    if path.exists():raise FileExistsError(path)
    records=[]
    for i,w in enumerate(data['world']):
        o=_latest_observation(data,w['time_s'])
        records.append(dict(index=i,time_s=w['time_s'],image=f'replay_frames/{i:04d}.png',active=w['active'],
                            world_status=w['world_status'],observation=o,
                            events=[r['event'] for r in data['events'] if r['time_s']<=w['time_s']+1e-9]))
    payload=json.dumps(records,ensure_ascii=False,allow_nan=False)
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>190→191 单步到达识别</title>
<style>body{font:16px "Microsoft YaHei",sans-serif;background:#eef3f7;color:#173a53;margin:24px}main{max-width:1200px;margin:auto;background:white;padding:20px;border-radius:12px}header{display:flex;justify-content:space-between}section{display:grid;grid-template-columns:3fr 1fr;gap:20px}img{width:100%;display:block}button,select{font:inherit;padding:8px;margin:6px}input{width:97%}aside{line-height:1.9}small{font-size:14px;color:#516675}.events{padding-top:10px}</style>
<main><header><b>SIMULATION · 190 → 191</b><span id="time"></span></header><section><img id="scene"><aside><b>液滴／观测</b><div id="info"></div><div class="events" id="events"></div></aside></section>
<input id="seek" type="range" min="0" max="300" value="0" step="1"><div><button id="play">播放</button><button id="pause">暂停</button><button id="prev">上一时刻</button><button id="next">下一时刻</button><select id="speed"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option></select></div>
<small>二维几何运动与合成Mask；不是CFD、真实U-Net或实物实验。轮廓为内部模拟，青色Mask为实际处理观测。逐时刻回放，无插值。<a href="figures/map_full.pdf">完整420地图</a> · <a href="figures/feature_timeline.pdf">特征曲线</a> · <a href="figures/arrival_timeline.pdf">判定时刻</a></small></main>
<script>const frames=__DATA__;let i=0,timer=null;const $=id=>document.getElementById(id);$('seek').max=frames.length-1;
const names={request:'请求191',simulated_applied:'模拟Applied',single_confirmation:'单帧确认',window_confirmation:'连续确认',spatiotemporal_confirmation:'时空确认',independent_reference:'独立参考到达'};
const phases={held_at_source:'保持源区',response_delay:'响应延迟',moving:'迁移',at_target_center:'目标中心保持',blocked_no_overlap:'无交叠，保持'};
function show(){let f=frames[i],o=f.observation;$('scene').src=f.image;$('seek').value=i;$('time').textContent=f.time_s.toFixed(2)+' s';
$('info').innerHTML='等效直径：4.0 mm<br>激活电极：'+f.active+'<br>模型阶段：'+(phases[f.world_status]||f.world_status)+(o?'<br>Mask帧号：'+o.frame_id+'<br>曝光开始：'+o.exposure_start_s.toFixed(2)+' s<br>处理时刻：'+o.processed_at_s.toFixed(2)+' s<br>目标覆盖：'+(100*o.rho_target).toFixed(1)+'%<br>源区残留：'+(100*o.eta_source).toFixed(1)+'%<br>连续证据：'+o.window_count+'帧 / '+o.window_span_s.toFixed(2)+' s':'<br>尚无可用观测');
$('events').textContent=f.events.map(x=>names[x]||x).join(' → ')}
function stop(){clearInterval(timer);timer=null}function play(){stop();if(i===frames.length-1)i=0;timer=setInterval(()=>{if(i<frames.length-1){i++;show()}else stop()},10/Number($('speed').value));show()}
$('play').onclick=play;$('pause').onclick=stop;$('next').onclick=()=>{stop();i=Math.min(i+1,frames.length-1);show()};$('prev').onclick=()=>{stop();i=Math.max(0,i-1);show()};$('seek').oninput=()=>{stop();i=Number($('seek').value);show()};$('speed').onchange=()=>{if(timer)play()};show();</script></html>'''
    path.write_text(html.replace('__DATA__',payload).replace('href="figures/','href="'+figure_directory+'/').replace('map_full.pdf',map_filename),encoding='utf-8')


def export_replay(data,output,ffmpeg):
    output=Path(output);frames=output/'replay_frames';frames.mkdir(exist_ok=False);_style()
    fig,ax=plt.subplots(figsize=(9.6,5.4));fig.subplots_adjust(left=.02,right=.98,bottom=.05,top=.82)
    fig.suptitle('SIMULATION',fontsize=12);_scene_legend(fig)
    for i in range(len(data['world'])):
        ax.clear();_scene(ax,data,i)
        fig.savefig(frames/f'{i:04d}.png',dpi=120)
    plt.close(fig)
    write_player(data,output/'player.html')
    movie=output/'single_step.mp4'
    if movie.exists():raise FileExistsError(movie)
    command=[str(ffmpeg),'-nostdin','-v','error','-framerate','25','-i',str(frames/'%04d.png'),
             '-c:v','h264_mf','-b:v','3500k','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)]
    subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    capture=cv2.VideoCapture(str(movie));count=0
    while True:
        ok,_=capture.read()
        if not ok:break
        count+=1
    fps=capture.get(cv2.CAP_PROP_FPS);capture.release()
    if count!=len(data['world']):raise ValueError('encoded/decoded frame count mismatch')
    return dict(decoded_frames=count,fps=fps,simulation_seconds=3.,playback_seconds=count/fps,
                no_interpolation=True,slow_motion_factor=4,encoder='h264_mf',
                encoder_sha256=hashlib.sha256(Path(ffmpeg).read_bytes()).hexdigest())
