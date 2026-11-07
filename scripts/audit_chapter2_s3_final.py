"""G5 independent saved-data audit. No model, controller or scorer execution.

Reuses the independently hand-tested G0-G2 arithmetic, not algorithm/scorer
code. New checks cover formal plan, actual stored arrays and seed intervals.
"""
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import audit_chapter2_s3 as independent

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
DATA=BASE/'2026-10-26_S3正式仿真_v1'
OUT=BASE/'2026-10-26_S3正式验收与论文图_v1'
G3=BASE/'2026-10-26_S3_G3协议冻结_v1'

def core_hash_errors(expected,actual):return [name for name,h in expected.items() if actual.get(name)!=h]

def check_array_payload(arrays,external):
    errors=[]
    for k in ('world_noise','camera_errors','camera_uniform'):
        if hashlib.sha256(arrays[k].tobytes(order='C')).hexdigest()!=external[k]:errors.append('array_'+k)
    if float(arrays['speed_factor'])!=external['speed_factor']:errors.append('speed_factor')
    return errors

def independent_wilson(k,n):
    z=1.959963984540054;q=k/n;d=1+z*z/n
    c=(q+z*z/(2*n))/d;h=z*math.sqrt(q*(1-q)/n+z*z/(4*n*n))/d
    return max(0.,c-h),min(1.,c+h)

def verify_statistics(metrics):
    errors=[];summary=independent.read_csv(DATA/'formal_summary.csv');paired=independent.read_csv(DATA/'paired_contrasts.csv')
    for row in summary:
        rs=[r for r in metrics if all(r[k]==row[k] for k in ('cohort','scenario','method','protection'))]
        if len(rs)!=20:errors.append('summary_20_trials')
        complete=sum(r['path_complete'] for r in rs);unsafe=sum(r['unsupported_requests']>0 for r in rs)
        lo,hi=independent_wilson(complete,len(rs));u,v=independent_wilson(unsafe,len(rs))
        expected=dict(planned_trials=20,planned_steps=60,path_complete=complete,path_rate=complete/20,path_ci_low=lo,path_ci_high=hi,
                      unsafe_trials=unsafe,unsafe_rate=unsafe/20,unsafe_ci_low=u,unsafe_ci_high=v,
                      budgetized_mean_s=sum(r['execution_time_s'] if r['path_complete'] else 24. for r in rs)/20)
        for k,val in expected.items():
            if not independent.same(val,row[k]):errors.append('summary:'+str(row['scenario'])+':'+row['method']+':'+k)
    for r in paired:
        a={m['seed']:m for m in metrics if m['cohort']=='main' and m['scenario']==r['scenario'] and m['method']==r['left']}
        b={m['seed']:m for m in metrics if m['cohort']=='main' and m['scenario']==r['scenario'] and m['method']==r['right']}
        field=r['metric']
        seeds=[s for s in sorted(a) if not a[s]['infrastructure_invalid'] and not b[s]['infrastructure_invalid']]
        if field=='conditional_both_success_time_s':seeds=[s for s in seeds if a[s]['path_complete'] and b[s]['path_complete']]
        def get(m):
            if field=='path_rate':return int(m['path_complete'])
            if field=='unsafe_trial_rate':return int(m['unsupported_requests']>0)
            if field=='conditional_both_success_time_s':return m['execution_time_s']
            if field=='budgetized_completion_s':return m['execution_time_s'] if m['path_complete'] else 24.
            return m[field]
        d=np.asarray([get(a[s])-get(b[s]) for s in seeds],float)
        expected=dict(n=len(d),difference=None,ci_low=None,ci_high=None)
        if len(d):
            rng=np.random.default_rng(np.random.SeedSequence([20261026,303]));ix=rng.integers(0,len(d),(2000,len(d)))
            samples=np.mean(d[ix],axis=1);lo,hi=np.quantile(samples,[.025,.975])
            expected.update(difference=float(np.mean(d)),ci_low=float(lo),ci_high=float(hi))
        for key,val in expected.items():
            if not independent.same(val,r[key]):errors.append('paired:'+r['scenario']+':'+field+':'+key)
    return errors

