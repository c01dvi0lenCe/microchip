"""S3 fixed G3-gated formal batch, no seed or parameter overrides."""
import argparse
import json
from dmf.chapter2_sim.s3_final.study import formal_plan,run_formal

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('plan','run'));p.add_argument('--output');a=p.parse_args()
    if a.mode=='plan':print(json.dumps(formal_plan(),ensure_ascii=False,indent=2))
    elif not a.output:p.error('--output required')
    else:print(run_formal(a.output))
