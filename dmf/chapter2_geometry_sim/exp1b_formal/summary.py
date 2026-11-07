"""Stable scientific tables; all conditions stay separate and every planned identity is checked."""
import csv
import json
from pathlib import Path
from collections import Counter
from .spec import planned_identities,validate_identities,STATISTICS_VERSION,LATENCY_POLICY
from . import statistics as stats

RATE_FIELDS=('reference_id','condition','stratum','method','endpoint','n_planned','n_known','n_unknown',
    'k','estimate','ident_lower','ident_upper','ci_lower','ci_upper','ci_method')
PAIR_FIELDS=('reference_id','condition','stratum','contrast','endpoint','n_planned','n_known','n_unknown',
    'estimate','ident_lower','ident_upper','ci_lower','ci_upper','discordant_plus','discordant_minus','ci_method')
LATENCY_FIELDS=('reference_id','condition','stratum','method','n_supported','median_s','ci_lower','ci_upper')
PAIRED_LATENCY_FIELDS=('reference_id','condition','stratum','contrast','n_joint','n_supported_a','n_supported_b',
    'median_difference_s','ci_lower','ci_upper','raw_differences_json')
COUNT_FIELDS=('reference_id','condition','stratum','method','primary_outcome','count','n_planned',
    'observation_censored_count','reference_censored_count','reference_unknown_count')
TABLE_FIELDS={'statistics_rates.csv':RATE_FIELDS,'paired_binary.csv':PAIR_FIELDS,
    'latency_summary.csv':LATENCY_FIELDS,'paired_latency.csv':PAIRED_LATENCY_FIELDS,'outcomes_counts.csv':COUNT_FIELDS}


def build_tables(records,config):
    validate_identities(records,planned_identities(config))
    tables={name:[] for name in TABLE_FIELDS}
    for reference in config['reference']['one_factor_sensitivity']:
        rid=reference['id']
        for condition in config['conditions']:
            cid=condition['id'];base=condition['strata']=='base'
            by_method={m['name']:[r for r in records if r['reference_id']==rid and r['condition']==cid
                and r['method']==m['name']] for m in config['methods']}
            strata=['base'] if base else ['low','high','mixture']
            for stratum in strata:
                subset=lambda rows: rows if stratum=='mixture' else [r for r in rows if r['stratum']==stratum]
                split=lambda rows:[[r for r in rows if r['stratum']==s] for s in ('low','high')]
                common=dict(reference_id=rid,condition=cid,stratum=stratum)
                for method,all_rows in by_method.items():
                    rows=subset(all_rows);key=dict(common,method=method)
                    for endpoint in (*stats.PRIMARY_ENDPOINTS,'reference_recall'):
                        value=stats.mixture_rate(split(all_rows),endpoint) if stratum=='mixture' else stats.rate(rows,endpoint)
                        tables['statistics_rates.csv'].append(dict(key,endpoint=endpoint,**value))
                    tables['latency_summary.csv'].append(dict(key,**stats.latency(rows,
                        stream=f'{rid}/{cid}/{stratum}/{method}',inferential=stratum!='mixture')))
                    counts=Counter(r['primary_outcome'] for r in rows)
                    for category in stats.CATEGORIES:
                        selected=[r for r in rows if r['primary_outcome']==category]
                        tables['outcomes_counts.csv'].append(dict(key,primary_outcome=category,count=counts[category],
                            n_planned=len(rows),observation_censored_count=sum(stats.flag(r.get('observation_right_censored')) for r in selected),
                            reference_censored_count=sum(stats.flag(r.get('reference_right_censored')) for r in selected),
                            reference_unknown_count=sum(not stats.flag(r.get('reference_known',True)) for r in selected)))
                for a,b in stats.CONTRASTS:
                    aa,bb=subset(by_method[a]),subset(by_method[b]);contrast=f'{a}_minus_{b}'
                    key=dict(common,contrast=contrast)
                    for endpoint in stats.PRIMARY_ENDPOINTS:
                        value=stats.mixture_paired(split(by_method[a]),split(by_method[b]),endpoint) if stratum=='mixture' else stats.paired_rate(aa,bb,endpoint)
                        tables['paired_binary.csv'].append(dict(key,endpoint=endpoint,**value))
                    tables['paired_latency.csv'].append(dict(key,**stats.paired_latency(aa,bb,
                        stream=f'{rid}/{cid}/{stratum}/{contrast}',inferential=stratum!='mixture')))
    return tables


def definitions(config):
    return dict(statistics_version=STATISTICS_VERSION,planned=dict(config['actual_plan']),
        no_cross_condition_grand_accuracy=True,no_correlated_cache_pooling=True,
        base_and_individual_strength_ci='two-sided Clopper-Pearson 95%',
        mixture_rate_ci='0.5 low + 0.5 high; simultaneous two-sided CP97.5% bounds; not pooled binomial',
        paired_ci='CP discordant-plus/minus with alpha=.05/(2*nstrata), weighted [pl-mu,pu-ml]',
        missing='keep planned N, k/N and [k/N,(k+u)/N]; unknown suppresses ordinary CI; partial-pair identification bounds retained',
        fixed_H='future censoring alone does not erase known by-H category or completed-reference miss',
        reference_recall='conditional on known completed reference arrivals; unattempted prediction stays unknown, never zero',
        latency='conditional supported latency; same-seed jointly supported pairs only; n<5 suppresses 10000 percentile bootstrap',
        latency_mixture_policy=LATENCY_POLICY,analysis_seed=stats.ANALYSIS_SEED,bootstrap_replicates=stats.BOOTSTRAPS,
        signed_deviation='signed decision minus first reference completion; negative values are not latency',
        seven_references='rescore identical saved predictions, not seven new trials',
        uncertainty='pointwise exploratory; no significance stars; degenerate bootstrap is not equivalence or physical precision')


def write_statistics(output,records,config):
    output=Path(output);tables=build_tables(records,config)
    for name,rows in tables.items():
        with (output/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=TABLE_FIELDS[name]);writer.writeheader();writer.writerows(rows)
    summary=definitions(config)
    summary['primary_categories']=list(stats.CATEGORIES)
    (output/'statistics_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary
