"""Draw personas that reproduce the real respondents' demographic mix.

Unlike the random draw in screen_and_draw.py, this one is deliberately NOT independent of the real
survey: it reproduces the joint distribution of age band x gender x income bracket x region taken
from match_targets.json.

What that buys and costs is worth stating plainly, because it changes what the end-of-month
comparison can claim:

  * GAINED — answer differences are no longer confounded by demographic differences. If the
    synthetic respondents answer differently, it is not because they were younger or richer.
  * LOST  — demographic agreement stops being evidence. The two sets match on these four variables
    by construction, so agreement there proves nothing. Only the ANSWERS remain informative.

Nothing about the respondents' answers enters this file. The only real-survey input is the
aggregate cell counts in match_targets.json.

Usage:
    python phase1/matched_draw.py --tag matched600
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_match_targets as targets_module  # noqa: E402
import labels  # noqa: E402
from screen_and_draw import REFERENCE_PERSON, describe, puma_to_county  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "out"

# US Census regions by state FIPS. Labels match the survey file's spelling exactly, including
# "NorthEast", so cell keys line up without normalisation.
REGION_BY_FIPS = {
    **{f: "NorthEast" for f in ["09", "23", "25", "33", "44", "50", "34", "36", "42"]},
    **{f: "Midwest" for f in ["17", "18", "26", "39", "55", "19", "20", "27", "29", "31", "38", "46"]},
    **{f: "South" for f in ["10", "12", "13", "24", "37", "45", "51", "11", "54",
                            "01", "21", "28", "47", "05", "22", "40", "48"]},
    **{f: "West" for f in ["04", "08", "16", "30", "32", "35", "49", "56",
                           "02", "06", "15", "41", "53"]},
}

SEX_LABEL = {1: "Male", 2: "Female"}

# Outdoor-space screen, applied at draw time so the final 600 all qualify and the cell mix stays
# exact. Deriving it from the Census structure type is deterministic and free; an LLM screener
# call per candidate would cost money, vary between runs, and add nothing the data does not say.
#
# PQ1 asks whether the property has outdoor area where a ~117 sq ft detached structure could go.
#   detached  BLD 2 only. A detached single-family house on its own lot is the defensible proxy.
#   lot       BLD 1, 2, 3 — adds mobile homes and attached houses, which sit on a lot but may not
#             have 117 sq ft of placeable yard.
#   none      no screen.
OUTDOOR_SPACE_BLD = {
    "detached": {2},
    "lot": {1, 2, 3},
}


def build_national_frame() -> pd.DataFrame:
    """Join national person and housing records into one row per household."""
    person = pd.read_parquet(OUT_DIR / "acs_person_slim_national.parquet")
    housing = pd.read_parquet(OUT_DIR / "acs_housing_slim_national.parquet")
    print(f"  person records  {len(person):,}")
    print(f"  housing records {len(housing):,}")

    housing = housing[pd.to_numeric(housing["TEN"], errors="coerce").notna()]
    print(f"  occupied units  {len(housing):,}")

    householders = person[pd.to_numeric(person["RELSHIPP"], errors="coerce") == REFERENCE_PERSON]
    frame = housing.merge(
        householders.drop(columns=[c for c in ("PUMA", "STATE") if c in householders.columns]),
        on="SERIALNO",
        how="inner",
        validate="one_to_one",
    )
    frame = frame[pd.to_numeric(frame["WGTP"], errors="coerce") > 0]
    print(f"  households with a householder record  {len(frame):,}")
    return frame.reset_index(drop=True)


def add_match_keys(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive the four variables the draw matches on."""
    frame = frame.copy()

    frame["household_income"] = (
        pd.to_numeric(frame["HINCP"], errors="coerce")
        * pd.to_numeric(frame["ADJINC"], errors="coerce")
        / 1_000_000
    )
    frame["age"] = pd.to_numeric(frame["AGEP"], errors="coerce")
    frame["m_age"] = frame["age"].map(lambda a: targets_module.age_band(int(a)) if pd.notna(a) else None)
    frame["m_gender"] = pd.to_numeric(frame["SEX"], errors="coerce").map(SEX_LABEL)
    frame["m_income"] = frame["household_income"].map(
        lambda d: targets_module.income_band(d) if pd.notna(d) else None
    )
    # ST arrives as an int from parquet; the region table is keyed by zero-padded FIPS.
    frame["m_region"] = (
        pd.to_numeric(frame["STATE"], errors="coerce")
        .map(lambda s: REGION_BY_FIPS.get(f"{int(s):02d}") if pd.notna(s) else None)
    )

    complete = frame[["m_age", "m_gender", "m_income", "m_region"]].notna().all(axis=1)
    dropped = int((~complete).sum())
    if dropped:
        print(f"  dropped {dropped:,} households missing a match key (incl. Puerto Rico, no region)")
    return frame[complete].reset_index(drop=True)


