"""Read-only preservation/provenance checks and final PDF rendering."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import pymupdf


def main(root):
    root=Path(root);protected=json.loads((root/'manifests/protected_inputs.json').read_text(encoding='utf-8'))
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    old=json.loads(Path(protected['inventory_source']).read_text(encoding='utf-8'))
    changed=[n for n,h in protected['files'].items() if not Path(n).exists() or sha(n)!=h]
    inventory=[]
    for n,v in old['frozen_inventory'].items():
        p=Path(n)
        if not p.exists() or [p.stat().st_size,p.stat().st_mtime_ns]!=v:inventory.append(n)
    manifest=json.loads((root/'图稿_交付/figure_manifest.json').read_text(encoding='utf-8'))
    source_changes=[n for n,h in manifest['source_hashes'].items() if sha(n)!=h]
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    preview=root/'pdf_review';preview.mkdir(exist_ok=True)
    doc=pymupdf.open(root/'审查交付_最终/第二章v2_过程图与双层比较协议_审查包.pdf');pages=[]
    for i,p in enumerate(doc):
        p.get_pixmap(matrix=pymupdf.Matrix(1.4,1.4)).save(preview/f'page-{i+1:02d}.png')
        pages.append(dict(page=i+1,characters=len(p.get_text()),width=p.rect.width,height=p.rect.height))
    report=dict(protected_files=len(protected['files']),changed=changed,frozen_v1_inventory=len(old['frozen_inventory']),inventory_check='size_and_mtime_ns_not_full_rehash',inventory_changes=inventory,figure_sources=len(manifest['source_hashes']),source_changes=source_changes,git_head=head,head_unchanged=head==protected['git_head'],new_research_trials=0,formal_E4_E7_scans=0,pdf_pages=pages,passed=not(changed or inventory or source_changes) and head==protected['git_head'])
    (root/'manifests/final_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='pdf_pages'},ensure_ascii=False));print('Rendered PDF pages:',len(pages))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args();main(a.root)
