"""Check a phase-1 persona CSV before it is used for a run or handed to the team.

Errors (exit 1): wrong header, survey-answer columns, duplicate or missing ids, non-numeric exact
values, bucket labels that contradict the exact values, blank story headlines. Warnings (exit 0
unless --strict): a constant home_type while renters exist, stories that describe an apartment or
mobile home under a "detached single-family" label, blank county, renters without a housing-cost
share. The counts are printed and can be saved with --json.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/lint_personas.py <personas.csv> [--json report.json] [--strict]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
PHASE2 = HERE.parent / "phase2"
for folder in (HERE, PHASE2):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import run_survey  # noqa: E402  (phase2; loads the legacy runtime, no network)

STORY_COLUMNS = ["headline", "biography", "daily_routine", "weekend_routine", "household_and_home", "outdoor_space", "home_projects",
                 "work_setup", "space_pressure", "money_decisions", "priorities", "financial_picture", "free_time", "communication_style"]
EXPECTED_HEADER: List[str] = (
    ["persona_id", "age_bucket", "income_bucket", "ownership", "work_mode", "home_type", "lifestyle_tags"]
    + list(run_survey.CLASSIFIER_COLUMNS) + list(run_survey.CENSUS_COLUMNS) + ["name"] + [f"story_{c}" for c in STORY_COLUMNS]
)
_SURVEY_COLUMN = re.compile(r"^(S\d|Q\d|PQ\d)")
_NOT_DETACHED = re.compile(r"\b(apartment|condo|condominium|townhouse|townhome|duplex|mobile home|trailer|manufactured home)\b", re.IGNORECASE)
_ID = re.compile(r"^P\d{3,}$")


def _int(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def lint(path: Path) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    counts: Counter = Counter()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    counts["rows"] = len(rows)

    survey_like = [c for c in header if _SURVEY_COLUMN.match(c.strip())]
    if survey_like:
        errors.append(f"survey-answer columns present (not a persona file): {survey_like[:5]}")
    missing = [c for c in EXPECTED_HEADER if c not in header]
    extra = [c for c in header if c not in EXPECTED_HEADER]
    if missing:
        errors.append(f"missing columns: {missing[:8]}")
    if extra:
        warnings.append(f"unexpected columns: {extra[:8]}")
    if header[: len(EXPECTED_HEADER)] != EXPECTED_HEADER and not missing:
        warnings.append("columns are present but not in the expected order")

    ids = [row.get("persona_id", "") for row in rows]
    duplicates = sorted({pid for pid, n in Counter(ids).items() if n > 1})
    if duplicates:
        errors.append(f"duplicate persona ids: {duplicates[:5]}")
    bad_ids = [pid for pid in ids if not _ID.match(pid or "")]
    if bad_ids:
        errors.append(f"persona ids not P-numbered: {bad_ids[:5]}")

    examples: Dict[str, List[str]] = {"income_bucket_mismatch": [], "age_bucket_mismatch": []}
    for row in rows:
        pid = row.get("persona_id", "?")
        age = _int(row.get("exact_age", ""))
        income = _int(row.get("exact_household_income", ""))
        if age is None:
            counts["exact_age_not_numeric"] += 1
        if income is None:
            counts["exact_household_income_not_numeric"] += 1
        if age is not None:
            expected = run_survey.band_label(age, run_survey.AGE_BANDS)
            if expected != (row.get("age_bucket") or "").strip():
                counts["age_bucket_mismatch"] += 1
                examples["age_bucket_mismatch"].append(pid)
            if age < 30:
                counts["age_under_30"] += 1
        if income is not None:
            expected = run_survey.band_label(income, run_survey.INCOME_BANDS)
            if expected != (row.get("income_bucket") or "").strip():
                counts["income_bucket_mismatch"] += 1
                examples["income_bucket_mismatch"].append(pid)
        if (row.get("ownership") or "").strip() == "renter":
            counts["renters"] += 1
            if not (row.get("housing_cost_pct_of_income") or "").strip():
                counts["renters_missing_housing_cost"] += 1
        if not (row.get("county") or "").strip():
            counts["county_blank"] += 1
        story_text = " ".join(row.get(f"story_{c}", "") or "" for c in STORY_COLUMNS)
        if "detached" in (row.get("home_type") or "").lower() and _NOT_DETACHED.search(story_text):
            counts["home_type_story_conflict"] += 1
        if not (row.get("story_headline") or "").strip():
            counts["story_headline_blank"] += 1

    for key, label in (("income_bucket_mismatch", "income_bucket"), ("age_bucket_mismatch", "age_bucket")):
        if counts[key]:
            errors.append(f"{label} contradicts the exact value on {counts[key]} rows (e.g. {examples[key][:5]}); derive labels from exact values")
    for key in ("exact_age_not_numeric", "exact_household_income_not_numeric", "story_headline_blank"):
        if counts[key]:
            errors.append(f"{key}: {counts[key]} rows")
    home_types = {(row.get("home_type") or "").strip() for row in rows}
    if counts["renters"] and len(home_types) == 1:
        warnings.append(f"home_type is the constant {home_types.pop()!r} although {counts['renters']} rows are renters; derive it from the Census building field")
    if counts["home_type_story_conflict"]:
        warnings.append(f"home_type says detached single-family but the story describes an apartment/condo/mobile home on {counts['home_type_story_conflict']} rows")
    if rows and counts["county_blank"] / len(rows) > 0.05:
        warnings.append(f"county blank on {counts['county_blank']} of {len(rows)} rows; add state/region for a national draw")
    if counts["renters_missing_housing_cost"]:
        warnings.append(f"housing_cost_pct_of_income blank for {counts['renters_missing_housing_cost']} renters; use the renter cost-burden field")
    return {"path": str(path), "errors": errors, "warnings": warnings, "counts": dict(counts)}


def render(report: Dict[str, Any]) -> str:
    lines = [f"lint: {report['path']}", f"rows: {report['counts'].get('rows', 0)}"]
    lines += [f"ERROR   {e}" for e in report["errors"]] + [f"WARNING {w}" for w in report["warnings"]]
    lines.append("counts: " + json.dumps(report["counts"], sort_keys=True))
    lines.append("result: " + ("FAIL" if report["errors"] else "OK" if not report["warnings"] else "OK with warnings"))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", help="warnings also fail")
    args = parser.parse_args(argv)
    run_survey.assert_not_real_data(args.path, "path")
    report = lint(args.path)
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    failed = bool(report["errors"]) or (args.strict and bool(report["warnings"]))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
