"""offline/r020_r021_attribution.py on tiny fake run folders: discovery, pairing, income link, rules, checks, guards."""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "offline"))
import make_real_split  # noqa: E402
import r020_r021_attribution as attr  # noqa: E402
from conftest import LIKERT_INTEREST, LIKERT_WOULD  # noqa: E402

PIDS = [f"P00{i}" for i in range(1, 7)]
INCOMES = [30000, 50000, 70000, 90000, 120000, 200000]
MODELS = ["q/qwen"] * 3 + ["g/gemini"] * 3
TRAITS = ["skeptical", "", "pragmatic", "enthusiastic", "skeptical", "indifferent"]
# Fake real score half (conftest's respondents 1000-1005) answers Q1 1, 2, 3 twice each: an answer set with
# two 1s, two 2s and two 3s has TV 0 and rank agreement 1.
RULE_R020 = ("Pass (Dr. Lin's rule): rho(income, Q1) falls by at least 0.20 AND validation TV falls by at least 0.05, both against R018u, the same mix")
RULE_R020B = ("Pass (Dr. Lin's rule): rho(income, Q1) falls by at least 0.20 AND validation TV falls by at least 0.05 against R018b; "
              "styles are credited only if R020b beats R020 on mean_spearman beyond the run-to-run range")
ATTRIBUTION = ("Attribution rule, per metric: a component is credited with a metric when its panel moves that metric from R018u toward R020 "
               "by at least half of R020's gain, in both repeats. R020's gains over R018u: TV -0.333 (half 0.167), mean_spearman +0.344 (half 0.172), "
               "rho on the models' stated belief -0.37 (0.85 to 0.49; half 0.18). For the drawn panel rho is judged on the expected Q1 from the odds, so draw noise does not count")
HYPOTHESES = {
    "R020": RULE_R020,
    "R020b": RULE_R020B,
    "R021": "Drawing accounts for R020's gain in distance and rank agreement but not for its drop in the income link. " + ATTRIBUTION,
    "R021b": "Drivers account for R020's drop in the models' income link (toward 0.49) but not for its gain in distance and rank agreement. " + ATTRIBUTION,
}
CONDITIONS = {"R020": "pass needs rho <= 0.64 and TV <= 0.283 (repeat means)", "R020b": "pass needs rho <= 0.73 and TV <= 0.033 (repeat means)"}


def _write(path: Path, header: Sequence[str], rows: List[Dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header))
        writer.writeheader()
        writer.writerows(rows)


def _panel(folder: Path, name: str, rep: int, q1: Sequence[int], *, traits: Optional[Sequence[str]] = None, odds: Optional[Sequence[int]] = None,
           kind: str = "synthetic", models: Sequence[str] = MODELS) -> Path:
    """A run folder in run_survey.py's layout; odds[k] puts k/10 of persona k's Q1 mass on option 5 and the rest on 1."""
    run = folder / name
    run.mkdir(parents=True)
    _write(run / "questions.csv", ["question_id", "question_type", "min_value", "max_value", "options", "text"],
           [{"question_id": "Q1", "question_type": "likert", "min_value": 1, "max_value": 5, "options": LIKERT_INTEREST, "text": "Purchase interest"},
            {"question_id": "Q2", "question_type": "likert", "min_value": 1, "max_value": 5, "options": LIKERT_WOULD, "text": "Purchase likelihood"}])
    base = {"run_id": name, "repeat": rep, "seed": 7}
    _write(run / "answers_wide.csv", ["run_id", "model", "repeat", "seed", "persona_id", "respondent_id", "trait", "Q1", "Q2"],
           [dict(base, model="mixed panel", persona_id=p, respondent_id=f"RESP_{i}", trait=(traits or [""] * 6)[i], Q1=q1[i], Q2=q1[i]) for i, p in enumerate(PIDS)])
    _write(run / "answers_long.csv", ["run_id", "model", "repeat", "seed", "persona_id", "respondent_id", "question_id", "question_type", "answer", "answer_json", "is_fallback"],
           [dict(base, model=models[i], persona_id=p, respondent_id=f"RESP_{i}", question_id=q, question_type="likert", answer=q1[i], answer_json=q1[i], is_fallback="false")
            for i, p in enumerate(PIDS) for q in ("Q1", "Q2")])
    if odds:
        _write(run / "probabilities.csv", ["run_id", "persona_id", "question_id", "option", "probability", "drawn", "status"],
               [{"run_id": name, "persona_id": p, "question_id": "Q1", "option": option, "probability": prob, "drawn": q1[i], "status": "ok"}
                for i, p in enumerate(PIDS) for option, prob in ((1, round(1 - odds[i] / 10, 2)), (2, 0), (3, 0), (4, 0), (5, round(odds[i] / 10, 2)))])
    (run / "manifest.json").write_text(json.dumps({"run_id": name, "status": "completed", "persona_kind": kind,
                                                   "answer_mode": "distribution" if odds else "single"}), encoding="utf-8")
    return run


