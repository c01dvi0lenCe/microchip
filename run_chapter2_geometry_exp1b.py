"""Only the predeclared deterministic experiment1B mechanism set."""
import argparse
from dmf.chapter2_geometry_sim.exp1b.generate import run_development


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--reuse-normal-from',help='reuse completed persisted normal world after a recorded failed preparation')
    args=parser.parse_args()
    results=run_development(args.output,args.reuse_normal_from)
    if any(r['status']!='executed' for r in results):raise SystemExit(1)
