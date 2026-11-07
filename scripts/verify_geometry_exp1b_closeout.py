"""Fresh regression evidence for the B1 replay supplement."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.verify_geometry_exp1b import LOCAL


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output');a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    commands={'local':[sys.executable,'-m','unittest','tests.test_geometry_exp1b_closeout']+['tests.'+m for m in LOCAL]+['-v'],
        'compile':[sys.executable,'-m','compileall','-q','main.py','app_controller.py','controllers','dmf','simulation','validation'],
        'diff':['git','diff','--check'],'full':[sys.executable,'-m','unittest','discover','-s','tests','-v'],
        'software_chain':[sys.executable,'-m','validation.closed_loop_chain.run_validation'],
        'protect':[sys.executable,'.planning/geometry_single_step_20261028/protect.py','verify']}
    summary={}
    for name,command in commands.items():
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        text=result.stdout+result.stderr;(out/(name+'.txt')).write_text(text,encoding='utf-8');match=re.search(r'Ran (\d+) tests?',text)
        summary[name]=dict(exit_code=result.returncode,tests=int(match.group(1)) if match else None,command=command)
        (out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,summary[name],flush=True)
