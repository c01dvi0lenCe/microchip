"""2026-10-27 read-only archive/data audit. No inference or control imports."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
SIM=CH/'仿真结果'
OUT=CH/'审查材料/2026-10-27_真实视觉离线验证准备与S3封存_v1'

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def rows(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def write_csv(name,data):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)

def main():
    if (OUT/'QA/本轮只读核查.json').exists():raise FileExistsError('new output only')
    OUT.mkdir(parents=True,exist_ok=True)
    # Parallel file reads only. Do not call a previous package writer or scorer.
    formal_root=SIM/'2026-10-26_S3正式仿真_v1'
    frozen_index=load(SIM/'2026-10-26_S3正式验收与论文图_v1/QA/formal_frozen_input_index.json')
    expected={str(formal_root/rel):h for rel,h in frozen_index.items()}
    for rel in frozen_index:
        if rel.endswith('trial_manifest.json'):
            p=formal_root/rel
            expected.update({str(p.parent/k):v for k,v in load(p)['files'].items()})
    expected.update(load(SIM/'2026-10-26_S3_G3协议冻结_v1/QA/protected_before.json'))
    def verify_one(item):
        name,h=item;p=Path(name)
        return name if not p.is_file() or sha(p)!=h else None
    changes=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(verify_one,item) for item in expected.items()]
        for i,future in enumerate(as_completed(futures),1):
            mismatch=future.result()
            if mismatch:changes.append(mismatch)
            if i%50000==0:print('parallel protected files checked:',i,flush=True)
    protected=dict(protected=dict(checked_files=len(expected),changed=changes,passed=not changes))
    save('QA/冻结资产只读哈希核查.json',protected)
    assert not changes
    g3=SIM/'2026-10-26_S3_G3协议冻结_v1'
    formal=SIM/'2026-10-26_S3正式仿真_v1'
    final=SIM/'2026-10-26_S3正式验收与论文图_v1'
    admission=load(g3/'S3_G4准入凭证.json');contract=load(g3/'S3_正式冻结协议.json')
    errors=[];links=[]
    def check(path,expected,role):
        digest=sha(path);ok=digest==expected
        links.append(dict(role=role,path=str(path),sha256=digest,expected_sha256=expected,match=ok))
        if not ok:errors.append(role+': '+str(path))
    check(g3/'S3_正式冻结协议.json',admission['contract_sha256'],'G3 contract/admission')
    check(g3/'QA/g3_audit.json',admission['audit_sha256'],'G3 audit/admission')
    for name,h in admission['documents'].items():check(g3/name,h,'G3 document')
    for rel,h in admission['source_hashes'].items():check(ROOT/rel,h,'G3 current source')
    completion=load(formal/'completion_manifest.json')
    if completion['G3_contract_sha256']!=sha(g3/'S3_正式冻结协议.json'):errors.append('G4 completion/G3 hash')
    delivery=load(final/'交付manifest.json')
    for rel,h in delivery['source_data'].items():check(formal/rel,h,'G5 aggregate source')
    check(final/'第二章S3_G3-G5正式验收与图稿审查.pdf',delivery['pdf_sha256'],'G5 report')
    paper=load(final/'figures/figure_sources.json')
    for rel,h in paper['source_files'].items():check(formal/rel,h,'figure aggregate source')
    for rel,h in paper['tables'].items():check(final/'tables'/rel,h,'figure table source')
    for rel,h in paper['trial_files'].items():check(formal/rel,h,'figure trial source')
    check(ROOT/'scripts/plot_chapter2_s3_final.py',paper['plot_script_sha256'],'figure plot source')
    # Figure provenance is archived separately; paths and all actual export hashes are indexed.
    figures=[]
    for p in sorted((final/'figures').iterdir()):
        if p.is_file():figures.append(dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size))
    source_index=[]
    for top in ('dmf','controllers','configs','tests','docs'):
        for p in (ROOT/top).rglob('*'):
            if p.is_file() and p.suffix in ('.py','.yaml','.json','.md'):
                source_index.append(dict(path=str(p),sha256=sha(p)))
    resources=load(CH/'真实分割研究/2026-10-21_第一阶段与Pilot_v1/resource_manifest.json')
    video_hash_checks=[]
    for v in resources['videos']:
        digest=sha(v['source']);ok=digest==v['sha256']
        video_hash_checks.append(dict(path=v['source'],sha256=digest,match=ok))
        if not ok:errors.append('video hash mismatch '+v['video_id'])
    snapshot=CH/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot'
    samples=load(snapshot/'snapshot_manifest.json')
    by_video={r['video_id']:r for r in resources['videos']}
    # Audit exact coordinates and original frame provenance; no segmentation prediction.
    import cv2
    import numpy as np
    roi_rows=[];caps={}
    for r in samples:
        v=by_video[r['parent_video_id']];vid=r['parent_video_id']
        if vid not in caps:caps[vid]=cv2.VideoCapture(v['source'])
        cap=caps[vid];frame_id=int(r['source_frame_id']);cap.set(cv2.CAP_PROP_POS_FRAMES,frame_id)
        ok,frame=cap.read()
        image=cv2.imdecode(np.fromfile(snapshot/r['frame_path'],np.uint8),cv2.IMREAD_COLOR)
        mask=cv2.imdecode(np.fromfile(snapshot/r['mask_path'],np.uint8),cv2.IMREAD_GRAYSCALE)
        x,y=int(r['roi_x']),int(r['roi_y']);w,h=int(r['width']),int(r['height'])
        bounds=ok and x>=0 and y>=0 and x+w<=frame.shape[1] and y+h<=frame.shape[0]
        equal=bool(bounds and image is not None and np.array_equal(frame[y:y+h,x:x+w],image))
        binary=bool(mask is not None and mask.shape==(h,w) and np.isin(mask,(0,255)).all())
        image_hash_ok=sha(snapshot/r['frame_path'])==r['frame_path_sha256']
        mask_hash_ok=sha(snapshot/r['mask_path'])==r['mask_path_sha256']
        row=dict(parent_video_id=vid,source_frame_id=frame_id,roi_x=x,roi_y=y,width=w,height=h,
            coordinate_domain='roi_local_px',resize=False,rotation=False,distortion_correction=False,
            source_video_sha256=v['sha256'],image_path=str(snapshot/r['frame_path']),
            mask_path=str(snapshot/r['mask_path']),image_sha256=r['frame_path_sha256'],
            mask_sha256=r['mask_path_sha256'],mask_reviewed=r['mask_reviewed'],state_gt=r['state_gt'],
            split=r['split'],map_version_recorded=r['map_version'],valid_video_map_binding=False,
            raw_roi_pixels_equal=equal,binary_mask_and_shape_valid=binary,
            image_hash_match=image_hash_ok,mask_hash_match=mask_hash_ok)
        roi_rows.append(row)
        if not equal or not binary or not image_hash_ok or not mask_hash_ok:errors.append('ROI or mask mismatch '+vid+':'+str(frame_id))
    for cap in caps.values():cap.release()
    write_csv('sources/18张审核Mask_ROI与坐标来源核查.csv',roi_rows)
    video_rows=[]
    for v in resources['videos']:
        video_rows.append(dict(video_id=v['video_id'],path=v['source'],sha256=v['sha256'],
            width=v['width'],height=v['height'],frames=v['frames'],fps=v['fps'],
            exposure_timing_verified=v.get('exposure_timing_verified'),
            timing_sidecar_status=v.get('timing_sidecar_status'),
            acquisition_group='user_confirmed_shared_loading_round_1',
            formal_event_labels_available=False,valid_video_map_binding=False))
    write_csv('sources/10段真实视频与绑定状态.csv',video_rows)
    write_csv('sources/S3_G3-G5索引链核查.csv',links)
    write_csv('sources/S3已有图稿导出摘要.csv',figures)
    group_counts=Counter(r['parent_video_id'] for r in samples)
    latest_candidates=[dict(path=str(p),sha256=sha(p),mtime_ns=p.stat().st_mtime_ns)
        for p in (CH/'真实分割研究').rglob('*') if p.is_file() and p.name in
        ('workspace.json','snapshot_manifest.json','segmentation_reviewed.csv','dataset_manifest.csv')]
    baseline=SIM/'2026-10-26_S3仿真与实物对应性审查_v1'
    result=dict(schema='chapter2_real_offline_preparation_read_only_audit_v1',date='2026-10-27',
        passed=not errors,errors=errors,new_simulation_trials=0,inference_calls=0,hardware_connections=0,
        previous_scope_protection=protected['protected'],
        S3=dict(planned=completion['planned'],completed=completion['completed'],steps=completion['planned_steps'],
            cohorts=completion['cohorts'],seed_replacements=completion['seed_replacements'],
            G3_contract_sha256=sha(g3/'S3_正式冻结协议.json'),
            G5_audit_path=str(final/'QA/independent_final_audit.json'),
            G5_audit_sha256=sha(final/'QA/independent_final_audit.json'),
            G5_historical_passed=load(final/'QA/independent_final_audit.json')['passed'],
            figure_sources=paper,figure_export_files=len(figures)),
        real_data=dict(videos=len(video_rows),reviewed_masks=len(roi_rows),independent_acquisition_groups=1,
            video_hash_checks=video_hash_checks,
            masks_per_source_video=dict(group_counts),raw_roi_pixel_matches=sum(r['raw_roi_pixels_equal'] for r in roi_rows),
            binary_mask_shape_checks=sum(r['binary_mask_and_shape_valid'] for r in roi_rows),
            latest_manifest_candidates=sorted(latest_candidates,key=lambda r:r['mtime_ns'],reverse=True)),
        current_source_snapshot=source_index,
        latest_baseline_pdf=dict(path=str(baseline/'第二章S3_G3仿真与实物对应性完整审查报告.pdf'),
            sha256=sha(baseline/'第二章S3_G3仿真与实物对应性完整审查报告.pdf')),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    save('QA/本轮只读核查.json',result)
    print(json.dumps(dict(passed=not errors,errors=errors,S3_records=completion['completed'],
        raw_roi_matches=result['real_data']['raw_roi_pixel_matches'],source_files=len(source_index)),ensure_ascii=False),flush=True)
    assert not errors

if __name__=='__main__':main()
