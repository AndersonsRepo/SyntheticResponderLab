"""Compression diagnostics for one or more experiment arms, beyond the distance to the real 600.

For each arm (a set of run folders, ideally two repeats on the same personas) it reports:
  q1_ne_q2_share    share of personas whose Q1 (interest) and Q2 (likelihood) answers differ
  mean_sd           mean within-question standard deviation over the 25 likert items (the real survey's: --real-from)
  top2_share        share of likert answers that are 4 or 5
  repeat_agreement  share of answers identical between repeat 1 and repeat 2 (same persona)
  q1_concept_corr   Pearson r between Q1 and the mean of Q9B..Q13B (concept purchase likelihood):
                    high when one early stance drives every later answer
  rho_income_q1     Spearman rank correlation between the persona's exact household income and Q1
                    (needs --personas). The real association needs respondent-level income, so it is
                    not computed here; it is recorded with R010 in the Assets folder beside the
                    repository (0_logs/EXPERIMENT_LOG.md), not in this file

--real-from <compare_real output folder> adds a "real" row computed at runtime from that folder's
comparison_options.csv: mean_sd and top2_share over the likert items compare_real maps (24; Q7 has
no real counterpart), for whichever real respondents that comparison scored. The other columns need
respondent-level joins and read n/a. No real value is written into this file; with --real-from the
--out file holds real-derived numbers, so it must be outside the repository.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/spread_diagnostics.py \\
        --arm baseline=<run_r1>,<run_r2> --arm qpc10=<run_r1>,<run_r2> [--personas <persona csv>] \\
        [--real-from <compare_real output folder>] [--out diagnostics.csv]
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import make_real_split  # noqa: E402
import realdata  # noqa: E402

LIKERT_ITEMS = ["Q0B", "Q1", "Q2", "Q5_1", "Q5_2", "Q5_3", "Q5_4", "Q5_5", "Q5_6", "Q5_7", "Q7", "Q9A", "Q9B", "Q10A", "Q10B",
                "Q11A", "Q11B", "Q12A", "Q12B", "Q13A", "Q13B", "Q15", "Q16", "Q17", "Q19"]
CONCEPT_PURCHASE = ["Q9B", "Q10B", "Q11B", "Q12B", "Q13B"]
AGREEMENT_ITEMS = LIKERT_ITEMS + ["Q6", "Q14", "Q24"]
COLUMNS = ["arm", "runs", "n_personas", "n_likert_items", "q1_ne_q2_share", "mean_sd", "top2_share", "repeat_agreement", "q1_concept_corr", "rho_income_q1"]
NAN = float("nan")


def read_wide(run_dir: Path) -> List[Dict[str, str]]:
    with open(Path(run_dir) / "answers_wide.csv", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ranks(values: List[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2.0 + 1.0
        start = end + 1
    return ranks


def _spearman(x: List[float], y: List[float]) -> float:
    return _pearson(_ranks(x), _ranks(y))


def read_incomes(personas_csv: Optional[Path]) -> Dict[str, int]:
    if personas_csv is None:
        return {}
    with open(personas_csv, newline="", encoding="utf-8-sig") as handle:
        return {row["persona_id"]: int(float(row["exact_household_income"])) for row in csv.DictReader(handle) if (row.get("exact_household_income") or "").strip()}


def _pearson(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n < 3:
        return NAN
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return NAN
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def diagnose_arm(name: str, run_dirs: List[Path], personas_csv: Optional[Path] = None) -> Dict[str, Any]:
    runs = [read_wide(p) for p in run_dirs]
    incomes = read_incomes(personas_csv)
    inc_x: List[float] = []
    inc_y: List[float] = []
    items = [q for q in LIKERT_ITEMS if runs and q in runs[0][0]]
    values: Dict[str, List[int]] = {q: [] for q in items}
    ne, pairs, top, total = 0, 0, 0, 0
    q1s: List[float] = []
    concept: List[float] = []
    for rows in runs:
        for row in rows:
            a, b = _int(row.get("Q1")), _int(row.get("Q2"))
            if a is not None and b is not None:
                pairs += 1
                ne += a != b
            if a is not None and row.get("persona_id") in incomes:
                inc_x.append(float(incomes[row["persona_id"]]))
                inc_y.append(float(a))
            for q in items:
                v = _int(row.get(q))
                if v is not None:
                    values[q].append(v)
                    total += 1
                    top += v >= 4
            cp = [_int(row.get(q)) for q in CONCEPT_PURCHASE if q in row]
            cp = [v for v in cp if v is not None]
            if a is not None and cp:
                q1s.append(float(a))
                concept.append(sum(cp) / len(cp))
    sds = []
    for q, vs in values.items():
        if vs:
            m = sum(vs) / len(vs)
            sds.append(math.sqrt(sum((v - m) ** 2 for v in vs) / len(vs)))
    agreement = NAN
    if len(runs) >= 2:
        by_id = {row["persona_id"]: row for row in runs[0]}
        same = compared = 0
        for row in runs[1]:
            first = by_id.get(row["persona_id"])
            if first is None:
                continue
            for q in AGREEMENT_ITEMS:
                if q in row and q in first:
                    compared += 1
                    same += row[q] == first[q]
        agreement = same / compared if compared else NAN
    return {
        "arm": name, "runs": ";".join(Path(p).name for p in run_dirs), "n_personas": len(runs[0]) if runs else 0, "n_likert_items": len(items),
        "q1_ne_q2_share": ne / pairs if pairs else NAN, "mean_sd": sum(sds) / len(sds) if sds else NAN,
        "top2_share": top / total if total else NAN, "repeat_agreement": agreement, "q1_concept_corr": _pearson(q1s, concept),
        "rho_income_q1": _spearman(inc_x, inc_y) if inc_x else NAN,
    }


def read_real_likert(folder: Path) -> Dict[str, Dict[int, int]]:
    """{likert item: {level: real count}} from one compare_real output folder's comparison_options.csv.

    The file repeats every (question, option) row once per run compared in that folder; the real
    columns are identical in every repeat because they describe the real respondents, not the run,
    so later rows simply overwrite earlier ones with the same count.
    """
    counts: Dict[str, Dict[int, int]] = {}
    with open(Path(folder) / "comparison_options.csv", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("kind") != "likert" or row.get("our_id") not in LIKERT_ITEMS:
                continue
            level, count = _int(row.get("category")), _int(row.get("real_count"))
            if level is not None and count is not None:
                counts.setdefault(row["our_id"], {})[level] = count
    return counts


def diagnose_real(folder: Path) -> Dict[str, Any]:
    """The real side's likert SD and top-2 share, computed at runtime from compare_real's marginals.

    Same definitions as diagnose_arm: population SD per item, averaged over items; top-2 pooled over
    every likert answer. Columns that need respondent-level joins are NaN.
    """
    counts = read_real_likert(folder)
    items = [q for q in LIKERT_ITEMS if sum(counts.get(q, {}).values())]
    sds: List[float] = []
    top = total = largest = 0
    for q in items:
        levels = counts[q]
        n = sum(levels.values())
        mean = sum(level * c for level, c in levels.items()) / n
        sds.append(math.sqrt(sum(c * (level - mean) ** 2 for level, c in levels.items()) / n))
        top += sum(c for level, c in levels.items() if level >= 4)
        total += n
        largest = max(largest, n)
    return {
        "arm": "real", "runs": Path(folder).name, "n_personas": largest, "n_likert_items": len(items),
        "q1_ne_q2_share": NAN, "mean_sd": sum(sds) / len(sds) if sds else NAN, "top2_share": top / total if total else NAN,
        "repeat_agreement": NAN, "q1_concept_corr": NAN, "rho_income_q1": NAN,
    }


def _fmt(value: Any, pct: bool = False) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "n/a"
        return f"{value:.1%}" if pct else f"{value:.2f}"
    return str(value)


def render(arms: List[Dict[str, Any]]) -> str:
    header = "| arm | n | Q1 != Q2 | likert SD | answers 4-5 | repeat agreement | r(Q1, concept likelihood) | rho(income, Q1) |"
    lines = [header, "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for a in arms:
        lines.append(f"| {a['arm']} | {a['n_personas']} | {_fmt(a['q1_ne_q2_share'], True)} | {_fmt(a['mean_sd'])} | {_fmt(a['top2_share'], True)} | "
                     f"{_fmt(a['repeat_agreement'], True)} | {_fmt(a['q1_concept_corr'])} | {_fmt(a['rho_income_q1'])} |")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", action="append", required=True, metavar="NAME=RUN_DIR[,RUN_DIR...]")
    parser.add_argument("--personas", type=Path, default=None, help="persona CSV with exact_household_income, for the income gradient")
    parser.add_argument("--real-from", type=Path, default=None,
                        help="a compare_real output folder; adds a 'real' row computed from its marginals at runtime")
    parser.add_argument("--out", type=Path, default=None, help="also write the table as CSV")
    args = parser.parse_args(argv)
    if args.real_from is not None and args.out is not None:
        # The real row is derived from the AYTM file, so it never lands in the repository or the real-data folder.
        make_real_split.assert_outside_repo(realdata.assert_not_real_data_path(args.out, "--out"), "--out")
    arms = []
    for spec in args.arm:
        name, _, paths = spec.partition("=")
        arms.append(diagnose_arm(name.strip(), [Path(p.strip()) for p in paths.split(",") if p.strip()], personas_csv=args.personas))
    if args.real_from is not None:
        arms.append(diagnose_real(args.real_from))
    print(render(arms))
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(arms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
