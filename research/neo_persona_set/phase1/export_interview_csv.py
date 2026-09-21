"""Phase 1, step 5 — export the persona set in the column format the interview flow reads.

Emits Anderson's exact headers so his code can read the file with no conversion step, then the
funnel columns he asked to be left blank, then the precise values the buckets are derived from.

Three notes on fidelity, expanded in the docstrings below:

* age_bucket and income_bucket are LOSSY. The exact values are kept in later columns so nothing is
  destroyed by the conversion.
* work_mode cannot express "hybrid". The ACS records a single means of transport to work, so a
  household is either "worked from home" or "travelled to work" — there is no data that
  distinguishes a hybrid worker from a full-time commuter.
* lifestyle_tags contains only tags derivable from the household's own Census record. Tags like
  "gardens" would be invention, and the whole point of this pipeline is that persona attributes
  trace back to real data.

Usage:
    python phase1/export_interview_csv.py --tag owners
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "out"

# Columns the interview flow reads.
INTERVIEW_COLUMNS = [
    "persona_id",
    "age_bucket",
    "income_bucket",
    "ownership",
    "work_mode",
    "home_type",
    "lifestyle_tags",
]

# Retired with the four-stage funnel design. Emitted empty so the header set stays stable.
RETIRED_COLUMNS = [
    "fit_tier",
    "awareness_stage",
    "segment_label",
    "likely_use_case",
    "likely_barrier",
    "affordability_pressure",
]

# Exact values, kept so the bucketing above is never the only record of a number.
PRECISE_COLUMNS = [
    # region and state come first among the location fields: the county lookup only resolves
    # California PUMAs, so for a national draw it is blank for most rows and cannot stand alone.
    "exact_age", "exact_household_income", "sex", "region", "state", "county",
    "marital_status", "education",
    "occupation", "employment_status", "hours_worked_per_week", "commute_mode", "commute_minutes",
    "household_size", "children_in_household", "household_type", "tenure_detail", "bedrooms",
    "rooms", "year_built", "moved_in", "vehicles", "housing_cost_pct_of_income",
    "housing_cost_basis", "name",
]

# The written profile, so one file serves both the interview flow and a human reading the persona.
STORY_COLUMNS = [
    "headline", "biography", "daily_routine", "weekend_routine", "household_and_home",
    "outdoor_space", "home_projects", "work_setup", "space_pressure", "money_decisions",
    "priorities", "financial_picture", "free_time", "communication_style",
]


def age_bucket(age: int | None) -> str:
    """Bucket age across the full adult range.

    The ladder used to start at 30-34 and end at a bare "65", because every draw was screened to
    30-65 so nothing could fall outside. The matched draw is not screened and spans 24 to 95, where
    that shape silently mislabelled a 24-year-old as "30-34" and a 95-year-old as "65". The bands
    below cover any age; the screened sets still only ever produce the original labels.
    """
    if age is None:
        return ""
    if age < 25:
        return "18-24"
    if age < 30:
        return "25-29"
    if age < 35:
        return "30-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 65:
        return "55-64"
    if age < 75:
        return "65-74"
    return "75+"


def income_bucket(income: float | None) -> str:
    """Bucket household income across the full range.

    The first branch used to be `income < 150_000 -> "$100k-$150k"`, which was only safe because
    every draw was screened to $100k and up. In the unscreened matched draw it labelled a $31,980
    household as "$100k-$150k". The bands below start at zero; the screened sets still only ever
    produce the original labels.
    """
    if income is None:
        return ""
    if income < 25_000:
        return "under $25k"
    if income < 50_000:
        return "$25k-$50k"
    if income < 75_000:
        return "$50k-$75k"
    if income < 100_000:
        return "$75k-$100k"
    if income < 150_000:
        return "$100k-$150k"
    if income < 200_000:
        return "$150k-$200k"
    if income < 300_000:
        return "$200k-$300k"
    if income < 500_000:
        return "$300k-$500k"
    return "$500k+"


def work_mode(persona: dict) -> str:
    """Map the ACS commute record onto a work mode.

    The ACS asks for ONE means of transportation to work. Someone in the office three days a week
    answers with their commute mode, exactly as a five-day commuter does. "hybrid" is therefore not
    recoverable from this data, and guessing at it would be invention.
    """
    employment = str(persona.get("employment_status") or "")
    if "not in labor force" in employment.lower() or "unemployed" in employment.lower():
        return "not working"
    mode = str(persona.get("commute_mode") or "")
    if "home" in mode.lower():
        return "works from home"
    if mode:
        return "commutes"
    return "not working"


def lifestyle_tags(persona: dict) -> str:
    """Build tags from the household's own record. Nothing here is invented.

    Every tag below is a restatement of a Census field. Tags describing taste or hobbies —
    "gardens", "tech-forward", "outdoorsy" — are deliberately absent: the ACS does not ask, so
    producing them would mean inventing an attribute and presenting it beside real ones.
    """
    tags: list[str] = []

    size = persona.get("household_size")
    children = persona.get("children_in_household")
    if size == 1:
        tags.append("lives alone")
    if children:
        tags.append("has kids")
    if size and size >= 5:
        tags.append("large household")
    if str(persona.get("marital_status") or "").startswith("Married"):
        tags.append("married")

    mode = work_mode(persona)
    if mode == "works from home":
        tags.append("works from home")
    elif mode == "commutes":
        tags.append("commutes daily")
    minutes = persona.get("commute_minutes")
    if minutes and minutes >= 45:
        tags.append("long commute")

    hours = persona.get("hours_worked_per_week")
    if hours and hours >= 50:
        tags.append("works long hours")
    elif hours and hours < 35:
        tags.append("works part-time")

    vehicles = str(persona.get("vehicles") or "")
    if vehicles.startswith("No "):
        tags.append("no vehicle")
    elif any(vehicles.startswith(n) for n in ("3", "4", "5", "6")):
        tags.append("multiple vehicles")

    moved = str(persona.get("moved_in") or "")
    if moved.startswith(("20 to 29", "30 years")):
        tags.append("long-time resident")
    elif moved.startswith(("12 months", "13 to 23")):
        tags.append("recently moved")

    year = str(persona.get("year_built") or "")
    if year[:4].isdigit():
        if int(year[:4]) < 1970:
            tags.append("older home")
        elif int(year[:4]) >= 2000:
            tags.append("newer home")

    education = str(persona.get("education") or "")
    if any(k in education for k in ("bachelor", "master", "doctorate", "professional")):
        tags.append("college educated")

    return ";".join(tags)


def resolve_input(tag: str, override: str | None) -> Path:
    """Find the persona file, tolerating the names it gets renamed to when it is shared."""
    if override:
        path = Path(override)
        if not path.exists():
            raise SystemExit(f"No such file: {path}")
        return path

    candidates = [
        OUT_DIR / f"phase1_personas_{tag}_full.json",
        OUT_DIR / f"30_personas_{tag}.json",
        OUT_DIR / f"30_personas_{tag}_only.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"Could not find the '{tag}' persona file. Looked for:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + "\nPass --input to point at it directly."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="owners")
    parser.add_argument("--input", default=None, help="Explicit path to the persona JSON.")
    args = parser.parse_args()

    source = resolve_input(args.tag, args.input)
    print(f"Reading {source.name}")
    payload = json.loads(source.read_text())
    personas = payload["personas"]

    header = (
        INTERVIEW_COLUMNS
        + RETIRED_COLUMNS
        + PRECISE_COLUMNS
        + [f"story_{c}" for c in STORY_COLUMNS]
    )
    out_path = OUT_DIR / f"phase1_interview_{args.tag}.csv"

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)

        for index, persona in enumerate(personas, start=1):
            tenure = str(persona.get("tenure") or "")
            row = [
                f"P{index:03d}",
                age_bucket(persona.get("age")),
                income_bucket(persona.get("household_income")),
                "owner" if tenure.startswith("Owned") else "renter",
                work_mode(persona),
                # Was hardcoded. Real structure type, so an apartment is not reported as a house.
                persona.get("home_type") or "",
                lifestyle_tags(persona),
            ]
            row += [""] * len(RETIRED_COLUMNS)
            row += [
                persona.get("age"),
                persona.get("household_income"),
                persona.get("sex"),
                persona.get("match_region") or persona.get("region"),
                persona.get("state"),
                persona.get("county"),
                persona.get("marital_status"),
                persona.get("education"),
                persona.get("occupation"),
                persona.get("employment_status"),
                persona.get("hours_worked_per_week"),
                persona.get("commute_mode"),
                persona.get("commute_minutes"),
                persona.get("household_size"),
                persona.get("children_in_household"),
                persona.get("household_type"),
                persona.get("tenure"),
                persona.get("bedrooms"),
                persona.get("rooms"),
                persona.get("year_built"),
                persona.get("moved_in"),
                persona.get("vehicles"),
                persona.get("housing_cost_pct_of_income"),
                persona.get("housing_cost_basis"),
                persona.get("name"),
            ]

            story = persona.get("story", {})
            for field in STORY_COLUMNS:
                value = story.get(field)
                # priorities is a list; flatten it to one cell so the CSV stays rectangular.
                row.append("; ".join(str(v) for v in value) if isinstance(value, list) else value)

            writer.writerow(row)

    print(f"Wrote {out_path.name} — {len(personas)} rows x {len(header)} columns")
    print(f"  interview columns : {', '.join(INTERVIEW_COLUMNS)}")
    print(f"  retired (blank)   : {', '.join(RETIRED_COLUMNS)}")
    print(f"  precise values    : {len(PRECISE_COLUMNS)} further columns")
    print(f"  story text        : {len(STORY_COLUMNS)} columns (story_*)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
