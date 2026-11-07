"""Read-only protection and result-integrity checks; writes QA outside old results."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_sim.batch import _write_json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def protect(output):
    files={}
    for folder in ('dmf','controllers','configs','simulation','validation','tests','scripts'):
        for p in (ROOT/folder).rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts or p.suffix not in ('.py','.yaml','.json','.mjs','.ps1','.html'):continue
            rel=p.relative_to(ROOT).as_posix()
            if rel.startswith('dmf/chapter2_sim/s2/') or rel.startswith('tests/test_chapter2_s2_'):continue
            if rel in ('configs/chapter2_s2_arrival.yaml','configs/chapter2_s2_confirmatory.yaml'):continue
            if rel in ('scripts/chapter2_s2_formal_figures.py','scripts/verify_chapter2_s2_formal.py','scripts/package_chapter2_s2_formal.py'):continue
            files[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    for p in ROOT.glob('run_chapter2*.py'):
        if p.name=='run_chapter2_s2.py':continue
        files[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    base=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
    s1root=base/'2026-10-25_S1两张核心图_定稿候选_v1'
    s1={str(p.relative_to(s1root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in s1root.rglob('*') if p.is_file()}
    old={}
    for folder in ('2026-10-21_B1-B4正式算法_v1','2026-10-24_chapter2_sim_v2_E0-E3_v1'):
        for p in (base/folder).rglob('*'):
            if p.is_file():old[str(p)]=[p.stat().st_size,p.stat().st_mtime_ns]
    devroot=base/'2026-10-25_S2开发验收_v1'
    dev={str(p.relative_to(devroot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in devroot.rglob('*') if p.is_file()}
    result=dict(code_files=len(files),code_sha256=digest(files),s1_files=len(s1),s1_sha256=digest(s1),
        frozen_files=len(old),frozen_size_mtime_sha256=digest(old),development_files=len(dev),development_sha256=digest(dev))
    expected=dict(code_files=227,code_sha256='5ff322c851a98fd043bf90ccd2061a8d386c66c12970b9e8f4e417e72925fa63',
        s1_files=116,s1_sha256='9da44db15fdb1a76c2cbb9d57b1ef336b6caac59b5287cd6aaedd06ad251952f',
        frozen_files=82247,frozen_size_mtime_sha256='29b5511096fe190ca3929d0ed3405e2fcad3e568c63a5a4b400ac33cf155c572',
        development_files=4048,development_sha256='209664dc1c6588a4aef3ccf115df12bc2f2097ad169ccf739c5fd35438555570')
    result['all_protected_unchanged']=result==expected
    result['expected']=expected
    _write_json(Path(output),result)
    if not result['all_protected_unchanged']:raise ValueError('protected baseline changed; inspect QA JSON')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    print(json.dumps(protect(parser.parse_args().output),ensure_ascii=False))
