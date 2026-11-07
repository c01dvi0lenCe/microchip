"""Read-only final evidence check and additive delivery seal; never simulate."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def seal(data, output):
    data, output=Path(data).resolve(),Path(output).resolve()
    target=output/'交付manifest.json'
    if target.exists():
        raise FileExistsError('Preserve the existing delivery seal')
    with (output/'来源与hash索引.csv').open(encoding='utf-8-sig',newline='') as stream:
        records=list(csv.DictReader(stream))
    failures=[]
    for record in records:
        for path in [record['path']]+([record['snapshot_path']] if record['snapshot_path'] else []):
            if sha(path)!=record['sha256']:
                failures.append('source_or_snapshot:'+path)
    supplemental=[]
    for rel in ['docs/chapter2-geometry-exp1b-random-development-2026-10-29.md',
                'docs/superpowers/plans/2026-10-29-exp1b-random-development.md',
                'scripts/protect_geometry_exp1b_random.py','scripts/verify_geometry_exp1b_random.py',
                'scripts/seal_geometry_exp1b_random_development.py']:
        source=ROOT/rel; dest=output/'源码与协议快照'/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if sha(dest)!=sha(source):failures.append('supplement_snapshot:'+rel)
        else:shutil.copyfile(source,dest)
        supplemental.append(dict(path=str(source),snapshot=str(dest),sha256=sha(source)))
    pdfs=list(output.glob('*.pdf'))
    if len(pdfs)!=1:raise ValueError('One final report PDF required')
    pdf=pdfs[0]
    with fitz.open(pdf) as document:
        text='\n'.join(page.get_text() for page in document)
        if len(document)!=7:failures.append('expected_seven_pages')
        for token in ['144','1008','4800','28422','268000','268001','980','skipped=1']:
            if token not in text:failures.append('pdf_content:'+token)
    if not (output/'QA/visual_review.md').exists():failures.append('visual_review_record')
    qa=load(output/'QA/text_layout_check.json')
    if len(qa)!=7 or any(r['missing_glyph'] or r['minimum_font_pt']<8.49 for r in qa):
        failures.append('layout_check')
    if any(not (output/'QA'/f'page_{n:02d}.png').exists() for n in range(1,8)):
        failures.append('all_pages_rendered')
    audit=load(data/'independent_audit.json')
    if not audit['passed'] or audit['actual_caches']!=24 or audit['checked_masks']!=4800:
        failures.append('simulation_audit')
    verification=load(output/'QA/verification.json')
    if len(verification)!=7 or any(r['exit_code'] for r in verification.values()):
        failures.append('regression_stages')
    result=dict(passed=not failures,failures=failures,pdf=str(pdf),pdf_sha256=sha(pdf),
        checked_source_records=len(records),supplemental=supplemental,
        manual_visual_review=dict(pages=list(range(1,8)),completed=True,clipping_observed=False),
        actual_development_seeds=[268000,268001],base_worlds=8,shared_caches=24,
        method_records=144,reference_scores=1008,formal_batch_run=False,
        experiment_two_run=False,physical_safety_evaluated=False,
        files={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()})
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','supplemental')},ensure_ascii=False,indent=2))
    if failures:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data');parser.add_argument('output');args=parser.parse_args()
    seal(args.data,args.output)
