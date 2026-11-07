"""G3-gated fixed formal plan; unchanged S3 run_trial and scoring."""
from collections import Counter
from dataclasses import dataclass,asdict
import hashlib
import json
from pathlib import Path
import shutil
import traceback
from unittest.mock import patch
import numpy as np
from ..s3.spec import S3Spec
from ..s3 import runner
from ..s3.persistence import save_trial
from ..s3.study import infrastructure_failure
from ..batch import _write_csv,_write_json
from .statistics import summarize_trials

ROOT=Path(__file__).resolve().parents[3]
G3=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果/2026-10-26_S3_G3协议冻结_v1')
VERSION='chapter2_s3_confirmatory_v1'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load_admission(path=G3/'S3_G4准入凭证.json'):
    path=Path(path);gate=json.loads(path.read_text(encoding='utf-8'))
    if not gate['technical_g3_passed'] or not gate['user_conditional_authorization']:raise ValueError('G3 or user authorization missing')
    if sha(path.parent/'S3_正式冻结协议.json')!=gate['contract_sha256']:raise ValueError('contract changed')
    if sha(path.parent/'QA/g3_audit.json')!=gate['audit_sha256']:raise ValueError('G3 audit changed')
    for name,h in gate['documents'].items():
        if sha(path.parent/name)!=h:raise ValueError('protocol document changed')
    for name,h in gate['source_hashes'].items():
        if sha(ROOT/name)!=h:raise ValueError('G3 scientific source changed: '+name)
    return gate

def formal_plan():
    scenarios=('normal','delayed','partial_stall','jitter','dropout','deviation','failure');methods=('A_fixed','B_single','BTQ','F_full')
    p=[dict(cohort='main',scenario=s,seed=i,method=m,protection=None,phase_mode='end_to_end') for s in scenarios for i in range(265000,265020) for m in methods]
    p += [dict(cohort='bridge',scenario=s,seed=i,method=m,protection=q,phase_mode='end_to_end') for s in ('partial_stall','deviation') for i in range(265000,265020) for m,q in (('F_full','P_B'),('BTQ','P_F'))]
    p += [dict(cohort='diagnostic',scenario=s,seed=i,method=m,protection=None,phase_mode='transport_only') for s in ('jitter','dropout') for i in range(265000,265020) for m in methods]
    return p

@dataclass(frozen=True)
class FormalSpec(S3Spec):
    version:str=VERSION
    def validate_seed(self,seed):
        if type(seed) is not int or seed not in range(265000,265020):raise ValueError('only frozen formal seeds allowed')

def capture_initial_arrays(call):
    """Observe/copy actual constructor output without additional RNG draws."""
    world_class=runner.DropletWorld;camera_class=runner.SyntheticCamera;captured={}
    def world(*args,**kwargs):
        obj=world_class(*args,**kwargs);captured['world_noise']=obj.noise.copy();captured['speed_factor']=np.array(obj.speed_factor);return obj
    def camera(*args,**kwargs):
        obj=camera_class(*args,**kwargs);captured['camera_errors']=obj.errors.copy();captured['camera_uniform']=obj.uniform.copy();return obj
    with patch.object(runner,'DropletWorld',world),patch.object(runner,'SyntheticCamera',camera):result=call()
    return result,captured

