"""Regression and immutable-evidence checks; no simulation entry is called."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.analyze_geometry_exp2_outcomes import sha, load, write_json
CHAPTER=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
OLD_PACKET=CHAPTER/'审查材料/2026-10-30_实验二单活动电极闭环机制_Chat审查包_v1'


def guard_old_exp2():
    saved=load(OLD_PACKET/'交付核验与hash封存.json');changed=[]
    for name,digest in saved['packet_artifacts'].items():
        if sha(OLD_PACKET/name)!=digest:changed.append(str(OLD_PACKET/name))
    import csv
    with (OLD_PACKET/'来源与hash索引.csv').open(encoding='utf-8-sig',newline='') as stream:
        sources=list(csv.DictReader(stream))
    for row in sources:
        if sha(row['path'])!=row['sha256']:changed.append(row['path'])
        if row['snapshot_path'] and sha(row['snapshot_path'])!=row['sha256']:changed.append(row['snapshot_path'])
    print(json.dumps(dict(passed=not changed,changed=changed,indexed_sources=len(sources),packet_artifacts=len(saved['packet_artifacts'])),ensure_ascii=False))
    return bool(changed)


def verify(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False);py=sys.executable
    commands=dict(local=[py,'-m','unittest','tests.test_geometry_exp2_faults','tests.test_geometry_exp2_outcomes',
        'tests.test_geometry_exp2_fault_audit','tests.test_geometry_exp2','tests.test_geometry_exp2_audit',
        'tests.test_geometry_exp2_figures','tests.test_geometry_exp1b','tests.test_geometry_exp1b_closeout',
        'tests.test_geometry_exp1b_formal','tests.test_chapter2_evidence','tests.test_chapter2_causality','-v'],
        compile=[py,'-m','compileall','-q','main.py','app_controller.py','controllers','dmf','simulation','validation'],
        diff=['git','diff','--check'], full=[py,'-m','unittest','discover','-s','tests','-v'],
        software_chain=[py,'-m','validation.closed_loop_chain.run_validation'],
        existing_sources=[py,'scripts/protect_geometry_exp1b_formal.py','verify','.planning/geometry_exp2_faults_20261030/before.json'],
        historical_assets=[py,'.planning/geometry_single_step_20261028/protect.py','verify'],
        formal_exp1b_frozen=[py,'scripts/verify_geometry_exp2_mechanisms.py','--guard-only'],
        old_exp2_packet=[py,__file__,'--guard-old-exp2'])
    results={}
    for name,command in commands.items():
        print('Checking '+name,flush=True)
        run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        text=run.stdout+run.stderr;(output/(name+'.txt')).write_text(text,encoding='utf-8')
        count=re.search(r'Ran (\d+) tests?',text)
        results[name]=dict(command=command,exit_code=run.returncode,tests=int(count[1]) if count else None)
        write_json(output/'verification.json',results)
        if run.returncode:
            print(text[-4000:]);raise SystemExit('Verification failed: '+name)
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output');p.add_argument('--guard-old-exp2',action='store_true');a=p.parse_args()
    if a.guard_old_exp2:raise SystemExit(guard_old_exp2())
    if not a.output:p.error('--output required')
    verify(a.output)
