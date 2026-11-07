"""Rendered publication QA only; does not change plots, data or statistics."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]
SKILL=Path.home()/'.agents/skills/nature-figure/scripts'
NAMES=['Exp1B_formal_1_reference_categories','Exp1B_formal_2_reliability_and_time','Exp1B_formal_3_ablation_and_reference']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('figures');args=parser.parse_args()
    folder=Path(args.figures).resolve();qa=folder/'QA';qa.mkdir(exist_ok=False)
    source=subprocess.run([sys.executable,str(SKILL/'validate_figure.py'),str(ROOT/'scripts/plot_geometry_exp1b_formal.py'),'--json'],
        capture_output=True,text=True,encoding='utf-8',errors='replace')
    (qa/'source_preflight.json').write_text(source.stdout,encoding='utf-8')
    if source.returncode:raise SystemExit('Plot source validation failed')
    checks=[]
    for name in NAMES:
        pdf=folder/(name+'.pdf');alignment=json.loads((folder/(name+'.alignment.json')).read_text(encoding='utf-8'))
        alignment_exit=0 if alignment['auditable'] and alignment['verdict']=='PASS' else 1
        text=subprocess.run([sys.executable,str(SKILL/'audit_pdf_text.py'),str(pdf),'--min-pt','5','--json'],
            capture_output=True,text=True,encoding='utf-8',errors='replace')
        (qa/(name+'_text.json')).write_text(text.stdout,encoding='utf-8')
        collision=subprocess.run([sys.executable,str(SKILL/'audit_figure_collisions.py'),str(pdf),'--json-out',
            str(qa/(name+'_collision.json')),'--overlay-pdf',str(qa/(name+'_collision.pdf'))],
            capture_output=True,text=True,encoding='utf-8',errors='replace')
        (qa/(name+'_collision.txt')).write_text(collision.stdout+collision.stderr,encoding='utf-8')
        with fitz.open(pdf) as document:
            page=document[0]
            if abs(page.rect.width*25.4/72-183)>.05:raise ValueError('Incorrect physical figure width')
            if '\x00' in page.get_text() or '\ufffd' in page.get_text():raise ValueError('Missing scientific figure glyph')
            page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(qa/(name+'_preview.png'))
        checks.append(dict(figure=name,source_exit=source.returncode,alignment_exit=alignment_exit,
            text_exit=text.returncode,collision_exit=collision.returncode))
    (qa/'figure_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    (qa/'source_warning_interpretation.md').write_text(
        '# Source preflight warning interpretation\n\n'
        '- PNG600dpi plus editablePDF/SVG were requested; noTIFF is intentionally supplied.\n'
        '- Forest uncertainty is drawn from frozenCI endpoints as line segments andcaps, not the literalerrorbar API.\n'
        '- Raw paired timing points and conditionalmedianCI are explicit; sensitivitymatrix is descriptive withfullCI sourceCSV.\n'
        '- These notes do not waive renderedtext/collision/alignment failures or replace visualinspection.\n',encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False,indent=2))
    if any(r['alignment_exit'] or r['text_exit'] or r['collision_exit'] for r in checks):raise SystemExit(1)
