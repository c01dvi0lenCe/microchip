"""Render review PDF and seal formal input index; no research execution."""
import hashlib
import json
from pathlib import Path
import pymupdf
from PIL import Image,ImageDraw

BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
DATA=BASE/'2026-10-26_S3正式仿真_v1';OUT=BASE/'2026-10-26_S3正式验收与论文图_v1'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=OUT/'第二章S3_G3-G5正式验收与图稿审查.pdf';manifest=json.loads((OUT/'交付manifest.json').read_text(encoding='utf-8'))
    assert sha(p)==manifest['pdf_sha256'];doc=pymupdf.open(p);dest=OUT/'QA/report_render';dest.mkdir(exist_ok=True)
    pages=[];issues=[]
    for i,page in enumerate(doc):
        q=dest/f'page-{i+1:02d}.png';page.get_pixmap(matrix=pymupdf.Matrix(1.2,1.2),alpha=False).save(q);pages.append(q)
        for b in page.get_text('dict')['blocks']:
            for line in b.get('lines',[]):
                for span in line['spans']:
                    x0,y0,x1,y1=span['bbox']
                    if min(x0,y0)<-.5 or x1>page.rect.width+.5 or y1>page.rect.height+.5:issues.append(dict(page=i+1,text=span['text'],bbox=span['bbox']))
    text='\n'.join(page.get_text() for page in doc)
    for key in ('800','2400','852','80/80','B_single','SIMULATION','dropout','jitter'):assert key in text,key
    for start in range(0,len(pages),6):
        sheet=Image.new('RGB',(1200,1160),'#DCE1E5');draw=ImageDraw.Draw(sheet)
        for j,path in enumerate(pages[start:start+6]):
            im=Image.open(path).convert('RGB');im.thumbnail((380,535));x=10+j%3*400;y=30+j//3*580
            sheet.paste(im,(x,y));draw.text((x,y-18),f'Page {start+j+1}',fill='black')
        sheet.save(dest/f'contact-{start//6+1}.png')
    index={p.relative_to(DATA).as_posix():sha(p) for p in DATA.glob('*') if p.is_file()}
    index.update({p.relative_to(DATA).as_posix():sha(p) for p in (DATA/'trials').glob('*/trial_manifest.json')})
    (OUT/'QA/formal_frozen_input_index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    result=dict(passed=not issues,pages=len(doc),out_of_page_spans=issues,source_pdf_sha256=manifest['pdf_sha256'],
                no_new_research_runs=True,formal_index_items=len(index),manual_visual_review_required=True)
    (OUT/'QA/delivery_render_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result));assert not issues

if __name__=='__main__':main()
