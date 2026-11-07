"""Text-only vector cleanup; all scientific graphics and retained text audited."""
from pathlib import Path
from collections import Counter
import argparse
import copy
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET

BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
SOURCE=BASE/'2026-10-27_仿真论文图_学术整理候选_v2'
CAPTIONS=BASE/'2026-10-27_仿真图定稿前复核与版心预览_v3/每图正式caption草稿.md'
OUT=BASE/'2026-10-27_仿真论文图_移除说明小字_v4'
REMOVE={
    'S1-A':{
        'normal:262000:F:end_to_end  |  n=1 机制示例',
        '参考区间 [1.45, 1.46] s',
        '新任务191→192；旧Mask拒绝',
        '单位pitch；模拟观测，非真实U-Net结果；预测状态不是GT。',
        '1.96 s新任务切换，旧Mask不复用；该tick的world.active仍为191。'},
    'S1-B':{
        'normal:262000:F:end_to_end  |  n=1 机制示例',
        '任务阶段按日志模拟Applied划分；观测量按处理时刻显示。',
        '单位pitch；n=1机制示例；模拟观测，非真实U-Net结果。η分母为液滴Mask面积。',
        '目标距离/方向进展取自原日志；缺失、丢帧及任务切换断线；源准备不展示运输特征。'}}
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
ET.register_namespace('xlink','http://www.w3.org/1999/xlink')

def sha(q):return hashlib.sha256(Path(q).read_bytes()).hexdigest()
def remove_ranges(stream,ranges):
    for start,end in sorted(ranges,reverse=True):stream=stream[:start]+stream[end:]
    return stream
def svg_geometry(text):
    root=ET.fromstring(text)
    for parent in root.iter():
        for child in list(parent):
            if child.tag==f'{{{NS}}}text':parent.remove(child)
    return ET.tostring(root,encoding='unicode')
