"""Paired bootstrap over personas: does a difference between two experiment arms survive resampling? Offline.

Recovered 2026-10-18 from the Oct 5 inline analysis (the noise check Anderson's real-baselines report
asked for before S2 is locked; results in 5_experiments/2026-10-05_noise_check_and_average_shape).
No API calls and no real survey data: it reads saved synthetic run folders and the persona file's
exact_household_income.

An arm is one or more run folders on the same personas (normally the two repeats). For one question
(default Q1, purchase interest) each run gives three persona-level statistics:
  rho_belief      Spearman between the persona's exact household income and the run's expected
                  answer (sum of option x probability in probabilities.csv); a run without
                  probabilities.csv uses its point answers from answers_wide.csv
  top45_expected  share answering 4 or 5, expected from the stated odds (point answers when none)
  top45_drawn     share whose drawn (or point) answer is 4 or 5
An arm's statistic is the mean over its runs. Each bootstrap resample draws the persona list with
replacement, the same draw for both arms (paired), and recomputes A - B; the interval is the 2.5th
to 97.5th percentile over resamples, and the difference "separates" when the interval excludes 0.
One random.Random(--seed) serves the comparisons in the order given (as on Oct 5), so a
comparison's interval depends on its position in the list.

Optional tie-table gaps (--summaries, --gap): repeat-mean TV and rank agreement (mean_spearman) are
read from compare_real.py comparison_summary.csv files and differenced. The tie band is a
real-vs-real number from Anderson's report, so it is passed in (--tie-band-tv / --tie-band-rank)
and never stored here.

--preset oct05 fills in the Oct 5 arms (R018u, R020, R021, R021b on the 100 S1 personas), the six
comparisons, the persona file and the summary globs, relative to --assets:

    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/noise_check_bootstrap.py \\
        --preset oct05 --assets ../SyntheticResponderLab-Assets \\
        --tie-band-tv <TV band> --tie-band-rank <rank band> \\
        --out ../SyntheticResponderLab-Assets/5_experiments/2026-10-05_noise_check_and_average_shape/reproduced_2026-10-18

or explicitly:

    ... noise_check_bootstrap.py --personas <persona csv> --arm A=<run_r1>,<run_r2> --arm B=<run_r1>,<run_r2> \\
        --compare A,B,rho_belief --compare A,B,top45_drawn --out <folder outside the repo>

Outputs in --out: bootstrap.csv, gaps.csv (with --gap), noise_check.json (inputs, settings, results).
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import random
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
REPO_ROOT = PHASE3.parents[2]
if str(PHASE3) not in sys.path:
    sys.path.insert(0, str(PHASE3))

import filter_qualified  # noqa: E402
import make_real_split  # noqa: E402
import metrics  # noqa: E402
import realdata  # noqa: E402

SCRIPT_PATH = "research/neo_persona_set/phase3/offline/noise_check_bootstrap.py"
CSV_ENCODING = "utf-8-sig"
KINDS: Dict[str, str] = {
    "rho_belief": "income link: Spearman(income, expected answer; point answers when a run has no odds)",
    "top45_expected": "share answering 4-5, expected from the stated odds (point answers when none)",
    "top45_drawn": "share whose drawn / point answer is 4-5",
}
BOOTSTRAP_COLUMNS = ["a", "b", "kind", "question", "n_personas", "observed_a", "observed_b", "diff", "ci_low", "ci_high",
                     "reading", "a_uses_odds", "b_uses_odds", "resamples", "seed", "description"]
GAP_COLUMNS = ["a", "b", "tv_a", "tv_b", "tv_gap_a_better", "rank_a", "rank_b", "rank_gap_a_better", "n_runs_a", "n_runs_b",
               "tv_reading", "rank_reading"]

PRESETS: Dict[str, Dict[str, Any]] = {
    "oct05": {
        "personas": "4_persona_sets/matched_600_v2_S1-S6_2026-09-16/phase1_interview_matched600_s1.csv",
        # arm -> glob under 5_experiments; each must match exactly the two repeats
        "arms": {
            "R018u": "2026-09-30_rescore_on_DrLin_standard/survey_runs/*R018u*",
            "R021": "2026-10-02_R021_drawing_only_vs_drivers_only/survey_runs/*mixed-panel*R021-draw-mixed",
            "R021b": "2026-10-02_R021_drawing_only_vs_drivers_only/survey_runs/*mixed-panel*R021b-hybrid-mixed",
            "R020": "2026-10-01_R020_drivers_plus_drawing/survey_runs/*mixed-panel*R020-hybrid-mixed",
        },
        "runs_per_arm": 2,
        "compare": [("R020", "R021", "rho_belief"), ("R020", "R021", "top45_expected"), ("R020", "R021", "top45_drawn"),
                    ("R021b", "R018u", "rho_belief"), ("R021b", "R018u", "top45_drawn"), ("R021", "R018u", "top45_drawn")],
        "summaries": ["5_experiments/*/real_comparison/*lin13-validation*/comparison_summary.csv",
                      "5_experiments/*/*lin13-validation-rescore/comparison_summary.csv"],
        # arm -> substring of the run_id in the comparison summaries
        "gap_arms": {"R018u": "R018u-unstyled", "R021": "R021-draw-mixed", "R021b": "R021b-hybrid-mixed",
                     "R020": "R020-hybrid-mixed", "R020b": "R020b-hybrid-mixed", "random": "RANDOM"},
        "gaps": [("R021", "R018u"), ("R020", "R021"), ("R020b", "R020"), ("R020", "random"), ("R021b", "R018u")],
    },
}


# ---------------------------------------------------------------- loading


class RunAnswers:
    """One run's answers to one question: point answers, and expected / 4-5 mass from the odds when present."""

    def __init__(self, path: Path, point: Dict[str, int], expected: Optional[Dict[str, float]], top45: Optional[Dict[str, float]]) -> None:
        self.path = path
        self.point = point
        self.expected = expected
        self.top45 = top45

    @property
    def uses_odds(self) -> bool:
        return self.expected is not None


