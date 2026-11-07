"""Read-only source inventory for the 2026-10-28 thesis restructure (no algorithms run)."""
from pathlib import Path
import csv, hashlib, json, subprocess
from zipfile import ZipFile
from lxml import etree

REPO=Path(__file__).resolve().parents[1]
ROOT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
OUT=ROOT/'论文初稿/2026-10-28_第二章学术结构重构候选_v2'
V1=ROOT/'论文初稿/2026-10-26_第二章Word工作初稿_v1/第二章_单液滴视觉闭环控制_硕士论文工作初稿_v1.docx'
S3=ROOT/'仿真结果/2026-10-26_S3正式仿真_v1'
S3Q=ROOT/'仿真结果/2026-10-26_S3正式验收与论文图_v1'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def readcsv(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=OUT/'source';source.mkdir(exist_ok=True)
    with ZipFile(V1) as z:
        tree=etree.fromstring(z.read('word/document.xml'))
        styles=etree.fromstring(z.read('word/styles.xml'))
        names={s.get('{'+NS['w']+'}styleId'):s.xpath('./w:name/@w:val',namespaces=NS)[0] for s in styles.xpath('//w:style[w:name]',namespaces=NS)}
        records=[];section='前置页';h1=0;h2=0
        for i,p in enumerate(tree.xpath('//w:body//w:p',namespaces=NS),1):
            text=''.join(p.xpath('.//w:t/text() | .//m:t/text()',namespaces=NS))
            style=p.xpath('./w:pPr/w:pStyle/@w:val',namespaces=NS)
            if not text and not p.xpath('.//w:drawing',namespaces=NS):continue
            name=names.get(style[0],style[0]) if style else 'Normal'
            if name.lower()=='heading 1':h1+=1;h2=0;section=f'2.{h1} '+text
            elif name.lower()=='heading 2':h2+=1;section=f'2.{h1}.{h2} '+text
            records.append(dict(id=f'P{i:03d}',section=section,style=name,text=text,
                in_table=bool(p.xpath('ancestor::w:tbl',namespaces=NS)),math_count=len(p.xpath('.//m:oMath',namespaces=NS)),
                image_count=len(p.xpath('.//w:drawing',namespaces=NS))))
        dump(source/'v1_all_paragraphs.json',records)
        (source/'v1全文逐段提取.md').write_text('\n\n'.join(f"[{r['id']}] [{r['section']}] [{r['style']}] {r['text']}" for r in records),encoding='utf-8')
        dump(source/'v1_structure.json',dict(tables=len(tree.xpath('//w:tbl',namespaces=NS)),paragraphs=len(records),
             equations=len(tree.xpath('//m:oMath',namespaces=NS)),images={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}))
    import sys
    if '--extract-only' in sys.argv:
        print('extracted',len(records));return
    if (OUT/'QA/protected_before.json').exists():
        raise FileExistsError('Keep the original protection baseline; use a new version directory for a new inventory')
    import chapter2_thesis_evidence as ev
    e=ev.collect();dump(source/'legacy_evidence_snapshot.json',e)
    groups={}
    for name in ('formal_summary.csv','formal_trials.csv','formal_steps.csv','request_applied_evaluation.csv'):
        path=S3/name
        groups[name]=readcsv(path)
    dump(source/'s3_frozen_aggregates.json',groups)
    protected={V1,*[Path(r['path']) for r in e['evidence'] if r['exists']]}
    for root in (S3,S3Q,ROOT/'仿真结果/2026-10-26_S3_G3协议冻结_v1'):
        for p in root.rglob('*'):
            if p.is_file() and (p.suffix in ('.json','.csv','.yaml','.md','.pdf','.svg') or p.parent.name=='figures'):
                protected.add(p)
    for top in ('dmf','configs','controllers','simulation','validation'):
        protected.update(p for p in (REPO/top).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    dump(OUT/'QA/protected_before.json',{str(p):sha(p) for p in sorted(protected)})
    dump(OUT/'QA/git_before.json',dict(status=subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True),head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()))
    print(json.dumps(dict(paragraphs=len(records),protected=len(protected),s3_rows={k:len(v) for k,v in groups.items()},out=str(OUT)),ensure_ascii=False))
if __name__=='__main__':main()
