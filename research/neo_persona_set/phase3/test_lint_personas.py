"""The persona-file linter reports the matched-set defects with exact counts and passes a clean file."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_personas  # noqa: E402

STORY = ["headline", "biography", "daily_routine", "weekend_routine", "household_and_home", "outdoor_space", "home_projects",
         "work_setup", "space_pressure", "money_decisions", "priorities", "financial_picture", "free_time", "communication_style"]


def _row(pid, age, income, *, age_bucket, income_bucket, ownership="owner", home_type="detached single-family", county="Kern",
         housing_cost="17", home_text="a three-bedroom house"):
    row = {c: "" for c in lint_personas.EXPECTED_HEADER}
    row.update({"persona_id": pid, "age_bucket": age_bucket, "income_bucket": income_bucket, "ownership": ownership, "work_mode": "commutes",
                "home_type": home_type, "lifestyle_tags": "married", "exact_age": str(age), "exact_household_income": str(income), "sex": "Female",
                "county": county, "household_size": "2", "housing_cost_pct_of_income": housing_cost, "name": "Pat Doe"})
    for column in STORY:
        row[f"story_{column}"] = f"{column} text about {home_text}"
    return row


def _write(path: Path, rows, header=None):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header or lint_personas.EXPECTED_HEADER, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_clean_file_passes(tmp_path: Path) -> None:
    path = _write(tmp_path / "ok.csv", [_row("P001", 32, 104999, age_bucket="30-34", income_bucket="$100k-$150k"),
                                       _row("P002", 67, 214092, age_bucket="65+", income_bucket="$200k-$300k")])
    report = lint_personas.lint(path)
    assert report["errors"] == [] and report["warnings"] == []
    assert report["counts"]["rows"] == 2
    assert lint_personas.main([str(path)]) == 0


def test_matched_defects_are_counted(tmp_path: Path) -> None:
    rows = [
        _row("P001", 60, 31980, age_bucket="55-64", income_bucket="$100k-$150k", county="", housing_cost=""),
        _row("P002", 64, 30458, age_bucket="55-64", income_bucket="$100k-$150k", ownership="renter", county="", housing_cost="", home_text="a Maryland apartment"),
        _row("P003", 67, 34518, age_bucket="55-64", income_bucket="$100k-$150k", county="", housing_cost=""),
        _row("P004", 24, 120000, age_bucket="30-34", income_bucket="$100k-$150k", ownership="renter", county="", housing_cost="", home_text="a mobile home"),
    ]
    path = _write(tmp_path / "matched.csv", rows)
    report = lint_personas.lint(path)
    counts = report["counts"]
    assert counts["income_bucket_mismatch"] == 3 and counts["age_bucket_mismatch"] == 2 and counts["age_under_30"] == 1
    assert counts["renters"] == 2 and counts["county_blank"] == 4 and counts["renters_missing_housing_cost"] == 2
    assert counts["home_type_story_conflict"] == 2
    assert any("home_type" in w for w in report["warnings"]) and any("county" in w for w in report["warnings"])
    assert any("income_bucket" in e for e in report["errors"])
    assert lint_personas.main([str(path), "--json", str(tmp_path / "r.json")]) == 1
    assert json.loads((tmp_path / "r.json").read_text())["counts"]["rows"] == 4


def test_header_and_id_problems_are_errors(tmp_path: Path) -> None:
    header = list(lint_personas.EXPECTED_HEADER)[:-1] + ["Q1"]
    path = _write(tmp_path / "bad.csv", [{**_row("P001", 32, 104999, age_bucket="30-34", income_bucket="$100k-$150k"), "Q1": "x"}], header=header)
    report = lint_personas.lint(path)
    assert any("survey" in e.lower() for e in report["errors"]) and any("missing" in e.lower() for e in report["errors"])
    dup = _write(tmp_path / "dup.csv", [_row("P001", 32, 104999, age_bucket="30-34", income_bucket="$100k-$150k")] * 2)
    assert any("duplicate" in e for e in lint_personas.lint(dup)["errors"])


def test_bucket_labels_are_checked_by_bounds_not_spelling(tmp_path: Path) -> None:
    # Yaza's Sept 16 export uses "under $25k" and the finer "65-74" / "75+"; those are correct labels, not errors.
    assert lint_personas.label_bounds("under $25k") == (float("-inf"), 24999.0)
    assert lint_personas.label_bounds("<$25k") == (float("-inf"), 24999.0)
    assert lint_personas.label_bounds("$25k-$50k") == (25000.0, 49999.0) and lint_personas.label_bounds("$500k+") == (500000.0, float("inf"))
    assert lint_personas.label_bounds("65-74") == (65.0, 74.0) and lint_personas.label_bounds("75+") == (75.0, float("inf")) and lint_personas.label_bounds("18-24") == (18.0, 24.0)
    assert lint_personas.label_bounds("") is None
    rows = [
        _row("P001", 68, 20000, age_bucket="65-74", income_bucket="under $25k"),
        _row("P002", 80, 31980, age_bucket="75+", income_bucket="$25k-$50k"),
        _row("P003", 60, 31980, age_bucket="55-64", income_bucket="$100k-$150k"),  # the real defect
        _row("P004", 24, 120000, age_bucket="30-34", income_bucket="$100k-$150k"),  # the real defect
    ]
    report = lint_personas.lint(_write(tmp_path / "labels.csv", rows))
    assert report["counts"]["income_bucket_mismatch"] == 1 and report["counts"]["age_bucket_mismatch"] == 1


def test_county_blank_is_fine_when_state_is_present(tmp_path: Path) -> None:
    header = list(lint_personas.EXPECTED_HEADER)
    rows = [{**_row(f"P00{i}", 40, 80000, age_bucket="35-44", income_bucket="$75k-$100k", county=""), "state": "Texas", "region": "South"} for i in range(1, 5)]
    report = lint_personas.lint(_write(tmp_path / "state.csv", rows, header=header))
    assert report["counts"]["county_blank"] == 4 and not any("county" in w for w in report["warnings"])
    rows[0]["state"] = rows[0]["region"] = ""
    report = lint_personas.lint(_write(tmp_path / "nostate.csv", rows, header=header))
    assert report["counts"]["location_blank"] == 1 and any("location" in w for w in report["warnings"])
