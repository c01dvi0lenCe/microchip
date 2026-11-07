"""Freeze, run exactly once, or independently audit experiment-one-B formal data."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    freeze=commands.add_parser('freeze');freeze.add_argument('--output',type=Path,required=True)
    freeze.add_argument('--verification',type=Path,required=True);freeze.add_argument('--config',type=Path)
    run=commands.add_parser('run');run.add_argument('--freeze',type=Path,required=True)
    run.add_argument('--output',type=Path,required=True);run.add_argument('--config',type=Path)
    audit=commands.add_parser('audit');audit.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.command=='freeze':
        from dmf.chapter2_geometry_sim.exp1b_formal.freeze import create_freeze
        print(create_freeze(args.output,args.verification,args.config))
    elif args.command=='run':
        from dmf.chapter2_geometry_sim.exp1b_formal.runner import run_formal
        run_formal(args.output,args.freeze,args.config)
    else:
        from dmf.chapter2_geometry_sim.exp1b_formal.audit import audit_formal
        result=audit_formal(args.output)
        (args.output/'independent_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
