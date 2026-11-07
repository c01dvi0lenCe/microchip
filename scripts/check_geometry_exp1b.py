"""Independent saved-data audit; does not execute simulation or recognition."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b.audit import audit_development
from dmf.chapter2_geometry_sim.sdf_trial import js
from dmf.chapter2_geometry_sim.single_step import write_csv


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root');args=parser.parse_args()
    root=Path(args.root);result=audit_development(root)
    js(root/'independent_audit.json',result);write_csv(root/'gate_trigger_counts.csv',result['gate_counts'])
    print(json.dumps({k:v for k,v in result.items() if k!='gate_counts'},ensure_ascii=False,indent=2))
    if not result['passed']:raise SystemExit(1)
