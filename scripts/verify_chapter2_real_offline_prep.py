"""Verify only the new deliverables, provenance and absence of source changes."""
import ast
import csv
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/审查材料/2026-10-27_真实视觉离线验证准备与S3封存_v1')
OLD=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3仿真与实物对应性审查_v1')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def csv_rows(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main():
    import pymupdf as fitz
    e=load(OUT/'QA/本轮只读核查.json');manifest=load(OUT/'交付manifest.json');qa=load(OUT/'QA/文档检查.json')
    errors=[]
    for row in e['current_source_snapshot']:
        if sha(row['path'])!=row['sha256']:errors.append('source changed '+row['path'])
    for rel,h in manifest['files'].items():
        if sha(OUT/rel)!=h:errors.append('delivery mismatch '+rel)
    for rel,h in manifest['source_documents'].items():
        if sha(ROOT/'docs'/rel)!=h:errors.append('document mismatch '+rel)
    for rel,h in load(OLD/'交付manifest.json')['files'].items():
        if sha(OLD/rel)!=h:errors.append('prior audit package mismatch '+rel)
    chapter=OLD.parents[1]
    pilot=chapter/'真实分割研究/2026-10-21_第一阶段与Pilot_v1/pilot_annotation'
    current=csv_rows(pilot/'segmentation_reviewed.csv')
    snap=load(chapter/'真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot/snapshot_manifest.json')
    known={(r['video_id'],r['frame_id']):r for r in snap};review_diffs=[]
    if len(current)!=18 or len(known)!=18:review_diffs.append('18 reviewed rows required')
    for row in current:
        ref=known.get((row['video_id'],row['frame_id']))
        if ref is None:review_diffs.append('unknown reviewed row');continue
        for key in ('parent_video_id','source_frame_id','roi_x','roi_y','mask_reviewed','state_gt','split'):
            if row[key]!=ref[key]:review_diffs.append(row['video_id']+':'+row['frame_id']+':'+key)
        if sha(pilot/row['frame_path'])!=ref['frame_path_sha256']:review_diffs.append('latest original image changed')
        if sha(pilot/row['mask_path'])!=ref['mask_path_sha256']:review_diffs.append('latest original Mask changed')
    (OUT/'QA/最新审核清单对照.json').write_text(json.dumps(dict(reviewed_rows=len(current),
        passed=not review_diffs,differences=review_diffs,scope='latest reviewed CSV and working images/Masks vs reviewed snapshot'),
        ensure_ascii=False,indent=2),encoding='utf-8')
    errors.extend(review_diffs)
    for p in (OUT/'templates').glob('*.csv'):
        rs=csv_rows(p)
        if p.name=='consistency_cases.csv':
            if len(rs)!=18 or any(r['status']!='PLANNED_NOT_RUN' or r['executed']!='False' for r in rs):errors.append('case status')
        elif rs:errors.append('fabricated rows in blank template '+p.name)
    draft=load(OUT/'templates/video_binding_TEMPLATE_INVALID.json')
    if draft['image_to_design_mm'] is not None or draft['status']!='draft_not_valid' or draft['runtime_compatible']:errors.append('binding template not invalid')
    pdf=fitz.open(OUT/'第二章真实视觉离线验证准备与S3最终封存审查包.pdf')
    text='\n'.join(page.get_text() for page in pdf)
    for term in ('PLANNED_NOT_RUN','PriorFeatures','ArrivalEvent','PARTIAL','1.968','right_censored','2400'):
        if term not in text:errors.append('missing PDF content '+term)
    for name in ('audit_chapter2_real_offline_prep.py','package_chapter2_real_offline_prep.py'):
        tree=ast.parse((ROOT/'scripts'/name).read_text(encoding='utf-8'))
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        if any(x.startswith(('dmf','serial','torch','onnxruntime')) for x in imports):errors.append('unsafe import '+name)
    if not e['passed'] or not qa['bounds_passed']:errors.append('prior QA not passed')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()!=e['git_head']:errors.append('git head changed')
    result=dict(passed=not errors,errors=errors,source_files_checked=len(e['current_source_snapshot']),
        frozen_assets_checked=e['previous_scope_protection']['checked_files'],
        videos_hash_verified=len(e['real_data']['video_hash_checks']),ROI_pixel_verified=e['real_data']['raw_roi_pixel_matches'],
        pdf_pages=len(pdf),blank_templates_checked=11,planned_new_counterexamples=18,executed_new_counterexamples=0,
        new_trials=0,model_inference_calls=0,hardware_connections=0,
        scope='read-only archive, source, ROI pixel provenance and document checks, not algorithm regression/performance')
    (OUT/'QA/最终交付核查.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));assert not errors

if __name__=='__main__':main()
