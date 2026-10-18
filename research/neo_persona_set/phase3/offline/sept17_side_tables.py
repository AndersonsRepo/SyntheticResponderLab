"""Sept 17 side tables behind EXPERIMENT_LOG.md (R010 and R004), recovered from the session transcript. Offline.

On 2026-09-17 (about 19:43-20:08 UTC) two tables were computed inline and only their numbers went into
the log. This script recomputes them from the saved run folders, and the real file for the real side:

  income-table   R010: purchase interest (our Q1 = real Q6) by household income band, real against the
                 DeepSeek and Qwen s1 baselines (both repeats pooled, all 200 persona-answers, no
                 screener filter, as on Sept 17), and the Spearman rho of income with Q1 and with Q2.
                 Synthetic income is the persona's exact_household_income; real income is the
                 Household Income band in its survey order (Spearman uses ranks only, so this equals
                 the band midpoints used on Sept 17). The real rho is computed here, from --real.
  money-reasons  R004: among Q1 = 1 ("not at all interested") answers in the two --reason-per-answer
                 runs, the share whose reason mentions money; and how many answers carry a reason.

Each subcommand prints its table and a logged-vs-reproduced check list, and writes both as CSVs to
--out (default: 5_experiments/2026-09-17_S1_prompt_and_sampling_tests/reproduced_2026-10-18 in the
Assets folder). The logged numbers are read from EXPERIMENT_LOG.md when the script runs. Only
aggregates of the real file are computed or written; --out may not be inside the repository or the
real-data folder.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/sept17_side_tables.py income-table \\
        --real "../SyntheticResponderLab-Assets/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv"
    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/sept17_side_tables.py money-reasons
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import historic_common as hc  # noqa: E402  (also puts phase3 on sys.path)
import metrics  # noqa: E402
import realdata  # noqa: E402

# Synthetic bands, cut on exact_household_income (as on Sept 17).
SYNTH_BANDS: List[Tuple[str, float, float]] = [
    ("under $50k", 0, 50000), ("$50k-$100k", 50000, 100000), ("$100k-$150k", 100000, 150000), ("$150k+", 150000, float("inf")),
]
# The real file's Household Income options in survey order, and the Sept 17 grouping of them.
REAL_INCOME_OPTIONS = ["$0 - $24,999", "$25,000 - $49,999", "$50,000 - $74,999", "$75,000 - $99,999", "$100,000 - $199,999", "$200,000 or more"]
REAL_GROUP = {"$0 - $24,999": "under $50k", "$25,000 - $49,999": "under $50k", "$50,000 - $74,999": "$50k-$100k",
              "$75,000 - $99,999": "$50k-$100k", "$100,000 - $199,999": "$100k-$200k", "$200,000 or more": "$200k+"}
REAL_GROUPS = ["under $50k", "$50k-$100k", "$100k-$200k", "$200k+"]
# Rows of the logged R010 table: (label in the log, real group, synthetic band).
LOGGED_ROWS = [("under $50k", "under $50k", "under $50k"), ("$50k–$100k", "$50k-$100k", "$50k-$100k"),
               ("$150k+ (real: $100k–$200k)", "$100k-$200k", "$150k+")]
MODELS = ("deepseek", "qwen")
# The Sept 17 money theme for R004 (judge reasons), verbatim.
MONEY_REASON = re.compile(r"\b(afford|budget|income|money|expensive|price|cost|\$23,?000|23k|savings|pay|finances|financial|retire|fixed income|debt|mortgage|rent)\b", re.I)


# --------------------------------------------------------------------------- pure helpers (tested)

def synth_band(income: float) -> Optional[str]:
    for name, low, high in SYNTH_BANDS:
        if low <= income < high:
            return name
    return None


def shares_1_to_5(values: Sequence[int]) -> List[float]:
    counts = Counter(values)
    return [counts.get(k, 0) / len(values) if values else hc.NAN for k in range(1, 6)]


def pct_text(shares: Sequence[float]) -> str:
    """'50 / 25 / 0 / 0 / 25', formatted the way the Sept 17 table was (format(share, '.0%'))."""
    return " / ".join(format(s, ".0%").rstrip("%") for s in shares)


def by_band(pairs: Sequence[Tuple[Optional[str], Optional[int]]]) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for band, answer in pairs:
        if band is not None and answer is not None:
            out.setdefault(band, []).append(answer)
    return out


def money_reason_share(rows: Sequence[Dict[str, str]], answer: str = "1", pattern: re.Pattern = MONEY_REASON) -> Tuple[int, int]:
    """(Q1 == answer rows whose reason matches, Q1 == answer rows)."""
    q1 = [r for r in rows if r.get("question_id") == "Q1" and str(r.get("answer", "")).strip() == answer]
    return sum(1 for r in q1 if pattern.search(r.get("reason") or "")), len(q1)


def parse_logged_r010(log: hc.LogText) -> Dict[str, Optional[Sequence[str]]]:
    """Logged table cells and rhos, read from the log (never stored in code)."""
    out: Dict[str, Optional[Sequence[str]]] = {}
    for label, _, _ in LOGGED_ROWS:
        cells = log.groups(r"\|\s*" + re.escape(label) + r"\s*\|\s*([\d /]+?)\s*\|\s*([\d /]+?)\s*\|\s*([\d /]+?)\s*\|")
        out[label] = cells
    out["rho_q1"] = log.groups(r"ρ\(income, Q1\): \*\*real ([\d.]+), DeepSeek ([\d.]+), Qwen ([\d.]+)\.\*\*")
    out["q2_identical"] = ("yes",) if log.contains("ρ(income, Q2) is identical to Q1") else None
    return out


# --------------------------------------------------------------------------- I/O

def read_rows(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def find_runs(runs_dir: Path, model: str, tag: str) -> List[Path]:
    runs = sorted(p for p in runs_dir.glob(f"*{model}*_s1-{tag}") if p.is_dir())
    if not runs:
        raise SystemExit(f"no {model} runs tagged s1-{tag} in {runs_dir}")
    return runs


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def synthetic_income_table(runs: List[Path], personas: Dict[str, Dict[str, str]]) -> Tuple[Dict[str, List[int]], float, float, int]:
    """Q1 by synthetic band, rho(income, Q1), rho(income, Q2) over all rows of the runs (no screener filter)."""
    pairs, inc, q1s, q2s = [], [], [], []
    for run in runs:
        for row in read_rows(run / "answers_wide.csv"):
            income = float(personas[row["persona_id"]]["exact_household_income"])
            a, b = _int(row.get("Q1")), _int(row.get("Q2"))
            pairs.append((synth_band(income), a))
            if a is not None and b is not None:
                inc.append(income)
                q1s.append(float(a))
                q2s.append(float(b))
    return by_band(pairs), metrics.spearman(inc, q1s), metrics.spearman(inc, q2s), len(inc)


def real_income_table(real: realdata.RealSurvey) -> Tuple[Dict[str, List[int]], float, float, int]:
    """Real Q6 by income group, rho(income band, Q6) and rho(income band, Q7). Aggregates only."""
    q6, q7, inc = real.find("Q6"), real.find("Q7"), real.find("Household Income")
    if not (q6 and q7 and inc):
        raise SystemExit("the real file has no Q6 / Q7 / Household Income column")
    pairs, x6, y6, x7, y7 = [], [], [], [], []
    for row in real.rows:
        option = row[inc].strip()
        a = realdata.likert_label_to_int(row[q6])
        if option not in REAL_GROUP or not a:
            continue
        pairs.append((REAL_GROUP[option], a))
        x6.append(float(REAL_INCOME_OPTIONS.index(option)))
        y6.append(float(a))
        b = realdata.likert_label_to_int(row[q7])
        if b:
            x7.append(x6[-1])
            y7.append(float(b))
    return by_band(pairs), metrics.spearman(x6, y6), metrics.spearman(x7, y7), len(x6)


def cmd_income_table(args: argparse.Namespace) -> int:
    assets = Path(args.assets)
    real_path = hc.real_file(args.real)
    out = hc.resolve_out(args.out, assets / hc.SEPT17_REL / hc.OUT_FOLDER, real_path)
    runs_dir = Path(args.runs_dir) if args.runs_dir else assets / hc.SEPT17_REL / "survey_runs"
    personas_csv = Path(args.personas) if args.personas else assets / hc.PERSONAS_600_V2_REL / "phase1_interview_matched600.csv"
    personas = {r["persona_id"]: r for r in read_rows(personas_csv)}
    log = hc.LogText.read(Path(args.log) if args.log else assets / hc.LOG_REL)
    logged = parse_logged_r010(log)

    synth = {m: synthetic_income_table(find_runs(runs_dir, m, "baseline"), personas) for m in MODELS}
    real_bands, real_rho6, real_rho7, n_real = real_income_table(realdata.load_real_survey(real_path))

    table = []
    print("Q1 purchase interest by household income, shares of 1 / 2 / 3 / 4 / 5 (synthetic: pooled r1+r2, all rows)")
    for source, bands, order in [("real 600 (Q6)", real_bands, REAL_GROUPS)] + [(f"{m} baseline", synth[m][0], [b for b, _, _ in SYNTH_BANDS]) for m in MODELS]:
        for band in order:
            values = bands.get(band, [])
            if not values:
                continue
            shares = shares_1_to_5(values)
            table.append({"source": source, "income_band": band, "n": len(values), "share_1": shares[0], "share_2": shares[1], "share_3": shares[2],
                          "share_4": shares[3], "share_5": shares[4], "mean": sum(values) / len(values)})
            print(f"  {source:18s} {band:12s} n={len(values):4d}  {pct_text(shares):24s} mean {sum(values) / len(values):.2f}")
    rhos = [{"source": "real 600", "income": "band order (= midpoints)", "n": n_real, "rho_income_q1": real_rho6, "rho_income_q2": real_rho7}]
    rhos += [{"source": f"{m} baseline", "income": "exact_household_income", "n": synth[m][3], "rho_income_q1": synth[m][1], "rho_income_q2": synth[m][2]} for m in MODELS]
    print("Spearman rho of income with purchase interest (Q1 / real Q6) and likelihood (Q2 / real Q7):")
    for r in rhos:
        print(f"  {r['source']:18s} n={r['n']:4d}  rho(income, Q1)={r['rho_income_q1']:.3f}  rho(income, Q2)={r['rho_income_q2']:.3f}")

    checks = []
    for label, real_group, synth_band_name in LOGGED_ROWS:
        cells = logged.get(label)
        columns = [("real", real_bands.get(real_group, [])), ("DeepSeek", synth["deepseek"][0].get(synth_band_name, [])),
                   ("Qwen", synth["qwen"][0].get(synth_band_name, []))]
        for i, (who, values) in enumerate(columns):
            got = pct_text(shares_1_to_5(values)) if values else "no rows"
            want = None if cells is None else re.sub(r"\s*/\s*", " / ", cells[i].strip())
            checks.append(hc.check_row("income-table", f"R010 {label}: {who} Q1 shares %", want, got, want == got,
                                       f"n={len(values)}; real group {real_group}" if who == "real" else f"n={len(values)}; synthetic band {synth_band_name}"))
    rho_logged = logged.get("rho_q1")
    for i, (who, value) in enumerate([("real", real_rho6), ("DeepSeek", synth["deepseek"][1]), ("Qwen", synth["qwen"][1])]):
        checks.append(hc.numeric_check("income-table", f"rho(income, Q1) {who}", None if rho_logged is None else rho_logged[i], value, digits=3,
                                       note="computed from the real file at run time" if who == "real" else "pooled r1+r2, exact income"))
    for m in MODELS:
        same = f"{synth[m][1]:.2f}" == f"{synth[m][2]:.2f}"
        checks.append(hc.check_row("income-table", f"rho(income, Q2) identical to Q1 ({m})", None if logged.get("q2_identical") is None else "identical",
                                   f"{synth[m][2]:.3f} vs {synth[m][1]:.3f}", same and logged.get("q2_identical") is not None, "compared at 2 decimals"))
    hc.write_csv(out / "R010_income_table.csv", table)
    hc.write_csv(out / "R010_income_rho.csv", rhos)
    hc.write_csv(out / "checks_income-table.csv", checks, hc.CHECK_COLUMNS)
    print("logged vs reproduced:")
    hc.print_checks(checks)
    print(f"wrote {out}")
    return 0


def cmd_money_reasons(args: argparse.Namespace) -> int:
    assets = Path(args.assets)
    out = hc.resolve_out(args.out, assets / hc.SEPT17_REL / hc.OUT_FOLDER)
    runs_dir = Path(args.runs_dir) if args.runs_dir else assets / hc.SEPT17_REL / "survey_runs"
    log = hc.LogText.read(Path(args.log) if args.log else assets / hc.LOG_REL)
    logged_shares = log.groups(r"a money reason appears in (\d+)% \(DeepSeek\) and (\d+)% \(Qwen\)")
    logged_count = log.groups(r"gave a reason for every one of ([\d,]+) answers")

    rows_out, checks = [], []
    print("R004: reasons for Q1 = 1 that mention money (Sept 17 theme regex), per --reason-per-answer run")
    for i, model in enumerate(MODELS):
        runs = find_runs(runs_dir, model, "reasons")
        if len(runs) != 1:
            raise SystemExit(f"expected one {model} reasons run, found {len(runs)}")
        rows = read_rows(runs[0] / "answers_long.csv")
        hits, n = money_reason_share(rows)
        with_reason = sum(1 for r in rows if (r.get("reason") or "").strip())
        rows_out.append({"model": model, "run": runs[0].name, "answers": len(rows), "answers_with_reason": with_reason,
                         "q1_eq_1": n, "q1_eq_1_money_reason": hits, "share": hits / n if n else hc.NAN})
        print(f"  {model:9s} {runs[0].name}: {with_reason}/{len(rows)} answers carry a reason; Q1 = 1 n={n}, money {hits} ({hits / n:.0%})")
        checks.append(hc.numeric_check("money-reasons", f"Q1=1 money-reason share ({model})", None if logged_shares is None else logged_shares[i] + "%",
                                       hits / n if n else None, percent=True, digits=1, note=f"{hits} of {n}"))
        checks.append(hc.check_row("money-reasons", f"answers with a reason ({model})", None if logged_count is None else logged_count[0],
                                   f"{with_reason} of {len(rows)}", logged_count is not None and with_reason == len(rows) == hc.to_number(logged_count[0])))
    hc.write_csv(out / "R004_money_reasons.csv", rows_out)
    hc.write_csv(out / "checks_money-reasons.csv", checks, hc.CHECK_COLUMNS)
    print("logged vs reproduced:")
    hc.print_checks(checks)
    print(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    commands: Dict[str, Tuple[Callable[[argparse.Namespace], int], str]] = {
        "income-table": (cmd_income_table, "R010: Q1 by income band, real vs DeepSeek / Qwen, and rho(income, Q1/Q2)"),
        "money-reasons": (cmd_money_reasons, "R004: share of Q1 = 1 reasons that mention money"),
    }
    for name, (func, help_text) in commands.items():
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--assets", type=Path, default=hc.DEFAULT_ASSETS, help="the reorganized research data folder (default: next to the repo)")
        p.add_argument("--runs-dir", type=Path, default=None, help="Sept 17 survey_runs (default: <assets>/5_experiments/2026-09-17_S1_prompt_and_sampling_tests/survey_runs)")
        p.add_argument("--log", type=Path, default=None, help="EXPERIMENT_LOG.md to read the logged numbers from (default: <assets>/0_logs/EXPERIMENT_LOG.md)")
        p.add_argument("--out", type=Path, default=None, help="output folder, outside the repo (default: <Sept 17 folder>/reproduced_2026-10-18)")
        if name == "income-table":
            p.add_argument("--real", type=Path, required=True, help="the AYTM raw-data CSV (read for aggregates only)")
            p.add_argument("--personas", type=Path, default=None, help="persona file the Sept 17 runs used (default: matched 600 v2)")
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
