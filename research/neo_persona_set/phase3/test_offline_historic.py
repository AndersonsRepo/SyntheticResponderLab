"""The recovered Sept 17 / Sept 25 side analyses (phase3/offline/), on tiny fake inputs only: no real data."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "offline"))
import compare_real  # noqa: E402
import historic_common as hc  # noqa: E402
import realdata  # noqa: E402
import sept17_side_tables as s17  # noqa: E402
import sept25_review_checks as s25  # noqa: E402


def _write(path: Path, rows: List[Dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


# --------------------------------------------------------------------------- shared helpers

def test_logged_numbers_parse_and_match_at_their_precision() -> None:
    assert hc.to_number("1,234") == 1234 and hc.to_number("−0.25") == -0.25 and hc.to_number("+0.5") == 0.5 and hc.to_number("12%") == 12
    assert hc.matches_logged("0.334", 0.33352) and hc.matches_logged("0.334", 0.3335) and not hc.matches_logged("0.334", 0.33348)
    assert hc.matches_logged("12%", 0.117, percent=True) and not hc.matches_logged("12%", 0.1251, percent=True)
    assert hc.matches_logged("−0.25", -0.2512) and not hc.matches_logged("0.020", 0.020501)
    assert not hc.matches_logged(None, 0.5) and not hc.matches_logged("0.5", float("nan"))
    log = hc.LogText("Money text alone: 11% (DeepSeek) / 12% (Qwen). Rest.")
    assert log.groups(r"Money text alone: (\d+)% \(DeepSeek\) / (\d+)% \(Qwen\)") == ("11", "12")
    assert log.groups(r"nothing like this (\d+)") is None
    row = hc.numeric_check("x", "m", None, 0.3)
    assert row["logged"] == "NOT FOUND IN LOG" and row["match"] == "false"


def test_output_folder_refuses_the_repo_and_the_real_data_folder(tmp_path: Path) -> None:
    with pytest.raises(realdata.RealDataPathError):
        hc.resolve_out(HERE / "should_not_exist_out", tmp_path / "x")
    with pytest.raises(realdata.RealDataPathError):
        hc.resolve_out(tmp_path / "aytm_copy", tmp_path / "x")
    real = tmp_path / "realfolder" / "fake.csv"
    real.parent.mkdir()
    real.write_text("x", encoding="utf-8")
    with pytest.raises(realdata.RealDataPathError):
        hc.resolve_out(real.parent / "out", tmp_path / "x", real)
    assert hc.resolve_out(None, tmp_path / "ok" / "reproduced", real).is_dir()
    assert not (HERE / "should_not_exist_out").exists()


# --------------------------------------------------------------------------- Sept 25

def test_all_arms_rows_average_the_written_values_per_model() -> None:
    summaries = [
        {"model": "deepseek/deepseek-v4", "mean_spearman": "0.4400", "share_top_match": "0.5000", "mean_tv": "0.4000", "questions_close": "2", "questions_compared": "36"},
        {"model": "deepseek/deepseek-v4", "mean_spearman": "0.4100", "share_top_match": "0.5000", "mean_tv": "0.3990", "questions_close": "3", "questions_compared": "36"},
        {"model": "qwen/qwen3", "mean_spearman": "0.5000", "share_top_match": "0.2500", "mean_tv": "0.3000", "questions_close": "5", "questions_compared": "36"},
    ]
    rows = s25.all_arms_rows("F", summaries)
    assert [r["model"] for r in rows] == ["deepseek-v4", "qwen3"] and [r["runs"] for r in rows] == [2, 1]
    assert rows[0]["mean_spearman"] == round((0.4400 + 0.4100) / 2, 3) and rows[0]["mean_tv"] == 0.3995 and rows[0]["questions_close"] == 2.5
    assert rows[1]["share_top_match"] == 0.25


def test_assignment_is_recovered_by_identical_rows() -> None:
    a = {"P1": {"Q1": "1", "Q2": "2"}, "P2": {"Q1": "3", "Q2": "3"}}
    b = {"P1": {"Q1": "5", "Q2": "5"}, "P2": {"Q1": "4", "Q2": "4"}}
    mixed = {"P1": dict(a["P1"]), "P2": dict(b["P2"]), "P3": {"Q1": "9", "Q2": "9"}}
    deal, ambiguous, unmatched = s25.recover_assignment(mixed, {"a": a, "b": b}, ["Q1", "Q2"])
    assert deal == {"P1": "a", "P2": "b"} and ambiguous == 0 and unmatched == 1


def test_removed_sentences_cues_and_categories() -> None:
    original = [{"persona_id": "P1", "story_biography": "He works nights. Income is $40,000 a year. The garage feels tight.",
                 "story_priorities": "Retirement contributions; Keeping the yard tidy", "story_money_decisions": "They compare prices online."}]
    stripped = [{"persona_id": "P1", "story_biography": "He works nights.", "story_priorities": "Retirement contributions; Keeping the yard tidy",
                 "story_money_decisions": "They compare prices online."}]
    removed, total, added = s25.removed_sentences(original, stripped)
    assert total == 6 and added == 0 and [r["sentence"] for r in removed] == ["Income is $40,000 a year.", "The garage feels tight."]
    assert [s25.removed_category(r["sentence"]) for r in removed] == ["money", 'space/physical "tight"']
    assert s25.removed_category("She does not work for pay.") == 'employment status ("works for pay")'
    assert s25.removed_category("A cheaper grocery run on weekends.") == "money (weak)"
    assert s25.removed_category("He walks unless the weather is poor.") == "other"
    cues = s25.finance_cues(stripped)
    assert [(c["tier"], c["section"]) for c in cues] == [("A", "priorities"), ("B", "money_decisions")]
    assert s25.finance_cues([{"persona_id": "P2", "story_biography": "She moved into a principal research role."}]) == []
    assert s25.finance_cues([{"persona_id": "P3", "story_financial_picture": "They draw down slowly, keeping the principal intact."}])[0]["tier"] == "A"


def test_rho_by_style_and_percentile() -> None:
    incomes = {f"P{i}": float(i * 10000) for i in range(1, 7)}
    rows = [{"persona_id": f"P{i}", "Q1": str(i), "trait": "skeptical" if i <= 3 else ""} for i in range(1, 7)]
    rho = s25.rho_by_style(rows, incomes)
    assert rho["skeptical"] == pytest.approx(1.0) and rho["unstyled"] == pytest.approx(1.0) and rho["pooled"] == pytest.approx(1.0)
    assert rho["enthusiastic"] != rho["enthusiastic"]  # no rows -> nan
    assert s25.pctl([4.0, 1.0, 3.0, 2.0], 0.5) == 2.5 and s25.pctl([1.0, 2.0], 0.0) == 1.0


def test_fast_scorer_equals_compare_real(fake_real_csv: Path, fake_run_dir: Path) -> None:
    real = realdata.load_real_survey(fake_real_csv)
    run = s25.load(fake_run_dir)
    scorer = s25.FastScorer(real, run)
    s25.check_equal(scorer, real, run)
    shim = compare_real.load_run(fake_run_dir, require_outdoor_space=True, exclude_fallback=False)
    shim.rows = run.rows[:3]
    s25.check_equal(scorer, real, shim)  # a resampled subset scores the same both ways too


def test_money_strip_cli_on_a_fake_assets_folder(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    folder = assets / hc.SEPT24_REL
    original = [{"persona_id": f"P{i}", "story_biography": f"Person {i} lives here. Income is ${i}0,000. The kitchen feels tight.",
                 "story_priorities": "Building retirement contributions; Gardening"} for i in range(1, 5)]
    stripped = [{"persona_id": f"P{i}", "story_biography": f"Person {i} lives here.", "story_priorities": "Building retirement contributions; Gardening"} for i in range(1, 5)]
    _write(folder / "phase1_interview_matched600_s1.csv", original)
    _write(folder / "phase1_interview_matched600_s1_nomoney.csv", stripped)
    (folder / "survey_runs").mkdir()
    log = assets / hc.LOG_REL
    log.parent.mkdir(parents=True)
    log.write_text("| x | About 4 personas keep finance cues (retirement); the saved prompt contains them. About 50% of removed sentences were not about money "
                   "(4 \"space is tight\") |\n- numbers ... and the 8 removed sentences.\n", encoding="utf-8")
    out = tmp_path / "out"
    assert s25.main(["money-strip", "--assets", str(assets), "--out", str(out)]) == 0
    checks = {r["metric"]: r for r in hc.read_csv(out / "checks_money-strip.csv")}
    assert checks["removed sentences"]["match"] == "true" and checks["removed sentences"]["reproduced"] == "8"
    assert checks["personas keeping finance cues (tier A)"]["match"] == "true"
    assert checks["share of removed sentences not about money"]["match"] == "true"
    assert checks["removed 'tight' sentences in space_pressure"]["match"] == "false"  # the fake 'tight' sentences are in the biography
    assert checks["saved R019a prompt has finance cues"]["match"] == "false"  # no prompt sample in the fake folder


# --------------------------------------------------------------------------- Sept 17

def test_income_bands_shares_and_formatting() -> None:
    assert s17.synth_band(49999) == "under $50k" and s17.synth_band(50000) == "$50k-$100k" and s17.synth_band(150000) == "$150k+"
    shares = s17.shares_1_to_5([1, 1, 2, 5])
    assert shares == [0.5, 0.25, 0.0, 0.0, 0.25] and s17.pct_text(shares) == "50 / 25 / 0 / 0 / 25"
    assert s17.by_band([("a", 1), ("a", 2), (None, 3), ("b", None)]) == {"a": [1, 2]}


def test_real_income_table_uses_band_order(tmp_path: Path) -> None:
    options = s17.REAL_INCOME_OPTIONS
    rows = [{"household income": options[i % 6], "q6": str(1 + i % 5), "q7": str(1 + i % 5)} for i in range(12)]
    real = realdata.RealSurvey(path="fake", columns=["household income", "q6", "q7"], header_text={}, rows=rows)
    bands, rho6, rho7, n = s17.real_income_table(real)
    assert n == 12 and sum(len(v) for v in bands.values()) == 12 and set(bands) <= set(s17.REAL_GROUPS)
    assert rho6 == pytest.approx(rho7)


def test_money_reasons_cli_on_fake_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for model, reasons in (("deepseek-x", ["Too expensive for us.", "No room in the yard."]), ("qwen-y", ["$23,000 is a lot of money.", "We cannot afford it."])):
        rows = [{"question_id": "Q1", "answer": "1", "reason": r} for r in reasons] + [{"question_id": "Q2", "answer": "2", "reason": "fine"}]
        _write(runs / f"20260917T200000Z_{model}_r1_p100_s1-reasons" / "answers_long.csv", rows)
    log = tmp_path / "log.md"
    log.write_text("- Both models gave a reason for every one of 3 answers.\n- a money reason appears in 50% (DeepSeek) and 100% (Qwen) of cases\n", encoding="utf-8")
    out = tmp_path / "out"
    assert s17.main(["money-reasons", "--assets", str(tmp_path), "--runs-dir", str(runs), "--log", str(log), "--out", str(out)]) == 0
    checks = hc.read_csv(out / "checks_money-reasons.csv")
    assert [c["match"] for c in checks] == ["true"] * 4
    assert s17.money_reason_share([{"question_id": "Q1", "answer": "1", "reason": "the price"}, {"question_id": "Q1", "answer": "2", "reason": "money"}]) == (1, 1)


def test_logged_r010_table_is_read_from_the_log() -> None:
    log = hc.LogText("  | under $50k | 1 / 2 / 3 / 4 / 90 | 9 / 1 / 0 / 0 / 0 | 5 / 5 / 0 / 0 / 0 |\n"
                     "- ρ(income, Q1): **real 0.50, DeepSeek 0.20, Qwen 0.30.** ρ(income, Q2) is identical to Q1 in\n")
    parsed = s17.parse_logged_r010(log)
    assert parsed["under $50k"] == ("1 / 2 / 3 / 4 / 90", "9 / 1 / 0 / 0 / 0", "5 / 5 / 0 / 0 / 0")
    assert parsed["rho_q1"] == ("0.50", "0.20", "0.30") and parsed["q2_identical"] == ("yes",)
    assert parsed["$50k–$100k"] is None
