"""Fixed-H full-denominator, stratified exploratory inference (no grand pooling)."""
import hashlib
import json
import math
import numpy as np
from ..exp1b_random.statistics import clopper_pearson

PRIMARY_ENDPOINTS = ('before_reference_per_planned','no_reference_confirmation_per_planned',
    'reference_supported_per_planned')
CONTRASTS = (('M2','M1'),('M3','M2'),('GQ','M1'),('M2','GQ'),('M2_S','M2'),('M2_K','M2'))
CATEGORIES = ('reference_supported','before_reference','no_reference_confirmation',
    'outside_reference_support','reference_not_confirmed','no_reference_no_confirmation',
    'confirmation_reference_pending_at_H','no_confirmation_reference_pending_at_H',
    'permanent_stall_no_confirmation','unattempted')
ANALYSIS_SEED = 930100
BOOTSTRAPS = 10000


def flag(value): return value is True or value == 'True' or value == 'true' or value == 1


def number(value):
    if value is None or value == '': return None
    result = float(value)
    if not math.isfinite(result): raise ValueError('Non-finite scientific value')
    return result


def endpoint(row,name):
    if name not in (*PRIMARY_ENDPOINTS,'reference_recall'):
        raise ValueError('Undeclared endpoint')
    if row.get('status') != 'executed' or row.get('primary_outcome') == 'unattempted': return None
    if not flag(row.get('reference_known',True)): return None
    if row['primary_outcome'] not in CATEGORIES: raise ValueError('Unknown primary category')
    if name == 'reference_recall':
        if number(row.get('reference_arrivals')) in (None,0): return None
        return int(row['primary_outcome']=='reference_supported')
    return int(row['primary_outcome'] == name.removesuffix('_per_planned'))


def _recall_rows(rows):
    return [r for r in rows if flag(r.get('reference_known',True))
        and (number(r.get('reference_arrivals')) or 0)>0]


def rate(rows,name,alpha=.05):
    if name=='reference_recall': rows=_recall_rows(rows)
    values=[endpoint(r,name) for r in rows];n=len(values);u=sum(v is None for v in values)
    k=sum(v for v in values if v is not None)
    lo,hi=clopper_pearson(k,n,alpha) if n and not u else (None,None)
    return dict(n_planned=n,n_known=n-u,n_unknown=u,k=k,estimate=k/n if n else None,
        ident_lower=k/n if n else None,ident_upper=(k+u)/n if n else None,
        ci_lower=lo,ci_upper=hi,ci_method=f'two-sided Clopper-Pearson {100*(1-alpha):g}%' if lo is not None else 'suppressed_unknown_or_empty')


def mixture_rate(strata,name):
    if len(strata)!=2: raise ValueError('Exactly low/high strata required')
    parts=[rate(rows,name,.025) for rows in strata]
    n=sum(p['n_planned'] for p in parts);u=sum(p['n_unknown'] for p in parts)
    def weighted(key):
        return sum(p[key]*.5 for p in parts) if all(p[key] is not None for p in parts) else None
    return dict(n_planned=n,n_known=n-u,n_unknown=u,k=sum(p['k'] for p in parts),
        estimate=weighted('estimate'),ident_lower=weighted('ident_lower'),ident_upper=weighted('ident_upper'),
        ci_lower=weighted('ci_lower') if not u else None,ci_upper=weighted('ci_upper') if not u else None,
        ci_method='equal-weight 0.5 low + 0.5 high; simultaneous CP97.5% stratum bounds' if not u and all(p['n_planned'] for p in parts) else 'suppressed_unknown_or_empty')


def _matched(a,b):
    aa={str(r['seed']):r for r in a};bb={str(r['seed']):r for r in b}
    if len(aa)!=len(a) or len(bb)!=len(b) or set(aa)!=set(bb):
        raise ValueError('Unique identical planned seed identities required for a pair')
    return [(aa[k],bb[k]) for k in sorted(aa,key=int)]


