"""offline/noise_check_bootstrap.py and offline/average_shape_baseline.py on tiny fake inputs (no real data)."""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "offline"))
import average_shape_baseline as asb  # noqa: E402
import item_sets  # noqa: E402
import metrics  # noqa: E402
import noise_check_bootstrap as ncb  # noqa: E402

PIDS = [f"P{i}" for i in range(1, 7)]
INCOMES = {pid: 10000.0 * (i + 1) for i, pid in enumerate(PIDS)}


def _write(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _run(root: Path, name: str, point: List[int], odds: Optional[List[List[float]]] = None) -> Path:
    """A fake run folder: Q1 point answers per persona, and optional 1..5 odds per persona."""
    run = root / name
    run.mkdir(parents=True)
    _write(run / "answers_wide.csv", ["run_id", "persona_id", "Q1"], [{"run_id": name, "persona_id": pid, "Q1": str(a)} for pid, a in zip(PIDS, point)])
    if odds is not None:
        _write(run / "probabilities.csv", ["run_id", "persona_id", "question_id", "option", "probability", "drawn", "status"],
               [{"run_id": name, "persona_id": pid, "question_id": "Q1", "option": str(k), "probability": str(p), "drawn": str(a), "status": "ok"}
                for pid, a, row in zip(PIDS, point, odds) for k, p in zip(range(1, 6), row)])
    return run


def _personas(path: Path) -> Path:
    _write(path, ["persona_id", "exact_household_income"], [{"persona_id": pid, "exact_household_income": str(v)} for pid, v in INCOMES.items()])
    return path


# Odds that rise with income: expected answers 1.5, 2, ... and 4-5 mass 0, 0, 0.2, 0.5, 0.8, 1.0.
RISING = [[0.5, 0.5, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0.2, 0.6, 0.2, 0], [0, 0, 0.5, 0.5, 0], [0, 0, 0.2, 0.4, 0.4], [0, 0, 0, 0.5, 0.5]]


def test_run_statistics_use_the_odds_when_present_and_point_answers_otherwise(tmp_path: Path) -> None:
    with_odds = ncb.load_run(_run(tmp_path, "odds", [1, 2, 3, 4, 5, 5], RISING))
    no_odds = ncb.load_run(_run(tmp_path, "plain", [5, 4, 3, 2, 1, 1]))
    assert with_odds.uses_odds and not no_odds.uses_odds
    assert ncb.run_stat(with_odds, "rho_belief", PIDS, INCOMES) == pytest.approx(1.0)
    assert ncb.run_stat(no_odds, "rho_belief", PIDS, INCOMES) == pytest.approx(metrics.spearman(list(INCOMES.values()), [5, 4, 3, 2, 1, 1]))
    assert ncb.run_stat(with_odds, "top45_expected", PIDS, INCOMES) == pytest.approx((0.2 + 0.5 + 0.8 + 1.0) / 6)
    assert ncb.run_stat(with_odds, "top45_drawn", PIDS, INCOMES) == pytest.approx(3 / 6)
    assert ncb.run_stat(no_odds, "top45_expected", PIDS, INCOMES) == pytest.approx(2 / 6)
    assert ncb.arm_stat([with_odds, no_odds], "top45_drawn", PIDS, INCOMES) == pytest.approx((3 / 6 + 2 / 6) / 2)


def test_percentile_range_matches_the_oct05_indexing() -> None:
    assert ncb.percentile_range(list(range(200))) == (5, 194)
    assert ncb.percentile_range(list(range(2000))) == (50, 1949)
    assert asb.percentile_range(list(range(200))) == (5, 194)


def test_paired_bootstrap_ties_identical_arms_and_separates_a_clear_gap(tmp_path: Path) -> None:
    high = [ncb.load_run(_run(tmp_path, "high", [5, 5, 4, 5, 4, 5]))]
    low = [ncb.load_run(_run(tmp_path, "low", [1, 2, 1, 2, 1, 3]))]

    def stat(runs: List[ncb.RunAnswers]):
        return lambda ids: ncb.arm_stat(runs, "top45_drawn", ids, INCOMES)

    same = ncb.paired_bootstrap(stat(high), stat(high), PIDS, 200, random.Random(1))
    assert same[2:] == (0.0, 0.0, 0.0) and ncb.reading(same[3], same[4]) == "tie"
    gap = ncb.paired_bootstrap(stat(high), stat(low), PIDS, 200, random.Random(1))
    assert gap[2] == 1.0 and ncb.reading(gap[3], gap[4]) == "separates (A higher)"
    assert ncb.reading(-0.3, -0.1) == "separates (A lower)"


def test_main_writes_bootstrap_and_gap_tables(tmp_path: Path) -> None:
    arms = tmp_path / "arms"
    a = [_run(arms, f"A_r{r}", [1, 2, 3, 4, 5, 5], RISING) for r in (1, 2)]
    b = [_run(arms, f"B_r{r}", [3, 3, 3, 3, 3, 2]) for r in (1, 2)]
    summary = tmp_path / "comparison_summary.csv"
    _write(summary, ["run_id", "mean_tv", "mean_spearman"],
           [{"run_id": "x_r1_s1-ARMA", "mean_tv": "0.20", "mean_spearman": "0.50"}, {"run_id": "x_r2_s1-ARMA", "mean_tv": "0.22", "mean_spearman": "0.60"},
            {"run_id": "x_r1_s1-ARMB", "mean_tv": "0.30", "mean_spearman": "0.52"}, {"run_id": "x_r2_s1-ARMB", "mean_tv": "0.32", "mean_spearman": "0.54"}])
    out = tmp_path / "out"
    argv = ["--personas", str(_personas(tmp_path / "personas.csv")), "--arm", f"A={a[0]},{a[1]}", "--arm", f"B={arms}/B_r*",
            "--compare", "A,B,rho_belief", "--compare", "A,B,top45_drawn", "--resamples", "100", "--summaries", str(summary),
            "--gap-arm", "A=ARMA", "--gap-arm", "B=ARMB", "--gap", "A,B", "--tie-band-tv", "0.05", "--tie-band-rank", "0.10", "--out", str(out)]
    assert ncb.main(argv) == 0
    with open(out / "bootstrap.csv", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["kind"], r["n_personas"], r["a_uses_odds"], r["b_uses_odds"]) for r in rows] == [("rho_belief", "6", "true", "false"), ("top45_drawn", "6", "true", "false")]
    assert float(rows[1]["diff"]) == pytest.approx(3 / 6)
    with open(out / "gaps.csv", encoding="utf-8-sig") as handle:
        (gap,) = list(csv.DictReader(handle))
    assert float(gap["tv_gap_a_better"]) == pytest.approx(0.10) and gap["tv_reading"] == "A better"
    assert float(gap["rank_gap_a_better"]) == pytest.approx(0.02) and gap["rank_reading"] == "tie"
    record = json.loads((out / "noise_check.json").read_text(encoding="utf-8"))
    assert record["bootstrap"]["n_personas_used"] == 6 and record["gaps"]["tie_band_tv"] == 0.05


