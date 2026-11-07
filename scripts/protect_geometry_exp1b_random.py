"""Protect all pre-existing repository sources and frozen r3 content."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
DATA=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-29_实验一B_机制收尾_有效轮廓重放_r3')
EXCLUDE=('dmf/chapter2_geometry_sim/exp1b_random/','tests/test_geometry_exp1b_random.py',
    'run_chapter2_geometry_exp1b_random.py','.planning/','docs/superpowers/plans/2026-10-29-exp1b-random-development.md')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def baseline(output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode('utf-8').split('\0')
    code={str(ROOT/name):sha(ROOT/name) for name in names if name and not name.startswith(EXCLUDE) and (ROOT/name).is_file()}
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    frozen={str(DATA/rel):digest for rel,digest in manifest['artifacts'].items()}
    frozen[str(DATA/'manifest.json')]=sha(DATA/'manifest.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(code=code,frozen=frozen),ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(source_files=len(code),frozen_files=len(frozen))


def verify(output):
    data=json.loads(Path(output).read_text(encoding='utf-8'));changed=[]
    for kind in ('code','frozen'):
        for path,digest in data[kind].items():
            if not Path(path).is_file() or sha(path)!=digest:changed.append(path)
    return dict(passed=not changed,changed=changed,source_files=len(data['code']),frozen_files=len(data['frozen']))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['baseline','verify']);p.add_argument('path');a=p.parse_args()
    r=baseline(a.path) if a.mode=='baseline' else verify(a.path)
    print(json.dumps(r,ensure_ascii=False))
    if not r.get('passed',True):sys.exit(1)
