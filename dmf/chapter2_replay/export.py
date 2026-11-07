"""Render an already sealed replay bundle; no model, recognizer or policy calls."""
import argparse
import base64
import csv
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont

from .data import sha,audit_bundle

C=dict(ink='#203448',gray='#6c8293',blue='#176eaa',orange='#d77a20',green='#17826d',purple='#8061a7',red='#b35064')


def load_verified_bundle(root):
    root=Path(root);m=json.loads((root/'source_manifest.json').read_text(encoding='utf-8'))
    if sha(root/'replay_bundle.json')!=m['bundle_sha256']:raise ValueError('sealed bundle hash mismatch')
    b=json.loads((root/'replay_bundle.json').read_text(encoding='utf-8'))
    a=audit_bundle(b,b['source_trial'])
    if not a['passed']:raise ValueError(a)
    return b


@lru_cache(maxsize=32)
def font(size,bold=False):return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',size)


@lru_cache(maxsize=128)
def mask_image(data):return Image.open(BytesIO(base64.b64decode(data.split(',',1)[1]))).convert('L')


def render_snapshot(b,index):
    s=b['ticks'][index];truth=s['truth'];f=s['frame'];w=s['gate'];im=Image.new('RGB',(1600,900),'white');d=ImageDraw.Draw(im)
    def text(t,x,y,size=20,color='ink',bold=False):d.text((x,y),str(t),font=font(size,bold),fill=C.get(color,color),anchor='ls')
    def line(p,color,width=1):d.line(p,fill=C.get(color,color),width=width)
    def dot(x,y,color,r=6):d.ellipse((x-r,y-r,x+r,y+r),fill=C.get(color,color))
    def value(v,n=3):return '—' if v is None else f'{v:.{n}f}'
    text('二维单液滴视觉闭环：持久化日志回放',50,48,30,bold=True);text('SIMULATION',1325,47,25,'blue',True)
    text(b['trial_id'],50,83,18,'gray');text('二维点运动、简化Mask、单位pitch。不是CFD或实物电润湿动力学仿真',50,111,18,'gray')
    line((990,130,990,630),'#c9d7e2');text('任务区域放大图',60,140,23,'blue',True)
    x0,x1,y0,y1=b['viewport'];k=min(860/(x1-x0),355/(y1-y0));X=lambda x:475+(x-(x0+x1)/2)*k;Y=lambda y:355+(y-(y0+y1)/2)*k
    background=im.copy()
    for key,points in b['geometry']['polygons'].items():
        if all(p[0]<x0 or p[0]>x1 or p[1]<y0 or p[1]>y1 for p in points):continue
        n=int(key);p=[(X(x),Y(y)) for x,y in points]
        d.polygon(p,fill='#dceaf4' if n==truth['source'] else '#faead9' if n==truth['target'] else '#f8fafc',outline='#adbfce',width=2)
        if n==truth['world_active']:d.line(p+[p[0]],fill=C['green'],width=4)
        text(key,X(sum(p[0] for p in points)/len(points))-16,Y(min(p[1] for p in points)+.14),18,'gray')
    m=b['masks'].get(s['mask_key']);raw=mask_image(m['data_url']) if m else None
    if s['overlay_valid'] and raw:
        # Crop/nearest-neighbour display only. Original PNG bytes remain in bundle.
        lo=b['geometry']['lower'];scale=b['geometry']['scale']
        crop=raw.crop(((x0-lo[0])*scale,(y0-lo[1])*scale,(x1-lo[0])*scale,(y1-lo[1])*scale))
        ww,hh=round((x1-x0)*k),round((y1-y0)*k);alpha=crop.resize((ww,hh),Image.Resampling.NEAREST).point(lambda v:110 if v>127 else 0)
        rgba=Image.new('RGBA',(ww,hh),(215,122,32,0));rgba.putalpha(alpha)
        im.paste(rgba,(round(X(x0)),round(Y(y0))),rgba)
        if f.get('x') is not None:
            xx,yy=X(f['x']),Y(f['y']);line((xx-7,yy-7,xx+7,yy+7),'orange',3);line((xx-7,yy+7,xx+7,yy-7),'orange',3)
    dot(X(truth['x']),Y(truth['y']),'blue',8)
    map_area=im.crop((48,155,953,565));im.paste(background);im.paste(map_area,(48,155))
    text('x、y单位：pitch，y向下',60,583,17,'gray');dot(65,620,'blue');text('内部模拟位置',82,626,18)
    line((270,614,282,626),'orange',3);line((270,626,282,614),'orange',3);text('观测质心 / 实际Mask',297,626,18)
    line((555,620,590,620),'green',4);text('world.active',605,626,18)
    d.rectangle((815,170,965,320),fill='#f5f8fb')
    if raw:
        lo=b['geometry']['lower'];scale=b['geometry']['scale'];crop=raw.crop(((x0-lo[0])*scale,(y0-lo[1])*scale,(x1-lo[0])*scale,(y1-lo[1])*scale));im.paste(crop.resize((150,150),Image.Resampling.NEAREST),(815,170))
    else:text('无已处理Mask',823,248,16,'gray')
    text('实际Mask（任务ROI）',810,346,15,'gray');text('有效，可叠加' if s['overlay_valid'] else '缺失 / 拒绝，不叠加',810,373,15,'green' if s['overlay_valid'] else 'red')
    text(f"t = {s['time_s']:.2f} s",1030,158,38,'blue',True)
    text(f"任务 {truth['step']+1}/{len(b['config']['environment']['route'])-1}   epoch {truth['epoch']}   {truth['phase']}",1030,203,20)
    text(f"源 {truth['source']}    目标 {truth['target']}    active {truth['world_active']}",1030,244,22)
    colors=dict(Unknown='gray',Moving='blue',Partial='orange',Arrived='green',Stationary='gray',Deviation='red')
    text(s['state'],1030,294,32,colors[s['state']],True);text('当前tick动作：'+s['action'],1255,292,22,bold=True)
    text(f"连续证据：{w.get('window_count',0)} 帧 / {value(w.get('window_duration_s',0))} s",1030,335,21)
    text(f"阶段 {w.get('stage','无当前帧')}   eligible={w.get('eligible','—')}   confirmed={w.get('confirmed','—')}",1030,370,17)
    text(f"η目标 {value(f.get('eta_target') if f else None)}    η源残留 {value(f.get('eta_source') if f else None)}",1030,405,21)
    text(f"相机帧 {f['frame_id']}  处理 {value(f['processing_s'])} s  年龄 {value(s['observation_age_s'])} s" if f else '当前epoch尚无已处理帧',1030,442,17,'gray')
    text(f"曝光结束 {value(f['exposure_s'])} s   可用 {value(f['available_s'])} s" if f else '相机观测缺失，内部点状态仍保留',1030,474,17,'gray')
    text('C0通过：最近已处理有效观测' if s['overlay_valid'] else '观测缺失/拒绝：'+str(w.get('C0_reason') or 'NO_CURRENT_EPOCH_FRAME'),1030,506,17,'green' if s['overlay_valid'] else 'red')
    req=s['last_request'];text(f"最近请求：{req['event'] if req else '—'} @ {value(req['time_s'] if req else None,2)} s",1030,541,19)
    env=b['config']['environment'];text(f"模拟应用延迟 {env['ack_delay_s']}s   响应延迟 {env['response_delay_s']}s",1030,574,17,'gray')
    text(f"world.response_at {value(truth['world_response_at_s'],2)} s",1030,605,17,'gray')
    text(f"本步参考 {value(s['reference']['upper_s'] if s['reference'] else None,2)} s   算法确认 {value(s['confirmation']['time_s'] if s['confirmation'] else None,2)} s",1030,635,17,'purple')
    text('覆盖率 / 液滴面积',60,662,18,bold=True);text('橙：目标覆盖率   蓝：源区残留（定义随步骤切换）',750,663,17,'gray')
    TX=lambda t:130+t/b['times'][-1]*1375
    for v in [0,.5,1]:
        y=680+(1-v)*83;line((130,y,1505,y),'#e2eaf0');text(v,89,y+6,15,'gray')
    for field,color in [('eta_target','orange'),('eta_source','blue')]:
        prev=None
        for f0 in b['processed']:
            v=f0.get(field)
            if v is None:prev=None;continue
            p=(TX(f0['processing_s']),680+(1-v)*83)
            if prev and f0['epoch']==prev[1]['epoch'] and f0['frame_id']==prev[1]['frame_id']+1:line((*prev[0],*p),color,2)
            dot(*p,color,2);prev=(p,f0)
    rows=[('独立参考','purple'),('算法确认','green'),('控制请求','ink'),('模拟Applied','gray')]
    for i,(name,color) in enumerate(rows):text(name,22,788+i*24,16,color)
    for ref in b['references']:dot(TX(ref['upper_s']),782,'purple',4)
    for e in b['events']:
        row=1 if e['event']=='ArrivalEvent' else 3 if e['event']=='Applied' else 2 if e['event'] in ['Prepare','Start','Update','Retry','Recovery','Complete','Stop'] else -1
        if row>=0:dot(TX(e['time_s']),782+row*24,rows[row][1],4)
    line((TX(s['time_s']),675,TX(s['time_s']),865),'red',2)
    for t in np.arange(0,4.01,.5):text(f'{t:.1f}',TX(t)-10,883,14,'gray')
    text('simulation时间 / s',1310,663,15,'gray')
    return im


