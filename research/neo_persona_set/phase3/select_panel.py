"""Pick a fixed persona panel that keeps the full set's mix of a few strata. Deterministic by seed.

Cells are the combinations of the strata columns; each cell gets its share of --size by largest
remainder, then that many ids are drawn from the cell with random.Random(seed). The panel file has
one id per line and feeds run_survey.py --persona-ids; a summary JSON records the cell counts.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/select_panel.py \\
        --personas <csv> --size 150 --seed 20260912 --out <panel_ids.txt> [--strata sex,age_bucket,income_bucket]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_STRATA = ["sex", "age_bucket", "income_bucket"]


def read_rows(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def largest_remainder(cell_sizes: "OrderedDict[Tuple[str, ...], int]", size: int) -> Dict[Tuple[str, ...], int]:
    total = sum(cell_sizes.values())
    if total == 0:
        return {}
    exact = {cell: n * size / total for cell, n in cell_sizes.items()}
    allocated = {cell: int(exact[cell]) for cell in cell_sizes}
    remaining = size - sum(allocated.values())
    for cell in sorted(cell_sizes, key=lambda c: (-(exact[c] - allocated[c]), c))[:remaining]:
        allocated[cell] += 1
    for cell in cell_sizes:  # never allocate more than the cell holds
        allocated[cell] = min(allocated[cell], cell_sizes[cell])
    return allocated


def select_panel(rows: List[Dict[str, str]], *, size: int, seed: int, strata: List[str]) -> List[str]:
    if size > len(rows):
        raise ValueError(f"size {size} exceeds {len(rows)} personas")
    cells: "OrderedDict[Tuple[str, ...], List[str]]" = OrderedDict()
    for row in rows:
        key = tuple((row.get(column) or "").strip() for column in strata)
        cells.setdefault(key, []).append(row["persona_id"])
    allocation = largest_remainder(OrderedDict((cell, len(ids)) for cell, ids in cells.items()), size)
    rng = random.Random(seed)
    chosen = set()
    for cell, ids in cells.items():
        chosen.update(rng.sample(ids, allocation.get(cell, 0)))
    short = size - len(chosen)
    if short > 0:  # cells capped at their size left a gap; top up at random from the rest
        rest = [row["persona_id"] for row in rows if row["persona_id"] not in chosen]
        chosen.update(rng.sample(rest, short))
    return [row["persona_id"] for row in rows if row["persona_id"] in chosen]


def summary(rows: List[Dict[str, str]], ids: List[str], *, size: int, seed: int, strata: List[str]) -> Dict[str, Any]:
    picked = set(ids)
    cells: Dict[str, Dict[str, int]] = {}
    for row in rows:
        key = " | ".join((row.get(column) or "").strip() for column in strata)
        entry = cells.setdefault(key, {"all": 0, "selected": 0})
        entry["all"] += 1
        if row["persona_id"] in picked:
            entry["selected"] += 1
    return {"size": size, "seed": seed, "strata": strata, "personas": len(rows), "cells": cells}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--personas", type=Path, required=True)
    parser.add_argument("--size", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20260912)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strata", type=lambda s: [c.strip() for c in s.split(",") if c.strip()], default=DEFAULT_STRATA)
    args = parser.parse_args(argv)
    rows = read_rows(args.personas)
    ids = select_panel(rows, size=args.size, seed=args.seed, strata=args.strata)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(f"# panel of {len(ids)} from {args.personas.name}; seed {args.seed}; strata {','.join(args.strata)}\n" + "\n".join(ids) + "\n", encoding="utf-8")
    Path(str(args.out) + ".summary.json").write_text(json.dumps(summary(rows, ids, size=args.size, seed=args.seed, strata=args.strata), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(ids)} ids to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
