"""G3: read-only protocol checks and constructor-only development RNG replay.

Never advances the world, exposes a frame, evaluates a controller, or uses a
formal seed. Rebuilt arrays are explicitly NEW audit artifacts, not old data.
"""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import types

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
OLD=BASE/'2026-10-26_S3_G0-G2开发验收_v1'
DATA=OLD/'development_smoke'
OUT=BASE/'2026-10-26_S3_G3协议冻结_v1'
METHODS=('A_fixed','B_single','BTQ','F_full')
SCENARIOS=('normal','delayed','partial_stall','jitter','dropout','deviation','failure')
FLAGS={'A_fixed':dict(S=False,W=False,K=False,Q=False),'B_single':dict(S=False,W=False,K=False,Q=False),
       'BTQ':dict(S=False,W=True,K=False,Q=True),'F_full':dict(S=True,W=True,K=True,Q=True)}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def js(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def rows(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_json(p,data):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def assert_development_seed(seed):
    if type(seed) is not int or seed not in (264000,264001,264002):raise ValueError('RNG audit permits development seeds only')

def compare_external(saved,rebuilt):
    return [k for k in sorted(set(saved)|set(rebuilt)) if saved.get(k)!=rebuilt.get(k)]

def check_trace(method,row):
    if row.get('stage')!='target':return []
    errors=[];flags=json.loads(row['enabled'])
    if flags!=FLAGS[method]:errors.append('arrival_flags')
    if row.get('C0_passed')=='True' and row.get('coverage_passed'):
        raw=json.loads(row['raw']);expected=row['coverage_passed']=='True' and all(not flags[k] or raw[k] for k in ('S','K','Q'))
        if (row['eligible']=='True')!=expected:errors.append('eligibility')
    return errors

def planned_formal_identities():
    # Merely design identities: no formal RNG is constructed here.
    p=[dict(cohort='main',scenario=s,seed_index=i,method=m,protection='P_F' if m=='F_full' else 'P_B',phase_mode='end_to_end')
       for s in SCENARIOS for i in range(20) for m in METHODS]
    p += [dict(cohort='bridge',scenario=s,seed_index=i,method=m,protection=q,phase_mode='end_to_end')
          for s in ('partial_stall','deviation') for i in range(20) for m,q in (('F_full','P_B'),('BTQ','P_F'))]
    p += [dict(cohort='diagnostic',scenario=s,seed_index=i,method=m,protection='P_F' if m=='F_full' else 'P_B',phase_mode='transport_only')
          for s in ('jitter','dropout') for i in range(20) for m in METHODS]
    return p

def frozen_rng(trial,manifest,seed):
    assert_development_seed(seed)
    import numpy as np
    import cv2
    expected=dict(python=manifest['python'],numpy=manifest['numpy'],opencv=manifest['opencv'])
    actual=dict(python=platform.python_version(),numpy=np.__version__,opencv=cv2.__version__)
    if expected!=actual:raise ValueError('Use frozen research environment: '+str(expected)+' != '+str(actual))
    prefix='_s3_g3_rng_snapshot';pkg=types.ModuleType(prefix);pkg.__path__=[];sys.modules[prefix]=pkg
    modules={}
    for name in ('config','world','vision'):
        relative='dmf/chapter2_sim/'+name+'.py';p=trial/'source_code'/relative
        if sha(p)!=manifest['source_hashes'][relative]:raise ValueError('frozen source hash mismatch: '+relative)
        module=types.ModuleType(prefix+'.'+name);module.__file__=str(p);module.__package__=prefix
        sys.modules[module.__name__]=module
        # compile/exec avoids writing __pycache__ into frozen source directories.
        exec(compile(p.read_bytes(),str(p),'exec'),module.__dict__);modules[name]=module
    env=dict(manifest['config']['common']['environment']);env['route']=tuple(env['route'])
    cfg=modules['config'].SimConfig(**env)
    geometry=types.SimpleNamespace(center=lambda _:np.zeros(2))
    world=modules['world'].DropletWorld(cfg,geometry,'normal',seed)
    camera=modules['vision'].SyntheticCamera(cfg,geometry,seed,'normal')
    arrays=dict(world_noise=world.noise,camera_errors=camera.errors,camera_uniform=camera.uniform)
    external={k:hashlib.sha256(a.tobytes(order='C')).hexdigest() for k,a in arrays.items()}
    external.update(speed_factor=world.speed_factor,max_time_s=cfg.max_time_s,world_stream=[seed,101],camera_stream=[seed,202])
    return arrays,external,actual

def protected_baseline():
    path=OUT/'QA/protected_before.json'
    if path.exists():raise FileExistsError('protection baseline already exists')
    prior=js(OLD/'QA/protected_before.json')
    files=set(Path(p) for p in prior)
    files.update(p for p in OLD.rglob('*') if p.is_file())
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode('utf-8').split('\0')
    for name in names:
        if not name or name.startswith('.planning/') or name in ('scripts/audit_chapter2_s3_g3.py','tests/test_chapter2_s3_g3.py'):continue
        p=ROOT/name
        if p.is_file():files.add(p)
    write_json(path,{str(p):sha(p) for p in sorted(files)})
    print('protected',len(files))

def verify_protected():
    files=js(OUT/'QA/protected_before.json')
    changes=[p for p,h in files.items() if not Path(p).is_file() or sha(p)!=h]
    result=dict(files=len(files),passed=not changes,changes=changes)
    write_json(OUT/'QA/protection_check.json',result);return result

def audit():
    import numpy as np
    if (OUT/'QA/g3_audit.json').exists():raise FileExistsError('G3 audit outputs are append-only')
    ms=rows(DATA/'development_trials.csv');errors=[];records=[];rng={};sources=None;total=Counter()
    for m in ms:
        trial=DATA/m['relative_trial_path'];manifest=js(trial/'trial_manifest.json');seed=int(m['seed']);assert_development_seed(seed)
        if sources is None:sources=manifest['source_hashes']
        if sources!=manifest['source_hashes']:errors.append([m['trial_id'],'core_source_set'])
        for rel,h in manifest['source_hashes'].items():
            if sha(ROOT/rel)!=h or sha(trial/'source_code'/rel)!=h:errors.append([m['trial_id'],'core_source:'+rel])
        for rel in ('observations/gate_trace.csv','observations/frames.csv','observations/events.csv','config_snapshot.json'):
            if sha(trial/rel)!=manifest['files'][rel]:errors.append([m['trial_id'],'input_hash:'+rel])
        if seed not in rng:
            arrays,external,environment=frozen_rng(trial,manifest,seed)
            dest=OUT/'reconstructed_development_rng'/f'seed-{seed}.npz';dest.parent.mkdir(parents=True,exist_ok=True)
            np.savez(dest,**arrays,speed_factor=np.array(external['speed_factor']))
            rng[seed]=dict(external=external,environment=environment,npz=str(dest.relative_to(OUT)),npz_sha256=sha(dest),
                           arrays={k:dict(shape=list(v.shape),dtype=v.dtype.str,order='C',raw_sha256=external[k]) for k,v in arrays.items()})
        differences=compare_external(manifest['exogenous'],rng[seed]['external'])
        if differences:errors.append([m['trial_id'],'RNG:'+','.join(differences)])
        counts=Counter();trace_errors=[]
        for row in rows(trial/'observations/gate_trace.csv'):
            for err in check_trace(m['method'],row):trace_errors.append([row['frame_id'],err])
            if row.get('stage')=='target':
                counts['target_rows']+=1
                raw=json.loads(row.get('raw') or '{}')
                if raw.get('Q') is False:counts['raw_Q_false']+=1
            elif row.get('stage') in ('source','recovery'):counts['P0_or_recovery_rows']+=1
        if trace_errors:errors.append([m['trial_id'],'gate_trace',trace_errors])
        total.update(counts)
        records.append(dict(trial_id=m['trial_id'],method=m['method'],flags=FLAGS[m['method']],trace_counts=dict(counts),
                            rng_differences=differences,source_hashes_match=True,manifest_sha256=sha(trial/'trial_manifest.json')))
    previous=js(OLD/'QA/independent_data_audit.json');bridge=js(OLD/'QA/bridge_control_comparison.json')
    if not previous['passed'] or not all(r['control_events_equal'] for r in bridge):errors.append('prior_independent_or_bridge_audit')
    protect=verify_protected()
    if not protect['passed']:errors.append('protected_files_changed')
    result=dict(schema='s3_g3_consistency_audit_v1',passed=not errors,errors=errors,records=len(ms),
                b_single_trials=sum(m['method']=='B_single' for m in ms),b_single_arrival_flags=FLAGS['B_single'],
                report_G_plus_Q_is_documentation_error=True,algorithm_protocol_deviation=False,development_rerun_required=False,
                common_safety_raw_Q=True,raw_Q_not_hard_eligibility_override=True,counts=dict(total),
                rng_replayed=rng,source_hashes=sources,trials=records,prior_independent_audit_sha256=sha(OLD/'QA/independent_data_audit.json'),
                bridge_equal_pairs=sum(r['control_events_equal'] for r in bridge),formal_seed_uses=0,new_research_trials=0,
                rng_only_world_and_camera_initialization=True,model_advance_calls=0,camera_expose_calls=0,
                approval_basis='User explicitly authorized G4 only after all G3 gates pass; no seed preselection.',
                formal_plan_cohorts=dict(Counter(r['cohort'] for r in planned_formal_identities())),
                rng_audit_script_sha256=sha(Path(__file__)),environment=rng[264000]['environment'])
    write_json(OUT/'QA/g3_audit.json',result)
    print(json.dumps({k:result[k] for k in ('passed','records','b_single_trials','b_single_arrival_flags','formal_seed_uses','new_research_trials','errors')},ensure_ascii=False))
    if errors:raise RuntimeError('G3 audit failed')
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('baseline','audit','verify'));a=p.parse_args()
    if a.mode=='baseline':protected_baseline()
    elif a.mode=='verify':print(verify_protected())
    else:audit()
