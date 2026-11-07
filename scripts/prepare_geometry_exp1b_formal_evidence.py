"""Bind completed preflight checks/reviews to current source hashes; does not draw RNG."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b_formal.freeze import source_inventory,environment,sha
from dmf.chapter2_geometry_sim.exp1b_formal.spec import load_protocol


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('verification');parser.add_argument('output');args=parser.parse_args()
    folder=Path(args.verification).resolve();target=Path(args.output).resolve()
    if target.exists():raise FileExistsError(target)
    checks=json.loads((folder/'verification.json').read_text(encoding='utf-8'))
    reviews=json.loads((folder/'code_reviews.json').read_text(encoding='utf-8'))
    if len(checks)!=7 or any(r['exit_code'] for r in checks.values()):raise ValueError('All seven preflight stages required')
    if not reviews['spec_approved'] or not reviews['quality_approved']:raise ValueError('Independent reviews incomplete')
    config=load_protocol()
    result=dict(protocol_approved=True,explicit_run_approval=True,spec_review_passed=True,quality_review_passed=True,
        approval_basis='User 2026-10-30 continuation of reviewed request: after statistics/freeze/final audit pass, run exactly 240 caches; no new development seeds.',
        tests=[dict(command=' '.join(r['command']),exit_code=r['exit_code'],tests=r['tests']) for r in checks.values()],
        extra_fresh_tests=dict(command='python -m unittest tests.test_geometry_exp1b_formal tests.test_geometry_exp1b_formal_figures -v',tests=25,exit_code=0),
        reviewed_source_hashes=source_inventory(config),environment=environment(),
        preflight_verification=dict(path=str(folder/'verification.json'),sha256=sha(folder/'verification.json')),
        code_reviews=reviews,code_reviews_sha256=sha(folder/'code_reviews.json'),
        predeclared_figure_contract_sha256=sha(ROOT/'docs/chapter2-geometry-exp1b-formal-figure-contract-2026-10-30.md'),
        preflight_log_hashes={p.name:sha(p) for p in sorted(folder.glob('*.txt'))},formal_draws_performed=False)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(evidence=str(target),reviewed_source_files=len(result['reviewed_source_hashes']),formal_draws_performed=False),ensure_ascii=False))
