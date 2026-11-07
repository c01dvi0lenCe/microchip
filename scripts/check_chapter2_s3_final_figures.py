"""Final figure source, alignment/export/font and collision records."""
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3正式验收与论文图_v1')
S=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")

def main():
    tasks=[('source',[str(S/'validate_figure.py'),str(ROOT/'scripts/plot_chapter2_s3_final.py'),'--json'])]
    for p in sorted((OUT/'figures').glob('*.pdf')):
        tasks += [(p.stem+'_font',[str(S/'audit_pdf_text.py'),str(p),'--json']),
                  (p.stem+'_collision',[str(S/'audit_figure_collisions.py'),str(p),'--json'])]
    results=[]
    for name,args in tasks:
        r=subprocess.run([sys.executable,*args],capture_output=True,encoding='utf-8',errors='replace',env=dict(os.environ,PYTHONIOENCODING='utf-8'))
        (OUT/'QA'/('figure_'+name+'.json')).write_text(r.stdout,encoding='utf-8')
        if r.stderr:(OUT/'QA'/('figure_'+name+'.stderr.log')).write_text(r.stderr,encoding='utf-8')
        results.append(dict(name=name,exit_code=r.returncode))
    (OUT/'QA/figure_checks.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))

if __name__=='__main__':main()
