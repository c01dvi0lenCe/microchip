"""Local image-review page, not a manuscript quantitative figure."""
import argparse
import csv
from html import escape
import json
from pathlib import Path
from urllib.parse import quote

from .data import sha256


def write_review(results, *, filename='review.html'):
    results = Path(results).resolve()
    if Path(filename).name != filename or not filename.endswith('.html'):
        raise ValueError('review filename must be a local HTML basename')
    target = results / filename
    provenance = results / (filename + '.provenance.json')
    if target.exists() or provenance.exists():
        raise FileExistsError('preserve existing review page')
    manifest_path = results / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for name, digest in manifest['artifacts_sha256'].items():
        if sha256(results / name) != digest:
            raise ValueError(f'input artifact hash mismatch: {name}')
    with (results / 'per_image.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    grouped = {}
    for row in rows:
        grouped.setdefault(row['sample_id'], []).append(row)
    def image(path, label):
        return (f'<figure><figcaption>{escape(label)}</figcaption>'
                f'<a href="{quote(path.replace(chr(92), "/"), safe="/")}">'
                f'<img loading="lazy" src="{quote(path.replace(chr(92), "/"), safe="/")}" alt="{escape(label)}"></a></figure>')
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<title>单液滴分割 Pilot 核对</title>',
             '<style>body{font:16px sans-serif;margin:24px;background:#fff;color:#20252b;max-width:1400px}'
             '.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}'
             'figure{margin:0}img{width:100%;height:200px;object-fit:contain;background:#eee}'
             'figcaption{min-height:40px;font-size:14px}section{border-top:1px solid #bbb;margin-top:24px;padding-top:12px}'
             'h2{font-size:17px}p{line-height:1.6}.notice{background:#fff2cc;padding:12px}'
             '@media(max-width:800px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}</style>',
             '<h1>单液滴分割 Pilot 逐图核对</h1>',
             '<p class="notice">Development Pilot — not a held-out test. '
             '人工审核 Mask 与两种固定参数传统基线对比；不是正式测试结论，未训练 U-Net。'
             'Unknown 状态不参与本页分割评价。点击图片可查看原尺寸。</p>',
             f'<p>data_kind: {escape(manifest["data_kind"])}；样本 {len(grouped)} 张。'
             'GT 只来自已审核清单。所有帧均展示，包括空预测与低得分，不按结果删图。</p>']
    for sample_id, values in grouped.items():
        first = values[0]
        parts.append(f'<section class="sample"><h2>Sample {escape(sample_id)} · '
                     f'{escape(first["parent_video_id"])} · 原视频帧 {escape(first["source_frame_id"])}（从0计数）</h2><div class="grid">')
        parts += [image(first['frame_path'], 'Original — 原始 ROI'), image(first['gt_mask_path'], 'Ground Truth — 人工审核 Mask')]
        for row in values:
            parts.append(image(row['prediction_path'], f'{row["method"]} · Dice {float(row["dice"]):.4f} · detected={row["detected"]}'))
        parts.append('</div></section>')
    parts.append('</html>')
    target.write_text('\n'.join(parts), encoding='utf-8')
    provenance.write_text(json.dumps(dict(source_manifest_sha256=sha256(manifest_path),
                                         review_sha256=sha256(target), renderer_sha256=sha256(Path(__file__)),
                                         purpose='local visual audit, not formal thesis figure'), indent=2), encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    print(write_review(args.results))
