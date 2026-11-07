"""Fresh formal-layer regressions; no research generation or hardware outputs."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.verify_geometry_exp1b import LOCAL


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output');args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    commands={
        'local':[sys.executable,'-m','unittest','tests.test_geometry_exp1b_formal',
            'tests.test_geometry_exp1b_formal_figures','tests.test_geometry_exp1b_random',
            'tests.test_geometry_exp1b_closeout']+['tests.'+name for name in LOCAL]+['-v'],
        'compile':[sys.executable,'-m','compileall','-q','main.py','app_controller.py','controllers','dmf','simulation','validation'],
        'diff':['git','diff','--check'],
        'full':[sys.executable,'-m','unittest','discover','-s','tests','-v'],
        'software_chain':[sys.executable,'-m','validation.closed_loop_chain.run_validation'],
        'source_and_DEV_protection':[sys.executable,'scripts/protect_geometry_exp1b_formal.py','verify',
            '.planning/geometry_exp1b_formal_20261029/before.json'],
        'older_asset_protection':[sys.executable,'.planning/geometry_single_step_20261028/protect.py','verify']}
    summary={}
    for name,command in commands.items():
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        text=result.stdout+result.stderr;(output/(name+'.txt')).write_text(text,encoding='utf-8')
        count=re.search(r'Ran (\d+) tests?',text)
        summary[name]=dict(exit_code=result.returncode,tests=int(count.group(1)) if count else None,command=command)
        (output/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,summary[name],flush=True)
    if any(r['exit_code'] for r in summary.values()):raise SystemExit(1)
