"""Final packet hash and fresh local checks; never runs a study entry point."""
import argparse
import csv
import importlib.metadata
import platform
from pathlib import Path
import re
import subprocess
import sys
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.analyze_geometry_exp2_outcomes import load,sha,write_json


def seal(packet):
    packet=Path(packet).resolve();destination=packet/'交付封存与独立核验.json'
    if destination.exists():raise FileExistsError(destination)
    failures=[]
    with (packet/'来源与hash索引.csv').open(encoding='utf-8-sig',newline='') as stream:records=list(csv.DictReader(stream))
    for row in records:
        if sha(row['path'])!=row['sha256']:failures.append('source changed: '+row['path'])
        if row['snapshot_path'] and sha(row['snapshot_path'])!=row['sha256']:failures.append('snapshot changed: '+row['snapshot_path'])
    helper=ROOT/'scripts/audit_geometry_exp2_mechanisms.py'
    if not any(Path(r['path'])==helper for r in records):failures.append('independent reference helper missing from source index')
    verification=load(packet/'QA/软件回归/verification.json')
    if len(verification)!=9 or any(r['exit_code'] for r in verification.values()):failures.append('regression/protection gate failed')
    audit=load(packet/'独立审计/independent_audit.json')
    if not audit['passed'] or audit['checked_masks']!=8000 or audit['source_sha256']!=sha(ROOT/'scripts/audit_geometry_exp2_faults.py'):
        failures.append('final audit is not current')
    for row in load(packet/'图稿/QA/figure_checks.json'):
        if row['text_exit'] or row['collision_exit'] or row['alignment_exit']:failures.append('figure QA failed')
        if row['pdf_sha256']!=sha(packet/'图稿'/(row['figure']+'.pdf')):failures.append('figure modified after QA')
    if any(r['outside'] or r['missing_glyph'] for r in load(packet/'QA/text_layout_check.json')):failures.append('PDF text/clipping failed')
    visual=load(packet/'QA/visual_review.json')
    if visual['verdict']!='PASS' or visual['reviewed_pages']!=list(range(1,9)):failures.append('eight-page visual review incomplete')
    commands=dict(final_local=[sys.executable,'-m','unittest','tests.test_geometry_exp2_faults','tests.test_geometry_exp2_outcomes',
        'tests.test_geometry_exp2_fault_audit','tests.test_geometry_exp2_fault_figures','-v'],
        original_source_guard=[sys.executable,'scripts/protect_geometry_exp1b_formal.py','verify','.planning/geometry_exp2_faults_20261030/before.json'],
        final_compile=[sys.executable,'-m','compileall','-q','dmf/chapter2_geometry_sim/exp2_faults',
            'scripts/analyze_geometry_exp2_outcomes.py','scripts/audit_geometry_exp2_faults.py','scripts/plot_geometry_exp2_faults.py',
            'scripts/package_geometry_exp2_faults.py','scripts/seal_geometry_exp2_faults.py'],
        final_diff=['git','diff','--check'])
    fresh={}
    for name,command in commands.items():
        run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        text=run.stdout+run.stderr;(packet/'QA'/(name+'.txt')).write_text(text,encoding='utf-8')
        match=re.search(r'Ran (\d+) tests?',text)
        fresh[name]=dict(exit_code=run.returncode,tests=int(match[1]) if match else None,command=command)
        if run.returncode:failures.append(name+' failed')
    write_json(packet/'QA/fresh_closeout_verification.json',fresh)
    versions={}
    for name in ('numpy','shapely','opencv-python','matplotlib','reportlab','PyMuPDF'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    write_json(packet/'QA/closeout_environment.json',dict(client_date='2026-11-01',python=platform.python_version(),
        executable=sys.executable,platform=platform.platform(),packages=versions,
        scope='closeout verification environment, not an invented capture-time metadata record'))
    pdf=packet/'实验二_十条异常机制与分列评价_Chat审查报告.pdf'
    with fitz.open(pdf) as document:
        if len(document)!=8:failures.append('unexpected final report page count')
    result=dict(passed=not failures,failures=failures,indexed_sources=len(records),
        actual_new_deterministic_studies=10,new_random_or_formal_studies=0,read_only_old_normal_cases=4,
        checked_visible_masks=8000,original_replaced_masks=28,
        source=str(Path(__file__).resolve()),source_sha256=sha(__file__),report_sha256=sha(pdf),
        new_study_runs_during_seal=0,commit_or_push_executed=False,
        artifacts={p.relative_to(packet).as_posix():sha(p) for p in sorted(packet.rglob('*')) if p.is_file()})
    write_json(destination,result)
    print({k:v for k,v in result.items() if k!='artifacts'})
    if failures:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('packet');seal(p.parse_args().packet)
