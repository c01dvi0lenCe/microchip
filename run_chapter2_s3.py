"""S3 G0–G2 only: no formal scan or seed override is exposed."""
import argparse
import json
from dmf.chapter2_sim.s3.spec import development_plan
from dmf.chapter2_sim.s3.study import run_development

def main():
    p=argparse.ArgumentParser(description='SIMULATION S3 development only; not physical EWOD or U-Net')
    p.add_argument('action',choices=('plan','development'));p.add_argument('--output')
    a=p.parse_args()
    if a.action=='plan':print(json.dumps(development_plan(),indent=2))
    elif not a.output:p.error('--output requires a new directory')
    else:print(json.dumps(run_development(a.output),indent=2))
if __name__=='__main__':main()
