"""Average human answer shape: a know-nothing baseline for the 1-5 items, fitted on Dr. Lin's cal half. Offline.

Recovered 2026-10-18 from the Oct 5 inline analysis (results in
5_experiments/2026-10-05_noise_check_and_average_shape; Anderson's real-baselines report has the
same baseline). One 1-5 distribution is pooled over the --pool-items answers of the fit respondents
(fit_ids.txt) and applied unchanged to every --score-items item. It is scored against the score
respondents (score_ids.txt) two ways, with metrics.py (TV, and rank agreement = Spearman over the
five option shares), each averaged over the scored items:
  expected   the shape itself vs each item's real shares, no draw
  panel      a --panel-size panel drawn from the shape, --draws times (one seeded random.Random per
             pool): mean and 2.5th-97.5th percentile range, the way a 100-persona AI arm is scored

--pool-items (repeatable) picks the items the shape is pooled over:
  lin13-calibration (default)  Dr. Lin's calibration items only, so no scored item informs the shape
  all-likert                   the 23 scored likert items. They include the 13 validation items (on
                               the fit respondents only), which is how the Oct 5 number and
                               Anderson's were computed; kept to reproduce them
  or any named set / item file item_sets.load_item_set accepts (likert items only)
A pool that shares items with --score-items is reported as such (items_overlap) and warned about.

The script reads the real file only to count answers; it prints and writes aggregate scores, and
the fitted shape goes only into the JSON record in --out, which must be outside the repository and
outside the real-data folder.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/average_shape_baseline.py \\
        --real "../SyntheticResponderLab-Assets/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv" \\
        --fit-ids ../SyntheticResponderLab-Assets/3_scoring_standard/real_splits/lin-seed42/fit_ids.txt \\
        --score-ids ../SyntheticResponderLab-Assets/3_scoring_standard/real_splits/lin-seed42/score_ids.txt \\
        --pool-items lin13-calibration --pool-items all-likert --score-items lin13-validation \\
        --out ../SyntheticResponderLab-Assets/5_experiments/2026-10-05_noise_check_and_average_shape/reproduced_2026-10-18

Outputs in --out (named after --score-items, without a file extension): average_shape_<score>.csv (one row per pool x arm),
average_shape_by_item_<score>.csv (per-item scores), average_shape_<score>.json (inputs, settings,
fitted shapes, results).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
REPO_ROOT = PHASE3.parents[2]
if str(PHASE3) not in sys.path:
    sys.path.insert(0, str(PHASE3))

import crosswalk  # noqa: E402
import filter_qualified  # noqa: E402
import item_sets  # noqa: E402
import make_real_split  # noqa: E402
import metrics  # noqa: E402
import realdata  # noqa: E402

SCRIPT_PATH = "research/neo_persona_set/phase3/offline/average_shape_baseline.py"
CSV_ENCODING = "utf-8-sig"
ALL_LIKERT = "all-likert"
SCALE = [1, 2, 3, 4, 5]
SUMMARY_COLUMNS = ["pool_items", "n_pool_items", "score_items", "n_score_items", "items_overlap", "arm", "panel_size", "draws", "seed",
                   "n_fit_respondents", "n_score_respondents", "tv_mean", "tv_low", "tv_high", "rank_mean", "rank_low", "rank_high"]
BY_ITEM_COLUMNS = ["pool_items", "item", "in_pool", "tv_expected", "rank_expected", "tv_panel_mean", "rank_panel_mean"]


def all_likert_items() -> List[str]:
    """The scored 1-5 items that are not set aside (23 on our survey)."""
    return [q.our_id for q in crosswalk.CROSSWALK if q.kind == "likert" and q.scored and q.our_id not in item_sets.SET_ASIDE]


def resolve_items(spec: str) -> Tuple[str, List[str]]:
    """(name, ids) for all-likert, a named set or an item file; every item must be a 1-5 item."""
    name, ids = (ALL_LIKERT, all_likert_items()) if spec == ALL_LIKERT else item_sets.load_item_set(spec)
    not_likert = [item for item in ids if crosswalk.BY_OUR_ID[item].kind != "likert"]
    if not_likert:
        raise ValueError(f"{name}: the average shape is a 1-5 distribution; not 1-5 items: {not_likert}")
    return name, ids


def likert_counts(survey: realdata.RealSurvey, item: str) -> Counter:
    """Counts of answers 1..5 to one item; blanks and anything off the scale are ignored."""
    counts: Counter = Counter()
    for cell in survey.values(crosswalk.BY_OUR_ID[item].real_key):
        value = realdata.likert_label_to_int(cell)
        if value in SCALE:
            counts[value] += 1
    return counts


def pooled_shape(survey: realdata.RealSurvey, items: Sequence[str]) -> List[float]:
    """Shares of 1..5 over all answers to `items` (answer counts pooled, not item shares averaged)."""
    pool: Counter = Counter()
    for item in items:
        pool.update(likert_counts(survey, item))
    total = sum(pool[k] for k in SCALE)
    if not total:
        raise ValueError(f"no 1-5 answers to pool over {list(items)}")
    return [pool[k] / total for k in SCALE]


def item_shares(survey: realdata.RealSurvey, item: str) -> List[float]:
    counts = likert_counts(survey, item)
    total = sum(counts[k] for k in SCALE)
    if not total:
        raise ValueError(f"{item}: no 1-5 answers among the score respondents")
    return [counts[k] / total for k in SCALE]


def _dist(shares: Sequence[float]) -> Dict[str, float]:
    return {str(k): share for k, share in zip(SCALE, shares)}


def score_item(shares: Sequence[float], real: Sequence[float]) -> Tuple[float, float]:
    """(TV, rank agreement) of one distribution over 1..5 against the real shares."""
    return metrics.tv_distance(_dist(shares), _dist(real)), metrics.spearman(list(shares), list(real))


def draw_panel(shape: Sequence[float], panel_size: int, rng: random.Random) -> List[float]:
    """Shares of 1..5 among `panel_size` answers drawn from `shape`."""
    counts = Counter(rng.choices(SCALE, weights=shape, k=panel_size))
    return [counts[k] / panel_size for k in SCALE]


def percentile_range(sorted_values: Sequence[float]) -> Tuple[float, float]:
    """(2.5th, 97.5th) percentile of an ascending list, as on Oct 5: v[int(.025 n)], v[int(.975 n) - 1]."""
    n = len(sorted_values)
    return sorted_values[int(0.025 * n)], sorted_values[int(0.975 * n) - 1]


def evaluate(shape: Sequence[float], real: Dict[str, List[float]], items: Sequence[str], panel_size: int, draws: int,
             seed: int) -> Dict[str, Any]:
    """Expected and drawn-panel scores of one shape over `items` (in order)."""
    expected = {item: score_item(shape, real[item]) for item in items}
    rng = random.Random(seed)
    tv_draws: List[float] = []
    rank_draws: List[float] = []
    per_item_tv: Dict[str, List[float]] = {item: [] for item in items}
    per_item_rank: Dict[str, List[float]] = {item: [] for item in items}
    for _ in range(draws):
        tvs: List[float] = []
        ranks: List[float] = []
        for item in items:
            tv, rank = score_item(draw_panel(shape, panel_size, rng), real[item])
            tvs.append(tv)
            ranks.append(rank)
            per_item_tv[item].append(tv)
            per_item_rank[item].append(rank)
        tv_draws.append(sum(tvs) / len(tvs))
        rank_draws.append(sum(ranks) / len(ranks))
    tv_draws.sort()
    rank_draws.sort()
    return {
        "expected": {"tv_mean": sum(v[0] for v in expected.values()) / len(items), "rank_mean": sum(v[1] for v in expected.values()) / len(items)},
        "panel": {"tv_mean": sum(tv_draws) / draws, "rank_mean": sum(rank_draws) / draws,
                  "tv_range": percentile_range(tv_draws), "rank_range": percentile_range(rank_draws)},
        "by_item": {item: {"tv_expected": expected[item][0], "rank_expected": expected[item][1],
                           "tv_panel_mean": metrics.mean(per_item_tv[item]), "rank_panel_mean": metrics.mean(per_item_rank[item])}
                    for item in items},
    }


def _cell(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return "" if value != value else f"{value:.4f}"
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


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "items"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real", type=Path, required=True, help="the AYTM raw-data CSV (read only)")
    parser.add_argument("--fit-ids", type=Path, required=True, help="Response IDs the shape is fitted on (Dr. Lin's cal half)")
    parser.add_argument("--score-ids", type=Path, required=True, help="Response IDs it is scored against (Dr. Lin's val half)")
    parser.add_argument("--pool-items", action="append", default=None, metavar="SET_OR_FILE",
                        help=f"items the shape is pooled over (repeatable): {ALL_LIKERT}, one of {', '.join(item_sets.NAMED_SETS)}, or a file (default: lin13-calibration)")
    parser.add_argument("--score-items", default="lin13-validation", metavar="SET_OR_FILE", help="items it is scored on (default: lin13-validation)")
    parser.add_argument("--panel-size", type=int, default=100)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--out", type=Path, required=True, help="output folder (outside the repository and the real-data folder)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    real_path = Path(args.real).expanduser().resolve()
    if not real_path.is_file():  # before the guards: a missing file's folder would be the wrong one to refuse
        print(f"--real {real_path} is not a file", file=sys.stderr)
        return 2
    out = realdata.assert_outside_real_folder(args.out, real_path, "--out")
    out = make_real_split.assert_outside_repo(out, "--out")
    try:
        score_name, score_items = resolve_items(args.score_items)
        pools = [resolve_items(spec) for spec in (args.pool_items or ["lin13-calibration"])]
        fit_ids = realdata.read_id_file(args.fit_ids)
        score_ids = realdata.read_id_file(args.score_ids)
        shared = sorted(set(fit_ids) & set(score_ids))
        if shared:
            raise ValueError(f"{len(shared)} respondents are in both --fit-ids and --score-ids; the halves must not overlap")
        if args.panel_size < 1 or args.draws < 1:
            raise ValueError("--panel-size and --draws must be positive")
        real = realdata.load_real_survey(real_path)
        fit = realdata.subset_by_response_id(real, fit_ids)
        score = realdata.subset_by_response_id(real, score_ids)
        real_shares = {item: item_shares(score, item) for item in score_items}
        shapes = {name: pooled_shape(fit, items) for name, items in pools}
    except (ValueError, KeyError, OSError) as error:  # OSError: a missing --fit-ids / --score-ids / item file
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    summary_rows: List[Dict[str, Any]] = []
    item_rows: List[Dict[str, Any]] = []
    results: Dict[str, Any] = {}
    print(f"Average shape fitted on {fit.n} fit respondents, scored on {len(score_items)} items ({score_name}) against {score.n} score respondents")
    for name, items in pools:
        overlap = sorted(set(items) & set(score_items))
        if overlap:
            print(f"WARNING: pool {name} includes {len(overlap)} of the scored items ({', '.join(overlap)}): "
                  "their fit-half answers inform the shape (respondents are held out, items are not)")
        result = evaluate(shapes[name], real_shares, score_items, args.panel_size, args.draws, args.seed)
        results[name] = {"pool_items": items, "items_overlap": overlap, "fitted_shape": dict(zip([str(k) for k in SCALE], shapes[name])), **result}
        base = {"pool_items": name, "n_pool_items": len(items), "score_items": score_name, "n_score_items": len(score_items),
                "items_overlap": len(overlap), "seed": args.seed, "n_fit_respondents": fit.n, "n_score_respondents": score.n}
        expected, panel = result["expected"], result["panel"]
        summary_rows.append({**base, "arm": "expected", "panel_size": "", "draws": "", "tv_mean": expected["tv_mean"], "rank_mean": expected["rank_mean"]})
        summary_rows.append({**base, "arm": f"panel{args.panel_size}", "panel_size": args.panel_size, "draws": args.draws,
                             "tv_mean": panel["tv_mean"], "tv_low": panel["tv_range"][0], "tv_high": panel["tv_range"][1],
                             "rank_mean": panel["rank_mean"], "rank_low": panel["rank_range"][0], "rank_high": panel["rank_range"][1]})
        for item in score_items:
            item_rows.append({"pool_items": name, "item": item, "in_pool": item in items, **result["by_item"][item]})
        print(f"  pool {name} ({len(items)} items, {len(overlap)} scored items in the pool)")
        print(f"    expected (no draw):          TV {expected['tv_mean']:.3f}  rank {expected['rank_mean']:.3f}")
        print(f"    {args.panel_size}-person panel ({args.draws} draws): TV {panel['tv_mean']:.3f} ({panel['tv_range'][0]:.3f}-{panel['tv_range'][1]:.3f})"
              f"  rank {panel['rank_mean']:.3f} ({panel['rank_range'][0]:.3f}-{panel['rank_range'][1]:.3f})")

    out.mkdir(parents=True, exist_ok=True)
    tag = slug(Path(score_name).stem)
    write_csv(out / f"average_shape_{tag}.csv", SUMMARY_COLUMNS, summary_rows)
    write_csv(out / f"average_shape_by_item_{tag}.csv", BY_ITEM_COLUMNS, item_rows)
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(), "script": SCRIPT_PATH, "git": git_info(),
        "argv": list(argv) if argv is not None else sys.argv[1:],
        "real": {"path": str(real_path), "sha256": filter_qualified.sha256_of_file(real_path), "n_rows": real.n},
        "fit_ids": {"path": str(Path(args.fit_ids).resolve()), "sha256": filter_qualified.sha256_of_file(Path(args.fit_ids)), "n": len(fit_ids)},
        "score_ids": {"path": str(Path(args.score_ids).resolve()), "sha256": filter_qualified.sha256_of_file(Path(args.score_ids)), "n": len(score_ids)},
        "score_items": {"name": score_name, "ids": score_items}, "panel_size": args.panel_size, "draws": args.draws, "seed": args.seed,
        "note": "Aggregate real-survey statistics (the fitted shapes); keep outside the repository.",
        "results": results,
    }
    (out / f"average_shape_{tag}.json").write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
