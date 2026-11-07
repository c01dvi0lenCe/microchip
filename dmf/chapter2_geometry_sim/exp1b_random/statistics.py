"""Exact binomial inversion without SciPy; development summaries are counts only."""
import math
from collections import Counter


def _cdf(k, n, p):
    if p <= 0: return 1.
    if p >= 1: return float(k >= n)
    return sum(math.comb(n, j)*p**j*(1-p)**(n-j) for j in range(k+1))


def _solve_cdf(k, n, probability):
    low, high = 0., 1.
    for _ in range(100):
        mid = (low+high)/2
        if _cdf(k, n, mid) > probability: low = mid
        else: high = mid
    return (low+high)/2


def clopper_pearson(k, n, alpha=.05):
    if type(k) is not int or type(n) is not int or n <= 0 or not 0 <= k <= n or not 0 < alpha < 1:
        raise ValueError('Valid integer binomial counts and alpha required')
    return (0. if k == 0 else _solve_cdf(k-1, n, 1-alpha/2),
            1. if k == n else _solve_cdf(k, n, alpha/2))


def paired_binary_difference(a, b, alpha=.05, number_of_strata=1):
    if len(a) != len(b) or not a or any(v not in (0, 1) for v in [*a, *b]):
        raise ValueError('Nonempty matched binary arrays required')
    n = len(a); plus = sum(x == 1 and y == 0 for x, y in zip(a, b))
    minus = sum(x == 0 and y == 1 for x, y in zip(a, b))
    pl, pu = clopper_pearson(plus, n, alpha/(2*number_of_strata))
    ml, mu = clopper_pearson(minus, n, alpha/(2*number_of_strata))
    return dict(estimate=(plus-minus)/n, lower=pl-mu, upper=pu-ml, n=n,
                discordant_plus=plus, discordant_minus=minus, method='Bonferroni discordant-cell exact bounds')


def summarize_development(records):
    counts = Counter((r['condition'], r['method'], r['primary_outcome']) for r in records)
    return dict(performance_CI_reported=False, planned_method_records=len(records),
        unique_development_seeds=len({r['seed'] for r in records}), counts_only=True,
        counts=[dict(condition=c, method=m, primary_outcome=o, count=n)
                for (c, m, o), n in sorted(counts.items())])