def encoder_args(encoder):
    if encoder=='libx264':return ['-c:v','libx264','-crf','18']
    if encoder=='h264_mf':return ['-c:v','h264_mf','-b:v','6000000']
    raise ValueError('Only explicitly configured H.264 encoders are supported')


def export(root,ffmpeg,encoder='libx264'):
    options=encoder_args(encoder)
    available=subprocess.check_output([str(ffmpeg),'-hide_banner','-encoders'],stderr=subprocess.STDOUT,text=True,errors='replace')
    if not any(len(line.split())>1 and line.split()[1]==encoder for line in available.splitlines()):raise ValueError('Encoder unavailable: '+encoder)
    root=Path(root);b=load_verified_bundle(root);out=root/'视频与关键帧'
    if out.exists():raise FileExistsError(out)
    out.mkdir();frames=out/'逐帧PNG';frames.mkdir();keys=out/'六张关键帧';keys.mkdir()
    key_times={round(k['time_s'],8):k for k in b['keyframes']};index=[]
    for i,s in enumerate(b['ticks']):
        dest=frames/f'frame-{i:04d}.png';render_snapshot(b,i).save(dest)
        if round(s['time_s'],8) in key_times:
            k=key_times[round(s['time_s'],8)];shutil.copy2(dest,keys/f"{len(list(keys.glob('*.png')))+1:02d}_{s['time_s']:.2f}s.png")
        f=s['frame'];m=b['masks'].get(s['mask_key'])
        index.append(dict(video_frame=i,video_time_s=i/25,simulation_time_s=s['time_s'],trial_id=b['trial_id'],truth_csv_line=s['truth']['csv_line'],frame_csv_line=f['csv_line'] if f else None,frame_id=f['frame_id'] if f else None,state=s['state'],action=s['action'],events_now=json.dumps(s['events_now'],ensure_ascii=False),overlay_valid=s['overlay_valid'],mask_sha256=m['sha256'] if m else None,world_active=s['truth']['world_active'],source=s['truth']['source'],target=s['truth']['target'],epoch=s['truth']['epoch']))
        if i%100==0:print(f'Export {i+1}/{len(b["ticks"])}',flush=True)
    for name,rows in [('frame_index.csv',index),('keyframe_sources.csv',b['keyframes'])]:
        with (out/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    movie=out/'DMF_normal_262000_F_严格回放.mp4'
    subprocess.run([str(ffmpeg),'-nostdin','-v','error','-framerate','25','-i',str(frames/'frame-%04d.png'),*options,'-pix_fmt','yuv420p','-movflags','+faststart',str(movie)],check=True)
    cap=cv2.VideoCapture(str(movie));fps=cap.get(cv2.CAP_PROP_FPS);count=0;shape=None
    while True:
        ok,im=cap.read()
        if not ok:break
        count+=1;shape=im.shape[:2]
    cap.release()
    if count!=len(b['ticks']) or shape!=(900,1600) or fps!=25:raise RuntimeError('MP4 decode check failed')
    report=dict(simulation=True,trial_id=b['trial_id'],bundle_sha256=sha(root/'replay_bundle.json'),exporter_sha256=sha(__file__),encoder=encoder,encoder_arguments=options,encoder_binary_sha256=sha(ffmpeg),new_simulation_runs=0,no_interpolation=True,renderer='Pillow consumes same sealed snapshots as HTML; display renderer differs, data do not',fps=fps,decoded_frames=count,frame_size=[1600,900],keyframes=len(list(keys.glob('*.png'))),playback_duration_s=count/fps,nominal_slow_motion=4,simulation_end_s=b['times'][-1],event_audit=audit_bundle(b,b['source_trial']),files={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()})
    (out/'export_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(str(movie))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--player-root',type=Path,required=True);p.add_argument('--ffmpeg',type=Path,required=True);p.add_argument('--encoder',choices=['libx264','h264_mf'],default='libx264');a=p.parse_args();export(a.player_root,a.ffmpeg,a.encoder)