def _leading_int(cell: Optional[str]) -> Optional[int]:
    text = (cell or "").strip()
    return int(text[0]) if text[:1].isdigit() else None


def load_run(run_dir: Path, question: str = "Q1") -> RunAnswers:
    """Point answers from answers_wide.csv; expected answer and 4-5 mass from probabilities.csv if the run has one."""
    run_dir = Path(run_dir)
    point: Dict[str, int] = {}
    with open(run_dir / "answers_wide.csv", newline="", encoding=CSV_ENCODING) as handle:
        for row in csv.DictReader(handle):
            value = _leading_int(row.get(question))
            if value is not None:
                point[row["persona_id"]] = value
    probabilities = run_dir / "probabilities.csv"
    if not probabilities.is_file():
        return RunAnswers(run_dir, point, None, None)
    expected: Dict[str, float] = defaultdict(float)
    top45: Dict[str, float] = defaultdict(float)
    with open(probabilities, newline="", encoding=CSV_ENCODING) as handle:
        for row in csv.DictReader(handle):
            if row.get("question_id") != question or not (row.get("probability") or "").strip():
                continue
            option = int(row["option"])
            probability = float(row["probability"])
            expected[row["persona_id"]] += option * probability
            if option >= 4:
                top45[row["persona_id"]] += probability
    return RunAnswers(run_dir, point, dict(expected), dict(top45))


def load_incomes(path: Path) -> Dict[str, float]:
    """persona_id -> exact_household_income; personas with a blank or non-numeric income are left out."""
    incomes: Dict[str, float] = {}
    with open(path, newline="", encoding=CSV_ENCODING) as handle:
        for row in csv.DictReader(handle):
            try:
                incomes[row["persona_id"]] = float(row["exact_household_income"])
            except (KeyError, TypeError, ValueError):
                continue
    return incomes


def expand_runs(spec: str) -> List[Path]:
    """Comma-separated run folders; an entry with a wildcard is expanded (sorted)."""
    runs: List[Path] = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        matches = sorted(glob.glob(part)) if any(ch in part for ch in "*?[") else [part]
        if not matches:
            raise ValueError(f"no run folder matches {part!r}")
        runs.extend(Path(m) for m in matches)
    return runs


# ---------------------------------------------------------------- statistics


def run_stat(run: RunAnswers, kind: str, ids: Sequence[str], incomes: Dict[str, float]) -> float:
    if kind == "rho_belief":
        answers = run.expected if run.expected is not None else run.point
        return metrics.spearman([incomes[i] for i in ids], [float(answers[i]) for i in ids])
    if kind == "top45_drawn":
        return sum(run.point[i] >= 4 for i in ids) / len(ids)
    if kind == "top45_expected":
        if run.top45 is not None:
            return sum(run.top45[i] for i in ids) / len(ids)
        return sum(float(run.point[i] >= 4) for i in ids) / len(ids)
    raise ValueError(f"unknown statistic {kind!r}; expected one of {sorted(KINDS)}")