def _assets(root: Path) -> Path:
    exp = root / "assets" / "5_experiments"
    base, styles = exp / "2026-09-30_base" / "survey_runs", exp / "2026-09-24_styles" / "survey_runs"
    r020, r021 = exp / "2026-10-01_R020" / "survey_runs", exp / "2026-10-02_R021" / "survey_runs"
    answers = {  # arm: (r1, r2)
        "R018u": ([1, 1, 1, 1, 2, 2], [1, 1, 1, 2, 2, 2]), "R018b": ([1, 1, 1, 2, 3, 3], [1, 1, 2, 2, 3, 3]),
        "R020": ([2, 1, 3, 1, 3, 2], [1, 2, 3, 3, 1, 2]), "R020b": ([1, 1, 2, 2, 3, 3], [2, 1, 1, 2, 3, 3]),
        "R021": ([1, 2, 1, 3, 2, 3], [2, 1, 1, 3, 2, 3]), "R021b": ([1, 1, 1, 1, 2, 2], [1, 1, 1, 2, 2, 2]),
    }
    for rep in (1, 2):
        i = rep - 1
        _panel(base, f"T0_mixed-panel_r{rep}_s1-R018u-unstyled", rep, answers["R018u"][i])
        _panel(styles, f"T0_mixed-panel_r{rep}_s1-R018b-prereg", rep, answers["R018b"][i], traits=TRAITS)
        _panel(styles, f"T0_random-uniform_r{rep}_s1-RANDOM", rep, [1, 2, 3, 4, 5, 1], models=["random-uniform"] * 6)
        _panel(r020, f"T1_mixed-panel_r{rep}_s1-R020-hybrid-mixed", rep, answers["R020"][i], odds=[3, 1, 5, 2, 6, 4], kind="hybrid")
        _panel(r020, f"T1_mixed-panel_r{rep}_s1-R020b-hybrid-mixed", rep, answers["R020b"][i], traits=TRAITS, odds=[3, 1, 5, 2, 6, 4], kind="hybrid")
        _panel(r021, f"T2_mixed-panel_r{rep}_s1-R021-draw-mixed", rep, answers["R021"][i], odds=[1, 2, 3, 4, 5, 6])
        _panel(r021, f"T2_mixed-panel_r{rep}_s1-R021b-hybrid-mixed", rep, answers["R021b"][i], kind="hybrid")
    _panel(r021, "T2_qwen_r1_s1-R021-draw-only", 1, answers["R021"][0], odds=[1, 2, 3, 4, 5, 6])  # one single-model arm
    log = root / "assets" / "0_logs" / "EXPERIMENT_LOG.md"
    log.parent.mkdir(parents=True)
    log.write_text("# log\n\n### 2026-10-02 — R021 / R021b: fake\n\n"
                   "| Panel (r1 / r2), Lin standard | Drivers | TV | Spearman | ρ on expected Q1 | Q1 4–5 |\n| --- | --- | --- | --- | --- | --- |\n"
                   "| **R021** | – | 0.000 / 0.100 | 1.000 / 1.000 | 1.00 / 1.00 | 0% / 0% |\n"
                   "| Real vs real | | 0.42 | 0.17 | — | 64% |\n\n"  # made-up numbers; the row must be skipped
                   "- **R021 (drawing only): supported.** fake\n- **R021b (drivers only): not supported** fake\n\n---\n", encoding="utf-8")
    return root / "assets"


@pytest.fixture
def setup(tmp_path: Path, fake_real_csv: Path) -> Dict[str, Path]:
    assets = _assets(tmp_path)
    personas = tmp_path / "personas.csv"
    _write(personas, ["persona_id", "exact_household_income"], [{"persona_id": p, "exact_household_income": inc} for p, inc in zip(PIDS, INCOMES)])
    ids = tmp_path / "ids" / "score_ids.txt"
    ids.parent.mkdir()
    ids.write_text("# fake score half\n" + "\n".join(str(1000 + i) for i in range(6)) + "\n", encoding="utf-8")
    registry = tmp_path / "registry.csv"
    _write(registry, ["registry_id", "hypothesis", "condition"], [{"registry_id": k, "hypothesis": v, "condition": CONDITIONS.get(k, "")} for k, v in HYPOTHESES.items()])
    return {"assets": assets, "real": fake_real_csv, "personas": personas, "ids": ids, "registry": registry}


