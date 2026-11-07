"""Read-only simulation audit, writing only new derived check artifacts."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b_closeout.audit import audit_closeout
from dmf.chapter2_geometry_sim.sdf_trial import js
from dmf.chapter2_geometry_sim.single_step import write_csv


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');a=p.parse_args();root=Path(a.root)
    audit=audit_closeout(root);js(root/'closeout_audit.json',audit)
    js(root/'independent_audit.json',audit['core_audit'])
    write_csv(root/'gate_trigger_counts.csv',audit['core_audit']['gate_counts'])
    print(json.dumps({k:v for k,v in audit.items() if k not in ('core_audit','checked_actual_perturbations')},ensure_ascii=False,indent=2))
    if not audit['passed']:raise SystemExit(1)
