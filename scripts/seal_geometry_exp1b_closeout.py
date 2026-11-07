"""Read-only source checks plus an additive delivery seal; no new simulation."""
import csv
from pathlib import Path
import sys
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b.audit import load,sha
from dmf.chapter2_geometry_sim.sdf_trial import js


if __name__=='__main__':
    chapter=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
    data=chapter/'仿真结果/2026-10-29_实验一B_机制收尾_有效轮廓重放_r3'
    out=chapter/'审查材料/2026-10-29_实验一B机制收尾_Chat审查包_v2'
    target=out/'QA/最终交付核验.json'
    if target.exists():raise FileExistsError('do not overwrite a delivery seal')
    failures=[]
    def require(ok,name):
        if not ok:failures.append(name)
    with (out/'来源与hash索引.csv').open(encoding='utf-8-sig',newline='') as stream:records=list(csv.DictReader(stream))
    snapshots=0
    for record in records:
        require(sha(record['path'])==record['sha256'],'source:'+record['path'])
        if record['snapshot_path']:
            snapshots+=1;require(sha(record['snapshot_path'])==record['sha256'],'snapshot:'+record['path'])
    delivery=load(out/'交付manifest.json')
    for name,digest in delivery['files'].items():require(sha(out/name)==digest,'delivery:'+name)
    pdf=Path(delivery['pdf']);require(sha(pdf)==delivery['pdf_sha256'],'pdf_hash')
    with fitz.open(pdf) as doc:
        require(len(doc)==8,'pdf_pages')
        text='\n'.join(page.get_text() for page in doc)
        for token in ['8.12','8.05','8.30','19.2','0.25','96','950']:
            require(token in text,'pdf_content:'+token)
    require(all((out/'QA'/f'page_{n:02d}.png').is_file() for n in range(1,9)),'rendered_all_pages')
    audit=load(data/'closeout_audit.json');require(audit['passed'],'independent_audit')
    require(audit['preserved_old_method_records']==90 and audit['new_B1_method_records']==6,'new_and_reused_counts')
    verification=load(data/'QA/software/verification.json')
    require(len(verification)==6 and all(v['exit_code']==0 for v in verification.values()),'software_verification')
    require(verification['local']['tests']==161 and verification['full']['tests']==950,'test_counts')
    require(all(r['text_exit']==0 and r['collision_exit']==0 for r in load(out/'QA/figure_checks.json')),'final_figure_qa')
    supplemental=[]
    for relative in ['scripts/seal_geometry_exp1b_closeout.py','run_chapter2_geometry_exp1b_closeout.py',
        'docs/chapter2-geometry-exp1b-closeout-2026-10-29.md','docs/superpowers/plans/2026-10-29-exp1b-closeout-replay.md']:
        source=ROOT/relative;snapshot=out/'源码快照'/relative;snapshot.parent.mkdir(parents=True,exist_ok=True)
        if snapshot.exists():require(sha(snapshot)==sha(source),'existing_supplement_snapshot:'+relative)
        else:snapshot.write_bytes(source.read_bytes())
        supplemental.append(dict(source=str(source),snapshot=str(snapshot),sha256=sha(source)))
    result=dict(passed=not failures,failures=failures,pdf=str(pdf),pdf_sha256=sha(pdf),
        checked_source_records=len(records),checked_existing_source_snapshots=snapshots,supplemental_source_snapshots=supplemental,
        manual_visual_review=dict(pages=list(range(1,9)),completed=True,clipping_or_overlap_observed=False),
        new_cache_runs=1,reused_caches=15,method_records=96,formal_batch_run=False,
        physical_control_safety_evaluated=False,simulation_code_or_predictions_changed_during_sealing=False)
    js(target,result)
    print(result,flush=True)
    if failures:raise SystemExit(1)
