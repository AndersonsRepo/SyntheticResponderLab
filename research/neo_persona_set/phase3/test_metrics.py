"""Unit tests for the hand-rolled statistics (known chi-square tails, ties, edge cases)."""
from __future__ import annotations

import doctest
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402


def test_doctests_pass() -> None:
    failed, attempted = doctest.testmod(metrics)
    assert attempted > 10 and failed == 0


def test_chi_square_known_tails() -> None:
    assert abs(metrics.chi2_sf(3.841, 1) - 0.05) < 1e-3
    assert abs(metrics.chi2_sf(5.991, 2) - 0.05) < 1e-3
    assert abs(metrics.chi2_sf(7.815, 3) - 0.05) < 1e-3
    assert metrics.chi2_sf(0.0, 3) == 1.0
    assert metrics.chi2_sf(math.inf, 2) == 0.0


def test_gammq_identities() -> None:
    assert metrics.gammq(2.5, 0.0) == 1.0
    assert abs(metrics.gammq(1.0, 2.0) - math.exp(-2.0)) < 1e-12
    assert abs(metrics.gammq(1.0, 0.5) - math.exp(-0.5)) < 1e-12
    assert abs(metrics.gammq(3.0, 1.0) - math.exp(-1) * (1 + 1 + 0.5)) < 1e-12
    for bad in ((0.0, 1.0), (1.0, -1.0)):
        try:
            metrics.gammq(*bad)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def test_chi2_gof_paths() -> None:
    assert metrics.chi2_gof({"a": 50, "b": 50}, {"a": 0.5, "b": 0.5}) == (0.0, 1, 1.0)
    assert metrics.chi2_gof_pvalue({"a": 5, "b": 0}, {"a": 0.0, "b": 1.0}) == 0.0
    assert metrics.chi2_gof({"a": 5, "b": 0, "c": 0}, {"a": 0.5, "b": 0.5, "c": 0.0})[1] == 1
    assert math.isnan(metrics.chi2_gof({"a": 0}, {"a": 1.0})[2])
    stat, df, p = metrics.chi2_gof({"a": 70, "b": 30}, {"a": 0.5, "b": 0.5})
    assert df == 1 and abs(stat - 16.0) < 1e-9 and p < 1e-3


def test_two_proportion_z() -> None:
    assert metrics.two_proportion_z(50, 100, 50, 100) == (0.0, 1.0)
    z, p = metrics.two_proportion_z(90, 100, 10, 100)
    assert z > 0 and p < 1e-10
    assert metrics.two_proportion_z(10, 100, 90, 100)[0] == -z
    assert abs(metrics.two_proportion_z_pvalue(60, 100, 50, 100) - 0.1561) < 1e-3
    assert math.isnan(metrics.two_proportion_z(1, 0, 1, 1)[1])


def test_distances_and_ranks() -> None:
    p = {"1": 0.1, "2": 0.2, "3": 0.4, "4": 0.2, "5": 0.1}
    assert metrics.tv_distance(p, p) == 0.0 and metrics.js_divergence(p, p) < 1e-12
    assert abs(metrics.tv_distance(p, {"1": 0.3, "2": 0.2, "3": 0.2, "4": 0.2, "5": 0.1}) - 0.2) < 1e-12
    assert metrics.tv_distance({"a": 1.0}, {"b": 1.0}) == 1.0 and metrics.js_divergence({"a": 1.0}, {"b": 1.0}) == 1.0
    assert metrics.spearman([1, 2, 3], [1, 2, 3]) == 1.0 and metrics.spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert metrics.average_ranks([5, 5, 5]) == [2.0, 2.0, 2.0] and math.isnan(metrics.spearman([1, 1, 1], [1, 2, 3]))
    assert abs(metrics.spearman([1, 2, 2, 4], [1, 3, 2, 4]) - 0.9487) < 1e-3
    assert metrics.top_option_match(p, {"1": 0.5, "3": 0.5}) is False and metrics.top_option({"a": 0.0}) is None
    assert metrics.distribution(["3", "3", "x"], ["1", "2", "3"]) == {"1": 0.0, "2": 0.0, "3": 1.0}
    assert metrics.median([3, 1, 2]) == 2 and metrics.median([1, 2, 3, 4]) == 2.5 and math.isnan(metrics.mean([]))