def paired_rate(a,b,name,number_of_strata=1):
    pairs=[(endpoint(x,name),endpoint(y,name)) for x,y in _matched(a,b)]
    n=len(pairs);known=[(x,y) for x,y in pairs if x is not None and y is not None]
    plus=sum(x==1 and y==0 for x,y in known);minus=sum(x==0 and y==1 for x,y in known)
    lower=upper=0.
    for x,y in pairs:
        lower+=(x if x is not None else 0)-(y if y is not None else 1)
        upper+=(x if x is not None else 1)-(y if y is not None else 0)
    ci_lower=ci_upper=None
    if n and len(known)==n:
        alpha=.05/(2*number_of_strata)
        pl,pu=clopper_pearson(plus,n,alpha);ml,mu=clopper_pearson(minus,n,alpha)
        ci_lower,ci_upper=pl-mu,pu-ml
    return dict(n_planned=n,n_known=len(known),n_unknown=n-len(known),
        estimate=(plus-minus)/n if n else None,ident_lower=lower/n if n else None,
        ident_upper=upper/n if n else None,ci_lower=ci_lower,ci_upper=ci_upper,
        discordant_plus=plus,discordant_minus=minus,
        ci_method='Bonferroni exact discordant-cell bounds' if ci_lower is not None else 'suppressed_unknown_or_empty')


def mixture_paired(strata_a,strata_b,name):
    if len(strata_a)!=2 or len(strata_b)!=2: raise ValueError('Exactly low/high strata required')
    parts=[paired_rate(a,b,name,2) for a,b in zip(strata_a,strata_b)]
    result={k:sum(p[k] for p in parts) for k in ('n_planned','n_known','n_unknown','discordant_plus','discordant_minus')}
    for key in ('estimate','ident_lower','ident_upper','ci_lower','ci_upper'):
        result[key]=sum(p[key]*.5 for p in parts) if all(p[key] is not None for p in parts) else None
    result['ci_method']='equal-weight simultaneous Bonferroni discordant-cell bounds' if not result['n_unknown'] else 'suppressed_unknown_or_empty'
    return result


def bootstrap_median(values,stream):
    values=np.asarray(values,dtype=float)
    if len(values)<5: return None,None
    digest=hashlib.sha256(stream.encode('utf-8')).digest()
    entropy=[ANALYSIS_SEED,*[int.from_bytes(digest[i:i+4],'little') for i in range(0,16,4)]]
    rng=np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))
    samples=values[rng.integers(0,len(values),size=(BOOTSTRAPS,len(values)))]
    lo,hi=np.percentile(np.median(samples,axis=1),[2.5,97.5])
    return float(lo),float(hi)


def supported_latency(row):
    if endpoint(row,'reference_supported_per_planned')!=1: return None
    value=number(row.get('latency_s'))
    if value is None or value < -1e-9: raise ValueError('Reference-supported latency must be known and nonnegative')
    return max(value,0.)


def latency(rows,stream='',inferential=True):
    values=[v for row in rows if (v:=supported_latency(row)) is not None]
    lo,hi=bootstrap_median(values,stream) if inferential else (None,None)
    return dict(n_supported=len(values),median_s=float(np.median(values)) if values else None,ci_lower=lo,ci_upper=hi)


def paired_latency(a,b,stream='',inferential=True):
    pairs=_matched(a,b);differences=[]
    for x,y in pairs:
        vx,vy=supported_latency(x),supported_latency(y)
        if vx is not None and vy is not None: differences.append(vx-vy)
    lo,hi=bootstrap_median(differences,stream) if inferential else (None,None)
    return dict(n_joint=len(differences),n_supported_a=sum(supported_latency(r) is not None for r in a),
        n_supported_b=sum(supported_latency(r) is not None for r in b),
        median_difference_s=float(np.median(differences)) if differences else None,
        ci_lower=lo,ci_upper=hi,raw_differences_json=json.dumps(differences,separators=(',',':')))
