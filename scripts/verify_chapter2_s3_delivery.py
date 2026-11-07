"""Render and verify the S3 report; no simulation execution."""
from pathlib import Path
import hashlib
import json
import pymupdf
from PIL import Image, ImageOps, ImageDraw

OUT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G0-G2开发验收_v1')

def main():
    path=OUT/'第二章S3_G0-G2实施与验收报告.pdf'
    manifest=json.loads((OUT/'QA/report_manifest.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest['report_sha256']
    doc=pymupdf.open(path);dest=OUT/'QA/report_render';dest.mkdir(exist_ok=True)
    pages=[];issues=[]
    for i,page in enumerate(doc):
        pix=page.get_pixmap(matrix=pymupdf.Matrix(1.2,1.2),alpha=False)
        p=dest/f'page-{i+1:02d}.png';pix.save(p);pages.append(p)
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    x0,y0,x1,y1=span['bbox']
                    if min(x0,y0)<-.5 or x1>page.rect.width+.5 or y1>page.rect.height+.5:
                        issues.append(dict(page=i+1,text=span['text'],bbox=span['bbox']))
    text='\n'.join(p.get_text() for p in doc)
    for token in ('120','360','56','833','G4','SIMULATION','jitter','dropout','12/12'):
        assert token in text,token
    for start in range(0,len(pages),6):
        sheet=Image.new('RGB',(1200,1160),'#dce1e5');draw=ImageDraw.Draw(sheet)
        for j,p in enumerate(pages[start:start+6]):
            im=Image.open(p).convert('RGB');im.thumbnail((380,535))
            x=10+(j%3)*400;y=30+(j//3)*580
            sheet.paste(im,(x,y));draw.text((x,y-18),f'Page {start+j+1}',fill='black')
        sheet.save(dest/f'contact-{start//6+1}.png')
    result=dict(passed=not issues,pages=len(doc),out_of_page_spans=issues,report_sha256=manifest['report_sha256'],
                simulation_execution=False,requires_visual_review=True)
    (OUT/'QA/report_render_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result));assert not issues

if __name__=='__main__':main()