def persist(trial,path,spec,arrays,gate):
    save_trial(trial,path,spec)
    if arrays:
        for k in ('world_noise','camera_errors','camera_uniform'):
            if hashlib.sha256(arrays[k].tobytes(order='C')).hexdigest()!=trial.metrics['exogenous'][k]:raise ValueError('runtime array mismatch '+k)
        if float(arrays['speed_factor'])!=trial.metrics['exogenous']['speed_factor']:raise ValueError('speed factor mismatch')
        np.savez(path/'exogenous_arrays.npz',**arrays)
        _write_json(path/'random_sources.json',dict(origin='actual frozen World/Camera constructor arrays copied before movement, no extra RNG draws',
            simulation=True,seed=trial.metrics['seed'],streams=[[trial.metrics['seed'],101],[trial.metrics['seed'],202]],
            bit_generator='numpy.default_rng PCG64',arrays={k:dict(shape=list(a.shape),dtype=a.dtype.str,order='C',raw_sha256=hashlib.sha256(a.tobytes()).hexdigest()) for k,a in arrays.items()},
            activation_latency_s=.04,not_a_real_ack=True))
    manifest=json.loads((path/'trial_manifest.json').read_text(encoding='utf-8'))
    for p in Path(__file__).parent.glob('*.py'):
        rel=p.relative_to(ROOT);dest=path/'source_code'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);manifest['source_hashes'][rel.as_posix()]=sha(p)
    manifest.update(schema=VERSION,purpose='formal_prespecified_SIMULATION_not_physical_experiment',formal_seed_runs=1,
                    G3_contract_sha256=gate['contract_sha256'],actual_random_arrays_saved=bool(arrays),
                    frozen_scientific_sources_unchanged=True)
    manifest['files']={p.relative_to(path).as_posix():sha(p) for p in path.rglob('*') if p.is_file() and p.name!='trial_manifest.json'}
    _write_json(path/'trial_manifest.json',manifest)

def run_formal(output):
    gate=load_admission();output=Path(output)
    if output.exists():raise FileExistsError('formal output must be new; no overwrite/replacement')
    output.mkdir(parents=True);spec=FormalSpec()
    approved=json.loads((G3/'S3_正式冻结协议.json').read_text(encoding='utf-8'))
    if json.dumps(asdict(spec.common),sort_keys=True)!=json.dumps(approved['common'],sort_keys=True):raise ValueError('formal parameters differ from G3')
    plan=formal_plan();_write_json(output/'planned_trials.json',plan)
    _write_json(output/'config_manifest.json',dict(schema=VERSION,spec=asdict(spec),G3=gate,planned_trials=800,
        cohorts=dict(main=560,bridge=80,diagnostic=160),examples=[dict(scenario=s,seed=265000) for s in ('normal','deviation')]))
    metrics=[];steps=[];events=[]
    for i,item in enumerate(plan):
        try:trial,arrays=capture_initial_arrays(lambda:runner.run_trial(spec,**item))
        except Exception as exc:
            trial=infrastructure_failure(spec,item,exc);arrays={}
            _write_json(output/f'error-{i:03d}.json',dict(item=item,error=str(exc),traceback=traceback.format_exc()))
        path=output/'trials'/f"{i:03d}_{item['scenario']}_{item['seed']}_{item['method']}_{trial.metrics['protection']}"
        persist(trial,path,spec,arrays,gate);trial.metrics['relative_trial_path']=path.relative_to(output).as_posix()
        metrics.append(dict(trial.metrics));steps.extend(dict(s,trial_id=trial.trial_id,cohort=item['cohort']) for s in trial.steps)
        events.extend(dict(e,trial_id=trial.trial_id,cohort=item['cohort']) for e in trial.event_evaluation)
        if (i+1)%20==0:print(json.dumps(dict(completed=i+1,planned=800,cohort=item['cohort'],scenario=item['scenario']),ensure_ascii=False),flush=True)
    _write_csv(output/'formal_trials.csv',metrics);_write_csv(output/'formal_steps.csv',steps);_write_csv(output/'request_applied_evaluation.csv',events)
    summary,paired=summarize_trials(metrics);_write_csv(output/'formal_summary.csv',summary);_write_csv(output/'paired_contrasts.csv',paired)
    _write_json(output/'completion_manifest.json',dict(completed=len(metrics),planned=800,planned_steps=len(steps),
         cohorts=dict(Counter(m['cohort'] for m in metrics)),infrastructure_invalid=sum(m['infrastructure_invalid'] for m in metrics),
         methods_unchanged=True,seed_replacements=0,G3_contract_sha256=gate['contract_sha256']))
    load_admission();return output
