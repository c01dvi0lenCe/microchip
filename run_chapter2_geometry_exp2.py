"""Run only the declared experiment2 normal development mechanisms."""
import argparse
from dmf.chapter2_geometry_sim.exp2.runner import run_mechanisms


def main():
    parser=argparse.ArgumentParser(description='SIMULATION development only: four normal causal mechanisms, no formal/random execution')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    run_mechanisms(args.output)


if __name__=='__main__':main()
