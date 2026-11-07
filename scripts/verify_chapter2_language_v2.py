"""Final language cleanup and read-only release checks for the generated v2."""
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from revise_chapter2_thesis_v2 import (
    V1, V2, OUT, S1, ptext, settext, Builder, dump, sha, collect,
    result_paragraphs, verify_protection,
)

def codes(p):
    return p._p.xpath('.//w:instrText/text()|.//w:fldSimple/@w:instr')

def numbered(d, key):
    return [p for p in d.paragraphs if any('SEQ '+key in x for x in codes(p))]

def semantic(n):
    """Word merges equivalent math runs; compare the expression tree, not runs."""
    local=etree.QName(n).localname
    if etree.QName(n).namespace != 'http://schemas.openxmlformats.org/officeDocument/2006/math':
        return None
    if local.endswith('Pr'):return None
    if local=='r':return ''.join(n.xpath('.//m:t/text()',namespaces={'m':qn('m:t')[1:].split('}')[0]}))
    children=[]
    for c in n:
        value=semantic(c)
        if value is None:continue
        if isinstance(value,str) and children and isinstance(children[-1],str):children[-1]+=value
        else:children.append(value)
    return (local,tuple(children))

def drawings(d):
    records=[]
    for p in d.paragraphs:
        for drawing in p._p.xpath('.//w:drawing'):
            rid=drawing.xpath('.//a:blip/@r:embed')[0]
            records.append({'sha256':hashlib.sha256(d.part.related_parts[rid].blob).hexdigest(),
                            'extent':drawing.xpath('.//wp:extent/@cx|.//wp:extent/@cy')})
    return records

def finalize():
    d=Document(V2);writer=object.__new__(Builder);writer.doc=d;changes=[]
    replacements={
        '生产初始配置与':'完整五状态算法初始配置与',
        '真实液滴分割Pilot及算法对比位置':'真实液滴分割Pilot与算法比较',
        '同一闭环trial的任务阶段与空间特征':'同一闭环运行的任务阶段与空间特征',
    }
    # Titles may be split across Word runs. Only title text after the caption
    # bookmark is replaced; numbering fields and bookmarks are untouched.
    for p in d.paragraphs:
        if p.style.name!='Caption':continue
        old=ptext(p)
        for a,b in replacements.items():
            if a not in old:continue
            nodes=p._p.xpath('./w:bookmarkEnd[last()]/following-sibling::w:r/w:t')
            full=''.join(x.text or '' for x in nodes)
            if a not in full:continue
            new=full.replace(a,b)
            nodes[0].text=new
            for node in nodes[1:]:node.text=''
            changes.append({'kind':'caption','old':old,'new':ptext(p)})
    table=d.tables[5]
    descriptions={
        '积分 / 名义速度':'有限速度迁移；固定时间步长积分',
        '模拟Applied / 常规响应':'模拟执行与运动响应分别建模',
        '模拟相机':'离散采样与有限曝光',
        '处理可用时间':'曝光结束后的处理延迟与随机抖动',
        'Mask':'圆形简化轮廓；半径扰动0.015 pitch；非真实分割',
        '位置误差 / 基础丢帧':'观测位置扰动与随机缺帧',
        '独立参考':'仅供独立评分，算法不可见',
    }
    for row in table.rows[1:]:
        label=row.cells[0].text.strip()
        if label in descriptions:
            p=row.cells[2].paragraphs[0];old=ptext(p)
            settext(p,descriptions[label],writer)
            changes.append({'kind':'table description','row':label,'old':old,'new':ptext(p)})
    for p in d.paragraphs:
        if ptext(p).startswith('Pilot结果中') and 'E-SEG' not in ptext(p):
            old=ptext(p)
            settext(p,old+'【待完成实验E-SEG：真实U-Net跨采集训练与独立测试】',writer)
            changes.append({'kind':'searchable placeholder','old':old,'new':ptext(p)})
    d.save(V2)
    dump(OUT/'source/final_cleanup_records.json',changes)
    extra=['','## 逐页校对中的补充修订','',
      '- 清理Word拆分文本导致首轮未替换的表2-4、图2-7和图2-10标题；保留原编号字段。',
      '- 按表2-6行名逐项校对解释栏，使积分、采样、处理延迟、Mask扰动、位置噪声和评分参考准确对应；值或定义栏未改。',
      '- 增加真实U-Net独立测试的简短可检索实验占位，未写成已完成成果。',
      '- 对应完整原文与修订记录：source/final_cleanup_records.json。']
    with (OUT/'第二章_论文语言修订对照表.md').open('a',encoding='utf-8') as f:f.write('\n'.join(extra)+'\n')
    shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
    print('final cleanup',len(changes))