def arm_stat(runs: Sequence[RunAnswers], kind: str, ids: Sequence[str], incomes: Dict[str, float]) -> float:
    """Mean of the statistic over the arm's runs (the repeats)."""
    values = [run_stat(run, kind, ids, incomes) for run in runs]
    return sum(values) / len(values)


def common_personas(arms: Dict[str, List[RunAnswers]], incomes: Dict[str, float]) -> List[str]:
    """Sorted persona ids that have an income and an answer (and odds, where a run has odds) in every run."""
    ids = set(incomes)
    for runs in arms.values():
        for run in runs:
            ids &= set(run.point)
            if run.expected is not None:
                ids &= set(run.expected)
    return sorted(ids)


def percentile_range(sorted_values: Sequence[float]) -> Tuple[float, float]:
    """(2.5th, 97.5th) percentile of an ascending list, as on Oct 5: v[int(.025 n)], v[int(.975 n) - 1]."""
    n = len(sorted_values)
    return sorted_values[int(0.025 * n)], sorted_values[int(0.975 * n) - 1]


def paired_bootstrap(stat_a: Callable[[Sequence[str]], float], stat_b: Callable[[Sequence[str]], float], pids: Sequence[str],
                     resamples: int, rng: random.Random) -> Tuple[float, float, float, float, float]:
    """(observed A, observed B, A - B, interval low, interval high); both arms see the same resample."""
    observed_a, observed_b = stat_a(pids), stat_b(pids)
    diffs: List[float] = []
    for _ in range(resamples):
        ids = [rng.choice(pids) for _ in pids]
        diffs.append(stat_a(ids) - stat_b(ids))
    diffs.sort()
    low, high = percentile_range(diffs)
    return observed_a, observed_b, observed_a - observed_b, low, high


def reading(low: float, high: float) -> str:
    if low > 0:
        return "separates (A higher)"
    if high < 0:
        return "separates (A lower)"
    return "tie"


# ---------------------------------------------------------------- tie-table gaps


def read_summaries(paths: Sequence[Path]) -> Dict[str, Tuple[float, float]]:
    """run_id -> (mean_tv, mean_spearman) from comparison_summary.csv files; a later file wins on a repeated run_id."""
    scores: Dict[str, Tuple[float, float]] = {}
    for path in paths:
        with open(path, newline="", encoding=CSV_ENCODING) as handle:
            for row in csv.DictReader(handle):
                scores[row["run_id"]] = (float(row["mean_tv"]), float(row["mean_spearman"]))
    return scores


def arm_scores(scores: Dict[str, Tuple[float, float]], tag: str, repeats: Optional[int]) -> Tuple[float, float, int]:
    """Mean TV and rank over the runs whose run_id contains `tag` (identical score pairs counted once)."""
    values = list(dict.fromkeys(scores[k] for k in scores if tag in k))
    if not values:
        raise ValueError(f"no scored run matches {tag!r}")
    if repeats is not None and len(values) != repeats:
        raise ValueError(f"{tag!r}: expected {repeats} scored runs, found {len(values)}")
    return sum(v[0] for v in values) / len(values), sum(v[1] for v in values) / len(values), len(values)


def gap_reading(gap: float, band: Optional[float]) -> str:
    if band is None:
        return ""
    if abs(gap) < band:
        return "tie"
    return "A better" if gap > 0 else "A worse"


