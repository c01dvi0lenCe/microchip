"""Read-only native G4 predictions on new real ROIs, never GT or control."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def write_json(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def write_csv(path,rows,fields):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def png(path,image):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    ok,data=cv2.imencode('.png',image)
    if not ok: raise OSError('PNG encode failed')
    Path(path).write_bytes(data.tobytes())


def load_candidates(root):
    root=Path(root).resolve()
    with (root/'annotations.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    seen=set()
    for row in rows:
        sid=row['sample_id']
        if not sid or Path(sid).name!=sid or sid in seen or '/' in sid or '\\' in sid:
            raise ValueError('invalid/duplicate sample ID')
        seen.add(sid)
        p=(root/row['frame_path']).resolve()
        if not p.is_relative_to(root): raise ValueError('image path outside source root')
        if sha(p)!=row['frame_path_sha256']: raise ValueError(f'image hash mismatch: {sid}')
        image=cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if image is None or image.shape[:2]!=(int(row['roi_h']),int(row['roi_w'])):
            raise ValueError(f'native ROI shape mismatch: {sid}')
    return rows


def component_rows(mask,row,method):
    n,_,stats,centroids=cv2.connectedComponentsWithStats((mask>0).astype(np.uint8),8)
    return [dict(sample_id=row['sample_id'],method=method,component_id=i,
        area_px=int(stats[i,cv2.CC_STAT_AREA]),centroid_roi_u_px=float(centroids[i,0]),
        centroid_roi_v_px=float(centroids[i,1]),centroid_full_u_px=float(centroids[i,0])+int(row['roi_x']),
        centroid_full_v_px=float(centroids[i,1])+int(row['roi_y']),
        role='untracked_component_not_task_identity') for i in range(1,n)]


def contact_sheets(output,rows,methods):
    try: font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
    except OSError: font=ImageFont.load_default()
    files=[]
    for start in range(0,len(rows),20):
        page=Image.new('RGB',(1320,2660),'white'); d=ImageDraw.Draw(page)
        d.text((12,8),'REAL IMAGE | MODEL PREDICTION | NO GT | UNREGISTERED',fill='#163B64',font=font)
        for offset,row in enumerate(rows[start:start+20]):
            x=(offset%2)*660; y=40+(offset//2)*260
            d.text((x+4,y),row['sample_id']+' / '+row.get('category',''),fill='black',font=font)
            panels=[output/'originals'/f'{row["sample_id"]}.png']
            panels += [output/'overlays'/m/f'{row["sample_id"]}.png' for m in methods]
            for i,(title,path) in enumerate(zip(['Original']+list(methods),panels)):
                d.text((x+i*220+4,y+24),title,fill='#163B64',font=font)
                if path.exists():
                    with Image.open(path) as raw:
                        image=raw.convert('RGB'); image.thumbnail((212,208))
                        page.paste(image,(x+i*220+(220-image.width)//2,y+48+(208-image.height)//2))
                else: d.text((x+i*220+5,y+90),'FAILED',fill='red',font=font)
        name=f'preview_{start//20+1:02}.png'; page.save(output/name); files.append(name)
    return files


def run_preview(roi_root,output,predictors,provenance=None):
    roi_root=Path(roi_root).resolve(); output=Path(output).resolve()
    if output.exists(): raise FileExistsError('preview output exists; no overwrite')
    if output.is_relative_to(roi_root) or roi_root.is_relative_to(output):
        raise ValueError('output must be separate from source ROI root')
    rows=load_candidates(roi_root)
    protected={str(p):sha(p) for p in roi_root.rglob('*') if p.is_file()}
    for p in (provenance or {}).get('protected_files',[]): protected[str(p)]=sha(p)
    output.mkdir(parents=True)
    scores=[]; components=[]
    for row in rows:
        image=cv2.imdecode(np.frombuffer((roi_root/row['frame_path']).read_bytes(),np.uint8),1)
        png(output/'originals'/f'{row["sample_id"]}.png',image)
        for method,predict in predictors.items():
            record=dict(sample_id=row['sample_id'],method=method,parent_video_id=row['parent_video_id'],
                source_frame_id=row['source_frame_id'],source_sha256=row['source_sha256'],
                roi_x=row['roi_x'],roi_y=row['roi_y'],roi_w=row['roi_w'],roi_h=row['roi_h'],
                timestamp_s=row.get('timestamp_s',''),timestamp_source=row.get('timestamp_source',''),
                category=row.get('category',''),status='failed',error='',foreground_px='',components='',
                mask_sha256='',pipeline_ms='',calibration_status='unbound',gt_used=False)
            try:
                start=time.perf_counter(); mask=predict(image)
                record['pipeline_ms']=(time.perf_counter()-start)*1000
                if mask.shape!=image.shape[:2] or mask.dtype!=np.uint8 or not set(np.unique(mask)).issubset({0,255}):
                    raise ValueError('prediction must be native uint8 0/255 Mask')
                parts=component_rows(mask,row,method); components.extend(parts)
                target=output/'masks'/method/f'{row["sample_id"]}.png'; png(target,mask)
                contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                overlay=image.copy(); cv2.drawContours(overlay,contours,-1,(40,190,20) if method=='unet' else (20,130,230),2)
                png(output/'overlays'/method/f'{row["sample_id"]}.png',overlay)
                record.update(status='predicted',foreground_px=int((mask>0).sum()),components=len(parts),mask_sha256=sha(target))
            except Exception as exc:
                record['error']=f'{type(exc).__name__}: {exc}'
            scores.append(record)
        if len(scores)%40==0: print(f'predictions attempted: {len(scores)}',flush=True)
    write_csv(output/'predictions.csv',scores,list(scores[0]) if scores else ['sample_id'])
    write_csv(output/'components.csv',components,list(components[0]) if components else ['sample_id','method','component_id'])
    write_csv(output/'source_selection.csv',rows,list(rows[0]) if rows else ['sample_id'])
    sheets=contact_sheets(output,rows,tuple(predictors))
    changed=[p for p,h in protected.items() if sha(p)!=h]
    manifest=dict(schema='real_vision_unregistered_preview_v1',simulation=False,planned_samples=len(rows),
        planned_predictions=len(rows)*len(predictors),successful_predictions=sum(r['status']=='predicted' for r in scores),
        failed_predictions=sum(r['status']=='failed' for r in scores),accuracy_evaluated=False,
        calibration_bound=False,arrival_evaluated=False,control_output=False,training_performed=False,
        source_roi_root=str(roi_root),source_sha256=protected,input_changes=changed,read_only_inputs_verified=not changed,
        provenance=provenance or {},script_sha256=sha(__file__),contact_sheets=sheets,
        timing_scope='unwarmed_diagnostic_not_formal_benchmark',
        output_sha256={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()})
    html=['<!doctype html><meta charset="utf-8"><title>真实液滴离线预测</title>',
        '<h1>真实液滴离线预测预览</h1><p>模型预测，未使用GT；尚未绑定电极配准；不控制电极。</p>']
    html += [f'<p><a href="{f}">打开原尺寸第{i+1}页</a></p><img src="{f}" style="width:100%;max-width:1320px">' for i,f in enumerate(sheets)]
    (output/'预览.html').write_text('\n'.join(html),encoding='utf-8')
    manifest['output_sha256']['预览.html']=sha(output/'预览.html')
    write_json(output/'manifest.json',manifest)
    if changed: raise RuntimeError('protected input changed during preview')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roi-root',required=True,type=Path)
    parser.add_argument('--model-run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError('output exists')
    import torch
    from scripts.train_real_segmentation_g4 import build_model
    from scripts.evaluate_real_segmentation_g4 import predict
    cv2.setNumThreads(1); torch.set_num_threads(4)
    torch.backends.cudnn.benchmark=False; torch.backends.cudnn.deterministic=True
    config=json.loads((args.model_run/'frozen_protocol.json').read_text(encoding='utf-8'))
    pretrained=torch.load(args.model_run/'resnet34-b627a593.pth',map_location='cpu',weights_only=True)
    predictors={}; models={}; paths=[args.model_run/'frozen_protocol.json',args.model_run/'resnet34-b627a593.pth']
    for name in ('unet','deeplabv3plus'):
        file=args.model_run/name/'best.pt'; meta=args.model_run/name/'training_manifest.json'
        manifest=json.loads(meta.read_text(encoding='utf-8'))
        if sha(file)!=manifest['best_checkpoint_sha256']: raise ValueError('checkpoint hash mismatch')
        checkpoint=torch.load(file,map_location='cpu',weights_only=False)
        if checkpoint['config_sha256']!=sha(args.model_run/'frozen_protocol.json'): raise ValueError('protocol mismatch')
        model=build_model(name,pretrained).cuda(); model.load_state_dict(checkpoint['model_state'],strict=True); model.eval()
        predictors[name]=lambda image,m=model:predict(m,image,config)
        paths.extend([file,meta]); models[name]=dict(epoch=checkpoint['epoch'],sha256=sha(file))
    result=run_preview(args.roi_root,args.output,predictors,dict(models=models,protected_files=[str(p) for p in paths],
        torch=torch.__version__,gpu=torch.cuda.get_device_name(),preprocessing='unchanged_G4_predict_letterbox_RGB_ImageNet_512_native_restore',
        inference_sha256=sha(ROOT/'scripts/evaluate_real_segmentation_g4.py')))
    print(json.dumps({k:result[k] for k in ('planned_samples','planned_predictions','successful_predictions','failed_predictions','read_only_inputs_verified')},indent=2))


if __name__=='__main__': main()
