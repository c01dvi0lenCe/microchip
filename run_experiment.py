"""Chapter 2 CLI; real AM output is disabled unless explicitly configured."""
import argparse
import json
from dmf.experiment.runner import run_experiment


def main(argv=None):
    parser=argparse.ArgumentParser(description='Single-droplet visual closed-loop experiment')
    parser.add_argument('--config',required=True)
    parser.add_argument('--mode',choices=['offline','dry_run','experiment'])
    args=parser.parse_args(argv)
    try:report=run_experiment(args.config,args.mode)
    except (ValueError,OSError,RuntimeError) as exc:parser.exit(2,f'Preflight failed: {exc}\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status'] in {'complete','incomplete'} else 1


if __name__=='__main__':raise SystemExit(main())