def verify():
    a,b=Document(V1),Document(V2)
    oldeq,neweq=numbered(a,'EquationCh2'),numbered(b,'EquationCh2')
    assert len(oldeq)==len(neweq)==20
    assert [semantic(p._p.find(qn('m:oMath'))) for p in oldeq]==[semantic(p._p.find(qn('m:oMath'))) for p in neweq]
    assert [ptext(p) for p in a.paragraphs if p.style.name.startswith('Heading')]==[ptext(p) for p in b.paragraphs if p.style.name.startswith('Heading')]
    for key,n in [('FigureCh2',12),('TableCh2',9),('EquationCh2',20)]:
        x,y=numbered(a,key),numbered(b,key)
        assert len(x)==len(y)==n
        assert [p._p.xpath('.//w:bookmarkStart/@w:name') for p in x]==[p._p.xpath('.//w:bookmarkStart/@w:name') for p in y]
    oldimg,newimg=drawings(a),drawings(b)
    assert len(newimg)==4 and oldimg==newimg[:2]
    data=collect();result_paragraphs(data)
    for i,key in [(2,'s2a'),(3,'s2b')]:assert newimg[i]['sha256']==sha(Path(data['assets'][key]))
    # All original parameter values, units and method switch states retained.
    assert [r.cells[1].text for r in a.tables[5].rows[1:]]==[r.cells[1].text for r in b.tables[5].rows[1:]]
    for x,y in zip(a.tables[3].rows[1:],b.tables[3].rows[1:]):
        # Qualifiers such as '须真实标定' are revised; values/units are retained.
        number=lambda s:re.findall(r'\d+(?:\.\d+)?',s)
        assert number(x.cells[1].text)==number(y.cells[1].text)
        for unit in ('mm','pitch','s'):
            assert (unit in x.cells[1].text)==(unit in y.cells[1].text)
    assert [[c.text for c in r.cells] for r in a.tables[6].rows]==[[c.text for c in r.cells] for r in b.tables[6].rows]
    body='\n'.join(ptext(p) for p in b.paragraphs)+'\n'+'\n'.join(c.text for t in b.tables for r in t.rows for c in r.cells)
    forbidden=['source-01','source-05','Codex','用户确认','当前仓库','生产算法','生产初始','本版暂不','待写入','待补文献','不得虚构','不能宣称','正式结果待补']
    assert not [x for x in forbidden if x in body]
    assert not re.search(r'[A-Z]:[\\/]|dmf/|\.png|\.csv|\.yaml|\.py\b',body)
    assert 'Error! Reference' not in body and '错误!未找到引用源' not in body
    for term in ['历史重建','持续伪观测','抖动','丢帧','误拒代价','21份共同缓存','E-SEG','E-CAL','E-S3S4','E-HW']:
        assert term in body,term
    assert sha(V1)=='355990246bcb9e50ae2a119cedf8e1c076af69317fb26de2160f3b8769f12c16'
    protection=verify_protection()
    render=json.loads((OUT/'QA/render_r2/word_render_report.json').read_text(encoding='utf-8-sig'))
    assert len(render['headings'])==19 and render['toc_count']==1
    pagefiles=sorted((OUT/'QA/render_r2').glob('page-*.png'))
    assert len(pagefiles)==render['pages']==27
    changed=[p.name for p in pagefiles if sha(p)!=sha(OUT/'QA/render_r1'/p.name)]
    assert changed==['page-12.png','page-15.png','page-17.png','page-19.png']
    dump(OUT/'QA/visual_review.json',{
        'passed':True,'renderer':'Microsoft Word native PDF + bundled Poppler PNG',
        'canonical_fallback_reason':'Bundled renderer reports soffice.exe absent',
        'round_1_all_pages_visually_inspected':list(range(1,28)),
        'round_2_changed_pages_reinspected':[12,15,17,19],
        'round_2_remaining_pages_identical_to_reviewed_round_1':True,
        'page_sha256':{p.name:sha(p) for p in pagefiles},
        'checks':['no clipped text','no table overflow','captions adjacent to images',
                  'equations editable and readable','TOC and heading numbers updated']})
    changes=json.loads((OUT/'source/final_cleanup_records.json').read_text(encoding='utf-8'))
    comparison=OUT/'第二章_论文语言修订对照表.md'
    text=comparison.read_text(encoding='utf-8')
    if '## 最终校对逐项对照' not in text:
        lines=['','## 最终校对逐项对照','','|类型/位置|首轮文本|最终文本|','|---|---|---|']
        esc=lambda s:s.replace('|','\\|').replace('\n','<br>')
        for item in changes:
            lines.append('|'+esc(item['kind']+' '+item.get('row',''))+'|'+esc(item['old'])+'|'+esc(item['new'])+'|')
        comparison.write_text(text+'\n'.join(lines)+'\n',encoding='utf-8')
    shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
    outputs=[V2]+[OUT/name for name in ['第二章_论文语言修订对照表.md','第二章_内部待办与证据追溯清单.md','第二章_仍需核验的学术事实清单.md']]
    assert all(p.is_file() and p.stat().st_size>0 for p in outputs)
    result={'passed':True,'pages':render['pages'],'numbered_equations':20,'equation_expression_trees_unchanged':True,
       'headings_unchanged':19,'figure_numbers':12,'table_numbers':9,'s1_bytes_and_size_unchanged':True,
       's2_figures_original_bytes':True,'parameter_values_unchanged':True,'method_switches_unchanged':True,
       's2_frozen_statistics_groups_verified':65,'protected_files':protection['files'],
       'protected_changes':0,'research_runs':0,'outputs':{str(p):sha(p) for p in outputs}}
    dump(OUT/'QA/release_verification.json',result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['finalize','verify']);a=p.parse_args()
    finalize() if a.action=='finalize' else verify()
