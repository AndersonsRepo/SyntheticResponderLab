"""offline/jev_drawn_offline.py on a tiny fake Jev run and the fake real CSV from conftest.py. No network, no real data."""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "offline"))
import jev_drawn_offline as jdo  # noqa: E402
import run_survey  # noqa: E402  (phase2; put on sys.path by jev_drawn_offline)

PIDS = [f"P00{i}" for i in range(1, 7)]
INTEREST = "Not at all interested|Slightly interested|Moderately interested|Very interested|Extremely interested"
WOULD = "Definitely would not|Probably would not|Might or might not|Probably would|Definitely would"
CHANNELS = ["Google / Search ads", "Friend / family referral", "Home improvement expos"]
INCOME = {pid: 40000.0 + 20000 * i for i, pid in enumerate(PIDS)}
# Q1 odds rise with income and are certain, so every seed draws the same point: 1, 1, 2, 3, 4, 5.
Q1_POINT = dict(zip(PIDS, (1, 1, 2, 3, 4, 5)))
SEEDS = ("101", "202")


def _write(path: Path, header: List[str], rows: List[List[object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _read(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _fake_jev_run(root: Path) -> Path:
    """A run folder in jev_survey.py's layout: argmax answers plus the odds behind them."""
    run = root / "20260101T000000Z_jev-latest_r1_fake"
    run.mkdir(parents=True)
    _write(run / "questions.csv", ["question_id", "question_type", "asked_as", "options"], [
        ["S3", "single_choice", "choice", "Yes|I'm not sure, but possibly|No"],
        ["Q1", "likert", "score", INTEREST],
        ["Q2", "likert", "score", WOULD],
        ["Q20", "multi_choice", "choice", "|".join(CHANNELS)],
    ])
    _write(run / "answers_wide.csv", ["run_id", "model", "repeat", "seed", "persona_id", "respondent_id", "trait", "S3", "Q1", "Q2", "Q20"],
           [[run.name, "jev-latest", 1, "", pid, f"RESP_{i + 1:03d}", "", "No" if pid == "P003" else "Yes", "2", "3", "|".join(CHANNELS[:2])]
            for i, pid in enumerate(PIDS)])
    odds = []
    for pid in PIDS:
        odds += [[run.name, pid, "S3", "Yes", 0.9, 0.9], [run.name, pid, "S3", "No", 0.1, 0.9]]
        odds += [[run.name, pid, "Q1", str(k), 1.0 if k == Q1_POINT[pid] else 0.0, 0.5] for k in range(1, 6)]
        odds += [[run.name, pid, "Q2", str(k), 0.2, 0.5] for k in range(1, 6)]
    _write(run / "probabilities.csv", ["run_id", "persona_id", "question_id", "option", "probability", "confidence"], odds)
    (run / "manifest.json").write_text(json.dumps({"run_id": run.name, "model": {"requested": "jev-latest"},
                                                   "panel": {"personas_file": "fake.csv", "personas_sha256": "f" * 64}}), encoding="utf-8")
    return run


def _fake_personas(path: Path) -> Path:
    _write(path, ["persona_id", "exact_household_income"], [[pid, INCOME[pid]] for pid in PIDS])
    return path


def _main(tmp_path: Path, real: Path, jev: Path, out: str, *extra: str) -> int:
    return jdo.main(["--jev-run", str(jev), "--real", str(real), "--out", str(tmp_path / out), "--seeds", *SEEDS,
                     "--personas", str(_fake_personas(tmp_path / "personas.csv")), "--items", "all-scored", *extra])


def test_each_likert_cell_is_run_survey_draw_answer_at_the_saved_odds(tmp_path: Path) -> None:
    source = jdo.load_source(_fake_jev_run(tmp_path))
    assert source["likert_ids"] == ["Q1", "Q2"] and len(source["odds"]) == 2 * len(PIDS)
    rows, drawn, counts = jdo.draw_panel(source["rows"], source["likert_ids"], source["odds"], 7, "jev-drawn_r1")
    assert counts == {"drawn": 12, "no_odds": 0, "zero_odds": 0}
    for before, after in zip(source["rows"], rows):
        pid = after["persona_id"]
        assert after["run_id"] == "jev-drawn_r1" and after["Q1"] == str(Q1_POINT[pid])
        assert after["Q2"] == str(run_survey.draw_answer({k: 0.2 for k in range(1, 6)}, 7, pid, "Q2")) == str(drawn[(pid, "Q2")])
        assert {k: after[k] for k in ("S3", "Q20", "model", "seed")} == {k: before[k] for k in ("S3", "Q20", "model", "seed")}
    again, _, _ = jdo.draw_panel(source["rows"], source["likert_ids"], source["odds"], 7, "jev-drawn_r1")
    other, _, _ = jdo.draw_panel(source["rows"], source["likert_ids"], source["odds"], 8, "jev-drawn_r1")
    assert again == rows and [r["Q2"] for r in other] != [r["Q2"] for r in rows]


def test_odds_off_one_are_renormalized_and_missing_or_zero_odds_keep_the_argmax(tmp_path: Path) -> None:
    rows = [{"run_id": "src", "persona_id": pid, "Q1": "3"} for pid in ("A", "B", "C")]
    odds = {("A", "Q1"): {1: 2.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}, ("B", "Q1"): {k: 0.0 for k in range(1, 6)}}
    drawn_rows, drawn, counts = jdo.draw_panel(rows, ["Q1"], odds, 1, "r")
    assert [r["Q1"] for r in drawn_rows] == ["1", "3", "3"] and counts == {"drawn": 1, "no_odds": 1, "zero_odds": 1}
    prob_rows, renormalized = jdo.probability_rows(drawn_rows, ["Q1"], odds, drawn, "r")
    assert renormalized == 1 and {(row[0], row[1], row[-1]) for row in prob_rows} == {("r", "A", "renormalized"), ("r", "B", "invalid")}
    assert [row[4] for row in prob_rows if row[1] == "A"] == [1.0, 0.0, 0.0, 0.0, 0.0]


def test_end_to_end_writes_runs_scores_income_link_and_is_byte_reproducible(tmp_path: Path, fake_real_csv: Path) -> None:
    jev = _fake_jev_run(tmp_path / "runs")
    assert _main(tmp_path, fake_real_csv, jev, "first") == 0
    out = tmp_path / "first"
    assert {p.name for p in out.iterdir()} == {"jev-drawn_r1", "jev-drawn_r2", "cmp", "summary.csv"}
    run = out / "jev-drawn_r1"
    assert {p.name for p in run.iterdir()} == {"answers_wide.csv", "answers_long.csv", "questions.csv", "probabilities.csv", "manifest.json"}
    wide = {r["persona_id"]: r for r in _read(run / "answers_wide.csv")}
    assert (run / "answers_wide.csv").read_bytes()[:3] == b"\xef\xbb\xbf" and list(wide) == PIDS
    long = _read(run / "answers_long.csv")
    assert list(long[0]) == jdo.LONG_COLUMNS and len(long) == len(PIDS) * 4
    assert all(row["answer"] == wide[row["persona_id"]][row["question_id"]] for row in long)
    odds = _read(run / "probabilities.csv")
    assert len(odds) == len(PIDS) * 2 * 5 and all(row["drawn"] == wide[row["persona_id"]][row["question_id"]] for row in odds)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 101 and manifest["answer_mode"] == "distribution" and manifest["model"]["api_calls"] == 0
    assert manifest["draw"]["cells_drawn"] == 12 and manifest["source_run"]["run_id"] == jev.name
    assert manifest["personas"]["file_matches_sha256"] is False  # the fake manifest names another file
    assert manifest["outputs"]["answers_wide.csv"] == jdo.sha256_of_file(run / "answers_wide.csv")

    scored = {r["run_id"] for r in _read(out / "cmp" / "comparison_summary.csv")}
    assert scored == {jev.name, "jev-drawn_r1", "jev-drawn_r2"}
    summary = {r["run_id"]: r for r in _read(out / "summary.csv")}
    rho = f"{jdo.metrics.spearman([INCOME[p] for p in PIDS], [Q1_POINT[p] for p in PIDS]):.4f}"  # ties on 1, so just under 1
    assert summary["jev-drawn_r1"]["rho_income_q1"] == rho and summary["jev-drawn_r1"]["share_q1_4_5"] == "0.3333"
    assert summary[f"{jev.name} (stated odds)"]["rho_income_q1"] == rho and summary["jev-drawn_r2"]["n_personas_q1"] == "6"
    assert summary[jev.name]["share_q1_4_5"] == "0.0000"  # every argmax answer is 2

    assert _main(tmp_path, fake_real_csv, jev, "second", "--check-against", str(out)) == 0
    report = json.loads((tmp_path / "second" / "check.json").read_text(encoding="utf-8"))
    assert report["all_identical"] and report["runs"]["jev-drawn_r2"]["answers_wide_bytes_identical"] and all(report["cmp"].values())


def test_check_against_reports_a_changed_answer(tmp_path: Path, fake_real_csv: Path) -> None:
    jev = _fake_jev_run(tmp_path / "runs")
    assert _main(tmp_path, fake_real_csv, jev, "first") == 0
    earlier = tmp_path / "earlier"
    shutil.copytree(tmp_path / "first", earlier)
    path = earlier / "jev-drawn_r1" / "answers_wide.csv"
    rows = _read(path)
    rows[0]["Q2"] = "5" if rows[0]["Q2"] != "5" else "4"
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert _main(tmp_path, fake_real_csv, jev, "second", "--check-against", str(earlier)) == 1
    report = json.loads((tmp_path / "second" / "check.json").read_text(encoding="utf-8"))
    entry = report["runs"]["jev-drawn_r1"]
    assert not report["all_identical"] and not entry["answers_wide_bytes_identical"]
    assert entry["cells_differing"] == 1 and entry["columns_differing"] == ["Q2"] and report["runs"]["jev-drawn_r2"]["identical"]


@pytest.mark.parametrize("where", ["repo", "real_folder"])
def test_refuses_out_inside_the_repo_or_the_real_data_folder(tmp_path: Path, fake_real_csv: Path, where: str) -> None:
    jev = _fake_jev_run(tmp_path / "runs")
    out = jdo.REPO_ROOT / "research" / "_jev_drawn_should_not_exist" if where == "repo" else fake_real_csv.parent / "out"
    with pytest.raises(SystemExit) as refused:
        jdo.main(["--jev-run", str(jev), "--real", str(fake_real_csv), "--out", str(out)])
    assert refused.value.code == 3 and not out.exists()
