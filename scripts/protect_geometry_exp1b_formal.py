"""Protect every pre-existing source and completed DEV/r3 artifacts by content."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
CHAPTER=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
DEV=CHAPTER/'仿真结果/2026-10-29_实验一B随机接口_双seed开发_v1'
EXCLUDED=('dmf/chapter2_geometry_sim/exp1b_formal/','tests/test_geometry_exp1b_formal.py',
    'tests/test_geometry_exp1b_formal_figures.py','run_chapter2_geometry_exp1b_formal.py',
    'configs/chapter2_geometry_exp1b_formal_v1.json','.planning/',
    'docs/superpowers/plans/2026-10-29-exp1b-formal-statistics-and-run.md',
    'docs/chapter2-geometry-exp1b-formal-2026-10-29.md',
    'scripts/plot_geometry_exp1b_formal.py','scripts/package_geometry_exp1b_formal.py',
    'scripts/verify_geometry_exp1b_formal.py','scripts/seal_geometry_exp1b_formal.py')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def baseline(path):
    path=Path(path)
    if path.exists():raise FileExistsError(path)
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode('utf-8').split('\0')
    code={str(ROOT/n):sha(ROOT/n) for n in names if n and not n.startswith(EXCLUDED) and (ROOT/n).is_file()}
    old=json.loads((ROOT/'.planning/geometry_exp1b_random_development_20261029/before.json').read_text(encoding='utf-8'))
    frozen=dict(old['frozen'])
    manifest=json.loads((DEV/'manifest.json').read_text(encoding='utf-8'))
    for relative,digest in manifest['artifacts'].items():frozen[str(DEV/relative)]=digest
    for name in ['manifest.json','independent_audit.json']:frozen[str(DEV/name)]=sha(DEV/name)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(code=code,frozen=frozen),ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(source_files=len(code),frozen_files=len(frozen))


def verify(path):
    saved=json.loads(Path(path).read_text(encoding='utf-8'));changed=[]
    for entries in saved.values():
        for p,digest in entries.items():
            if not Path(p).is_file() or sha(p)!=digest:changed.append(p)
    return dict(passed=not changed,changed=changed,source_files=len(saved['code']),frozen_files=len(saved['frozen']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['baseline','verify']);parser.add_argument('path')
    args=parser.parse_args();result=baseline(args.path) if args.mode=='baseline' else verify(args.path)
    print(json.dumps(result,ensure_ascii=False))
    if not result.get('passed',True):raise SystemExit(1)
