"""Check only the new audit deliverables and unchanged source snapshot."""
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3仿真与实物对应性审查_v1')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    import fitz
    e=json.loads((OUT/'只读审查证据.json').read_text(encoding='utf-8'))
    errors=[]
    for rel,h in e['current_source_sha256'].items():
        if sha(ROOT/rel)!=h:errors.append('source changed: '+rel)
    docs=('chapter2-s3-sim-to-real-contract.md','chapter2-real-experiment-readiness.md')
    for name in docs:
        if sha(ROOT/'docs'/name)!=sha(OUT/name):errors.append('document copy mismatch: '+name)
    manifest=json.loads((OUT/'交付manifest.json').read_text(encoding='utf-8'))
    for rel,h in manifest['files'].items():
        if sha(OUT/rel)!=h:errors.append('delivery hash mismatch: '+rel)
    pdf=fitz.open(OUT/'第二章S3_G3仿真与实物对应性完整审查报告.pdf')
    text='\n'.join(p.get_text() for p in pdf)
    for term in ('227,032','PARTIAL','ArrivalEvent','causality_unknown','1.968','1.620','B_single','right_censored'):
        if term not in text:errors.append('missing PDF content: '+term)
    for name in ('audit_chapter2_sim_to_real.py','package_chapter2_sim_to_real.py'):
        source=(ROOT/'scripts'/name).read_text(encoding='utf-8')
        tree=ast.parse(source)
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        if any(n.startswith(('dmf','serial','torch','onnxruntime')) for n in imports):errors.append('unsafe dependency: '+name)
    result=dict(passed=not errors,errors=errors,current_source_files_checked=len(e['current_source_sha256']),
        prior_frozen_files_checked=e['protected']['checked_files'],pdf_pages=len(pdf),
        copied_documents=2,new_trials=0,hardware_connections=0,
        scope='document, SHA256 and source-isolation checks; not new algorithm regressions')
    (OUT/'QA/最终交付核查.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    assert not errors

if __name__=='__main__':main()
