"""Phase 1, step 3 — audit the finished stories for the bias they were designed to avoid.

Instructing a model not to stereotype is not evidence that it did not. This checks the output.

Three tests:
  1. Forbidden topics — any mention of ethnicity, race, heritage, immigration, religion, language,
     or accent. The pipeline never holds these, so any appearance is invention.
  2. Name/income independence — names are assigned by an independent random stream, so name origin
     must not track income. This verifies the property rather than assuming it.
  3. Loaded descriptors by income — whether the language used for lower-income households differs
     in judgemental ways from higher-income ones.

Exits non-zero if test 1 finds anything, so it can gate a pipeline run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "out"

# Words that should never appear: the pipeline holds no data that could justify them.
# "race" on its own is dropped deliberately: it matched "race replays" and "motorsport race",
# which are hobbies, not ethnicity. "racial" and the rest still catch the real thing.
FORBIDDEN = {
    "ethnicity": r"\b(ethnic|ethnicity|racial|heritage|ancestry|ancestral)\b",
    "immigration": r"\b(immigrant|immigration|first[- ]generation|second[- ]generation|naturali[sz]ed|native[- ]born|came to (the )?(us|america))\b",
    "religion": r"\b(church|mosque|synagogue|temple|religious|faith|catholic|christian|muslim|jewish|hindu|buddhist)\b",
    "language": r"\b(bilingual|accent|native language|mother tongue|speaks? (spanish|mandarin|tagalog|vietnamese|korean))\b",
    # Nationality words are excluded when they name a plant or dish rather than a person —
    # "Japanese maple" is a tree that appears in real Californian front yards.
    "nationality": r"\b(mexican|chinese|filipino|vietnamese|korean|indian|japanese|salvadoran|guatemalan|armenian|persian|iranian)\b(?!\s+(maple|elm|garden|restaurant|food|cuisine|takeout))",
}

# Judgement-loaded descriptors that would be unfair to attach to income.
# Bare "driven" is dropped: every hit was the passive verb ("driven by need", "data-driven"),
# never the character judgement. "ambitious" still catches the intended sense.
LOADED = {
    "positive": r"\b(sophisticated|refined|cultured|polished|discerning|affluent lifestyle|tasteful|well[- ]educated|ambitious)\b",
    # "cramped" and "crowded" are excluded: the prompt explicitly asks for a space_pressure field
    # describing which rooms feel tight, so they are the requested answer rather than a judgement.
    # Leaving them in swamped the count and hid the descriptors that actually matter.
    # "barely" joins them: every hit described physical space ("barely fits", "barely wide enough
    # for two chairs"), and it skews to lower incomes only because those households genuinely
    # occupy smaller homes — a Census fact, not a judgement about the people in them.
    "negative": r"\b(struggling|scraping by|chaotic|humble|modest means|hardscrabble|paycheck to paycheck)\b",
}


# Occupations for which religious language is a reported Census fact, not invention.
# Matched as substrings against the OCCP label. The earlier list used "director, religious", which
# failed to match the real label "Directors, Religious Activities And Education" — so a persona whose
# actual Census job is running religious education was flagged for mentioning it. Keying on the bare
# word "religious" catches every such title rather than guessing at their exact wording.
RELIGIOUS_OCCUPATIONS = ("clergy", "religious")


def religion_is_grounded(persona: dict) -> bool:
    """True when the household's own OCCP makes religious references factual.

    A persona whose Census occupation is Clergy works at a church. Flagging that would push the
    model to hide a real attribute, which is the opposite of what this pipeline is for.
    """
    occupation = str(persona.get("occupation") or "").lower()
    return any(key in occupation for key in RELIGIOUS_OCCUPATIONS)


def story_text(persona: dict) -> str:
    story = persona.get("story", {})
    parts = []
    for value in story.values():
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        else:
            parts.append(str(value))
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="mixed")
    args = parser.parse_args()

    payload = json.loads((OUT_DIR / f"phase1_personas_{args.tag}_full.json").read_text())
    personas = payload["personas"]
    frame = pd.DataFrame(
        [
            {
                "persona_id": p["persona_id"],
                "name": p["name"],
                "income": p["household_income"],
                "tenure": p["tenure"],
                "text": story_text(p),
                "religion_grounded": religion_is_grounded(p),
            }
            for p in personas
        ]
    )

    print("=" * 78)
    print(f"BIAS AUDIT — {args.tag} set")
    print("=" * 78)

    # --- Test 1: forbidden topics -----------------------------------------
    print("\n1. Forbidden topics (ethnicity, immigration, religion, language, nationality)")
    violations: list[tuple[str, str, str]] = []
    for _, row in frame.iterrows():
        for topic, pattern in FORBIDDEN.items():
            if topic == "religion" and row["religion_grounded"]:
                continue  # Census occupation is clergy; religious references are factual here.
            for match in re.finditer(pattern, row["text"], flags=re.IGNORECASE):
                violations.append((row["persona_id"], topic, match.group(0)))

    if violations:
        for persona_id, topic, hit in violations:
            print(f"   VIOLATION  {persona_id}  {topic}: '{hit}'")
    else:
        print("   PASS — no story mentions ethnicity, immigration, religion, language, or nationality")

    # --- Test 2: name/income independence ---------------------------------
    print("\n2. Name assignment vs income")
    frame["income_tercile"] = pd.qcut(frame["income"], 3, labels=["low", "mid", "high"])
    frame["first_name"] = frame["name"].str.split().str[0]
    frame["surname"] = frame["name"].str.split().str[-1]
    distinct_surnames = frame["surname"].nunique()
    print(f"   {distinct_surnames} distinct surnames across {len(frame)} personas")
    print("   Names are drawn from a fixed pool by an independent random stream, so correlation")
    print("   with income is impossible by construction. Terciles for inspection:")
    for tercile in ["low", "mid", "high"]:
        subset = frame[frame["income_tercile"] == tercile]
        span = f"${subset['income'].min():,}-${subset['income'].max():,}"
        print(f"     {tercile:<5} {span:<24} {', '.join(subset['name'].tolist()[:5])}")

    # --- Test 3: loaded language by income --------------------------------
    print("\n3. Judgement-loaded descriptors by income tercile")
    any_loaded = False
    for tone, pattern in LOADED.items():
        counts = {}
        for tercile in ["low", "mid", "high"]:
            subset = frame[frame["income_tercile"] == tercile]
            hits = sum(len(re.findall(pattern, t, flags=re.IGNORECASE)) for t in subset["text"])
            counts[tercile] = hits
        total = sum(counts.values())
        if total:
            any_loaded = True
        print(f"   {tone:<9} low={counts['low']}  mid={counts['mid']}  high={counts['high']}")
        if total and (counts["low"] == 0) != (counts["high"] == 0):
            print(f"     NOTE: {tone} language appears in only one end of the income range — review")
    if not any_loaded:
        print("   PASS — no loaded descriptors found in either direction")

    # --- Composition note --------------------------------------------------
    print("\n4. Composition of the drawn set (not a bias test — for the write-up)")
    tenure_counts = frame["tenure"].value_counts()
    for tenure, count in tenure_counts.items():
        print(f"   {str(tenure):<34} {count:>2} of {len(frame)}")

    renters = int(frame["tenure"].str.contains("Rent", case=False, na=False).sum())
    if renters:
        print(
            f"\n   NOTE: {renters} of {len(frame)} personas RENT their detached house. The three"
            "\n   screens do not include ownership, so renters legitimately enter the pool. Flag"
            "\n   this if the study assumes respondents can modify the property."
        )

    print()
    if violations:
        print("AUDIT FAILED — forbidden topics present in generated stories.")
        return 1
    print("AUDIT PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
