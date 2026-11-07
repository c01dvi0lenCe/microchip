"""Read-only, condition-local seed-paired S2 statistics; no prediction input."""
from pathlib import Path
from statistics import mean
from ..batch import _wilson, _bootstrap, _write_csv, _write_json
from .spec import CONDITIONS, METHODS
from .study import _rows

COUNTS=('planned_steps','attempted_steps','reference_arrivals','supported_confirmations',
        'all_supported_confirmations','late_supported_confirmations','premature_confirmations',
        'unsupported_confirmations','timing_uncertain_confirmations','unassessable_confirmations',
        'missed_supported_confirmation','no_prediction_reference','confirmation_right_censored',
        'reference_right_censored','unattempted_steps','infrastructure_unknown','duplicate_events',
        'wrong_target_events','wrong_step_events','outside_task_events','issued_confirmation_events')


def _number(row,key):
    value=row.get(key)
    return None if value in (None,'') else float(value)


def summarize_group(rows):
    if not rows:raise ValueError('empty condition/method group')
    if len({int(r['seed']) for r in rows})!=len(rows):raise ValueError('duplicate seed in group')
    counts={k:sum(int(r.get(k,0) or 0) for r in rows) for k in COUNTS}
    n=counts['planned_steps'];refs=counts['reference_arrivals']
    result=dict(counts,seed_n=len(rows),simulation=True)
    for name,key,denom in [('S_H_yield','supported_confirmations',refs),
            ('premature_rate','premature_confirmations',n),('unsupported_rate','unsupported_confirmations',n),
            ('miss_rate','missed_supported_confirmation',refs)]:
        result[name]=counts[key]/denom if denom else None
        result[name+'_lo'],result[name+'_hi']=_wilson(counts[key],denom)
        result[name+'_denominator']=denom
    supported=[r for r in rows if int(r.get('supported_confirmations',0))]
    for side in ('lower','upper'):
        values=[_number(r,'latency_'+side+'_s') for r in supported]
        if any(x is None for x in values):raise ValueError('supported record missing latency')
        result['mean_latency_'+side+'_s']=mean(values) if values else None
    result['latency_n']=len(supported)
    return result


def paired_contrast(rows,baseline,comparison,*,repeats=2000):
    selected=[r for r in rows if r['method'] in (baseline,comparison)]
    if len({r['condition'] for r in selected})!=1:raise ValueError('contrast requires one condition')
    maps={m:{} for m in (baseline,comparison)}
    for row in selected:
        key=int(row['seed']);group=maps[row['method']]
        if key in group:raise ValueError('duplicate method/seed')
        group[key]=row
    if not maps[baseline] or maps[baseline].keys()!=maps[comparison].keys():
        raise ValueError('incomplete paired denominator')
    pairs=[(maps[baseline][seed],maps[comparison][seed]) for seed in sorted(maps[baseline])]
    for a,b in pairs:
        if int(a['reference_arrivals'])!=int(b['reference_arrivals']):raise ValueError('paired reference differs')
    condition=selected[0]['condition'];key=f'S2:{condition}:{baseline}:{comparison}'
    result=dict(condition=condition,baseline=baseline,comparison=comparison,paired_planned_n=len(pairs),
                simulation=True,bootstrap_repeats=repeats)
    for name,field,ref_only in [('support','supported_confirmations',True),
            ('premature','premature_confirmations',False),('unsupported','unsupported_confirmations',False),
            ('miss','missed_supported_confirmation',True)]:
        eligible=[p for p in pairs if not ref_only or int(p[0]['reference_arrivals'])]
        differences=[int(b.get(field,0))-int(a.get(field,0)) for a,b in eligible]
        result[name+'_difference']=mean(differences) if differences else None
        result[name+'_difference_lo'],result[name+'_difference_hi']=_bootstrap(differences,mean,repeats,key+name)
        result[name+'_paired_n']=len(differences)
    dual=[(a,b) for a,b in pairs if int(a.get('supported_confirmations',0)) and int(b.get('supported_confirmations',0))]
    result['dual_supported_n']=len(dual);result['latency_excluded_n']=len(pairs)-len(dual)
    for side in ('lower','upper'):
        differences=[]
        for a,b in dual:
            x,y=_number(a,'latency_'+side+'_s'),_number(b,'latency_'+side+'_s')
            if x is None or y is None:raise ValueError('supported pair missing latency')
            differences.append(y-x)
        stem='latency_difference_s' if side=='lower' else 'latency_upper_difference_s'
        result[stem]=mean(differences) if differences else None
        result[stem+'_lo'],result[stem+'_hi']=_bootstrap(differences,mean,repeats,key+'latency'+side)
    return result


def analyse(study):
    from .confirmatory import audit_confirmatory
    root=Path(study);output=root/'statistics'
    if output.exists():raise FileExistsError(output)
    audit_confirmatory(root)
    rows=_rows(root/'step_scores.csv');aux=_rows(root/'diagnostic_scores.csv')
    summary=[];contrasts=[];diagnostic=[]
    for condition in CONDITIONS:
        group=[r for r in rows if r['condition']==condition]
        for method in METHODS:
            summary.append(dict(condition=condition,method=method,
                category=next(r['category'] for r in group if r['method']==method),
                **summarize_group([r for r in group if r['method']==method])))
        for baseline,comparison in [('BTQ','F_arrival'),('BTQ','BTQ+S'),('BTQ','BTQ+K')]:
            contrasts.append(paired_contrast(group,baseline,comparison))
        joined=group+[r for r in aux if r['condition']==condition]
        for baseline,comparison in [('B_single_frame','BQ_single_frame'),('BQ_single_frame','BTQ')]:
            diagnostic.append(paired_contrast(joined,baseline,comparison))
    output.mkdir()
    _write_csv(output/'condition_statistics.csv',summary)
    _write_csv(output/'paired_contrasts.csv',contrasts)
    _write_csv(output/'diagnostic_contrasts.csv',diagnostic)
    result=dict(condition_groups=len(summary),primary_contrasts=len(contrasts),auxiliary_contrasts=len(diagnostic),
        simulation=True,independent_unit='seed within condition',cross_condition_pooling=False,
        latency_population='dual H-supported only; all other pairs retained in rate denominators',
        bootstrap_repeats=2000,bootstrap_rng='private SHA256-derived RNG, BOOTSTRAP_SEED=20261020',
        interpretation='conditional simulation; zero paired interval is not proof of zero physical risk')
    _write_json(output/'statistics_manifest.json',result)
    return result
