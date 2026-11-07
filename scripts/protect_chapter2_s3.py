"""Snapshot existing code and frozen S1/S2 files without modifying them."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

REPO=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def baseline():
    target=OUT/'QA/protected_before.json'
    if target.exists():raise FileExistsError(target)
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=REPO).decode('utf-8').split('\0')
    files={REPO/n for n in names if n and not n.startswith(('.planning/','dmf/chapter2_sim/s3/')) and (REPO/n).is_file()}
    root=OUT.parent
    for name in ('2026-10-25_S1两张核心图_定稿候选_v1','2026-10-25_S2正式仿真_v1','2026-10-26_S2收尾与S3方案_v1'):
        files.update(p for p in (root/name).rglob('*') if p.is_file())
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({str(p):sha(p) for p in sorted(files)},ensure_ascii=False),encoding='utf-8')
    print('protected',len(files))
def verify():
    files=json.loads((OUT/'QA/protected_before.json').read_text(encoding='utf-8'))
    changed=[name for name,h in files.items() if not Path(name).exists() or sha(Path(name))!=h]
    # Status documentation may be updated only after the protection check.
    result=dict(files=len(files),changes=changed,passed=not changed)
    (OUT/'QA/protection_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(result);assert not changed
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['baseline','verify']);a=p.parse_args()
    baseline() if a.action=='baseline' else verify()
