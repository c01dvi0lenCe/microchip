"""Standalone SIMULATION CLI; never opens serial or a real camera."""
import argparse
import json
from pathlib import Path

from dmf.chapter2_sim.batch import run_batch, run_sensitivity
from dmf.chapter2_sim.config import SCENARIOS, load_config
from dmf.chapter2_sim.runner import run_trial


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/chapter2_simulation.yaml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=20)
    parser.add_argument('--seed-start', type=int, default=260600)
    parser.add_argument('--scenarios', nargs='+', choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument('--sensitivity', action='store_true')
    parser.add_argument('--no-plots', action='store_true')
    args = parser.parse_args(argv)
    if args.seeds < 1 or args.seed_start < 0:
        parser.error('positive seed count and nonnegative seed start required')
    cfg = load_config(args.config)
    seeds = range(args.seed_start, args.seed_start+args.seeds)
    print('MODE=simulation; hardware=disabled; segmentation=synthetic_mask_proxy', flush=True)
    summary = run_batch(cfg, args.scenarios, seeds, args.output)
    sensitivity = []
    if args.sensitivity:
        sensitivity = run_sensitivity(cfg, 'jitter', seeds, [.65, .85, .95], [.25, .4, .6], args.output/'sensitivity')
    if not args.no_plots:
        from dmf.chapter2_sim.plotting import plot_results
        # Predetermined illustrative difficult case, same first paired seed.
        scene = 'partial_stall' if 'partial_stall' in args.scenarios else args.scenarios[0]
        examples = [run_trial(cfg, scene, args.seed_start, method) for method in 'ABC']
        plot_results(cfg, examples, summary, sensitivity, args.output/'figures')
        # Preserve illustrative data as exact raw CSVs through the same exporter.
        run_batch(cfg, [scene], [args.seed_start], args.output/'illustration', bootstrap_repeats=200)
    print(json.dumps({'simulation': True, 'trials': len(args.scenarios)*args.seeds*3,
                      'sensitivity_trials': len(sensitivity)*args.seeds,
                      'output': str(args.output.resolve())}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
