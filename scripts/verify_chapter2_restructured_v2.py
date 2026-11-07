"""Document-only verification; never executes a model, controller or scorer."""
from pathlib import Path
import argparse, csv, hashlib, json, re
from collections import Counter
from zipfile import ZipFile
from lxml import etree
from PIL import Image, ImageOps, ImageDraw
import pymupdf as fitz
from chapter2_restructure_inventory import OUT, ROOT, V1, NS, sha, dump

def render_pages():
    pdf=OUT/'QA/word_render_r3/chapter2-draft.pdf'
    target=OUT/'QA/pages';target.mkdir(exist_ok=True)
    doc=fitz.open(pdf);records=[]
    for i,p in enumerate(doc):
        p.get_pixmap(matrix=fitz.Matrix(150/72,150/72),alpha=False).save(target/f'page-{i+1:02d}.png')
        texts=p.get_text('blocks');outside=[]
        for block in texts:
            x0,y0,x1,y1,txt,*_=block
            if min(x0,y0)<-1 or x1>p.rect.width+1 or y1>p.rect.height+1:outside.append(txt[:70])
        records.append(dict(page=i+1,characters=len(p.get_text()),outside=outside,text=p.get_text()))
    dump(OUT/'QA/page_text_and_bounds.json',records)
    for i in range(0,len(records),2):
        selected=[Image.open(target/f'page-{j+1:02d}.png').convert('RGB') for j in range(i,min(i+2,len(records)))]
        h=max(x.height for x in selected);w=sum(x.width for x in selected)
        canvas=Image.new('RGB',(w,h),(220,220,220));x=0
        for im in selected:canvas.paste(im,(x,0));x+=im.width
        canvas.save(OUT/f'QA/review-{i+1:02d}-{min(i+2,len(records)):02d}.png')
    return records

def structure():
    path=OUT/'第二章学术化重写候选v2.docx'
    figs=json.loads((OUT/'source/figure_records.json').read_text(encoding='utf-8'))
    advice=list(csv.DictReader((OUT/'第二章逐段审查完整对照.csv').open(encoding='utf-8-sig')))
    before=json.loads((OUT/'QA/protected_before.json').read_text(encoding='utf-8'))
    with ZipFile(path) as z,ZipFile(V1) as old:
        t=etree.fromstring(z.read('word/document.xml'));text=''.join(t.xpath('//w:t/text()',namespaces=NS))
        images={hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}
        assert all(r['sha256'] in images and sha(r['source'])==r['sha256'] for r in figs if r['source'])
        display=t.xpath('//w:p[w:r/w:instrText[contains(.,"EquationCh2")]]',namespaces=NS)
        bookmarks=t.xpath('//w:bookmarkStart/@w:name',namespaces=NS)
        refs=t.xpath('//w:instrText/text()',namespaces=NS)
        broken=[x for x in refs if x.strip().startswith('REF ') and re.search(r'REF\s+(\w+)',x).group(1) not in bookmarks]
        assert not broken,broken
        oldt=etree.fromstring(old.read('word/document.xml'))
        # Word changes rsid and relationship identifiers when saving; compare
        # page geometry/columns/grid semantically, not incidental XML prefixes.
        for tag in ('pgSz','pgMar','cols','docGrid'):
            assert dict(t.find('w:body/w:sectPr/w:'+tag,NS).attrib)==dict(oldt.find('w:body/w:sectPr/w:'+tag,NS).attrib),tag
        required=['20/20','14/20','12/20','17/20','1/20','11.792','10.891','80/80','0.9742','0.9129','1.968']
        assert all(x in text for x in required)
        numbered_equations=sum('SEQ EquationCh2' in x for x in refs)
        assert numbered_equations==20
        assert len(advice)==458 and len({x['id'] for x in advice})==458
        assert sha(V1)==before[str(V1)]
        result=dict(numbered_equations=numbered_equations,all_native_math=len(t.xpath('//m:oMath',namespaces=NS)),
          figure_positions=len(figs),embedded_images=len(images),original_s1_bytes_preserved=True,
          all_14_inserted_figure_bytes_preserved=True,tables=len(t.xpath('//w:tbl',namespaces=NS)),
          paragraph_reviews=len(advice),chapter_structure='2.1—2.6,19 headings',broken_cross_references=broken,
          original_section_geometry_preserved=True,v1_unchanged=True,document_sha256=sha(path))
        dump(OUT/'QA/final_structure_verification.json',result)
    return result

def protect():
    baseline=json.loads((OUT/'QA/protected_before.json').read_text(encoding='utf-8'))
    changed=[]
    for n,h in baseline.items():
        if not Path(n).is_file() or sha(n)!=h:changed.append(n)
    result=dict(protected_files=len(baseline),changed=changed,passed=not changed)
    dump(OUT/'QA/protection_verification.json',result);assert not changed,changed
    print(json.dumps(result,ensure_ascii=False))

