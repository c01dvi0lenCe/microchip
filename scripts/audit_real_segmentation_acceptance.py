"""Read-only acceptance of human semantic masks; no model or control runs."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil
import sys
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.vision.image_io import read_image,write_image
from dmf.segmentation_research.data import sha256,write_csv


def inspect_pixels(image,mask,ignore):
    if image is None or image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3:
        raise ValueError('image must be native uint8 BGR')
    for value in [mask,ignore]:
        if value is None or value.dtype!=np.uint8 or value.ndim!=2 or value.shape!=image.shape[:2] or not np.isin(value,[0,255]).all():
            raise ValueError('semantic/ignore must be binary native same-size uint8')
    valid=ignore==0
    if not valid.any():raise ValueError('no evaluable pixels; not an empty-background sample')
    fg=((mask>0)&valid).astype(np.uint8)
    n,labels,stats,_=cv2.connectedComponentsWithStats(fg,connectivity=8)
    return dict(width=image.shape[1],height=image.shape[0],raw_foreground_px=int((mask>0).sum()),
        valid_foreground_px=int(fg.sum()),valid_px=int(valid.sum()),ignore_px=int((~valid).sum()),
        foreground_ignore_overlap_px=int(((mask>0)&(~valid)).sum()),components=n-1,
        tiny_components_lt16px=int(sum(stats[1:,cv2.CC_STAT_AREA]<16)),
        tiny_foreground_px=int(sum(stats[1:,cv2.CC_STAT_AREA][stats[1:,cv2.CC_STAT_AREA]<16])),
        foreground_touches_roi_edge=bool(fg[0].any() or fg[-1].any() or fg[:,0].any() or fg[:,-1].any()))


def split_structure(rows):
    seen={};leaks=[]
    for row in rows:
        identities=[('video',row['parent_video_id']),('hash',row['source_sha256']),('operation',row['operation_group'])]
        if row.get('instance_id_draft'):identities.append(('local_track',row['parent_video_id'],row['instance_id_draft']))
        for key in identities:
            old=seen.setdefault(key,row['proposed_split'])
            if old!=row['proposed_split']:leaks.append(str(key))
    return dict(leaks=sorted(set(leaks)),video_operation_local_track_disjoint=not leaks,
        independent_capture_groups_verified=False,cross_video_lineage_verified=False,
        protocol='same_day_video_disjoint_internal_validation_proposal_only')


def json_write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def overlay_image(image,mask,ignore):
    result=image.copy()
    selected=ignore>0
    result[selected]=(.75*result[selected]+.25*np.array([195,55,170])).astype(np.uint8)
    contours=cv2.findContours((mask>0).astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]
    cv2.drawContours(result,contours,-1,(40,255,70),2)
    return result


def make_sheets(snapshot,rows,output):
    output.mkdir()
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
    for page,start in enumerate(range(0,len(rows),15),1):
        sheet=Image.new('RGB',(1500,1050),'white');draw=ImageDraw.Draw(sheet)
        for j,row in enumerate(rows[start:start+15]):
            image=read_image(snapshot/row['frame_path'],cv2.IMREAD_COLOR)
            mask=read_image(snapshot/row['mask_path'],cv2.IMREAD_UNCHANGED)
            ignore=read_image(snapshot/row['exclusion_mask_path'],cv2.IMREAD_UNCHANGED)
            view=Image.fromarray(cv2.cvtColor(overlay_image(image,mask,ignore),cv2.COLOR_BGR2RGB));view.thumbnail((288,288))
            x,y=(j%5)*300,(j//5)*350
            sheet.paste(view,(x+(300-view.width)//2,y))
            draw.text((x+8,y+294),f'{row["sample_id"]}  有效前景{row["valid_foreground_px"]}px',font=font,fill='#183f60')
            draw.text((x+8,y+320),f'连通域{row["components"]} / 微小{row["tiny_components_lt16px"]}',font=font,fill='#7b4a36')
        sheet.save(output/f'标注核对_{page:02d}.jpg',quality=96)


def audit(workspace,output):
    if output.exists():raise FileExistsError('acceptance output must be new')
    workspace=workspace.resolve();raw=(workspace/'workspace.json').read_bytes()
    data=json.loads(raw.decode('utf-8'));rows=data['rows']
    if len(rows)!=180:raise ValueError('expected the declared180 rows')
    protected={str(workspace/'workspace.json'):sha256(workspace/'workspace.json')}
    for name in ['annotations.csv','segmentation_reviewed.csv','instances_to_review.csv']:
        protected[str(workspace/name)]=sha256(workspace/name)
    output.mkdir(parents=True);snapshot=output/'reviewed_snapshot';snapshot.mkdir()
    (snapshot/'images').mkdir();(snapshot/'semantic_masks').mkdir();(snapshot/'ignore_masks').mkdir()
    result=[];source_errors=[]
    for path,digest in data['input_sha256'].items():
        if sha256(path)!=digest:source_errors.append(path)
    seen=set()
    for row in rows:
        entry=dict(row);issues=[]
        for flag in ['mask_reviewed','boundary_reviewed','exclusion_reviewed']:
            if row.get(flag) is not True:issues.append(flag+'_not_true')
        roi=row['roi_xywh'];identity=(row['source_sha256'],row['source_frame_id'],tuple(roi))
        if identity in seen:issues.append('duplicate_source_frame_roi')
        seen.add(identity)
        if roi!=[row[k] for k in ['roi_x','roi_y','width','height']]:issues.append('ROI_metadata_conflict')
        for field,folder in [('frame_path','images'),('mask_path','semantic_masks'),('exclusion_mask_path','ignore_masks')]:
            src=workspace/row[field];digest=sha256(src);protected[str(src)]=digest
            if field=='frame_path' and digest!=row['frame_path_sha256']:issues.append('original_crop_hash_mismatch')
            dest=snapshot/folder/(row['sample_id']+'.png');shutil.copyfile(src,dest)
            if sha256(dest)!=digest:raise ValueError('snapshot copy changed bytes')
            entry['original_'+field]=str(src);entry[field]=dest.relative_to(snapshot).as_posix();entry[field+'_sha256']=digest
        image=read_image(snapshot/entry['frame_path'],cv2.IMREAD_COLOR)
        mask=read_image(snapshot/entry['mask_path'],cv2.IMREAD_UNCHANGED)
        ignore=read_image(snapshot/entry['exclusion_mask_path'],cv2.IMREAD_UNCHANGED)
        try:entry.update(inspect_pixels(image,mask,ignore))
        except ValueError as exc:issues.append(str(exc))
        entry.update(mechanical_issues=';'.join(issues),mechanical_pass=not issues,
            visual_acceptance='pending_technical_visual_review',training_released=False,
            instances_available=row.get('instances_reviewed') is True and bool(row.get('instance_mask_path')),
            task_electrode_identity='recorded_log_and_candidate_registration_no_manual_ID_required',
            target_coverage_metric_status='candidate_registration_only_not_final_metrology')
        result.append(entry)
    groups=split_structure(rows)
    write_csv(snapshot/'samples.csv',result)
    write_csv(output/'G1_180张逐样本技术验收.csv',result)
    write_csv(output/'G2_180张完整分组清单_未放行.csv',[dict(sample_id=r['sample_id'],
        parent_video_id=r['parent_video_id'],source_sha256=r['source_sha256'],source_frame_id=r['source_frame_id'],
        operation_group=r['operation_group'],video_qualified_draft_track=(r['parent_video_id']+':'+r['instance_id_draft']) if r['instance_id_draft'] else '',
        capture_group=r['capture_group'],capture_group_confirmed=r['capture_group_confirmed'],
        proposed_split=r['proposed_split'],actual_split='unassigned',training_released=False,
        mechanical_pass=r['mechanical_pass'],reference_snapshot='reviewed_snapshot/samples.csv') for r in result])
    for split in ['train','val']:
        write_csv(output/f'G2_{split}_候选清单_未放行.csv',[r for r in result if r['proposed_split']==split])
    summary=dict(schema='real_roi_G1_G2_acceptance_v1',simulation=False,images=len(rows),
        reviewed_semantic_masks=sum(r['mask_reviewed'] is True for r in rows),
        reviewed_boundaries=sum(r['boundary_reviewed'] is True for r in rows),
        reviewed_exclusions=sum(r['exclusion_reviewed'] is True for r in rows),
        mechanical_pass=sum(r['mechanical_pass'] for r in result),
        empty_valid_masks=sum(r.get('valid_foreground_px')==0 for r in result),
        nonzero_ignore_masks=sum(r.get('ignore_px',0)>0 for r in result),
        samples_with_tiny_components=sum(r.get('tiny_components_lt16px',0)>0 for r in result),
        samples_touching_roi_edge=sum(r.get('foreground_touches_roi_edge',False) for r in result),
        instance_annotations_reviewed=sum(r.get('instances_reviewed') is True for r in rows),
        proposed_split_counts=dict(Counter(r['proposed_split'] for r in rows)),
        source_hash_errors=source_errors,groups=groups,
        visual_review_status='pending',training_released=False,models_trained=0,
        formal_test_samples=0,protected_input_count=len(protected),independent_batch_count='unknown_not_4')
    json_write(output/'技术验收汇总.json',summary)
    json_write(output/'输入保护hash.json',protected)
    make_sheets(snapshot,result,output/'visual_review')
    changed=[p for p,h in protected.items() if sha256(p)!=h]
    if changed:raise ValueError('inputs changed during acceptance: '+str(changed))
    json_write(output/'输入只读核验.json',dict(files=len(protected),all_unchanged=True,changes=[]))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();audit(a.workspace,a.output)