def _main(s: Dict[str, Path], *extra: str) -> int:
    return attr.main(["--real", str(s["real"]), "--assets", str(s["assets"]), "--real-ids", str(s["ids"]), "--personas", str(s["personas"]),
                      "--registry", str(s["registry"]), "--out-name", "reproduced_test", *extra])


def _verdict(s: Dict[str, Path], exp: str, prefix: str) -> dict:
    return json.loads((s["assets"] / "5_experiments" / exp / "reproduced_test" / f"{prefix}_verdict.json").read_text(encoding="utf-8"))


def test_end_to_end_scores_income_link_and_both_rules(setup: Dict[str, Path]) -> None:
    assert _main(setup) == 0
    r020 = _verdict(setup, "2026-10-01_R020", "r020")
    assert r020["pairing_ok"] and r020["pairing"]["R020b"]["fields"] == ["model", "trait"]
    assert all(x["same"] == 6 for p in r020["pairing"].values() for x in p["per_repeat"])
    t = r020["table"]
    assert [round(r["tv"], 4) for r in t["R018u"]] == [0.3333, 0.3333] and [r["tv"] for r in t["R020"]] == [0.0, 0.0]
    assert t["R018u"][0]["rho_expected"] is None and t["R018u"][0]["q1_45_share"] == 0.0 and t["random"][0]["q1_45_share"] == pytest.approx(2 / 6)
    assert t["R020"][0]["rho_expected"] == pytest.approx(0.4857142857) and t["R020"][0]["n_expected"] == 6
    v = r020["verdicts"]
    assert v["R020"]["pass"] and v["R020"]["rho_drop"] == pytest.approx(0.841281820819 - 0.179284291400)
    assert not v["R020b"]["pass"] and v["R020b"]["tv_ok"] and not v["R020b"]["rho_ok"] and v["R020b"]["styles"]["credited"] is False
    assert v["R020"]["stated_thresholds"]["tv_max"]["agree_at_stated_precision"] and r020["verdict_words"] == {"R020": "pass", "R020b": "fail"}

    r021 = _verdict(setup, "2026-10-02_R021", "r021")
    a = r021["verdicts"]["R021"]
    assert a["metrics"]["tv"]["threshold"] == pytest.approx(0.3333 / 2)  # half of R020's gain from the score file (4 dp), not copied
    assert a["metrics"]["belief_rho"]["baseline_mean"] == pytest.approx((0.8280786712 + 0.8783100657) / 2)
    assert a["metrics"]["belief_rho"]["values"] == [pytest.approx(1.0), pytest.approx(1.0)]  # expected Q1 rises with income
    assert a["credited"] == {"tv": True, "spearman": True, "belief_rho": False} and a["supported"] is True
    b = r021["verdicts"]["R021b"]
    assert b["credited"] == {"tv": False, "spearman": False, "belief_rho": False} and b["supported"] is False
    assert b["supported_under_stated_thresholds"] is False and r021["rules"]["R021"]["source"]["checked_against_commit"] is False
    assert any("R021-draw-only" in str(p) for p in r021["singles"])

    out = setup["assets"] / "5_experiments" / "2026-10-02_R021" / "reproduced_test"
    assert {p.name for p in out.iterdir()} == {"lin13-validation", "r021_table.csv", "r021_spread_diagnostics.csv", "r021_verdict.json", "r021_reproduction_check.csv"}
    checks = list(csv.DictReader(open(out / "r021_reproduction_check.csv", encoding="utf-8-sig")))
    wrong = [c for c in checks if c["match"] != "true"]
    assert [c["what"] for c in wrong] == ["R021 r2 TV"]  # the fake log's 0.100 is caught, 0.000 matches
    assert not any("Real" in c["what"] for c in checks)  # the real-vs-real row is never read as a check
    assert {c["what"] for c in checks if "verdict" in c["what"]} == {"R021 verdict", "R021b verdict"}


