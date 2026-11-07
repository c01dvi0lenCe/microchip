"""Prespecified paired-seed summaries; no simulation or truth regeneration."""
from collections import defaultdict,Counter
import hashlib
import json
import math
import numpy as np

def wilson(k,n):
    if not n:return None
    z=1.959963984540054;p=k/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den;radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0.,center-radius),min(1.,center+radius)

def binary_outcome_bounds(values):
    n=len(values);success=sum(v is True for v in values);unknown=sum(v is None for v in values)
    return dict(planned=n,known_positive=success,unknown=unknown,lower_yield=success/n if n else None,
                upper_yield=(success+unknown)/n if n else None,wilson=wilson(success,n))

def paired_summary(left,right,key):
    if set(left)!=set(right):raise ValueError('paired seeds do not match')
    seeds=sorted(left);d=np.array([left[s]-right[s] for s in seeds],float)
    if not len(d):return dict(n=0,difference=None,ci_low=None,ci_high=None)
    rng=np.random.default_rng(np.random.SeedSequence([20261026,303]))
    b=d[rng.integers(0,len(d),size=(2000,len(d)))].mean(axis=1)
    lo,hi=np.quantile(b,[.025,.975])
    return dict(n=len(d),difference=float(d.mean()),ci_low=float(lo),ci_high=float(hi))

def outcome(row):
    return None if row['infrastructure_invalid'] else bool(row['path_complete'])

def summarize_trials(metrics):
    groups=defaultdict(list)
    for r in metrics:groups[r['cohort'],r['scenario'],r['method'],r['protection']].append(r)
    output=[]
    for (cohort,scenario,method,protection),rs in groups.items():
        n=len(rs);success=[r for r in rs if r['path_complete'] and not r['infrastructure_invalid']]
        path=binary_outcome_bounds([outcome(r) for r in rs])
        unsafe=binary_outcome_bounds([None if r['infrastructure_invalid'] else r.get('unsupported_requests',0)>0 for r in rs])
        row=dict(cohort=cohort,scenario=scenario,method=method,protection=protection,planned_trials=n,planned_steps=3*n,
                 path_complete=len(success),path_rate=path['lower_yield'],path_rate_upper=path['upper_yield'],
                 path_ci_low=path['wilson'][0],path_ci_high=path['wilson'][1],unknown_trials=path['unknown'],
                 unsafe_trials=unsafe['known_positive'],unsafe_rate=unsafe['lower_yield'],unsafe_rate_upper=unsafe['upper_yield'],
                 unsafe_ci_low=unsafe['wilson'][0],unsafe_ci_high=unsafe['wilson'][1],
                 successful_time_n=len(success),successful_time_mean_s=float(np.mean([r['execution_time_s'] for r in success])) if success else None,
                 budgetized_mean_s=float(np.mean([r.get('budgetized_completion_s',24.) for r in rs])),
                 actual_time_mean_s=float(np.mean([r['execution_time_s'] for r in rs if r.get('execution_time_s') is not None])) if any(r.get('execution_time_s') is not None for r in rs) else None)
        for k in ('source_prepared','transport_started','transport_complete','supported_confirmations','unsupported_requests','premature_requests',
                  'timing_uncertain_requests','missed_confirmations','unattempted_steps','reference_arrived_steps','reference_unknown_steps','censored_steps',
                  'retries','recoveries','recovery_resends','unknown_frames','missing_mask_frames','supported_at_applied'):
            row[k]=sum(r.get(k,0) for r in rs)
        row['terminals']=dict(Counter(r['terminal_outcome'] for r in rs));row['stop_reasons']=dict(Counter(r['stop_reason'] for r in rs))
        output.append(row)
    paired=[]
    for scenario in sorted({r['scenario'] for r in metrics if r['cohort']=='main'}):
        for left,right in (('BTQ','A_fixed'),('BTQ','B_single'),('F_full','BTQ')):
            a={r['seed']:r for r in metrics if r['cohort']=='main' and r['scenario']==scenario and r['method']==left}
            b={r['seed']:r for r in metrics if r['cohort']=='main' and r['scenario']==scenario and r['method']==right}
            for metric,fn in (('path_rate',lambda r:float(r['path_complete'])),('unsafe_trial_rate',lambda r:float(r.get('unsupported_requests',0)>0)),
                              ('budgetized_completion_s',lambda r:r.get('budgetized_completion_s',24.)),('retries',lambda r:r.get('retries',0)),
                              ('recoveries',lambda r:r.get('recoveries',0))):
                valid=sorted(s for s in a if not a[s]['infrastructure_invalid'] and not b[s]['infrastructure_invalid'])
                paired.append(dict(scenario=scenario,left=left,right=right,metric=metric,planned_pairs=len(a),unknown_pairs=len(a)-len(valid),
                                   **paired_summary({s:fn(a[s]) for s in valid},{s:fn(b[s]) for s in valid},scenario+left+right+metric)))
            valid=[s for s in a if a[s]['path_complete'] and b[s]['path_complete']]
            paired.append(dict(scenario=scenario,left=left,right=right,metric='conditional_both_success_time_s',planned_pairs=len(a),unknown_pairs=0,
                               **paired_summary({s:a[s]['execution_time_s'] for s in valid},{s:b[s]['execution_time_s'] for s in valid},scenario+left+right+'time')))
    return output,paired
