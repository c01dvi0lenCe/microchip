"""Final rendered checks for the two fault mechanism figures."""
import argparse
from pathlib import Path
import subprocess
import sys
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.analyze_geometry_exp2_outcomes import load,sha,write_json
SKILL=Path.home()/'.agents/skills/nature-figure/scripts'
NAMES=('Exp2_fault_1_causal_trajectories','Exp2_fault_2_outcome_separation')


def check(folder):
    folder=Path(folder).resolve();qa=folder/'QA';qa.mkdir(exist_ok=False);results=[]
    for name in NAMES:
        pdf=folder/(name+'.pdf')
        commands=dict(text=[str(SKILL/'audit_pdf_text.py'),str(pdf),'--min-pt','5','--json'],
            collision=[str(SKILL/'audit_figure_collisions.py'),str(pdf),'--json-out',str(qa/(name+'.collision.json')),
                '--overlay-pdf',str(qa/(name+'.collision.pdf'))])
        row=dict(figure=name,pdf_sha256=sha(pdf))
        for key,args in commands.items():
            run=subprocess.run([sys.executable,*args],capture_output=True,text=True,encoding='utf-8')
            (qa/(name+'.'+key+'.txt')).write_text(run.stdout+run.stderr,encoding='utf-8');row[key+'_exit']=run.returncode
        row['alignment_exit']=0 if load(folder/(name+'.alignment.json'))['verdict']=='PASS' else 1
        with fitz.open(pdf) as document:
            for i,page in enumerate(document):page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),alpha=False).save(qa/f'{name}.page_{i+1}.png')
        results.append(row)
    source=subprocess.run([sys.executable,str(SKILL/'validate_figure.py'),str(ROOT/'scripts/plot_geometry_exp2_faults.py'),'--json'],capture_output=True,text=True,encoding='utf-8')
    (qa/'source_preflight.json').write_text(source.stdout+source.stderr,encoding='utf-8')
    regression=subprocess.run([sys.executable,'-m','unittest','tests.test_geometry_exp2_fault_figures','tests.test_geometry_exp2_fault_audit',
        'tests.test_geometry_exp2_outcomes','tests.test_geometry_exp2_faults','-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (qa/'final_additional_regression.txt').write_text(regression.stdout+regression.stderr,encoding='utf-8')
    write_json(qa/'final_additional_regression.json',dict(exit_code=regression.returncode,source_sha256=sha(ROOT/'scripts/plot_geometry_exp2_faults.py')))
    write_json(qa/'figure_checks.json',results);print(results)
    if regression.returncode or any(r['text_exit'] or r['collision_exit'] or r['alignment_exit'] for r in results):raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('figures');check(p.parse_args().figures)