def test_saved_outputs_are_compared_exactly(setup: Dict[str, Path]) -> None:
    assert _main(setup, "--only", "R021") == 0
    exp = setup["assets"] / "5_experiments" / "2026-10-02_R021"
    saved = exp / "real_comparison" / "20261002_lin13-validation"
    shutil.copytree(exp / "reproduced_test" / "lin13-validation", saved)
    rows = list(csv.DictReader(open(saved / "comparison_summary.csv", encoding="utf-8-sig")))
    rows[0]["mean_tv"] = "0.9999"
    _write(saved / "comparison_summary.csv", list(rows[0]), rows)
    assert _main(setup, "--only", "R021") == 0
    checks = list(csv.DictReader(open(exp / "reproduced_test" / "r021_reproduction_check.csv", encoding="utf-8-sig")))
    saved_rows = [c for c in checks if c["source"].endswith("comparison_summary.csv")]
    assert len(saved_rows) == 11 * len(attr.SUMMARY_FIELDS)
    assert [c["what"] for c in saved_rows if c["match"] != "true"] == [f"{rows[0]['run_id']} mean_tv"]


def test_missing_mixed_panel_is_reported_not_built(setup: Dict[str, Path], capsys) -> None:
    gone = setup["assets"] / "5_experiments" / "2026-10-02_R021" / "survey_runs" / "T2_mixed-panel_r2_s1-R021b-hybrid-mixed"
    shutil.rmtree(gone)
    assert _main(setup) == 2
    err = capsys.readouterr().err
    assert "R021b r2: mixed panel missing" in err and "make_mixed_panel.py --keep-arm-order --repeat 2 --run-tag s1-R021b-hybrid-mixed" in err
    assert not gone.exists() and not list(setup["assets"].glob("5_experiments/*/reproduced_test"))


def test_unpaired_panel_is_flagged(setup: Dict[str, Path]) -> None:
    run = setup["assets"] / "5_experiments" / "2026-10-02_R021" / "survey_runs" / "T2_mixed-panel_r1_s1-R021-draw-mixed"
    rows = list(csv.DictReader(open(run / "answers_long.csv", encoding="utf-8-sig")))
    for row in rows:
        if row["persona_id"] == "P001":
            row["model"] = "g/gemini"
    _write(run / "answers_long.csv", list(rows[0]), rows)
    assert _main(setup, "--only", "R021") == 1
    pairing = _verdict(setup, "2026-10-02_R021", "r021")["pairing"]["R021"]
    assert pairing["ok"] is False and pairing["per_repeat"][0]["same"] == 5 and pairing["per_repeat"][1]["same"] == 6


def test_rule_is_read_from_the_registry_or_nothing_runs(setup: Dict[str, Path], capsys) -> None:
    _write(setup["registry"], ["registry_id", "hypothesis", "condition"],
           [{"registry_id": k, "hypothesis": (v if k != "R021" else "Drawing accounts for R020's gain in distance and rank agreement but not for its drop in the income link."),
             "condition": CONDITIONS.get(k, "")} for k, v in HYPOTHESES.items()])
    assert _main(setup) == 2
    assert "R021: no attribution rule" in capsys.readouterr().err
    assert not list(setup["assets"].glob("5_experiments/*/reproduced_test"))
    rule = attr.parse_attribution_rule(HYPOTHESES["R021"], "R021")
    assert rule["fraction"] == 0.5 and rule["repeats"] == "both" and rule["belief_on_expected"] and rule["stated"]["belief_rho"]["baseline"] == "0.85"


def test_outputs_inside_the_repository_are_refused(setup: Dict[str, Path], monkeypatch) -> None:
    monkeypatch.setattr(make_real_split, "REPO_ROOT", setup["assets"].parent.resolve())  # pretend the fake tree is the repository
    with pytest.raises(SystemExit):
        _main(setup, "--only", "R021")
    assert not list(setup["assets"].glob("5_experiments/*/reproduced_test"))


def test_expected_q1_and_the_45_share(tmp_path: Path) -> None:
    run = _panel(tmp_path, "T_mixed-panel_r1_s1-x", 1, [1, 2, 3, 4, 5, 5], odds=[0, 5, 10, 0, 0, 0])
    assert attr.q1_expected(run)["P002"] == pytest.approx(0.5 * 1 + 0.5 * 5) and attr.q1_expected(run)["P003"] == pytest.approx(5.0)
    assert attr.share_45(attr.q1_answers(run)) == pytest.approx(3 / 6)
    assert attr.q1_expected(_panel(tmp_path, "no_odds", 1, [1] * 6)) is None
    assert attr.log_arm("Real vs real") is None and attr.log_arm("R020b + drivers + drawing") == "R020b" and attr.log_arm("Random control") == "random"
