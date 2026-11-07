"""Run only the two explicitly approved development seeds. No formal option."""
import argparse
import json
from pathlib import Path
from dmf.chapter2_geometry_sim.exp1b_random.runner import run_development


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = run_development(args.output, args.config)
    print(json.dumps(dict(method_records=len(records), output=str(args.output.resolve()),
        formal_execution_allowed=False), ensure_ascii=False))


if __name__ == '__main__': main()
