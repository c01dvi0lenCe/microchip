"""Read-only saved-output checks and QA exports; never runs a World or controller."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path.home() / '.agents/skills/nature-figure/scripts'
NAMES = ('Exp2_mechanism_1_closed_loop', 'Exp2_mechanism_2_timing_counterfactual')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def check_counterfactuals(folder, output):
    manifest = load(folder / 'manifest.json')
    from shapely.geometry import Polygon
    electrode_map = load(manifest['inputs']['map_path'])
    target = next(e for e in electrode_map['electrodes'] if e['control_id'] == 192)
    cx, cy = Polygon(target['polygon_map_mm']).centroid.coords[0]
    failures = []
    def require(ok, message):
        if not ok:
            failures.append(message)
    for name, digest in manifest['artifacts'].items():
        require(sha(folder / name) == digest, 'artifact hash: ' + name)
    for name, digest in manifest['source_code'].items():
        require(sha(name) == digest, 'source hash: ' + name)
    require(sha(manifest['script']) == manifest['script_sha256'], 'runner hash')
    details = []
    traces = {}
    for case in manifest['cases']:
        name = case['case']; trace = rows(folder / name / 'world.csv')
        events = load(folder / name / 'events.json')
        traces[name] = trace
        requests = [event for event in events if event['event'] == 'request']
        applied = [event for event in events if event['event'] == 'simulated_applied']
        expected = [(191, .5), (192, case['request_192_s'])]
        require(len(trace) == 2001, name + ' fixed observation horizon')
        require(len(requests) == len(applied) == 2, name + ' transaction count')
        for event, (target, request_time) in zip(requests, expected):
            require(int(event['target']) == target and abs(event['time_s'] - request_time) < 1e-9,
                    name + ' predeclared request')
        for event, (target, request_time) in zip(applied, expected):
            require(int(event['target']) == target and abs(event['time_s'] - request_time - .04) < 1e-9,
                    name + ' actual Applied delay')
        blocked = [row for row in trace if row['world_status'] == 'blocked_no_overlap']
        require(len(blocked) == case['blocked_ticks'], name + ' blocked count')
        final_distance = ((float(trace[-1]['x_mm'])-cx)**2 + (float(trace[-1]['y_mm'])-cy)**2)**.5
        require(abs(final_distance-case['final_distance_to_192_mm']) < 1e-10,
                name + ' final distance recomputed from Gerber design')
        for previous, current in zip(trace, trace[1:]):
            if current['world_status'] == 'blocked_no_overlap':
                require(abs(float(previous['x_mm'])-float(current['x_mm'])) < 1e-10 and
                        abs(float(previous['y_mm'])-float(current['y_mm'])) < 1e-10,
                        name + ' movement while no-overlap blocked')
        details.append(dict(case=name, world_ticks=len(trace), request_count=len(requests),
                            applied_count=len(applied), blocked_ticks=len(blocked),
                            actual_events=events))
    # Same inputs before the predeclared intervention, different trajectories afterwards.
    require(all(a == b for a, b in zip(traces['early'][:81], traces['late'][:81])),
            'World-only common prefix before 0.80 s')
    require(traces['early'][-1]['x_mm'] != traces['late'][-1]['x_mm'], 'trajectory did not diverge')
    result = dict(passed=not failures, failures=failures, cases=details,
                  world_or_controller_called=False, source_sha256=sha(__file__))
    (output / 'counterfactual_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if failures:
        raise ValueError(failures)


def main(figures, counterfactuals, qa_subdir='QA'):
    figures, counterfactuals = Path(figures).resolve(), Path(counterfactuals).resolve()
    qa = figures / qa_subdir
    qa.mkdir(parents=True, exist_ok=False)
    check_counterfactuals(counterfactuals, qa)
    results = []
    for name in NAMES:
        pdf = figures / (name + '.pdf')
        text = subprocess.run([sys.executable, str(SKILL / 'audit_pdf_text.py'), str(pdf), '--min-pt', '5', '--json'], capture_output=True, text=True, encoding='utf-8')
        (qa / (name + '.text.json')).write_text(text.stdout + text.stderr, encoding='utf-8')
        collision = subprocess.run([sys.executable, str(SKILL / 'audit_figure_collisions.py'), str(pdf),
            '--json-out', str(qa / (name + '.collision.json')),
            '--overlay-pdf', str(qa / (name + '.collision.pdf'))], capture_output=True, text=True, encoding='utf-8')
        (qa / (name + '.collision.txt')).write_text(collision.stdout + collision.stderr, encoding='utf-8')
        alignment = load(figures / (name + '.alignment.json'))
        alignment_exit = 0 if alignment['verdict'] == 'PASS' else 1
        with fitz.open(pdf) as document:
            for i, page in enumerate(document):
                page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False).save(qa / f'{name}.page_{i+1}.png')
        results.append(dict(figure=name, text_exit=text.returncode, collision_exit=collision.returncode,
                            alignment_exit=alignment_exit, pdf_sha256=sha(pdf)))
    source_check = subprocess.run([sys.executable, str(SKILL / 'validate_figure.py'),
        str(ROOT / 'scripts/plot_geometry_exp2_mechanisms.py'), '--json'], capture_output=True, text=True, encoding='utf-8')
    (qa / 'figure_source_preflight.json').write_text(source_check.stdout + source_check.stderr, encoding='utf-8')
    regression = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_geometry_exp2_figures', '-v'],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    (qa / 'post_render_regression.txt').write_text(regression.stdout + regression.stderr, encoding='utf-8')
    (qa / 'post_render_regression.json').write_text(json.dumps(dict(exit_code=regression.returncode,
        source_sha256=sha(ROOT / 'scripts/plot_geometry_exp2_mechanisms.py')), indent=2), encoding='utf-8')
    (qa / 'figure_checks.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))
    if any(row['text_exit'] or row['collision_exit'] or row['alignment_exit'] for row in results):
        raise ValueError('figure QA failed; preserve these files and correct layout only')
    if regression.returncode:
        raise ValueError('post-render helper regression failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('figures'); parser.add_argument('counterfactuals')
    parser.add_argument('--qa-subdir', default='QA', help='New QA directory; existing records are never overwritten')
    args = parser.parse_args(); main(args.figures, args.counterfactuals, args.qa_subdir)
