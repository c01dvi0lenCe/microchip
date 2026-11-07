"""Capture regression output outside protected G0-G2 data."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G3协议冻结_v1/QA')
COMMANDS={
    'local':[sys.executable,'-m','unittest','discover','-s','tests','-p','test_chapter2_s3*.py','-v'],
    'full':[sys.executable,'-m','unittest','discover','-s','tests','-v'],
    'compile':[sys.executable,'-m','compileall','-q','main.py','app_controller.py','controllers','dmf','simulation','validation','run_chapter2_s3_formal.py'],
    'chain':[sys.executable,'-m','validation.closed_loop_chain.run_validation'],
    'diff':['git','diff','--check']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('kind',choices=COMMANDS);a=p.parse_args();start=time.perf_counter()
    r=subprocess.run(COMMANDS[a.kind],capture_output=True,encoding='utf-8',errors='replace',env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    text=r.stdout+'\n'+r.stderr;OUT.mkdir(parents=True,exist_ok=True)
    (OUT/(a.kind+'_final_verification.log')).write_text(text,encoding='utf-8')
    m=re.search(r'Ran (\d+) tests?',text)
    result=dict(passed=r.returncode==0,exit_code=r.returncode,tests=int(m[1]) if m else None,elapsed_s=time.perf_counter()-start)
    (OUT/(a.kind+'_final_verification.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result));print(text[-1200:]);sys.exit(r.returncode)
