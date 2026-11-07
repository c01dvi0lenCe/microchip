"""Hash/audit an existing development packet without executing simulations."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def seal(packet):
    packet = Path(packet).resolve()
    output = packet / '交付核验与hash封存.json'
    if output.exists():
        raise FileExistsError(output)
    with (packet / '来源与hash索引.csv').open(encoding='utf-8-sig', newline='') as stream:
        sources = list(csv.DictReader(stream))
    failures = []
    for row in sources:
        if sha(row['path']) != row['sha256']:
            failures.append('current source changed: ' + row['path'])
        if row['snapshot_path'] and sha(row['snapshot_path']) != row['sha256']:
            failures.append('snapshot changed: ' + row['snapshot_path'])
    checks = load(packet / 'QA/软件回归/verification.json')
    if len(checks) != 8 or any(row['exit_code'] for row in checks.values()):
        failures.append('regression or immutable-data guard failed')
    if load(packet / 'QA/visual_review.json')['verdict'] != 'PASS':
        failures.append('visual review failed')
    for row in load(packet / '图稿/QA/final_check/figure_checks.json'):
        if row['text_exit'] or row['collision_exit'] or row['alignment_exit']:
            failures.append('figure QA failed: ' + row['figure'])
        if sha(packet / '图稿' / (row['figure'] + '.pdf')) != row['pdf_sha256']:
            failures.append('figure changed after QA: ' + row['figure'])
    if load(packet / '图稿/QA/final_check/post_render_regression.json')['exit_code']:
        failures.append('post-render regression failed')
    if not load(packet / '图稿/QA/final_check/counterfactual_audit.json')['passed']:
        failures.append('counterfactual independent check failed')
    if any(row['missing_glyph'] or row['outside'] for row in load(packet / 'QA/text_layout_check.json')):
        failures.append('PDF text layout failed')
    result = dict(passed=not failures, failures=failures,
        indexed_sources=len(sources), source_and_snapshot_hashes_checked=True,
        no_simulation_executed=True, no_commit_or_push=True,
        simulation_scope='Four deterministic normal methods n=1 each plus two World-only timing interventions',
        source=str(Path(__file__).resolve()), source_sha256=sha(__file__),
        packet_artifacts={p.relative_to(packet).as_posix():sha(p) for p in sorted(packet.rglob('*')) if p.is_file()})
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key != 'packet_artifacts'}, ensure_ascii=False, indent=2))
    if failures:
        raise ValueError('delivery verification failed')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('packet')
    seal(parser.parse_args().packet)
