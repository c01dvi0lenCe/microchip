"""Read-only scientific/data QA; only writes its new QA output folder."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.normal_speed import audit_normal_trial
from dmf.chapter2_geometry_sim.audit import audit_trial

CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
NEW=CH/'2026-10-28_实验一_正常速度1p4mmps_v2'
OLD=CH/'2026-10-28_实验一_真实几何4mm到达识别_v1'
SKILL=Path("C:/Users/Rz'sLaptop/.agents/skills/nature-figure/scripts")


def check():
    qa=NEW/'QA';qa.mkdir(exist_ok=True)
    checks=[]
    for name in ('map_full','static_geometry','movement_keyframes','feature_timeline','arrival_timeline'):
        path=NEW/'visualization/figures'/(name+'.pdf')
        for script,args in [('audit_pdf_text.py',['--min-pt','5']),
                            ('audit_figure_collisions.py',['--json-out',str(qa/(name+'_collision.json'))])]:
            command=[sys.executable,str(SKILL/script),str(path),*args]
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
            (qa/(name+'_'+script+'.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
            checks.append(dict(figure=name,check=script,exit_code=result.returncode))
            print(name,script,result.returncode,flush=True)
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    visual=json.loads((NEW/'visualization/render_manifest.json').read_text(encoding='utf-8'))
    changes=[name for name,digest in visual['files'].items() if sha(NEW/'visualization'/name)!=digest]
    old_index=json.loads((OLD/'final_figure_index.json').read_text(encoding='utf-8'))
    old_changes=[name for name,digest in old_index['final_files'].items() if sha(OLD/name)!=digest]
    new_audit=audit_normal_trial(NEW/'trial');old_audit=audit_trial(OLD/'trial')
    result=dict(audit=new_audit,old_trial_audit=old_audit,figure_checks=checks,
                visualization_hash_changes=changes,old_final_figure_changes=old_changes,movie=visual['movie'],
                passed=new_audit['passed'] and old_audit['passed'] and not changes and not old_changes
                  and all(c['exit_code']==0 for c in checks))
    (qa/'delivery_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('passed',result['passed'])
    return result['passed']


if __name__=='__main__':raise SystemExit(0 if check() else 1)