def gap_rows(scores: Dict[str, Tuple[float, float]], tags: Dict[str, str], pairs: Sequence[Tuple[str, str]], repeats: Optional[int],
             band_tv: Optional[float], band_rank: Optional[float]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for a, b in pairs:
        tv_a, rank_a, n_a = arm_scores(scores, tags[a], repeats)
        tv_b, rank_b, n_b = arm_scores(scores, tags[b], repeats)
        tv_gap, rank_gap = tv_b - tv_a, rank_a - rank_b
        rows.append({"a": a, "b": b, "tv_a": tv_a, "tv_b": tv_b, "tv_gap_a_better": tv_gap, "rank_a": rank_a, "rank_b": rank_b,
                     "rank_gap_a_better": rank_gap, "n_runs_a": n_a, "n_runs_b": n_b,
                     "tv_reading": gap_reading(tv_gap, band_tv), "rank_reading": gap_reading(rank_gap, band_rank)})
    return rows


# ---------------------------------------------------------------- output


def _cell(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_csv(path: Path, header: List[str], rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(row.get(key, "")) for key in header})


def git_info() -> Dict[str, Any]:
    def _run(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""

    return {"commit": _run("rev-parse", "HEAD"), "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(_run("status", "--porcelain", "--untracked-files=no"))}


def _pair(text: str, n: int, flag: str) -> Tuple[str, ...]:
    parts = tuple(p.strip() for p in text.split(","))
    if len(parts) != n or not all(parts):
        raise argparse.ArgumentTypeError(f"{flag} expects {n} comma-separated values, got {text!r}")
    return parts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="output folder (outside the repository)")
    parser.add_argument("--preset", choices=sorted(PRESETS), default=None, help="fill in arms, comparisons, personas and summaries")
    parser.add_argument("--assets", type=Path, default=None, help="the SyntheticResponderLab-Assets folder (needed with --preset)")
    parser.add_argument("--personas", type=Path, default=None, help="persona CSV with persona_id and exact_household_income")
    parser.add_argument("--arm", action="append", default=[], metavar="NAME=RUN[,RUN...]", help="an arm and its run folders (repeats)")
    parser.add_argument("--compare", action="append", default=[], metavar="A,B,KIND", help=f"a comparison; KIND is one of {', '.join(KINDS)}")
    parser.add_argument("--question", default="Q1")
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--summaries", action="append", default=[], metavar="GLOB", help="comparison_summary.csv files for the tie-table gaps")
    parser.add_argument("--gap-arm", action="append", default=[], metavar="NAME=RUN_ID_TAG", help="arm name -> substring of its run_ids in the summaries")
    parser.add_argument("--gap", action="append", default=[], metavar="A,B", help="a tie-table gap (A vs B)")
    parser.add_argument("--gap-repeats", type=int, default=2, help="scored runs expected per arm in the summaries (0 = any)")
    parser.add_argument("--tie-band-tv", type=float, default=None, help="TV gap below which two panels tie (from Anderson's report)")
    parser.add_argument("--tie-band-rank", type=float, default=None, help="rank-agreement gap below which two panels tie")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    out = make_real_split.assert_outside_repo(args.out, "--out")
    out = realdata.assert_not_real_data_path(out, "--out")

    arm_specs: Dict[str, List[Path]] = {}
    compares: List[Tuple[str, ...]] = []
    summary_globs: List[str] = list(args.summaries)
    gap_tags: Dict[str, str] = {}
    gaps: List[Tuple[str, ...]] = []
    personas = args.personas
    runs_per_arm: Optional[int] = None
    try:
        if args.preset:
            if args.assets is None:
                raise ValueError("--preset needs --assets")
            preset = PRESETS[args.preset]
            assets = Path(args.assets).expanduser().resolve()
            runs_per_arm = preset["runs_per_arm"]
            for name, pattern in preset["arms"].items():
                arm_specs[name] = [Path(p) for p in sorted(glob.glob(str(assets / "5_experiments" / pattern)))]
            compares.extend(preset["compare"])
            summary_globs.extend(str(assets / p) for p in preset["summaries"])
            gap_tags.update(preset["gap_arms"])
            gaps.extend(preset["gaps"])
            personas = personas or assets / preset["personas"]
        for spec in args.arm:
            name, _, runs = spec.partition("=")
            if not name or not runs:
                raise ValueError(f"--arm expects NAME=RUN[,RUN...], got {spec!r}")
            arm_specs[name.strip()] = expand_runs(runs)
        compares.extend(_pair(text, 3, "--compare") for text in args.compare)
        for spec in args.gap_arm:
            name, _, tag = spec.partition("=")
            if not name or not tag:
                raise ValueError(f"--gap-arm expects NAME=TAG, got {spec!r}")
            gap_tags[name.strip()] = tag.strip()
        gaps.extend(_pair(text, 2, "--gap") for text in args.gap)
        for name, runs in arm_specs.items():
            if not runs:
                raise ValueError(f"arm {name}: no run folders")
            if runs_per_arm is not None and len(runs) != runs_per_arm:
                raise ValueError(f"arm {name}: expected {runs_per_arm} run folders, found {len(runs)}")
        for a, b, kind in compares:
            if a not in arm_specs or b not in arm_specs:
                raise ValueError(f"comparison {a},{b}: unknown arm (have {sorted(arm_specs)})")
            if kind not in KINDS:
                raise ValueError(f"comparison {a},{b}: unknown statistic {kind!r}; expected one of {sorted(KINDS)}")
        for a, b in gaps:
            for name in (a, b):
                if name not in gap_tags:
                    raise ValueError(f"gap {a},{b}: no --gap-arm for {name}")
        if compares and personas is None:
            raise ValueError("--personas is required for the bootstrap")
        if not compares and not gaps:
            raise ValueError("nothing to do: give --compare and/or --gap (or --preset)")
    except (ValueError, argparse.ArgumentTypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    record: Dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(), "script": SCRIPT_PATH, "git": git_info(),
        "argv": list(argv) if argv is not None else sys.argv[1:], "preset": args.preset, "question": args.question,
        "resamples": args.resamples, "seed": args.seed,
        "note": "Resamples personas within one persona set; it does not cover drawing a different set of personas.",
    }

    if compares:
        incomes = load_incomes(Path(personas))
        used = sorted({name for a, b, _ in compares for name in (a, b)})
        arms = {name: [load_run(path, args.question) for path in arm_specs[name]] for name in used}
        pids = common_personas(arms, incomes)
        if len(pids) < 3:
            print(f"ERROR: only {len(pids)} personas are common to every run and the persona file", file=sys.stderr)
            return 2
        rng = random.Random(args.seed)
        rows: List[Dict[str, Any]] = []
        for a, b, kind in compares:
            def stat_a(ids: Sequence[str], _runs: List[RunAnswers] = arms[a], _kind: str = kind) -> float:
                return arm_stat(_runs, _kind, ids, incomes)

            def stat_b(ids: Sequence[str], _runs: List[RunAnswers] = arms[b], _kind: str = kind) -> float:
                return arm_stat(_runs, _kind, ids, incomes)

            obs_a, obs_b, diff, low, high = paired_bootstrap(stat_a, stat_b, pids, args.resamples, rng)
            rows.append({"a": a, "b": b, "kind": kind, "question": args.question, "n_personas": len(pids), "observed_a": obs_a,
                         "observed_b": obs_b, "diff": diff, "ci_low": low, "ci_high": high, "reading": reading(low, high),
                         "a_uses_odds": all(r.uses_odds for r in arms[a]), "b_uses_odds": all(r.uses_odds for r in arms[b]),
                         "resamples": args.resamples, "seed": args.seed, "description": KINDS[kind]})
        write_csv(out / "bootstrap.csv", BOOTSTRAP_COLUMNS, rows)
        record["bootstrap"] = {
            "personas_file": {"path": str(Path(personas).resolve()), "sha256": filter_qualified.sha256_of_file(Path(personas)),
                              "n_with_income": len(incomes)},
            "n_personas_used": len(pids), "n_personas_left_out": len(incomes) - len(pids),
            "arms": {name: [str(Path(r.path).resolve()) for r in runs] for name, runs in arms.items()},
            "rows": rows,
        }
        print(f"Paired bootstrap over {len(pids)} personas ({args.resamples} resamples, seed {args.seed}, {args.question}; repeats averaged)")
        for row in rows:
            print(f"  {row['a']} - {row['b']:6s} {row['kind']:15s} diff {row['diff']:+.3f}  95% CI [{row['ci_low']:+.3f}, {row['ci_high']:+.3f}]  {row['reading']}")

    if gaps:
        paths = sorted({Path(p) for pattern in summary_globs for p in glob.glob(pattern)})
        if not paths:
            print("ERROR: --gap given but no comparison_summary.csv matched --summaries", file=sys.stderr)
            return 2
        try:
            rows_g = gap_rows(read_summaries(paths), gap_tags, gaps, args.gap_repeats or None, args.tie_band_tv, args.tie_band_rank)
        except ValueError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        write_csv(out / "gaps.csv", GAP_COLUMNS, rows_g)
        record["gaps"] = {"summaries": [str(p.resolve()) for p in paths], "tags": gap_tags,
                          "tie_band_tv": args.tie_band_tv, "tie_band_rank": args.tie_band_rank, "rows": rows_g}
        print("Tie-table gaps (repeat means; positive = A better)")
        for row in rows_g:
            print(f"  {row['a']:6s} vs {row['b']:6s} TV {row['tv_a']:.4f} vs {row['tv_b']:.4f} gap {row['tv_gap_a_better']:+.4f} {row['tv_reading']:8s}"
                  f" rank {row['rank_a']:.4f} vs {row['rank_b']:.4f} gap {row['rank_gap_a_better']:+.4f} {row['rank_reading']}")

    (out / "noise_check.json").write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
