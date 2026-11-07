"""Versioned simulation/GT-blind benchmark entry point; no hardware imports."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/chapter2_formal_simulation.yaml')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('smoke', 'formal', 'sensitivity'):
        p = sub.add_parser(command); p.add_argument('--output', required=True)
        if command != 'smoke': p.add_argument('--smoke-manifest', required=True)
    p = sub.add_parser('cache'); p.add_argument('--output', required=True)
    p.add_argument('--scenario', default='normal'); p.add_argument('--seed', type=int, default=260600)
    p = sub.add_parser('run'); p.add_argument('--cache', required=True); p.add_argument('--variant', required=True)
    p.add_argument('--output', required=True)
    p = sub.add_parser('evaluate'); p.add_argument('--prediction', required=True); p.add_argument('--references', required=True)
    p.add_argument('--trial-manifest', required=True); p.add_argument('--output', required=True)
    p.add_argument('--simulation', action='store_true')
    p = sub.add_parser('materials-check'); p.add_argument('--model'); p.add_argument('--human-reference'); p.add_argument('--map')
    args = parser.parse_args(argv)
    if args.command == 'materials-check':
        from dmf.experiment.benchmark import check_real_materials
        print(json.dumps(check_real_materials(model_path=args.model, human_reference_path=args.human_reference,
                                             calibrated_map_path=args.map), indent=2)); return 0
    if args.command == 'run':
        from dmf.experiment.benchmark import run_variant
        result = run_variant(args.cache, args.variant, args.output)
        print(json.dumps({k: v for k, v in result.items() if k not in {'frames', 'events'}}, indent=2)); return 0
    if args.command == 'evaluate':
        from dmf.chapter2_sim.study import evaluate_prediction_file
        result = evaluate_prediction_file(args.prediction, args.references, args.trial_manifest, args.output,
                                          simulation=args.simulation)
        print(json.dumps(result['rates'], indent=2)); return 0
    from dmf.chapter2_sim.config import load_config
    cfg = load_config(args.config)
    if args.command == 'cache':
        from dmf.chapter2_sim.fixed_inputs import generate_fixed_input
        print(json.dumps(generate_fixed_input(cfg, args.scenario, args.seed, args.output), indent=2)); return 0
    from dmf.chapter2_sim.study import run_study
    print(json.dumps(run_study(cfg, args.config, args.command, args.output,
                              smoke_manifest=getattr(args, 'smoke_manifest', None)), indent=2))
    return 0


if __name__ == '__main__': raise SystemExit(main())
