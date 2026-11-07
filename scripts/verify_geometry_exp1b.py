"""Persist fresh software checks; no algorithm research trials."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
LOCAL=['test_geometry_exp1b','test_shape_sequence_sdf','test_shape_review_package','test_pilot_annotation',
    'test_geometry_normal_speed','test_geometry_single_step','test_chapter2_geometry_sim',
    'test_video_geometry_estimate','test_video_speed_check','test_chapter2_causality','test_chapter2_evidence',
    'test_electrode_design_map','test_segmentation_research']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output');parser.add_argument('--full',action='store_true');args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    commands={'local':[sys.executable,'-m','unittest']+['tests.'+m for m in LOCAL]+['-v'],
        'compile':[sys.executable,'-m','compileall','-q','main.py','app_controller.py','controllers','dmf','simulation','validation'],
        'diff':['git','diff','--check'],
        'protect':[sys.executable,'.planning/geometry_single_step_20261028/protect.py','verify'],
        'software_chain':[sys.executable,'-m','validation.closed_loop_chain.run_validation']}
    if args.full:commands['full']=[sys.executable,'-m','unittest','discover','-s','tests','-v']
    summary={}
    for name,command in commands.items():
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        text=result.stdout+result.stderr;(out/(name+'.txt')).write_text(text,encoding='utf-8')
        match=re.search(r'Ran (\d+) tests?',text)
        summary[name]=dict(exit_code=result.returncode,tests=int(match.group(1)) if match else None,command=command)
        (out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,summary[name],flush=True)
