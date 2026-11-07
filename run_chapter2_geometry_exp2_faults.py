"""Only the ten declared deterministic development fault cases; no hardware."""
import argparse
from dmf.chapter2_geometry_sim.exp2_faults.runner import run_suite


def main():
    parser=argparse.ArgumentParser(description='SIMULATION: ten fixed fault mechanisms, no random/formal execution')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    run_suite(args.output)


if __name__=='__main__':main()
