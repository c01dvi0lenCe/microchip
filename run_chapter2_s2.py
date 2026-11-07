"""Development-only arrival study, no serial/camera/control ownership."""
import argparse
import json

from dmf.chapter2_sim.s2.spec import load_spec
from dmf.chapter2_sim.s2.study import run_development,run_mechanism,audit_development


def build_parser():
    parser=argparse.ArgumentParser(description='SIMULATION S2 development only; no confirmatory scans')
    parser.add_argument('command',choices=('validate-design','mechanism','development','audit'))
    parser.add_argument('--config',default='configs/chapter2_s2_arrival.yaml')
    parser.add_argument('--output')
    parser.add_argument('--study')
    return parser


def main(argv=None):
    parser=build_parser();args=parser.parse_args(argv);spec=load_spec(args.config)
    if args.command=='validate-design':result=dict(valid=True,version=spec.version,formal_runs_authorized=False)
    elif args.command=='audit':
        if not args.study:parser.error('--study required')
        result=audit_development(args.study)
    else:
        if not args.output:parser.error('--output required')
        result=(run_mechanism if args.command=='mechanism' else run_development)(args.output,spec)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(bool(result.get('infrastructure_errors')))


if __name__=='__main__':raise SystemExit(main())
