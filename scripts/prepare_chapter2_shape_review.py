"""Prepare an isolated eight-frame human-review package, not a simulation."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.vision.pilot_annotation import PilotWorkspace,prepare_pilot,sha256
from dmf.vision.image_io import read_image,write_image
from dmf.vision.dataset import write_csv_rows

CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
SNAP=CH/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot'
CACHE=CH/'真实分割研究/2026-10-28_视频时间与迁移速度核查_v1'
OUT=CH/'真实分割研究/2026-10-28_单次迁移8帧形态核查_v1'
SELECTED=(665,670,675,680,682,688,698,710)
VIDEO_ID='camera_20261014_112318_257662'


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def js(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def artifact_hash(index,relative_path):
    normalized={str(k).replace('\\','/'):v for k,v in index.items()}
    return normalized[str(relative_path).replace('\\','/')]


def inherit_reviewed_masks(workspace,snapshot):
    """Carry human-approved provenance only after exact pixel/hash checks."""
    snapshot=Path(snapshot)
    originals=rows(snapshot/'samples.csv')
    lookup={(r['parent_video_id'],int(r['source_frame_id'])):r for r in originals}
    staged=[]
    for index,row in enumerate(workspace.rows):
        source=lookup.get((row['parent_video_id'],int(row['source_frame_id'])))
        if source is None or str(source['mask_reviewed']).lower()!='true':continue
        for key,digest in [('frame_path','frame_path_sha256'),('mask_path','mask_path_sha256')]:
            if sha256(snapshot/source[key])!=source[digest]:raise ValueError('original snapshot hash mismatch')
        image,_=workspace.images(index)
        original=read_image(snapshot/source['frame_path'],cv2.IMREAD_COLOR)
        mask=read_image(snapshot/source['mask_path'],cv2.IMREAD_GRAYSCALE)
        if not np.array_equal(image,original):raise ValueError('reviewed frame pixels differ from current ROI')
        if mask is None or mask.shape!=image.shape[:2] or not np.isin(mask,(0,255)).all():
            raise ValueError('reviewed Mask image-domain mismatch')
        staged.append((index,source))
    original_indices={index:source for index,source in staged}
    (workspace.root/'masks_inherited').mkdir(exist_ok=True)
    for index,row in enumerate(workspace.rows):
        row.update(initial_review_origin='automatic_draft_pending_human',inherited_mask_source='',inherited_mask_sha256='',
                   state_gt='Unknown',state_draft='Unknown',state_reviewed=False,
                   source_electrode='',target_electrode='',map_version='')
        if index not in original_indices:
            row.update(mask_path='',working_mask_path='',mask_reviewed=False)
            continue
        source=original_indices[index]
        path=f'masks_inherited/frame_{int(row["source_frame_id"]):04d}.png'
        if (workspace.root/path).exists():raise FileExistsError(workspace.root/path)
        shutil.copyfile(snapshot/source['mask_path'],workspace.root/path)
        row.update(mask_path=path,working_mask_path=path,mask_reviewed=True,
                   initial_review_origin='inherited_previous_human_review_byte_exact',
                   inherited_mask_source=str(snapshot/source['mask_path']),
                   inherited_mask_sha256=source['mask_path_sha256'])
        for key in ('frame_path','mask_path'):
            workspace.data['input_sha256'][str(snapshot/source[key])]=sha256(snapshot/source[key])
    workspace.data['input_sha256'][str(snapshot/'samples.csv')]=sha256(snapshot/'samples.csv')
    workspace.persist()
    return dict(inherited_reviewed=len(staged),pending_review=len(workspace.rows)-len(staged))


def write_preview(workspace,path):
    # Human inspection sheet, not a performance/statistical figure.
    width,height=570,382;canvas=np.full((height*2,width*4,3),255,np.uint8)
    for i,row in enumerate(workspace.rows):
        image,mask=workspace.images(i);panel=image.copy()
        reviewed=bool(row['mask_reviewed']);color=(150,155,0) if reviewed else (30,130,230)
        contours,_=cv2.findContours((mask>0).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(panel,contours,-1,color,2)
        left=(i%4)*width;top=(i//4)*height
        canvas[top+40:top+40+336,left:left+570]=panel
        label=f'Frame {row["source_frame_id"]} | '+('REVIEWED (inherited)' if reviewed else 'PENDING REVIEW')
        cv2.putText(canvas,label,(left+12,top+27),cv2.FONT_HERSHEY_SIMPLEX,.65,(45,60,70),1,cv2.LINE_AA)
    write_image(path,canvas)


def prepare(output=OUT):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    cache=json.loads((CACHE/'manifest.json').read_text(encoding='utf-8'))
    source=Path(cache['source_video']);timestamps=Path(cache['timestamps_path'])
    if sha256(source)!=cache['source_sha256'] or sha256(timestamps)!=cache['timestamps_sha256']:
        raise ValueError('video/timestamp source hash mismatch')
    time_rows=rows(timestamps)
    x,y,w,h=(1566,2760,570,336);start,end=665,710
    duration=float(time_rows[end]['receive_relative_s'])-float(time_rows[start]['receive_relative_s'])
    mean_playback_fps=(end-start)/duration
    output.mkdir(parents=True);dataset=output/'source_dataset';dataset.mkdir()
    (dataset/'frames').mkdir()
    capture=cv2.VideoCapture(str(source));capture.set(cv2.CAP_PROP_POS_FRAMES,start)
    clip=dataset/'candidate_665_710_lossless.avi'
    writer=cv2.VideoWriter(str(clip),cv2.VideoWriter_fourcc(*'FFV1'),mean_playback_fps,(w,h))
    if not writer.isOpened():raise ValueError('lossless writer unavailable')
    expected=[];annotations=[];index=[]
    try:
        for frame_id in range(start,end+1):
            ok,full=capture.read()
            if not ok:raise ValueError('cannot read source frame '+str(frame_id))
            image=full[y:y+h,x:x+w]
            cached=CACHE/'frames'/f'{frame_id:04d}.png'
            if sha256(cached)!=artifact_hash(cache['files'],f'frames/{frame_id:04d}.png'):
                raise ValueError('cached image changed')
            if not np.array_equal(image,read_image(cached,cv2.IMREAD_COLOR)):
                raise ValueError('cache pixels differ from original video')
            writer.write(image);expected.append(image.copy())
            receive=float(time_rows[frame_id]['receive_relative_s'])
            index.append(dict(source_frame_id=frame_id,clip_frame_id=frame_id-start,
                 receive_relative_s=receive,receive_from_first_s=receive-float(time_rows[start]['receive_relative_s']),
                 sdk_frame_number=time_rows[frame_id]['sdk_frame_number'],
                 exposure_timing_verified=False,preview_constant_fps_not_exposure=True))
            if frame_id in SELECTED:
                path=dataset/'frames'/f'frame_{frame_id:04d}.png';shutil.copyfile(cached,path)
                annotations.append(dict(video_id='shape_candidate_f665_710',batch_id='same_acquisition_group_1',
                    frame_id=frame_id-start,timestamp_s=receive,image_path=str(path),
                    source_frame_id=frame_id,roi_x=x,roi_y=y))
    finally:
        writer.release();capture.release()
    check=cv2.VideoCapture(str(clip));decoded=0
    try:
        for image in expected:
            ok,frame=check.read()
            if not ok or not np.array_equal(image,frame):raise ValueError('lossless clip pixel mismatch')
            decoded+=1
        ok,_=check.read()
        if ok:raise ValueError('unexpected extra clip frame')
        encoded_fps=check.get(cv2.CAP_PROP_FPS)
    finally:check.release()
    clips=[dict(clip_id='shape_candidate_f665_710',video_id=VIDEO_ID,batch_id='same_acquisition_group_1',
          source=str(source),source_sha256=sha256(source),start_frame=start,end_frame_exclusive=end+1,
          fps=mean_playback_fps,roi_xywh=[x,y,w,h],path=str(clip),clip_sha256=sha256(clip),
          preview_only=True,ground_truth=False,frame_count=decoded,
          timing_note='Constant mean receive cadence for inspection only; exact receive sidecar saved separately; not exposure.')]
    js(dataset/'clips_manifest.json',clips);write_csv_rows(dataset/'annotations_to_label.csv',annotations)
    write_csv_rows(output/'逐帧来源与接收时间.csv',index)
    prepare_pilot(dataset,output/'review')
    workspace=PilotWorkspace(output/'review')
    inherited=inherit_reviewed_masks(workspace,SNAP)
    if inherited!=dict(inherited_reviewed=4,pending_review=4):raise ValueError('unexpected review count')
    timestamp_lookup={int(r['video_frame_index']):r for r in time_rows}
    metadata=[]
    for row in workspace.rows:
        fid=int(row['source_frame_id']);time=timestamp_lookup[fid]
        row['timestamp_s']=float(time['receive_relative_s']);row['timestamp_source']='host_receive_perf_counter'
        row['receive_from_candidate_start_s']=row['timestamp_s']-float(time_rows[start]['receive_relative_s'])
        row['timing_quality']='host_receive_not_exposure'
        row['notes']=f'原视频帧{fid}；'+('继承原人工审核Mask。' if row['mask_reviewed'] else '草稿待人工核对。')+'仅核对Mask，状态保持Unknown。'
        metadata.append(dict(source_frame_id=fid,clip_frame_id=row['frame_id'],mask_reviewed=row['mask_reviewed'],
            initial_review_origin=row['initial_review_origin'],receive_relative_s=row['timestamp_s'],
            state_gt='Unknown',task_binding_status='candidate_not_image_registered'))
    workspace.data['shape_review_scope']=dict(candidate_direction='386→385 per software log; image check pending',
        source_map_binding_valid=False,source_id_claimed_as_gt=False,arrival_gt_created=False,
        shape_model_created=False,new_simulation_trials=0,independent_acquisition_groups=1,
        exact_timestamp_table=str(output/'逐帧来源与接收时间.csv'),
        requested_human_checks=['four pending Masks','candidate clip direction/completeness'])
    workspace.persist();write_csv_rows(output/'8帧核查清单.csv',metadata)
    write_preview(workspace,output/'8帧核查预览.png')
    pending=[int(r['source_frame_id']) for r in workspace.rows if not r['mask_reviewed']]
    cards=[]
    for row in workspace.rows:
        relative='review/'+row['frame_path'];image,mask=workspace.images(workspace.rows.index(row))
        overlay=image.copy();overlay[mask>0]=(.75*image[mask>0]+.25*np.array([60,190,210])).astype(np.uint8)
        preview=output/'review'/f'preview_f{row["source_frame_id"]}.png';write_image(preview,overlay)
        status='已审核（继承）' if row['mask_reviewed'] else '待人工核对'
        cards.append(f'<article><h3>原视频帧{row["source_frame_id"]} · {status}</h3><img src="review/{preview.name}"><a href="{html.escape(relative)}">原图</a></article>')
    (output/'先看这里.html').write_text('<!doctype html><meta charset="utf-8"><title>8帧形态核查</title><style>body{font:17px Microsoft YaHei,sans-serif;max-width:1400px;margin:30px auto;color:#173a53}main{display:grid;grid-template-columns:1fr 1fr;gap:20px}img{width:100%}article{background:#eef3f7;padding:15px}h3{font-size:18px}</style><h1>单次迁移8帧形态核查</h1><p>待核对原视频帧：670、680、688、698。其余4张沿用已有人工审核。打开“启动Mask核查.cmd”修改/确认并保存；状态保持Unknown，不操作地图。当前仅候选片段，尚无有效视频电极配准。</p><p>以下是准备时静态预览，不会自动反映后续保存；实时状态以标注窗口为准。</p><main>'+''.join(cards)+'</main>',encoding='utf-8')
    launcher=output/'启动Mask核查.cmd'
    launcher.write_text('@echo off\r\nchcp 65001 >nul\r\n'+
        f'"{sys.executable}" "{Path(__file__).resolve()}" review --workspace "%~dp0review"\r\n'+
        'if errorlevel 1 (\r\n echo.\r\n echo 启动失败，请保留此窗口并反馈报错。\r\n pause\r\n)\r\n',encoding='utf-8',newline='')
    readme='''# 八帧核查说明

仅需核对原视频帧670、680、688、698的Mask。665、675、682、710已继承原人工审核Mask，原文件不变。

1. 双击“启动Mask核查.cmd”，默认进入Mask页并定位第一张待核对帧。
2. 核对青色/彩色区域是否完整包含黑色小液滴，特别注意前端、后部和细颈，不把反光、背景和电极纳入。
3. 必要时使用“补液滴/擦除”修正；勾选“Mask已核对”，点击“保存标注”。4张分别保存。
4. 状态保留Unknown，不勾选“状态已核对”，不填写源/目标ID，也不操作地图页。Unknown不影响本次形态Mask审核。
5. 看完整665—710候选片段，判断是否包含一次相邻移动的起点、迁移与恢复；日志提示386→385，但图像对应尚待确认。原713帧已出现额外激活，因此本包不混入717。

查看短片使用按接收平均帧率封装的核查预览；它不是曝光精确计时。原始46帧接收时刻另存CSV。后续用户若补帧，应另核对时间字段，不能用预览fps代替曝光时间。

“先看这里.html”和“8帧核查预览.png”是准备时静态预览，保存后的最新状态以标注窗口和review/annotations.csv为准。

当前为4/8审核Mask、0个状态GT、0个有效视频地图绑定。没有新SDF模型、没有新仿真或正式评价，原18张审核Mask与旧仿真保持原样。
'''
    (output/'核查说明.md').write_text(readme,encoding='utf-8')
    report=workspace.report();audit=workspace.audit_inputs()
    js(output/'准备与验收记录.json',dict(selected_frames=list(SELECTED),pending_frames=pending,
        inherited_frames=[665,675,682,710],candidate_window=[665,710],
        report=report,input_audit=audit,lossless_frames_pixel_equal=decoded,
        receive_duration_s=duration,preview_mean_fps_requested=mean_playback_fps,preview_encoded_fps=encoded_fps,
        simulation_runs=0,state_gt_created=False,source_map_binding=False,
        prepare_script_sha256=sha256(__file__),
        initial_files={p.relative_to(output).as_posix():sha256(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps(dict(output=str(output),report=report,pending=pending,source_pixel_checks=decoded),ensure_ascii=False,indent=2))
    return workspace


def review(workspace,check_ui=False):
    import tkinter as tk
    from tkinter import ttk
    from dmf.vision.pilot_annotation_gui import PilotAnnotationApp
    root=tk.Tk()
    if check_ui:root.withdraw()
    w=PilotWorkspace(workspace);app=PilotAnnotationApp(root,w)
    book=next(c for c in root.winfo_children() if isinstance(c,ttk.Notebook))
    book.select(1)
    index=next((i for i,r in enumerate(w.rows) if not r['mask_reviewed']),0)
    app._load_frame(index)
    if check_ui:
        root.update_idletasks();root.update()
        result=dict(rows=len(app.table.get_children()),selected_original_frame=w.rows[app.index]['source_frame_id'],
                    selected_tab=book.index(book.select()),report=w.report())
        root.destroy();print(json.dumps(result,ensure_ascii=False));return result
    root.mainloop()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','review','check-ui'))
    p.add_argument('--output',type=Path,default=OUT);p.add_argument('--workspace',type=Path,default=OUT/'review')
    args=p.parse_args()
    if args.action=='prepare':prepare(args.output)
    else:review(args.workspace,args.action=='check-ui')
