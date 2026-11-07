"""Persist fresh verification output; never invokes research scans."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1/QA')
COMMANDS={
    'local':[sys.executable,'-m','unittest','discover','-s','tests','-p','test_chapter2_s3*.py','-v'],
    'full':[sys.executable,'-m','unittest','discover','-s','tests','-v'],
    'compile':[sys.executable,'-m','compileall','-q','main.py','app_controller.py','controllers','dmf','simulation','validation'],
    'chain':[sys.executable,'-m','validation.closed_loop_chain.run_validation'],
    'diff':['git','diff','--check'],
}
def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=COMMANDS);a=p.parse_args()
    env=dict(os.environ,PYTHONIOENCODING='utf-8');t=time.perf_counter()
    r=subprocess.run(COMMANDS[a.kind],cwd=ROOT,env=env,capture_output=True,encoding='utf-8',errors='replace')
    text=r.stdout+'\n'+r.stderr;OUT.mkdir(parents=True,exist_ok=True)
    (OUT/f'{a.kind}_verification.log').write_text(text,encoding='utf-8')
    m=re.search(r'Ran (\d+) tests?',text)
    data=dict(kind=a.kind,command=COMMANDS[a.kind],exit_code=r.returncode,elapsed_s=time.perf_counter()-t,
              tests=int(m[1]) if m else None,passed=r.returncode==0,log=f'{a.kind}_verification.log')
    (OUT/f'{a.kind}_verification.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False));print(text[-1800:]);sys.exit(r.returncode)
if __name__=='__main__':main()
