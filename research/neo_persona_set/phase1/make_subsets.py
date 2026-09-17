"""Partition the matched 600 into 6 demographically equivalent subsets of 100.

Why a PARTITION rather than 6 independent samples: every persona is used exactly once, so the six
subsets are mutually exclusive. Independent samples would reuse people across subsets, and any
"replication" on a later subset would be partly re-testing the same personas.

Why stratified rather than random: the subsets exist so different models can be compared. If one
model happens to draw a subset that skews older or poorer, its results differ for reasons that have
nothing to do with the model. Dealing round-robin within each demographic cell keeps all six
subsets close to the same mix, so a difference between models is a difference between models.

Usage:
    python phase1/make_subsets.py --tag matched600 --subsets 6
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "out"

CELL_KEYS = ["match_age_band", "match_gender", "match_income_bracket", "match_region"]


def partition(personas: list[dict], n_subsets: int, seed: int) -> list[list[dict]]:
    """Deal personas into n_subsets so all four margins stay balanced at once.

    A single sort order cannot do this. Dealing cell-by-cell balances whichever variable leads the
    ordering and lets the others drift: age-first gave one subset 31 Westerners against another's
    19, and region-first fixed region but spread gender from 43 to 58.

    So assignment is greedy on the deficit instead. Each persona goes to whichever subset is
    currently furthest BELOW its target share for that persona's own four attribute values, summed.
    Every subset is pulled toward the parent mix on all four margins simultaneously, and no single
    variable is privileged by sort position.
    """
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(personas))

    size_target = len(personas) / n_subsets
    targets: dict[str, dict] = {}
    for key in CELL_KEYS:
        counts = Counter(p.get(key) for p in personas)
        targets[key] = {value: count / n_subsets for value, count in counts.items()}

    buckets: list[list[dict]] = [[] for _ in range(n_subsets)]
    counts: list[dict[str, Counter]] = [{key: Counter() for key in CELL_KEYS} for _ in range(n_subsets)]

    for position in order:
        persona = personas[position]
        best, best_score = None, None
        for index in range(n_subsets):
            if len(buckets[index]) >= size_target:
                continue  # keep subset sizes equal; a full one takes no more
            # Deficit across this persona's own four values: higher means this subset needs it more.
            score = sum(
                targets[key].get(persona.get(key), 0) - counts[index][key][persona.get(key)]
                for key in CELL_KEYS
            )
            if best_score is None or score > best_score:
                best, best_score = index, score

        if best is None:  # every subset at capacity; fall back to the emptiest
            best = min(range(n_subsets), key=lambda i: len(buckets[i]))

        buckets[best].append(persona)
        for key in CELL_KEYS:
            counts[best][key][persona.get(key)] += 1

    return buckets


def marginal_table(personas: list[dict], key: str) -> dict[str, int]:
    return dict(Counter(p.get(key) for p in personas))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="matched600")
    parser.add_argument("--subsets", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20260915)
    args = parser.parse_args()

    payload = json.loads((OUT_DIR / f"phase1_personas_{args.tag}_full.json").read_text())
    personas = payload["personas"]
    print(f"Partitioning {len(personas)} personas into {args.subsets} subsets\n")

    buckets = partition(personas, args.subsets, args.seed)

    # Every persona used once, none twice.
    ids = [p["persona_id"] for bucket in buckets for p in bucket]
    assert len(ids) == len(personas), f"{len(ids)} dealt vs {len(personas)} personas"
    assert len(set(ids)) == len(ids), "a persona landed in more than one subset"

    written = []
    for index, bucket in enumerate(buckets, start=1):
        subset_tag = f"{args.tag}_s{index}"
        out = dict(payload)
        out["personas"] = bucket
        out["subset"] = {
            "index": index,
            "of": args.subsets,
            "parent": args.tag,
            "size": len(bucket),
            "seed": args.seed,
            "method": (
                "Stratified partition of the parent set: personas were dealt round-robin within "
                "each age x gender x income x region cell, so every subset carries a like share of "
                "each cell and no persona appears in more than one subset."
            ),
        }
        path = OUT_DIR / f"phase1_personas_{subset_tag}_full.json"
        path.write_text(json.dumps(out, indent=2))
        written.append((subset_tag, len(bucket)))

    print(f"{'subset':<10}{'n':>5}   " + "  ".join(f"{r:<9}" for r in ["Female", "South", "West", "60-69", "70+"]))
    print("-" * 72)
    for (subset_tag, size), bucket in zip(written, buckets):
        gender = marginal_table(bucket, "match_gender")
        region = marginal_table(bucket, "match_region")
        age = marginal_table(bucket, "match_age_band")
        print(
            f"{subset_tag[-2:]:<10}{size:>5}   "
            f"{gender.get('Female',0):<9}  {region.get('South',0):<9}  {region.get('West',0):<9}  "
            f"{age.get('60-69',0):<9}  {age.get('70+',0):<9}"
        )

    parent_gender = marginal_table(personas, "match_gender")
    parent_region = marginal_table(personas, "match_region")
    parent_age = marginal_table(personas, "match_age_band")
    expected = args.subsets
    print("-" * 72)
    print(
        f"{'parent/6':<10}{len(personas)//expected:>5}   "
        f"{parent_gender.get('Female',0)/expected:<9.1f}  {parent_region.get('South',0)/expected:<9.1f}  "
        f"{parent_region.get('West',0)/expected:<9.1f}  {parent_age.get('60-69',0)/expected:<9.1f}  "
        f"{parent_age.get('70+',0)/expected:<9.1f}"
    )

    print(f"\nWrote {len(written)} subset files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