def draw_matched(frame: pd.DataFrame, cells: list[dict], seed: int) -> tuple[pd.DataFrame, list[dict]]:
    """Fill each target cell by weighted sampling from households in that same cell.

    Sampling is proportional to WGTP within the cell and without replacement, so no household is
    used twice. A cell the PUMS cannot fill is reported rather than quietly topped up from a
    neighbouring cell — a silent substitution would break the match it claims to make.
    """
    rng = np.random.default_rng(seed)
    grouped = {key: group for key, group in frame.groupby(["m_age", "m_gender", "m_income", "m_region"])}

    picked: list[pd.DataFrame] = []
    shortfalls: list[dict] = []

    for cell in cells:
        key = (cell["age_band"], cell["gender"], cell["income"], cell["region"])
        want = int(cell["count"])
        pool = grouped.get(key)

        if pool is None or pool.empty:
            shortfalls.append({**cell, "available": 0, "filled": 0})
            continue

        take = min(want, len(pool))
        weights = pool["WGTP"].to_numpy(dtype=float)
        idx = rng.choice(len(pool), size=take, replace=False, p=weights / weights.sum())
        picked.append(pool.iloc[idx])

        if take < want:
            shortfalls.append({**cell, "available": len(pool), "filled": take})

    drawn = pd.concat(picked, ignore_index=True) if picked else pd.DataFrame()
    return drawn, shortfalls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="matched600")
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument(
        "--outdoor-space",
        choices=["none", "detached", "lot"],
        default="detached",
        help="Restrict the pool to homes with usable outdoor space (Dr. Wang's screen).",
    )
    args = parser.parse_args()

    spec = json.loads((OUT_DIR / "match_targets.json").read_text())
    cells = spec["joint_cells"]
    print(f"Target: {spec['respondents_used']} respondents across {len(cells)} cells\n")

    print("Building the national frame")
    frame = add_match_keys(build_national_frame())
    print(f"  eligible households after match keys: {len(frame):,}")

    if args.outdoor_space != "none":
        allowed = OUTDOOR_SPACE_BLD[args.outdoor_space]
        before = len(frame)
        frame = frame[pd.to_numeric(frame["BLD"], errors="coerce").isin(allowed)].reset_index(drop=True)
        print(
            f"  outdoor-space screen ({args.outdoor_space}): {len(frame):,} of {before:,} "
            f"({len(frame)/before:.0%}) have usable outdoor space"
        )
    print()

    print(f"Drawing matched sample (seed {args.seed})")
    drawn, shortfalls = draw_matched(frame, cells, args.seed)
    print(f"  drawn: {len(drawn)} of {spec['respondents_used']}")
    if shortfalls:
        unfilled = sum(c["count"] - c["filled"] for c in shortfalls)
        print(f"  {len(shortfalls)} cells short, {unfilled} personas unfilled:")
        for cell in shortfalls[:8]:
            print(
                f"    want {cell['count']} got {cell['filled']}  "
                f"{cell['age_band']} / {cell['gender']} / {cell['income']} / {cell['region']}"
            )
    else:
        print("  every cell filled exactly")

    counties = puma_to_county()
    personas = []
    for index, (_, row) in enumerate(drawn.iterrows(), start=1):
        record = describe(row, counties)
        record["persona_id"] = f"M{index:03d}"
        record["match_age_band"] = row["m_age"]
        record["match_gender"] = row["m_gender"]
        record["match_income_bracket"] = row["m_income"]
        record["match_region"] = row["m_region"]
        personas.append(record)

    # Achieved vs target, so the match can be checked rather than trusted.
    achieved = {
        name: pd.Series([p[f"match_{name}"] for p in personas]).value_counts().to_dict()
        for name in ["age_band", "gender", "income_bracket", "region"]
    }

    payload = {
        "method": (
            "MATCHED DRAW. National ACS PUMS 2024 1-Year. Personas are drawn so that the joint "
            "distribution of age band x gender x income bracket x region reproduces the real "
            "survey respondents. Selection within each cell is proportional to the ACS household "
            "weight and without replacement. The earlier California / income / age screens are "
            "NOT applied — they excluded 97% of the real respondents."
        ),
        "matched_on": ["age_band", "gender", "income_bracket", "region"],
        "outdoor_space_screen": (
            "none — no eligibility screen applied" if args.outdoor_space == "none"
            else f"{args.outdoor_space}: ACS BLD in {sorted(OUTDOOR_SPACE_BLD[args.outdoor_space])}, "
                 "applied at draw time so all 600 qualify and the cell mix stays exact"
        ),
        "not_used_from_real_data": (
            "No answer column was read. Race and Hispanic origin were never read. Only aggregate "
            "cell counts were used, never respondent-level rows."
        ),
        "interpretation": (
            "Because these four variables match by construction, demographic agreement with the "
            "real respondents is not evidence of anything. Only answer-level agreement is "
            "informative. The independent random draw in phase1_personas_survey600owners is the "
            "set to use for any claim about demographic resemblance."
        ),
        "seed": args.seed,
        "target_respondents": spec["respondents_used"],
        "drawn": len(personas),
        "cells_targeted": len(cells),
        "cells_short": shortfalls,
        "target_marginals": spec["marginals"],
        "achieved_marginals": achieved,
        "personas": personas,
    }
    out_path = OUT_DIR / f"phase1_personas_{args.tag}.json"
    out_path.write_text(json.dumps(payload, indent=2))

    print("\nMatch check (target vs achieved):")
    for name, key in [("gender", "gender"), ("age", "age_band"), ("income", "income_bracket"), ("region", "region")]:
        print(f"  {name}:")
        target = spec["marginals"][name]
        for value in sorted(target, key=lambda v: -target[v]):
            got = achieved[key].get(value, 0)
            flag = "" if got == target[value] else "  <-- differs"
            print(f"    {value[:34]:<36} target {target[value]:>4}   got {got:>4}{flag}")

    print(f"\nWrote {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
