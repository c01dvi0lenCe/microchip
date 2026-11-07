"""One approved B1 replay supplement, not a random or closed-loop batch."""
import argparse
from dmf.chapter2_geometry_sim.exp1b_closeout.run import run_closeout


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run_closeout(a.parent,a.output)
