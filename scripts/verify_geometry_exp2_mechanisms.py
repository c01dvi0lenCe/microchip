"""Run mechanism regressions and immutable-evidence guards; no study runner."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHAPTER = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
FORMAL = CHAPTER / '仿真结果/2026-10-30_实验一B_正式随机配对_v1'


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def guard():
    manifest = json.loads((FORMAL / 'manifest.json').read_text(encoding='utf-8'))
    freeze = json.loads((FORMAL / 'provenance/freeze.json').read_text(encoding='utf-8'))
    changed = []
    for path, digest in freeze['source_hashes'].items():
        if sha(path) != digest:
            changed.append(path)
    for relative, digest in manifest['artifacts'].items():
        if sha(FORMAL / relative) != digest:
            changed.append(relative)
    result = dict(passed=not changed, changed=changed,
                  frozen_sources=len(freeze['source_hashes']), formal_artifacts=len(manifest['artifacts']))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


def verify(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    py = sys.executable
    commands = {
        'local': [py, '-m', 'unittest', 'tests.test_geometry_exp2',
                  'tests.test_geometry_exp2_audit', 'tests.test_geometry_exp2_figures',
                  'tests.test_geometry_exp1b', 'tests.test_geometry_exp1b_closeout',
                  'tests.test_geometry_exp1b_formal', 'tests.test_chapter2_evidence',
                  'tests.test_chapter2_causality', '-v'],
        'compile': [py, '-m', 'compileall', '-q', 'main.py', 'app_controller.py',
                    'controllers', 'dmf', 'simulation', 'validation'],
        'diff': ['git', 'diff', '--check'],
        'full': [py, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        'software_chain': [py, '-m', 'validation.closed_loop_chain.run_validation'],
        'preexisting_sources_and_DEV': [py, 'scripts/protect_geometry_exp1b_formal.py', 'verify',
                                       '.planning/geometry_exp2_mechanisms_20261030/before.json'],
        'historical_assets': [py, '.planning/geometry_single_step_20261028/protect.py', 'verify'],
        'formal_exp1b_frozen': [py, __file__, '--guard-only'],
    }
    result = {}
    for name, command in commands.items():
        print('Checking ' + name, flush=True)
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace')
        text = completed.stdout + completed.stderr
        (output / (name + '.txt')).write_text(text, encoding='utf-8')
        match = re.search(r'Ran (\d+) tests?', text)
        result[name] = dict(command=command, exit_code=completed.returncode,
                            tests=int(match.group(1)) if match else None)
        (output / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if completed.returncode:
            print(text[-5000:])
            raise SystemExit('Verification failed: ' + name)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard-only', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.guard_only:
        raise SystemExit(guard())
    if not args.output:
        parser.error('--output required')
    verify(args.output)
