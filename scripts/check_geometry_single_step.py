"""Audit the saved single-step experiment and its final visualization exports."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.audit import audit_trial

SKILL=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")


def check(root):
    root=Path(root);qa=root/'QA';qa.mkdir(exist_ok=True)
    audit=audit_trial(root/'trial')
    (qa/'independent_audit_final.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    figure_checks=[]
    figure_root=root/'visualization_clean_v2/figures_final'
    for name in ('map_full_clean','static_geometry','movement_keyframes','feature_timeline','arrival_timeline'):
        pdf=figure_root/(name+'.pdf')
        for script,args in (('audit_pdf_text.py',['--min-pt','5']),
                            ('audit_figure_collisions.py',['--json-out',str(qa/(pdf.stem+'_collision.json'))])):
            result=subprocess.run([sys.executable,str(SKILL/script),str(pdf),*args],capture_output=True,text=True,encoding='utf-8')
            (qa/(pdf.stem+'_'+script+'.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
            figure_checks.append(dict(figure=pdf.name,check=script,exit_code=result.returncode))
            print(pdf.name,script,result.returncode)
    manifest=json.loads((root/'trial/manifest.json').read_text(encoding='utf-8'))
    source_changes=[p for p,h in manifest['source_code']['files'].items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    render_manifest=json.loads((root/'visualization_clean_v2/render_manifest.json').read_text(encoding='utf-8'))
    render_changes=[p for p,h in render_manifest['files'].items() if hashlib.sha256((root/'visualization_clean_v2'/p).read_bytes()).hexdigest()!=h]
    result=dict(data_audit=audit,figure_checks=figure_checks,source_changes_since_trial=source_changes,
                visualization_hash_changes=render_changes,movie=render_manifest['movie'],
                passed=audit['passed'] and not source_changes and not render_changes and all(r['exit_code']==0 for r in figure_checks))
    (qa/'delivery_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('passed',result['passed'])
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path)
    result=check(p.parse_args().root)
    raise SystemExit(0 if result['passed'] else 1)