def run():
    OUT.mkdir(parents=True,exist_ok=True);qa=OUT/'QA';qa.mkdir(exist_ok=True)
    if (qa/'independent_final_audit.json').exists():raise FileExistsError('audit report exists; inspect rather than overwrite')
    contract=json.loads((G3/'S3_正式冻结协议.json').read_text(encoding='utf-8'))
    core=contract['source_hashes'];metrics=independent.read_csv(DATA/'formal_trials.csv')
    expected=Counter((r['cohort'],r['scenario'],r['seed'],r['method'],r['protection'],r['phase_mode']) for r in contract['plan'])
    errors=[]
    if Counter(independent.identity(r) for r in metrics)!=expected:errors.append('800 planned identities mismatch')
    aggsteps=independent.read_csv(DATA/'formal_steps.csv')
    if len(aggsteps)!=2400:errors.append('2400 planned steps missing')
    original_verify=independent.verify_files
    def formal_files(path,manifest):
        errs=core_hash_errors(core,manifest['source_hashes'])
        proxy=dict(manifest,source_hashes=core)
        e,count,masks,captures=original_verify(path,proxy);errs.extend(e)
        for name,h in manifest['source_hashes'].items():
            if independent.sha(path/'source_code'/name)!=h or independent.sha(ROOT/name)!=h:errs.append('extra_source_hash:'+name)
        if not manifest.get('actual_random_arrays_saved'):errs.append('random_arrays_not_saved')
        with np.load(path/'exogenous_arrays.npz',allow_pickle=False) as arrays:errs.extend(check_array_payload(arrays,manifest['exogenous']))
        if manifest.get('G3_contract_sha256')!=independent.sha(G3/'S3_正式冻结协议.json'):errs.append('G3_contract_hash')
        return errs,count,masks,captures
    independent.verify_files=formal_files
    groups=defaultdict(list);events=[];steps=[];files=masks=0;results=[]
    try:
        for i,m in enumerate(metrics):
            path=DATA/m['relative_trial_path'];r=independent.audit_trial(path,m)
            files+=r['files'];masks+=r['masks'];errors.extend(dict(trial_id=m['trial_id'],error=e) for e in r['errors'])
            d=r['data'];groups[m['scenario'],m['seed'],m['phase_mode']].append(d)
            events.extend(d['independent']);steps.extend(dict(s,trial_id=m['trial_id'],cohort=m['cohort']) for s in d['independent_steps'])
            # Truth and processed-frame rows have already been audited and their
            # normalized prefix hashed. Pairing/fork checks need only captures
            # and events; do not retain every truth tick for all 800 trials.
            d.pop('truth',None);d.pop('frames',None)
            results.append(dict(trial_id=m['trial_id'],errors=len(r['errors']),files=r['files'],masks=r['masks'],manifest_sha256=independent.sha(path/'trial_manifest.json')))
            if (i+1)%40==0:print('independent formal audit',i+1,'/800; errors=',len(errors),flush=True)
    finally:independent.verify_files=original_verify
    prefixes=0;forks=0
    for key,rs in groups.items():
        if len({independent.digest(r['metrics']['exogenous']) for r in rs})!=1:errors.append(['external pairing',key])
        if key[2]=='end_to_end':
            prefixes+=1
            if len({r['prefix_hash'] for r in rs})!=1:errors.append(['P0 pairing',key])
        if any(independent.mask_fork_witness(a,b) for i,a in enumerate(rs) for b in rs[i+1:]):forks+=1
    recorded=independent.read_csv(DATA/'request_applied_evaluation.csv')
    context=('scenario','seed','method','protection','phase_mode')
    errors.extend(independent.compare_ledger(recorded,[{k:v for k,v in r.items() if k not in context} for r in events],('trial_id','request_id')))
    errors.extend(independent.compare_ledger(aggsteps,steps,('trial_id','step')))
    errors.extend(verify_statistics(metrics))
    independent.write_csv(qa/'independent_events.csv',events);independent.write_csv(qa/'independent_steps.csv',steps)
    report=dict(passed=not errors,errors=errors,records=len(metrics),planned_steps=len(steps),files_verified=files,masks_verified=masks,
                actual_random_array_files_verified=len(metrics),common_P0_groups=prefixes,control_fork_groups=forks,paired_groups=len(groups),
                events=len(events),supported_requests=sum(r['supported_at_request'] for r in events),
                supported_applied=sum(r['supported_at_applied'] is True for r in events),trials=results,
                new_simulation_or_algorithm_runs=0,uses_original_reference_or_scorer=False,
                audit_script_sha256=independent.sha(Path(__file__)),independent_arithmetic_sha256=independent.sha(Path(independent.__file__)))
    (qa/'independent_final_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','records','planned_steps','events','masks_verified')},ensure_ascii=False))
    if errors:raise RuntimeError('formal audit failed; no scientific results may be claimed')

if __name__=='__main__':run()
