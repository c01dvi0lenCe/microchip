"""Run reviewed real-video segmentation Pilot without hardware or controllers."""
import argparse
import json
from pathlib import Path

from dmf.segmentation_research.evaluation import run_pilot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--groups', type=Path, help='Human-confirmed source hash to chip/session groups')
    parser.add_argument('--config', type=Path, default=Path(__file__).parent / 'configs/chapter2_segmentation_pilot.json')
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if args.groups:
        config['source_groups_path'] = str(args.groups.resolve())
    manifest = run_pilot(args.reviewed, args.output, config)
    print(json.dumps(dict(output=str(args.output), formal_test=False, summary=manifest['summary']),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