def lines(page):
    return [(tuple(line['bbox']),''.join(s['text'] for s in line['spans']))
        for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines']]
def normalize(value):
    if isinstance(value,float):return round(value,5)
    if isinstance(value,(tuple,list)):return [normalize(x) for x in value]
    if isinstance(value,dict):return {k:normalize(v) for k,v in value.items() if k not in ('seqno','layer','level')}
    if value.__class__.__name__ in ('Point','Rect','Quad'):return [normalize(v) for v in value]
    return value

def clean_svg(src,dest,removed,unit=False):
    text=src.read_text(encoding='utf-8');root=ET.fromstring(text);found=Counter()
    original_text=Counter(''.join(e.itertext()) for e in root.iter() if e.tag==f'{{{NS}}}text')
    for parent in root.iter():
        for child in list(parent):
            value=''.join(child.itertext())
            if child.tag==f'{{{NS}}}text' and value in removed:parent.remove(child);found[value]+=1
    assert set(found)==removed and all(n==1 for n in found.values())
    if unit:
        e=ET.SubElement(root,f'{{{NS}}}text',{'x':'28.512','y':'37.5','style':"font: 8.5px 'Times New Roman'; fill: #526879"})
        e.text='pitch'
    new=ET.tostring(root,encoding='unicode')
    assert svg_geometry(text)==svg_geometry(new),'non-text SVG geometry changed'
    after=Counter(''.join(e.itertext()) for e in root.iter() if e.tag==f'{{{NS}}}text')
    expected=original_text-Counter(removed)
    if unit:expected['pitch']+=1
    assert after==expected,'retained SVG text changed'
    dest.write_text('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n'+new,encoding='utf-8')
    return dict(svg_removed=len(found),svg_non_text_geometry_identical=True,svg_retained_text_identical=True)

def clean_pdf(src,dest,removed,unit=False):
    import pymupdf
    original=pymupdf.open(src);page=original[0]
    geometry=normalize(page.get_drawings());before=lines(page);found=[]
    # Drop only exact BT/ET text objects. Do not use redaction, which can
    # reserialize inherited stroke state even when graphics removal is disabled.
    contents=page.get_contents();assert len(contents)==1
    xref=contents[0];stream=original.xref_stream(xref);selected=[]
    old_counts=Counter(text for _,text in before)
    source_bytes=src.read_bytes()
    for match in re.finditer(rb'\bBT\b.*?\bET\b',stream,re.S):
        probe=pymupdf.open(stream=source_bytes,filetype='pdf')
        probe.update_stream(xref,remove_ranges(stream,[(match.start(),match.end())]))
        new_counts=Counter(t for _,t in lines(probe[0]));probe.close()
        missing=old_counts-new_counts;extra=new_counts-old_counts
        if missing and not extra and set(missing)<=removed:
            selected.append((match.start(),match.end()));found.extend(missing.elements())
    assert set(found)==removed and len(found)==len(removed)
    original.update_stream(xref,remove_ranges(stream,selected))
    if unit:page.insert_text((28.512,37.5),'pitch',fontsize=8.5,fontname='tiro',color=(.32,.41,.47))
    after=lines(page);expected=Counter(text for _,text in before)-Counter(removed)
    if unit:expected['pitch']+=1
    assert Counter(text for _,text in after)==expected,dict(missing=expected-Counter(t for _,t in after),extra=Counter(t for _,t in after)-expected)
    assert normalize(page.get_drawings())==geometry,'PDF paths changed'
    for box,text in before:
        if text not in removed:assert (box,text) in after,('retained text moved',text)
    original.save(dest,garbage=4,deflate=True)
    page.get_pixmap(dpi=600,alpha=False).save(dest.with_suffix('.png'))
    page.get_pixmap(dpi=180,alpha=False).save(OUT/'previews'/dest.with_suffix('.png').name)
    count=len(geometry);original.close()
    return dict(pdf_removed=len(found),pdf_text_objects_removed=len(selected),pdf_retained_text_identical=True,pdf_retained_text_positions_identical=True,
                pdf_drawing_count=count,pdf_paths_identical=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--revise',action='store_true');args=parser.parse_args()
    if OUT.exists() and not args.revise:raise FileExistsError(OUT)
    for name in ('figures','previews','QA','来源'): (OUT/name).mkdir(parents=True,exist_ok=True)
    protected={str(q):sha(q) for q in SOURCE.rglob('*') if q.is_file()};protected[str(CAPTIONS)]=sha(CAPTIONS)
    records=[]
    for src in sorted((SOURCE/'figures').glob('*.pdf')):
        key=src.name.split('_',1)[0];dest=OUT/'figures'/src.name
        if key in REMOVE:
            removed=REMOVE[key]
            svg=clean_svg(src.with_suffix('.svg'),dest.with_suffix('.svg'),removed,key=='S1-A')
            pdf=clean_pdf(src,dest,removed,key=='S1-A')
            records.append(dict(figure=key,source_pdf=str(src),source_sha256=sha(src),removed=sorted(removed),**svg,**pdf))
        else:
            for suffix in ('.pdf','.svg','.png'):shutil.copy2(src.with_suffix(suffix),dest.with_suffix(suffix))
            preview=SOURCE/'previews'/src.with_suffix('.png').name
            if preview.exists():shutil.copy2(preview,OUT/'previews'/preview.name)
            records.append(dict(figure=key,source_pdf=str(src),source_sha256=sha(src),unchanged_copy=True,
                removed=[],reason='no explanatory footnotes; all remaining labels/legends/data are necessary'))
    text=CAPTIONS.read_text(encoding='utf-8')
    text=text.replace('旧Mask被拒绝而内部位置仍保留。','旧Mask被拒绝而内部位置仍保留；该tick的world.active仍为191。')
    (OUT/'正式图注_含移出说明.md').write_text(text,encoding='utf-8')
    (OUT/'移除说明性文字清单.md').write_text('# 图内移出的说明性文字\n\n原图与数据未覆盖。S1仅在本独立候选中移除以下9条说明，内容保留于配套图注；轴名、单位、刻度、图例、电极/子图编号、状态/动作与时间戳不删。S2/S3无此类脚注，原样复制。S1-A另保留短单位标签pitch。\n\n'+''.join('## '+r['figure']+'\n\n'+''.join('- '+v+'\n' for v in r['removed'])+'\n' for r in records if r['removed']),encoding='utf-8')
    import pymupdf
    merged=pymupdf.open()
    for q in sorted((OUT/'figures').glob('*.pdf')):
        with pymupdf.open(q) as part:merged.insert_pdf(part)
    assert len(merged)==7;merged.save(OUT/'第二章七张仿真图_无说明小字候选v4.pdf');merged.close()
    changed=[q for q,h in protected.items() if sha(q)!=h];assert not changed
    result=dict(status='candidate_text_only',user_authorized_S1_note_removal=True,new_simulations=0,new_predictions=0,
        removed_notes=9,figures=records,source_files=protected,source_changes=changed,script_sha256=sha(__file__),
        alignment_evidence='Text-only native vector edit; SVG non-text tree and PDF drawing geometry unchanged; no plot-area layout was recomputed')
    (OUT/'QA/文字清理与图形一致性.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(__file__,OUT/'来源'/Path(__file__).name)
    print(json.dumps(dict(removed_notes=9,changed_figures=2,unchanged_figures=5,source_changes=changed),ensure_ascii=False))

if __name__=='__main__':main()
