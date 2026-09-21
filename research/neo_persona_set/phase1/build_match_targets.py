"""Extract the demographic targets for a matched draw from the real survey file.

Reads ONLY age, gender, household income and region. It never touches an answer column, and it
never touches race or Hispanic origin — the first would contaminate the comparison, the second is
excluded from this pipeline by design.

The output is aggregate counts only: how many respondents fall in each age band, each income band,
each gender, each region. No respondent-level row is ever written, so the real file stays outside
the repository and nothing identifying leaves it.

Usage:
    python phase1/build_match_targets.py --real ~/Downloads/survey-760085-2026-03-25-raw-data.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "out"

# Column positions in the aytm export. Confirmed against the header row.
COL_GENDER = 4
COL_AGE = 5
COL_INCOME = 6
COL_REGION = 65

# Only these four are read. Listed explicitly so the scope is auditable at a glance.
READ_COLUMNS = {
    COL_GENDER: "gender",
    COL_AGE: "age",
    COL_INCOME: "income",
    COL_REGION: "region",
}

# Age bands. The real respondents run 24 to 86, so the ladder spans that rather than the
# earlier 30-65 screen, which excluded 31% of them.
AGE_BANDS = [(18, 29), (30, 39), (40, 49), (50, 59), (60, 69), (70, 120)]

# The survey's own income brackets, kept verbatim so no re-bucketing distorts the target.
INCOME_ORDER = [
    "$0 - $24,999",
    "$25,000 - $49,999",
    "$50,000 - $74,999",
    "$75,000 - $99,999",
    "$100,000 - $199,999",
    "$200,000 or more",
]

# Midpoints used to place a synthetic household's exact dollar income into a survey bracket.
INCOME_BOUNDS = {
    "$0 - $24,999": (0, 24_999),
    "$25,000 - $49,999": (25_000, 49_999),
    "$50,000 - $74,999": (50_000, 74_999),
    "$75,000 - $99,999": (75_000, 99_999),
    "$100,000 - $199,999": (100_000, 199_999),
    "$200,000 or more": (200_000, 10_000_000),
}


def age_band(age: int) -> str | None:
    for low, high in AGE_BANDS:
        if low <= age <= high:
            return f"{low}-{high}" if high < 120 else f"{low}+"
    return None


def income_band(dollars: float) -> str | None:
    """Place an exact dollar figure into the survey's own bracket."""
    for label, (low, high) in INCOME_BOUNDS.items():
        if low <= dollars <= high:
            return label
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", required=True, help="Path to the real survey CSV.")
    args = parser.parse_args()

    path = Path(args.real).expanduser()
    if not path.exists():
        raise SystemExit(f"No such file: {path}")

    counts: dict[str, Counter] = {name: Counter() for name in READ_COLUMNS.values()}
    joint = Counter()
    total = 0
    dropped = 0

    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)  # header
        for row in reader:
            try:
                gender = row[COL_GENDER].strip()
                raw_age = row[COL_AGE].strip()
                income = row[COL_INCOME].strip()
                region = row[COL_REGION].strip()
            except IndexError:
                dropped += 1
                continue

            if not (gender and raw_age and income and region):
                dropped += 1  # one respondent has blank demographics
                continue
            try:
                band = age_band(int(raw_age))
            except ValueError:
                dropped += 1
                continue
            if band is None or income not in INCOME_BOUNDS:
                dropped += 1
                continue

            counts["gender"][gender] += 1
            counts["age"][band] += 1
            counts["income"][income] += 1
            counts["region"][region] += 1
            joint[(band, gender, income, region)] += 1
            total += 1

    payload = {
        "source_file": path.name,
        "source_note": (
            "Only age, gender, household income and region were read. No answer column was "
            "opened, and race and Hispanic origin were deliberately not read. Output is aggregate "
            "counts only; no respondent-level data is stored."
        ),
        "respondents_used": total,
        "respondents_dropped_for_blank_demographics": dropped,
        "age_bands": [f"{lo}-{hi}" if hi < 120 else f"{lo}+" for lo, hi in AGE_BANDS],
        "income_brackets": INCOME_ORDER,
        "marginals": {name: dict(counter) for name, counter in counts.items()},
        # The joint cell counts are what the matched draw actually reproduces. Marginals alone
        # would let a draw match each variable separately while getting the combinations wrong.
        "joint_cells": [
            {"age_band": a, "gender": g, "income": i, "region": r, "count": c}
            for (a, g, i, r), c in sorted(joint.items(), key=lambda kv: -kv[1])
        ],
        "joint_cell_count": len(joint),
    }

    out_path = OUT_DIR / "match_targets.json"
    out_path.write_text(json.dumps(payload, indent=2))

    print(f"Read {total} respondents ({dropped} dropped for blank demographics)\n")
    for name in ["gender", "age", "income", "region"]:
        print(f"{name}:")
        for value, count in counts[name].most_common():
            print(f"   {count:>4}  {count/total:>5.1%}  {value}")
        print()
    print(f"{len(joint)} distinct age x gender x income x region cells")
    print(f"Wrote {out_path.name} (aggregate counts only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
