"""Additive final delivery seal: verify existing evidence only, never simulate."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def seal(data, output):
    data, output = Path(data).resolve(), Path(output).resolve()
    target = output / '交付manifest.json'
    if target.exists():
        raise FileExistsError('Keep existing delivery seal')
    failures = []
    with (output / '来源与hash索引.csv').open(encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    for row in records:
        paths = [row['path']] + ([row['snapshot_path']] if row['snapshot_path'] else [])
        for path in paths:
            if sha(path) != row['sha256']:
                failures.append('source_or_snapshot:' + path)
    supplemental = []
    for relative in [
        'scripts/check_geometry_exp1b_formal_figures.py',
        'scripts/seal_geometry_exp1b_formal.py',
        'scripts/protect_geometry_exp1b_formal.py',
        'scripts/verify_geometry_exp1b_formal.py',
        'scripts/prepare_geometry_exp1b_formal_evidence.py',
        'docs/chapter2-geometry-exp1b-formal-closeout-2026-10-30.md',
    ]:
        source = ROOT / relative
        dest = output / '源码与协议' / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if sha(dest) != sha(source):
                failures.append('supplement_snapshot:' + relative)
        else:
            shutil.copyfile(source, dest)
        supplemental.append(dict(path=str(source), snapshot=str(dest), sha256=sha(source)))
    audit = load(data / 'independent_audit.json')
    if (not audit['passed'] or audit['actual_base_worlds'] != 80 or audit['actual_caches'] != 240
            or audit['checked_masks'] != 48000 or audit['planned_method_records'] != 1440
            or audit['reference_scores'] != 10080):
        failures.append('formal_raw_audit')
    manifest = load(data / 'manifest.json')
    if manifest['formal_batch_count'] != 1 or manifest['actual_formal_seeds'] != list(range(266000, 266020)):
        failures.append('exact_formal_batch_identity')
    verification = load(output / 'QA/软件回归/verification.json')
    if len(verification) != 7 or any(x['exit_code'] for x in verification.values()):
        failures.append('software_verification')
    figure_checks = load(output / '图稿/QA/figure_checks.json')
    if len(figure_checks) != 3 or any(x['alignment_exit'] or x['text_exit'] or x['collision_exit'] for x in figure_checks):
        failures.append('figure_checks')
    if not (output / 'QA/visual_review.md').exists():
        failures.append('manual_visual_review')
    pdfs = list(output.glob('*.pdf'))
    if len(pdfs) != 1:
        raise ValueError('Exactly one review report required')
    pdf = pdfs[0]
    layout = load(output / 'QA/text_layout_check.json')
    with fitz.open(pdf) as document:
        if len(layout) != len(document):
            failures.append('page_qa_count')
        text = '\n'.join(page.get_text() for page in document)
        for token in ['1440', '10080', '48000', '266000', '266019', '1005', '240']:
            if token not in text:
                failures.append('report_token:' + token)
        for number, row in enumerate(layout, 1):
            if row['missing_glyph'] or row['min_font_pt'] < 7.9:
                failures.append('page_glyph_or_font:' + str(number))
            if not (output / 'QA' / f'page_{number:02d}.png').exists():
                failures.append('page_not_rendered:' + str(number))
    result = dict(
        passed=not failures, failures=failures, report=str(pdf), report_sha256=sha(pdf),
        checked_source_records=len(records), supplemental=supplemental,
        formal_seeds=list(range(266000, 266020)), formal_batch_count=1,
        actual_base_worlds=80, actual_caches=240, method_records=1440,
        reference_scores=10080, checked_masks=48000, new_experiment_two_runs=0,
        physical_safety_evaluated=False,
        files={p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file()},
    )
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('files', 'supplemental', 'formal_seeds')}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data')
    parser.add_argument('output')
    args = parser.parse_args()
    seal(args.data, args.output)
