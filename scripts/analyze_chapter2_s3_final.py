"""Secondary prespecified tables from frozen S3 formal CSV, no simulation."""
from collections import Counter
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from audit_chapter2_s3_final import DATA,OUT,G3
from audit_chapter2_s3 import read_csv,write_csv,sha
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dmf.chapter2_sim.s3_final.statistics import paired_summary

def interval(values):
    a=np.asarray(values,float)
    if not len(a):return dict(n=0,mean=None,ci_low=None,ci_high=None)
    rng=np.random.default_rng(np.random.SeedSequence([20261026,303]));b=np.mean(a[rng.integers(0,len(a),(2000,len(a)))],axis=1)
    lo,hi=np.quantile(b,[.025,.975]);return dict(n=len(a),mean=float(np.mean(a)),ci_low=float(lo),ci_high=float(hi))

def main():
    metrics=read_csv(DATA/'formal_trials.csv');events=read_csv(DATA/'request_applied_evaluation.csv')
    dest=OUT/'tables';dest.mkdir(parents=True,exist_ok=True)
    bridge=[];identity=[];latency=[];times=[];actions=[];stage=[]
    for s in ('partial_stall','deviation'):
        cells={(m,p):{r['seed']:r for r in metrics if r['scenario']==s and r['phase_mode']=='end_to_end' and r['method']==m and r['protection']==p}
               for m in ('BTQ','F_full') for p in ('P_B','P_F')}
        for p in ('P_B','P_F'):
            for seed in range(265000,265020):
                a,b=[cells[m,p][seed] for m in ('BTQ','F_full')]
                fields=('event','time_s','step','epoch','attempt','phase','source','target','activated_target','action','activation_step')
                es=[[{k:e.get(k) for k in fields} for e in read_csv(DATA/r['relative_trial_path']/'observations/events.csv') if e['event']!='ArrivalEvent'] for r in (a,b)]
                identity.append(dict(scenario=s,seed=seed,protection=p,control_events_equal=es[0]==es[1]))
        getters={'path_rate':lambda r:float(r['path_complete']),'unsafe_rate':lambda r:float(r['unsupported_requests']>0),
                 'budgetized_completion_s':lambda r:r['budgetized_completion_s'],'retries':lambda r:r['retries'],
                 'recoveries':lambda r:r['recoveries'],'recovery_resends':lambda r:r['recovery_resends']}
        for metric,get in getters.items():
            arrays={k:{seed:get(r) for seed,r in v.items()} for k,v in cells.items()}
            pairs=[('gate_at_P_B',('F_full','P_B'),('BTQ','P_B')),('gate_at_P_F',('F_full','P_F'),('BTQ','P_F')),
                   ('protection_at_BTQ',('BTQ','P_F'),('BTQ','P_B')),('protection_at_F',('F_full','P_F'),('F_full','P_B'))]
            for name,a,b in pairs:bridge.append(dict(scenario=s,metric=metric,contrast=name,**paired_summary(arrays[a],arrays[b],s+metric+name)))
            pf={seed:arrays['F_full','P_F'][seed]-arrays['F_full','P_B'][seed] for seed in range(265000,265020)}
            pb={seed:arrays['BTQ','P_F'][seed]-arrays['BTQ','P_B'][seed] for seed in range(265000,265020)}
            bridge.append(dict(scenario=s,metric=metric,contrast='interaction_difference_in_differences',**paired_summary(pf,pb,s+metric+'interaction')))
    for row in read_csv(DATA/'formal_summary.csv'):
        group=[r for r in metrics if all(r[k]==row[k] for k in ('cohort','scenario','method','protection'))]
        base={k:row[k] for k in ('cohort','scenario','method','protection')}
        for field in ('budgetized_completion_s','execution_time_s','retries','recoveries','recovery_resends'):
            values=[r[field] for r in group if r.get(field) is not None]
            times.append(dict(base,metric=field,**interval(values)))
        supported=[e for e in events if e['trial_id'] in {r['trial_id'] for r in group} and e['supported_at_request']]
        per_trial=[]
        for r in group:
            es=[e for e in supported if e['trial_id']==r['trial_id']]
            if es:per_trial.append(dict(seed=r['seed'],lower=np.mean([e['delay_lower_s'] for e in es]),upper=np.mean([e['delay_upper_s'] for e in es])))
        latency.append(dict(base,event_n=len(supported),trial_n=len(per_trial),planned_trial_n=20,
                            lower=interval([x['lower'] for x in per_trial]),upper=interval([x['upper'] for x in per_trial])))
        for action in ('Update','Complete'):
            es=[e for e in events if e['trial_id'] in {r['trial_id'] for r in group} and e['action']==action]
            actions.append(dict(base,action=action,planned_trials=20,planned_steps=60,requests=len(es),
                supported_requests=sum(e['supported_at_request'] for e in es),unsupported_requests=sum(not e['supported_at_request'] for e in es),
                premature=sum(e['request_label']=='premature' for e in es),timing_uncertain=sum(e['request_label']=='timing_uncertain' for e in es),
                actual_applied=sum(e['applied_s'] is not None for e in es),supported_applied=sum(e['supported_at_applied'] is True for e in es),
                unsupported_applied=sum(e['supported_at_applied'] is False for e in es)))
        stage.append(dict(base,planned_trials=20,planned_steps=60,**{k:sum(r[k] for r in group) for k in
            ('source_prepared','transport_started','transport_complete','path_complete','reference_arrived_steps','supported_confirmations',
             'unsupported_requests','missed_confirmations','unattempted_steps','reference_unknown_steps','censored_steps','unknown_frames','missing_mask_frames')},
            stop_reasons=dict(Counter(r['stop_reason'] for r in group))))
    for name,data in (('bridge_paired_contrasts',bridge),('bridge_control_identity',identity),('time_and_action_intervals',times),
                      ('conditional_confirmation_latency',latency),('request_vs_applied',actions),('complete_stage_denominators',stage)):
        write_csv(dest/(name+'.csv'),data)
    note=dict(formal_trials=len(metrics),bridge_equal_pairs=sum(r['control_events_equal'] for r in identity),bridge_pairs=len(identity),
              source_inputs={name:sha(DATA/name) for name in ('formal_trials.csv','formal_steps.csv','formal_summary.csv','paired_contrasts.csv','request_applied_evaluation.csv')},
              no_new_research_runs=True,latency_unit='mean within trial; seed-level interval, event_n is not independent n',
              compatibility_metadata_erratum='Inherited trials.csv formal_seed_runs=0 is a legacy counter, not study status. Formal identity/seed and trial_manifest schema/purpose/formal_seed_runs=1 are authoritative. Original bytes kept.')
    (dest/'analysis_manifest.json').write_text(json.dumps(note,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:note[k] for k in ('formal_trials','bridge_equal_pairs','bridge_pairs')},ensure_ascii=False))

if __name__=='__main__':main()