def test_noise_check_refuses_an_out_folder_inside_the_repo(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", [1, 2, 3, 4, 5, 5])
    with pytest.raises(SystemExit):
        ncb.main(["--personas", str(_personas(tmp_path / "p.csv")), "--arm", f"A={run}", "--arm", f"B={run}", "--compare", "A,B,top45_drawn",
                  "--out", str(ncb.REPO_ROOT / "research" / "noise_out")])


def test_noise_check_rejects_an_unknown_statistic(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", [1, 2, 3, 4, 5, 5])
    assert ncb.main(["--personas", str(_personas(tmp_path / "p.csv")), "--arm", f"A={run}", "--arm", f"B={run}", "--compare", "A,B,mean",
                     "--out", str(tmp_path / "out")]) == 2


# ---------------------------------------------------------------- average shape (conftest's fake AYTM file: Response IDs 1000..1011)


def _ids(path: Path, ids: List[int]) -> Path:
    path.write_text("# fake ids\n" + "\n".join(str(i) for i in ids) + "\n", encoding="utf-8")
    return path


def _items(path: Path, ids: List[str]) -> Path:
    path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return path


def _shape_argv(fake_real_csv: Path, tmp_path: Path, pool: List[str], score: List[str], fit: List[int], held: List[int]) -> List[str]:
    return ["--real", str(fake_real_csv), "--fit-ids", str(_ids(tmp_path / "fit.txt", fit)), "--score-ids", str(_ids(tmp_path / "score.txt", held)),
            "--pool-items", str(_items(tmp_path / "pool.txt", pool)), "--score-items", str(_items(tmp_path / "score_items.txt", score)),
            "--draws", "50", "--out", str(tmp_path / "out")]


def test_all_likert_holds_the_validation_and_calibration_items(tmp_path: Path) -> None:
    items = asb.all_likert_items()
    assert len(items) == 23 and set(item_sets.LIN_VALIDATION) | set(item_sets.LIN_CALIBRATION) == set(items)
    with pytest.raises(ValueError):
        asb.resolve_items(str(_items(tmp_path / "single.txt", ["Q6"])))


def test_shape_is_fitted_on_the_fit_half_and_scored_on_the_held_out_half(fake_real_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # Fit half 1000..1005 answers all 5 to the cost barrier (Q5_1) and all 1 to HOA (Q5_2): shape 1:0.5, 5:0.5.
    # Held-out half 1006..1011 answers Q1 (real Q6) 3, 3, 4, 4, 5, 5.
    argv = _shape_argv(fake_real_csv, tmp_path, ["Q5_1", "Q5_2"], ["Q1"], list(range(1000, 1006)), list(range(1006, 1012)))
    assert asb.main(argv) == 0
    assert "WARNING" not in capsys.readouterr().out
    out = tmp_path / "out"
    record = json.loads((out / "average_shape_score_items.json").read_text(encoding="utf-8"))
    result = record["results"]["pool.txt"]
    assert list(result["fitted_shape"].values()) == [0.5, 0.0, 0.0, 0.0, 0.5]
    assert result["expected"]["tv_mean"] == pytest.approx(0.5 * (0.5 + 1 / 3 + 1 / 3 + 1 / 6))
    assert result["expected"]["rank_mean"] == pytest.approx(metrics.spearman([0.5, 0, 0, 0, 0.5], [0, 0, 1 / 3, 1 / 3, 1 / 3]))
    # Any panel drawn from that shape holds only 1s and 5s, so its TV to the held-out shares is always 2/3.
    assert result["panel"]["tv_mean"] == pytest.approx(2 / 3)
    assert result["panel"]["tv_range"] == pytest.approx([2 / 3, 2 / 3])
    low, high = result["panel"]["rank_range"]
    assert low <= result["panel"]["rank_mean"] <= high
    with open(out / "average_shape_score_items.csv", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["arm"], r["items_overlap"], r["n_fit_respondents"], r["n_score_respondents"]) for r in rows] == [("expected", "0", "6", "6"), ("panel100", "0", "6", "6")]
    # Same seed, same draws.
    assert asb.main(argv) == 0
    again = json.loads((out / "average_shape_score_items.json").read_text(encoding="utf-8"))["results"]["pool.txt"]
    assert again["panel"] == result["panel"]


def test_a_pool_that_contains_a_scored_item_is_flagged(fake_real_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    argv = _shape_argv(fake_real_csv, tmp_path, ["Q5_1", "Q1"], ["Q1"], list(range(1000, 1006)), list(range(1006, 1012)))
    assert asb.main(argv) == 0
    assert "WARNING: pool pool.txt includes 1 of the scored items (Q1)" in capsys.readouterr().out
    with open(tmp_path / "out" / "average_shape_score_items.csv", encoding="utf-8-sig") as handle:
        assert {r["items_overlap"] for r in csv.DictReader(handle)} == {"1"}


def test_overlapping_halves_and_non_likert_items_are_refused(fake_real_csv: Path, tmp_path: Path) -> None:
    assert asb.main(_shape_argv(fake_real_csv, tmp_path, ["Q5_1"], ["Q1"], list(range(1000, 1007)), list(range(1006, 1012)))) == 2
    assert asb.main(_shape_argv(fake_real_csv, tmp_path, ["Q6"], ["Q1"], list(range(1000, 1006)), list(range(1006, 1012)))) == 2


def test_a_missing_real_file_or_id_file_exits_2_and_writes_nothing(fake_real_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    argv = _shape_argv(fake_real_csv, tmp_path, ["Q5_1"], ["Q1"], list(range(1000, 1006)), list(range(1006, 1012)))
    for missing in (fake_real_csv.parent / "typo.csv", tmp_path / "nowhere" / "real.csv"):
        assert asb.main(["--real", str(missing)] + argv[2:]) == 2
        assert "is not a file" in capsys.readouterr().err
    no_ids = list(argv)
    no_ids[no_ids.index("--fit-ids") + 1] = str(tmp_path / "missing_ids.txt")
    assert asb.main(no_ids) == 2
    assert not (tmp_path / "out").exists()


def test_average_shape_refuses_out_next_to_the_real_file_or_inside_the_repo(fake_real_csv: Path, tmp_path: Path) -> None:
    argv = _shape_argv(fake_real_csv, tmp_path, ["Q5_1"], ["Q1"], list(range(1000, 1006)), list(range(1006, 1012)))
    for bad in (fake_real_csv.parent / "shape_out", asb.REPO_ROOT / "research" / "shape_out"):
        with pytest.raises(SystemExit):
            asb.main(argv[:-1] + [str(bad)])
        assert not bad.exists()
