"""Hand-rolled distribution distances, rank checks and tests for the real-vs-synthetic comparison.

No scipy in the venv: the chi-square tail comes from the regularized upper incomplete gamma Q(a, x)
(series + Lentz continued fraction, after Numerical Recipes `gammq`); the two-proportion z-test uses
math.erfc. Distributions are Dict[str, float] keyed by category label in display order; a missing
key counts as zero share.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

NAN = float("nan")


def distribution(values: Iterable[str], categories: Sequence[str]) -> Dict[str, float]:
    """Share of each category among values that are in `categories`; other values are ignored.

    >>> distribution(["a", "b", "a", "zzz"], ["a", "b", "c"])
    {'a': 0.6666666666666666, 'b': 0.3333333333333333, 'c': 0.0}
    >>> distribution([], ["a"])
    {'a': 0.0}
    """
    counts = {category: 0 for category in categories}
    for value in values:
        if value in counts:
            counts[value] += 1
    total = sum(counts.values())
    return {category: (counts[category] / total if total else 0.0) for category in categories}


def _aligned(p: Dict[str, float], q: Dict[str, float]) -> Tuple[List[float], List[float]]:
    keys = list(p) + [key for key in q if key not in p]
    return [float(p.get(k, 0.0)) for k in keys], [float(q.get(k, 0.0)) for k in keys]


def tv_distance(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Total variation distance: 0 identical, 1 disjoint.

    >>> tv_distance({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5})
    0.0
    >>> tv_distance({"a": 1.0}, {"b": 1.0})
    1.0
    """
    a, b = _aligned(p, q)
    return 0.5 * sum(abs(x - y) for x, y in zip(a, b))


def _kl_bits(a: Sequence[float], m: Sequence[float]) -> float:
    return sum(x * math.log2(x / y) for x, y in zip(a, m) if x > 0)


def js_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Jensen-Shannon divergence in bits: 0 identical, 1 disjoint supports.

    >>> js_divergence({"a": 1.0}, {"b": 1.0})
    1.0
    >>> round(js_divergence({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}), 12)
    0.0
    """
    a, b = _aligned(p, q)
    m = [(x + y) / 2.0 for x, y in zip(a, b)]
    return 0.5 * _kl_bits(a, m) + 0.5 * _kl_bits(b, m)


def average_ranks(values: Sequence[float]) -> List[float]:
    """1-based ranks; ties share the average of the ranks they span.

    >>> average_ranks([10, 30, 20, 20])
    [1.0, 4.0, 2.5, 2.5]
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        rank = (start + end) / 2.0 + 1.0
        for position in range(start, end + 1):
            ranks[order[position]] = rank
        start = end + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson correlation; NaN when either side is constant or n < 2."""
    n = len(x)
    if n != len(y):
        raise ValueError("x and y must have the same length")
    if n < 2:
        return NAN
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    sxx = sum((a - mean_x) ** 2 for a in x)
    syy = sum((b - mean_y) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return NAN
    return sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank correlation with average ranks for ties.

    >>> spearman([1, 2, 3, 4], [10, 20, 30, 40])
    1.0
    >>> spearman([1, 2, 3, 4], [40, 30, 20, 10])
    -1.0
    """
    return pearson(average_ranks(x), average_ranks(y))


def top_option(p: Dict[str, float]) -> Optional[str]:
    """Category with the largest share (first on ties); None when every share is zero.

    >>> top_option({"a": 0.2, "b": 0.5, "c": 0.3})
    'b'
    """
    best: Optional[str] = None
    best_share = 0.0
    for category, share in p.items():
        if share > best_share:
            best, best_share = category, share
    return best


def top_option_match(p: Dict[str, float], q: Dict[str, float]) -> bool:
    """True when both distributions have the same most-chosen category.

    >>> top_option_match({"a": 0.6, "b": 0.4}, {"a": 0.51, "b": 0.49})
    True
    >>> top_option_match({"a": 0.6, "b": 0.4}, {"a": 0.4, "b": 0.6})
    False
    """
    top_p = top_option(p)
    return top_p is not None and top_p == top_option(q)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else NAN


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return NAN
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


_ITMAX = 1000
_EPS = 1e-14
_FPMIN = 1e-300


def _gamma_series(a: float, x: float) -> float:
    term = total = 1.0 / a
    ap = a
    for _ in range(_ITMAX):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_continued_fraction(a: float, x: float) -> float:
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, _ITMAX + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = b + an / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammq(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) = 1 - P(a, x).

    >>> gammq(2.5, 0.0)
    1.0
    >>> round(gammq(1.0, 2.0), 10) == round(math.exp(-2.0), 10)
    True
    """
    if a <= 0 or x < 0:
        raise ValueError("gammq needs a > 0 and x >= 0")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gamma_series(a, x)
    return _gamma_continued_fraction(a, x)


def chi2_sf(statistic: float, df: int) -> float:
    """Upper tail P(X >= statistic) of chi-square with `df` degrees of freedom.

    >>> round(chi2_sf(3.841, 1), 3)
    0.05
    >>> chi2_sf(0.0, 3)
    1.0
    """
    if df <= 0:
        raise ValueError("df must be positive")
    if statistic <= 0:
        return 1.0
    if math.isinf(statistic):
        return 0.0
    return gammq(df / 2.0, statistic / 2.0)


def chi2_gof(observed_counts: Dict[str, int], expected_shares: Dict[str, float]) -> Tuple[float, int, float]:
    """(statistic, df, p) of synthetic counts against the real shares taken as expected.

    Categories with zero expected share and zero observed count are dropped. An observed count in a
    category the real survey never chose makes the statistic infinite (p = 0).

    >>> chi2_gof({"a": 50, "b": 50}, {"a": 0.5, "b": 0.5})
    (0.0, 1, 1.0)
    >>> chi2_gof({"a": 5, "b": 0}, {"a": 0.0, "b": 1.0})[2]
    0.0
    """
    ordered = list(expected_shares) + [k for k in observed_counts if k not in expected_shares]
    keys = [k for k in ordered if expected_shares.get(k, 0.0) > 0 or observed_counts.get(k, 0) > 0]
    n = sum(observed_counts.get(k, 0) for k in keys)
    df = len(keys) - 1
    if n == 0 or df < 1:
        return NAN, max(df, 0), NAN
    statistic = 0.0
    for key in keys:
        expected = expected_shares.get(key, 0.0) * n
        observed = observed_counts.get(key, 0)
        if expected <= 0:
            return math.inf, df, 0.0
        statistic += (observed - expected) ** 2 / expected
    return statistic, df, chi2_sf(statistic, df)


def chi2_gof_pvalue(observed_counts: Dict[str, int], expected_shares: Dict[str, float]) -> float:
    return chi2_gof(observed_counts, expected_shares)[2]


def two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> Tuple[float, float]:
    """Pooled two-proportion z statistic and two-sided p-value.

    >>> two_proportion_z(50, 100, 50, 100)
    (0.0, 1.0)
    >>> two_proportion_z(90, 100, 10, 100)[1] < 1e-10
    True
    """
    if n1 <= 0 or n2 <= 0:
        return NAN, NAN
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (k1 / n1 - k2 / n2) / se
    return z, math.erfc(abs(z) / math.sqrt(2.0))


def two_proportion_z_pvalue(k1: int, n1: int, k2: int, n2: int) -> float:
    return two_proportion_z(k1, n1, k2, n2)[1]
