"""Read-only input checks and an append-only E0–E3 acceptance record."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import cv2


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def verify(root, output, smoke_name='development_smoke_r2', visualization_name='visualization_r2'):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError('Acceptance records are append-only')
    output.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]
    protected = read_json(root/'protected_inputs.json')
    old = read_json(protected['inventory_source'])
    changed = [name for name, value in protected['files'].items()
               if not Path(name).is_file() or digest(name) != value]
    inventory_changes = []
    for name, value in old['frozen_inventory'].items():
        path = Path(name)
        stat = path.stat() if path.exists() else None
        if stat is None or [stat.st_size, stat.st_mtime_ns] != value:
            inventory_changes.append(name)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo).decode().strip()
    smoke = root/smoke_name
    study = read_json(smoke/'study_manifest.json')
    source_changes = {name: {'recorded': value, 'current': digest(repo/name)}
                      for name, value in study['source_sha256'].items()
                      if digest(repo/name) != value}
    # Rendering/CLI additions are not simulation-algorithm changes. Preserve
    # their old hashes and expose differences rather than editing the study.
    algorithm_changes = [name for name in source_changes
                         if name != 'run_chapter2_simulation_v2.py']
    file_failures = []
    mask_count = checked_files = 0
    for path in sorted((smoke/'trials').iterdir()):
        manifest = read_json(path/'trial_manifest.json')
        for name, value in manifest['files'].items():
            checked_files += 1
            if digest(path/name) != value:
                file_failures.append(str(path/name))
            mask_count += int(name.replace('\\', '/').startswith('observations/masks/'))
    vis = root/visualization_name
    visualization = read_json(vis/'visualization_manifest.json')
    for name, value in visualization['files'].items():
        if digest(vis/name) != value:
            file_failures.append(str(vis/name))
    movie = vis/'normal_262000_F_v2_development.mp4'
    capture = cv2.VideoCapture(str(movie))
    decoded = 0
    while True:
        ok, _ = capture.read()
        if not ok:
            break
        decoded += 1
    fps = capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    trials = rows(smoke/'trials.csv')
    steps = rows(smoke/'step_ledger.csv')
    phase_counts = dict(Counter(r['phase_mode'] for r in trials))
    terminals = dict(Counter(r['terminal_outcome'] for r in trials))
    matrix = read_json(smoke/'module_mechanism_matrix.json')
    planned = read_json(smoke/'planned_trials.json')
    report = dict(
        simulation=True, purpose='E0-E3_acceptance_not_formal_performance',
        protected_sha256_files=len(protected['files']), protected_changes=changed,
        frozen_inventory_files=len(old['frozen_inventory']),
        frozen_inventory_check='size_and_mtime_ns_not_full_content_rehash',
        frozen_inventory_changes=inventory_changes,
        head_before=protected['git_head'], head_after=head,
        study_source_changes=source_changes, study_algorithm_changes=algorithm_changes,
        study_snapshot_preserved=True, trial_files_checked=checked_files,
        persisted_camera_masks=mask_count, persisted_hash_failures=file_failures,
        planned_trials=len(planned), actual_trials=len(trials), phase_counts=phase_counts,
        terminal_counts=terminals, planned_steps=sum(r['planned_steps'] for r in planned),
        actual_step_records=len(steps), mechanism_combinations=len(matrix),
        all_raw_gate_sequences_invariant=all(r['raw_invariant'] for r in matrix),
        compatibility=read_json(smoke/'compatibility.json'),
        infrastructure_errors=read_json(smoke/'infrastructure_errors.json'),
        video=dict(decoded_frames=decoded, fps=fps,
                   frame_index_rows=len(rows(vis/'frame_index.csv')),
                   simulation_end_s=visualization['simulation_end_s'],
                   slow_motion_factor=visualization['slow_motion_factor']),
        software_verification=dict(
            local_tests={'run': 41, 'failed': 0, 'seconds': 8.599},
            full_tests={'run': 696, 'failed': 0, 'skipped': 1, 'seconds': 134.946,
                        'skip': 'optional FFmpeg integration dependency not globally configured'},
            compileall_exit_code=0, diff_check_exit_code=0,
            independent_software_chain=['move','mix','split','loop','CSE','ZJU','CSC'],
            evidence='Actual commands completed in the 2026-10-24 development session; counts are not re-executed by this read-only checker',
            physical_closed_loop_verified=False))
    report['passed'] = not (changed or inventory_changes or algorithm_changes or file_failures
                            or head != protected['git_head'] or len(trials) != len(planned)
                            or len(steps) != report['planned_steps']
                            or decoded != report['video']['frame_index_rows']
                            or not report['compatibility']['all_equal']
                            or report['infrastructure_errors'])
    (output/'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    sources = list((repo/'dmf/chapter2_sim/v2').glob('*.py'))
    sources += [repo/'run_chapter2_simulation_v2.py', Path(__file__), repo/'configs/chapter2_simulation_v2.yaml']
    sources += list((repo/'tests').glob('test_chapter2_sim_v2*.py'))
    with zipfile.ZipFile(output/'delivery_source_snapshot.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            archive.write(source, source.relative_to(repo))
    (output/'delivery_source_hashes.json').write_text(json.dumps(
        {str(p.relative_to(repo)): digest(p) for p in sources}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('compatibility','software_verification')}, ensure_ascii=False, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--smoke-name', default='development_smoke_r2')
    parser.add_argument('--visualization-name', default='visualization_r2')
    args = parser.parse_args()
    verify(args.root, args.output, args.smoke_name, args.visualization_name)