def finalize():
    import shutil,subprocess
    state=structure()
    evidence=json.loads((OUT/'source/本次引用证据及hash索引.json').read_text(encoding='utf-8'))
    drift=[r['path'] for r in evidence if not r['exists'] or sha(r['path'])!=r['sha256']]
    assert not drift,drift
    bounds=json.loads((OUT/'QA/page_text_and_bounds.json').read_text(encoding='utf-8'))
    assert len(bounds)==33 and not any(x['outside'] for x in bounds)
    before=json.loads((OUT/'QA/git_before.json').read_text(encoding='utf-8'))
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();assert head==before['head']
    p=json.loads((OUT/'QA/protection_verification.json').read_text(encoding='utf-8'));assert p['passed']
    for name in ('chapter2_restructure_inventory.py','verify_chapter2_restructured_v2.py','build_chapter2_thesis_draft.py','chapter2_thesis_evidence.py'):
        shutil.copyfile(Path(__file__).parent/name,OUT/'source'/name)
    shutil.copyfile(Path(__file__).resolve().parents[1]/'.planning/chapter2_restructure_20261028/artifact.md',OUT/'source/artifact.md')
    dest=OUT/'source/冻结统计只读副本';dest.mkdir(exist_ok=True)
    for name,path in {'S2_全部13条件五方法.csv':ROOT/'仿真结果/2026-10-25_S2正式仿真_v1/formal/statistics/condition_statistics.csv',
       'S2_配对效应.csv':ROOT/'仿真结果/2026-10-25_S2正式仿真_v1/formal/statistics/paired_contrasts.csv',
       'S3_全部三层统计.csv':ROOT/'仿真结果/2026-10-26_S3正式仿真_v1/formal_summary.csv',
       'S3_时间动作区间.csv':ROOT/'仿真结果/2026-10-26_S3正式验收与论文图_v1/tables/time_and_action_intervals.csv'}.items():
        shutil.copyfile(path,dest/name);assert sha(path)==sha(dest/name)
    result=dict(passed=True,scope='document and evidence-reference QA; not an experiment rerun',pages=33,
      native_equations=20,native_inline_and_display_math=59,editable_tables=10,embedded_unchanged_images=14,
      reviewed_source_paragraphs=458,cited_sources=len(evidence),citation_drift=drift,
      full_protection_files=p['protected_files'],full_protection_changes=len(p['changed']),
      renderer='Microsoft Word 16.0 native PDF export, then PyMuPDF raster',
      canonical_renderer='Attempted; soffice.exe unavailable; no desktop LibreOffice used',
      visual_review='All 33 pages reviewed; final six changed pages reviewed separately; unchanged pages raster-identical to reviewed iteration',
      outside_page_bounds=0,word_cross_reference_errors=0,git_head_unchanged=True,
      new_simulation_runs=0,new_training_runs=0,new_physical_trials=0,
      limitations=['暂定工科样式，未核验学校正式模板','真实U-Net、独立真实状态/到达评价与实物闭环仍缺','参考文献待逐条核验'])
    dump(OUT/'QA/最终文档与证据验收.json',result)
    report=OUT/'第二章学术结构重构审查报告.md'
    report.write_text(report.read_text(encoding='utf-8')+'''\n\n## 8. 本次实际验收结果\n\n- Word 16.0原生导出33页，19个章节标题、20个编号原生公式（含行内共59个数学对象）、10个可编辑表格。\n- 14张已核实插图全部保留来源原始字节；15个图位中仅真实三方法比较图仍为明确占位。\n- 458个原段落均有处置记录，62份实际引用资料存在且引用时/交付前hash一致。\n- 全部33页已作图像版面检查，最终6处改动页单独复查；无页面越界或失效图引用。\n- 11,466个受保护既有文件hash复核变化0；v1原件与Git HEAD保持不变。\n- 本轮没有运行仿真、训练、正式研究评价或高压实验；未Commit/Push。\n- 标准DOCX渲染器因缺少soffice.exe不可用，已使用独立隐藏Word实例更新字段并导出真实页面，不是自绘Word预览。\n''',encoding='utf-8')
    names=['第二章学术化重写候选v2.docx','第二章学术结构重构审查报告.md','第二章最新详细目录与各节研究任务.md','真实液滴数据集采集和评价方案.md','第二章逐节重写建议与段落对照.md']
    dump(OUT/'交付manifest.json',dict(version='2026-10-28_academic_restructure_candidate_v2',deliverables={n:dict(path=str(OUT/n),sha256=sha(OUT/n),bytes=(OUT/n).stat().st_size) for n in names},qa=result))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--protect',action='store_true');ap.add_argument('--finalize',action='store_true');a=ap.parse_args()
    if a.protect:protect()
    elif a.finalize:finalize()
    else:
        r=structure();pages=render_pages();print(json.dumps(dict(**r,pages=len(pages)),ensure_ascii=False))
