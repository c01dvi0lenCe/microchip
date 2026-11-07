"""Read-only exported figure QA; never invokes simulation."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1')
SKILL=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")

def main():
    checks=[]
    targets=[('source',[str(SKILL/'validate_figure.py'),str(ROOT/'scripts/plot_chapter2_s3_development.py'),'--json'])]
    for p in sorted((OUT/'figures').glob('*.pdf')):
        targets.extend([(p.stem+'_font',[str(SKILL/'audit_pdf_text.py'),str(p),'--json']),
                        (p.stem+'_collision',[str(SKILL/'audit_figure_collisions.py'),str(p),'--json'])])
    for name,args in targets:
        r=subprocess.run([sys.executable,*args],capture_output=True,encoding='utf-8',errors='replace',
                         env=dict(os.environ,PYTHONIOENCODING='utf-8'))
        (OUT/'QA'/f'figure_{name}.json').write_text(r.stdout,encoding='utf-8')
        if r.stderr:(OUT/'QA'/f'figure_{name}.stderr.log').write_text(r.stderr,encoding='utf-8')
        checks.append(dict(name=name,exit_code=r.returncode))
    (OUT/'QA/figure_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))

if __name__=='__main__':main()
