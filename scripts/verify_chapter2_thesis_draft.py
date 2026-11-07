"""Document-only structural, source-byte and rendering-release verification."""
from pathlib import Path
from zipfile import ZipFile
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys

from lxml import etree
from PIL import Image
from chapter2_thesis_evidence import OUT, REPO, S1, ROOT, js, dump, sha

NAME='第二章_单液滴视觉闭环控制_硕士论文工作初稿_v1.docx'

def main():
    doc=OUT/NAME
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'm':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
    with ZipFile(doc) as z:
        tree=etree.fromstring(z.read('word/document.xml'))
        styles=etree.fromstring(z.read('word/styles.xml'))
        text=''.join(tree.xpath('//w:t/text()',namespaces=ns))
        refs=tree.xpath('//w:instrText/text()',namespaces=ns)
        marks=set(tree.xpath('//w:bookmarkStart/@w:name',namespaces=ns))
        expected={f'ch2_fig_{i}' for i in range(1,13)}|{f'ch2_tbl_{i}' for i in range(1,10)}
        assert expected<=marks
        assert not styles.xpath('//w:pBdr',namespaces=ns)
        assert len(tree.xpath('//w:tbl',namespaces=ns))==9
        assert len(tree.xpath('//m:oMath',namespaces=ns))==79
        assert text.count('normal:262000:F:end_to_end')==2
        for bad in ('错误!未找到引用源','Error! Reference source not found','目录字段将在Word更新后显示'):
            assert bad not in text
        media={hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}
        image_identity={p.name:sha(p) in media for p in S1.glob('*.png')}
        assert all(image_identity.values()) and len(image_identity)==2
        assert sum('SEQ EquationCh2' in r for r in refs)==20
        assert sum('SEQ FigureCh2' in r for r in refs)==12
        assert sum('SEQ TableCh2' in r for r in refs)==9
    render=js(OUT/'QA/release_render/word_render_report.json')
    assert render['pages']==27 and render['toc_count']==1 and len(render['headings'])==19
    pages=list((OUT/'QA/release_render').glob('page-*.png'));assert len(pages)==27
    for page in pages:
        with Image.open(page) as im:assert im.width>800 and im.height>1100
    evidence=js(OUT/'source/evidence_snapshot.json')
    source_current={r['id']:Path(r['path']).is_file() and sha(r['path'])==r['sha256'] for r in evidence['evidence']}
    assert all(source_current.values())
    protection=js(OUT/'QA/protection_verification.json');assert protection['passed']
    deps={name:importlib.metadata.version(name) for name in ('python-docx','lxml','Pillow')}
    dump(OUT/'source/dependency_versions.json',dict(python=sys.version,packages=deps,runtime_bundle='26.1025.11240'))
    shutil.copy2(REPO/'scripts/render_chapter2_thesis_word.ps1',OUT/'source/render_chapter2_thesis_word.ps1')
    shutil.copy2(Path(__file__),OUT/'source'/Path(__file__).name)
    delivery_names=(NAME,'第二章_图表与待补实验清单.md','第二章_章节证据对应表.md','第二章_论文初稿生成与更新说明.md')
    result=dict(date='2026-10-26',passed=True,scope='document verification; no algorithm regression or new simulation',
        pages=27,heading_count=19,editable_numbered_equations=20,inline_math=59,editable_tables=9,
        figure_positions=12,inserted_final_s1_images=2,source_evidence_count=len(source_current),
        s1_image_bytes_identical=image_identity,protected_files=protection['protected_count'],protected_changes=0,
        renderer='Microsoft Word 16.0 native export plus bundled Poppler',
        canonical_renderer='attempted; unavailable because soffice.exe absent; did not use installed LibreOffice',
        visual_review='27 pages inspected; final changed pages 24–25 re-inspected, unchanged pages verified by raster hash',
        known_limits=['暂定工科格式，非已核实浙大官方模板','结果分析按用户要求暂缓','没有新真实训练/实物结果'],
        deliveries={n:dict(path=str(OUT/n),sha256=sha(OUT/n),bytes=(OUT/n).stat().st_size) for n in delivery_names},
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        new_research_runs=0,commit_push=False)
    dump(OUT/'QA/render_verification.json',result)
    dump(OUT/'交付清单与验收记录.json',result)
    print(json.dumps({k:result[k] for k in ('passed','pages','heading_count','editable_numbered_equations','editable_tables','source_evidence_count','protected_files','protected_changes','new_research_runs')},ensure_ascii=False))

if __name__=='__main__':main()
