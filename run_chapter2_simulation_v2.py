"""Research-only E0–E3 entry. No serial, camera SDK or formal scan command."""
import argparse
import json
from pathlib import Path

from dmf.chapter2_sim.v2.spec import load_spec


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('validate','compatibility','smoke','demo','visualize'))
    p.add_argument('--config',default=str(Path(__file__).parent/'configs/chapter2_simulation_v2.yaml'))
    p.add_argument('--output',type=Path)
    p.add_argument('--trial',type=Path)
    p.add_argument('--frozen-dir',type=Path)
    p.add_argument('--ffmpeg',type=Path)
    args=p.parse_args();spec=load_spec(args.config)
    if args.command=='validate':
        from dmf.chapter2_sim.v2.probes import run_probe_matrix
        records=run_probe_matrix(spec);print(json.dumps(dict(mechanism_runs=len(records),all_raw_invariant=all(r['raw_invariant'] for r in records)),indent=2));return
    if args.command=='compatibility':
        from dmf.chapter2_sim.v2.development import run_compatibility
        report=run_compatibility(spec,frozen_dir=args.frozen_dir);print(json.dumps(report,indent=2))
        if not report['all_equal']:raise SystemExit(1)
        return
    if args.output is None:p.error('--output is required and must be a new directory')
    if args.command=='smoke':
        from dmf.chapter2_sim.v2.development import run_smoke
        report=run_smoke(spec,args.output,frozen_dir=args.frozen_dir);print(json.dumps(report,ensure_ascii=False,indent=2));return
    if args.command=='demo':
        from dmf.chapter2_sim.v2.runner import run_trial_v2
        from dmf.chapter2_sim.v2.persistence import save_trial
        trial=run_trial_v2(spec,'normal',262000,'F');save_trial(trial,args.output,spec)
        print(json.dumps(trial.metrics,ensure_ascii=False,indent=2));return
    if args.command=='visualize':
        if args.trial is None:p.error('--trial is required')
        from dmf.chapter2_sim.v2.plotting import make_visualization
        print(make_visualization(args.trial,args.output,ffmpeg=args.ffmpeg))


if __name__=='__main__':main()
