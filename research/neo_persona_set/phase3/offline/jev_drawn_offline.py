"""Re-draw the Oct 5 "Jev drawn offline" arm from the saved Sept 24 Jev odds, then score it. Offline, $0.

The Sept 24 Jev run (R015, `..._s1-jev-full`) kept Jev's probability over the options for every
persona and question (probabilities.csv) beside the most probable answer it wrote to
answers_wide.csv. On 2026-10-05 an inline analysis turned those odds into answers the way
`run_survey.py --answer-mode distribution` turns a chat model's odds into answers: for each persona
and likert item, one scale point is drawn at Jev's stated odds (renormalized to sum to 1) with
phase2/run_survey.draw_answer, which seeds on seed, persona and question, so a draw never depends on
order. Items that are not likert keep Jev's most probable answer (Q20: its two most probable
options). Each seed gives one run folder. The arm was scored with compare_real.py on Dr. Lin's
standard (13 validation items, 300 val respondents) next to the most-probable-answer run, and the
income link was checked: Spearman rho between a persona's exact household income and its Q1 answer.

This script is that analysis, recovered from the session transcript. It writes, under --out:

  jev-drawn_r<i>/   one per --seeds entry, in order: answers_wide.csv, answers_long.csv,
                    questions.csv, probabilities.csv (the odds and the drawn point), manifest.json
  cmp/              compare_real.py output for the source run plus every drawn run
  summary.csv       per arm: TV, rank agreement, top match, and, with --personas, rho(income, Q1)
                    and the share answering 4-5 on Q1; one more row with rho(income, expected Q1
                    from Jev's odds)
  check.json        only with --check-against: whether the drawn answers and compare_real's
                    outputs are identical to an earlier output folder (the Oct 5 one)

answers_wide.csv is the source run's file with the likert cells replaced and run_id renamed,
written the same way, so with the default seeds it is byte-for-byte the Oct 5 file. Its seed column
stays blank, as in the source run and on Oct 5; the draw seed is in manifest.json. Jev's argmax is
kept for any likert cell without usable odds, and the manifest counts those cells.

No API call, no network. The real file is read only by compare_real.py. --out must be outside the
repository and outside the real-data folder, and the input paths must not name the real data.

    ASSETS=../SyntheticResponderLab-Assets
    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/jev_drawn_offline.py \\
        --jev-run $ASSETS/5_experiments/2026-09-24_Yaza_ablations_models_styles/survey_runs/20260924T170819Z_jev-latest_r1_s1-jev-full \\
        --personas $ASSETS/4_persona_sets/matched_600_v2_S1-S6_2026-09-16/phase1_interview_matched600_s1.csv \\
        --real "$ASSETS/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv" \\
        --real-ids $ASSETS/3_scoring_standard/real_splits/lin-seed42/score_ids.txt \\
        --out $ASSETS/5_experiments/2026-10-05_jev_drawn_offline/reproduced_2026-10-18 \\
        --check-against $ASSETS/5_experiments/2026-10-05_jev_drawn_offline

Exit 0 on success; 1 when --check-against finds a difference; 2 on bad input; 3 on a refused path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
REPO_ROOT = PHASE3.parents[2]
for _path in (PHASE3, PHASE3.parent / "phase2"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import compare_real  # noqa: E402
import make_real_split  # noqa: E402
import metrics  # noqa: E402
import realdata  # noqa: E402
import run_survey  # noqa: E402  draw_answer: the drawing every distribution-mode run uses

SCRIPT_PATH = "research/neo_persona_set/phase3/offline/jev_drawn_offline.py"
CSV_ENCODING = "utf-8-sig"
DEFAULT_SEEDS = (202610051, 202610052)  # the two Oct 5 draws, jev-drawn_r1 and jev-drawn_r2
DEFAULT_RUN_PREFIX = "jev-drawn"
DEFAULT_ITEMS = "lin13-validation"
INCOME_FIELD = "exact_household_income"
INCOME_QUESTION = "Q1"
TOP_BOX = 4  # "Q1 4-5": the share of personas answering 4 or 5
LONG_COLUMNS = ["run_id", "model", "repeat", "seed", "persona_id", "respondent_id",
                "question_id", "question_type", "answer", "answer_json", "is_fallback", "reason"]
PROB_COLUMNS = ["run_id", "persona_id", "question_id", "option", "probability", "drawn", "status"]
CMP_OUTPUTS = ("comparison_long.csv", "comparison_options.csv", "comparison_summary.csv",
               "comparison_by_question.md", "unmapped.md", "crosswalk.csv")
SUMMARY_METRICS = ("n_synth_after_filter", "questions_compared", "questions_close", "mean_tv", "median_tv",
                   "mean_js", "share_top_match", "mean_spearman", "mean_abs_mean_diff", "item_set", "n_real_respondents")
SUMMARY_COLUMNS = ["run_id", "arm", "seed", "mean_tv", "mean_spearman", "share_top_match", "mean_js",
                   "questions_compared", "n_personas_q1", "rho_income_q1", "share_q1_4_5"]

Odds = Dict[Tuple[str, str], Dict[int, float]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, newline="", encoding=CSV_ENCODING) as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def question_kinds(questions_csv: Path) -> Dict[str, str]:
    """{question_id: question_type} in questions.csv order."""
    _, rows = read_rows(questions_csv)
    return {row["question_id"]: row["question_type"] for row in rows}


def load_odds(probabilities_csv: Path, likert_ids: Sequence[str]) -> Odds:
    """{(persona_id, question_id): {scale point: probability}} for the likert items only.

    Jev's score questions are already shifted to the survey's 1-5 by jev_survey.discrete, so the
    option column holds the scale point.
    """
    wanted = set(likert_ids)
    odds: Odds = {}
    _, rows = read_rows(probabilities_csv)
    for row in rows:
        if row["question_id"] in wanted:
            odds.setdefault((row["persona_id"], row["question_id"]), {})[int(row["option"])] = float(row["probability"])
    return odds


def normalized(points: Dict[int, float]) -> Optional[Dict[int, float]]:
    total = sum(points.values())
    if total <= 0:
        return None
    return {point: share / total for point, share in points.items()}


def draw_panel(rows: List[Dict[str, str]], likert_ids: Sequence[str], odds: Odds, seed: int,
               run_id: str) -> Tuple[List[Dict[str, str]], Dict[Tuple[str, str], int], Dict[str, int]]:
    """A copy of the source rows with each likert cell drawn at its odds and run_id renamed.

    Returns (rows, {(persona_id, question_id): drawn point}, counts). A cell without usable odds
    keeps the source answer, Jev's most probable one, and is counted.
    """
    drawn: Dict[Tuple[str, str], int] = {}
    counts = {"drawn": 0, "no_odds": 0, "zero_odds": 0}
    out: List[Dict[str, str]] = []
    for source in rows:
        row = dict(source)
        persona_id = row["persona_id"]
        for question_id in likert_ids:
            points = odds.get((persona_id, question_id))
            if not points:
                counts["no_odds"] += 1
                continue
            probs = normalized(points)
            if probs is None:
                counts["zero_odds"] += 1
                continue
            point = run_survey.draw_answer(probs, seed, persona_id, question_id)
            row[question_id] = str(point)
            drawn[(persona_id, question_id)] = point
            counts["drawn"] += 1
        row["run_id"] = run_id
        out.append(row)
    return out, drawn, counts


def long_rows(rows: List[Dict[str, str]], kinds: Dict[str, str]) -> List[List[str]]:
    """answers_long.csv rows in the layout jev_survey.py writes, one per persona x question."""
    out: List[List[str]] = []
    for row in rows:
        for question_id, kind in kinds.items():
            value = row.get(question_id, "") or ""
            out.append([row.get("run_id", ""), row.get("model", ""), row.get("repeat", ""), row.get("seed", ""),
                        row["persona_id"], row.get("respondent_id", ""), question_id, kind, value,
                        json.dumps(value), "true" if not value else "false", ""])
    return out


def probability_rows(rows: List[Dict[str, str]], likert_ids: Sequence[str], odds: Odds,
                     drawn: Dict[Tuple[str, str], int], run_id: str) -> Tuple[List[List[Any]], int]:
    """probabilities.csv rows in the layout run_survey.py writes for distribution runs; also the renormalized count."""
    out: List[List[Any]] = []
    renormalized = 0
    for row in rows:
        persona_id = row["persona_id"]
        for question_id in likert_ids:
            points = odds.get((persona_id, question_id))
            if not points:
                continue
            probs = normalized(points)
            if probs is None:
                out.extend([run_id, persona_id, question_id, point, share, "", "invalid"] for point, share in sorted(points.items()))
                continue
            status = "ok" if abs(sum(points.values()) - 1.0) <= 0.01 else "renormalized"
            renormalized += status == "renormalized"
            out.extend([run_id, persona_id, question_id, point, round(probs[point], 6), drawn.get((persona_id, question_id), ""), status]
                       for point in sorted(probs))
    return out, renormalized


def write_table(path: Path, header: List[str], rows: Sequence[Sequence[Any]]) -> None:
    with open(path, "w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_wide(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    """Written as the Oct 5 analysis wrote it (csv.DictWriter, BOM, CRLF), so the bytes match."""
    with open(path, "w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def script_info() -> Dict[str, Any]:
    git = compare_real.git_info()
    return {"path": SCRIPT_PATH, "git_commit": git["commit"], "git_branch": git["branch"], "git_dirty": git["dirty"],
            "python": sys.version.split()[0]}


def write_drawn_run(run_dir: Path, *, source: Dict[str, Any], seed: int, run_id: str,
                    personas: Optional[Path] = None) -> Dict[str, Any]:
    """One drawn run folder. Returns the run's manifest."""
    started = utcnow()
    rows, drawn, counts = draw_panel(source["rows"], source["likert_ids"], source["odds"], seed, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_wide(run_dir / "answers_wide.csv", source["header"], rows)
    write_table(run_dir / "answers_long.csv", LONG_COLUMNS, long_rows(rows, source["kinds"]))
    (run_dir / "questions.csv").write_bytes((source["dir"] / "questions.csv").read_bytes())
    prob_rows, renormalized = probability_rows(rows, source["likert_ids"], source["odds"], drawn, run_id)
    write_table(run_dir / "probabilities.csv", PROB_COLUMNS, prob_rows)
    src_manifest = source["manifest"]
    panel = dict(src_manifest.get("panel") or {})
    manifest = {
        "run_id": run_id,
        "status": "completed",
        "started_at": started.isoformat(),
        "finished_at": utcnow().isoformat(),
        "script": script_info(),
        "model": {**(src_manifest.get("model") or {}), "api_calls": 0,
                  "answers": "likert items drawn offline from the source run's saved odds; other items are its most probable answer"},
        "source_run": {"run_id": src_manifest.get("run_id") or source["dir"].name, "run_dir": str(source["dir"]),
                       "script": src_manifest.get("script"),
                       "sha256": {name: sha256_of_file(source["dir"] / name) for name in
                                  ("answers_wide.csv", "questions.csv", "probabilities.csv", "manifest.json") if (source["dir"] / name).exists()}},
        "panel": panel,
        "personas": {"path": str(personas) if personas else panel.get("personas_file"), "sha256": panel.get("personas_sha256"),
                     "path_in_source_manifest": panel.get("personas_file"),
                     "file_matches_sha256": None if personas is None else sha256_of_file(personas) == panel.get("personas_sha256")},
        "survey": src_manifest.get("survey"),
        "multi_picks": src_manifest.get("multi_picks"),
        "seed": seed,
        "answer_mode": "distribution",
        "persona_kind": "synthetic",
        "trait_mix": None,
        "draw": {
            "seed": seed,
            "function": "phase2/run_survey.py draw_answer",
            "method": "odds renormalized to sum to 1; u = random.Random(f'{seed}:{persona_id}:{question_id}').random(); "
                      "the first scale point, in order 1-5, whose cumulative odds exceed u",
            "likert_items": list(source["likert_ids"]),
            "n_likert_items": len(source["likert_ids"]),
            "n_personas": len(rows),
            "cells_drawn": counts["drawn"],
            "cells_without_odds_kept_argmax": counts["no_odds"] + counts["zero_odds"],
            "persona_items_renormalized": renormalized,
            "seed_column": "blank, as in the source run and the Oct 5 files; the draw seed is recorded here",
        },
        "failures": [],
        "notes": f"offline: likert answers drawn from the saved Jev odds, seed {seed}. Recovers the 2026-10-05 inline "
                 "analysis (5_experiments/2026-10-05_jev_drawn_offline) as code.",
    }
    manifest["outputs"] = {name: sha256_of_file(run_dir / name) for name in
                           ("answers_wide.csv", "answers_long.csv", "questions.csv", "probabilities.csv")}
    write_json(run_dir / "manifest.json", manifest)
    return manifest


def load_source(jev_run: Path) -> Dict[str, Any]:
    for name in ("answers_wide.csv", "questions.csv", "probabilities.csv"):
        if not (jev_run / name).is_file():
            raise ValueError(f"{jev_run} has no {name}; pass a Jev run folder written by jev_survey.py")
    kinds = question_kinds(jev_run / "questions.csv")
    likert_ids = [question_id for question_id, kind in kinds.items() if kind == "likert"]
    header, rows = read_rows(jev_run / "answers_wide.csv")
    manifest_path = jev_run / "manifest.json"
    return {
        "dir": jev_run, "kinds": kinds, "likert_ids": likert_ids, "header": header, "rows": rows,
        "odds": load_odds(jev_run / "probabilities.csv", likert_ids),
        "manifest": json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {},
    }


def load_incomes(personas_csv: Path) -> Dict[str, float]:
    _, rows = read_rows(personas_csv)
    incomes: Dict[str, float] = {}
    for row in rows:
        try:
            incomes[row["persona_id"]] = float(row[INCOME_FIELD])
        except (KeyError, TypeError, ValueError):
            continue
    return incomes


def scale_answers(rows: List[Dict[str, str]], question_id: str) -> Dict[str, int]:
    """{persona_id: scale point} for every persona whose answer starts with a digit."""
    return {row["persona_id"]: int(row[question_id][0]) for row in rows if (row.get(question_id) or "")[:1].isdigit()}


def income_link(incomes: Dict[str, float], values: Dict[str, float]) -> Tuple[int, float]:
    """(n, Spearman rho) between persona income and a per-persona value; rho is nan below 3 personas."""
    keys = sorted(key for key in values if key in incomes)
    if len(keys) < 3:
        return len(keys), float("nan")
    return len(keys), metrics.spearman([incomes[key] for key in keys], [values[key] for key in keys])


def expected_points(odds: Odds, question_id: str) -> Dict[str, float]:
    """{persona_id: expected scale point under its stated odds} for one likert item."""
    out: Dict[str, float] = {}
    for (persona_id, qid), points in odds.items():
        total = sum(points.values())
        if qid == question_id and total > 0:
            out[persona_id] = sum(point * share for point, share in points.items()) / total
    return out


def diff_wide(ours: Path, theirs: Path) -> Dict[str, Any]:
    """Row-for-row comparison keyed by persona_id; counts only, no cell values."""
    our_header, our_rows = read_rows(ours)
    their_header, their_rows = read_rows(theirs)
    mine = {row["persona_id"]: row for row in our_rows}
    other = {row["persona_id"]: row for row in their_rows}
    columns = list(dict.fromkeys(our_header + their_header))
    differing_cells, differing_columns = 0, set()
    for persona_id in set(mine) & set(other):
        for column in columns:
            if (mine[persona_id].get(column) or "") != (other[persona_id].get(column) or ""):
                differing_cells += 1
                differing_columns.add(column)
    return {"rows_ours": len(our_rows), "rows_theirs": len(their_rows), "same_header": our_header == their_header,
            "personas_only_in_one": len(set(mine) ^ set(other)), "cells_differing": differing_cells,
            "columns_differing": sorted(differing_columns)}


def check_against(out_dir: Path, earlier: Path, run_ids: Sequence[str]) -> Dict[str, Any]:
    """Whether the drawn runs and compare_real's outputs equal an earlier output folder's."""
    report: Dict[str, Any] = {"against": str(earlier), "runs": {}, "cmp": {}, "summary": {}}
    for run_id in run_ids:
        theirs = earlier / run_id
        if not (theirs / "answers_wide.csv").is_file():
            report["runs"][run_id] = {"present": False, "identical": False}
            continue
        ours = out_dir / run_id
        wide_same = (ours / "answers_wide.csv").read_bytes() == (theirs / "answers_wide.csv").read_bytes()
        questions_same = (theirs / "questions.csv").is_file() and \
            (ours / "questions.csv").read_bytes() == (theirs / "questions.csv").read_bytes()
        rows = diff_wide(ours / "answers_wide.csv", theirs / "answers_wide.csv")
        report["runs"][run_id] = {"present": True, "answers_wide_bytes_identical": wide_same,
                                  "answers_wide_sha256": sha256_of_file(ours / "answers_wide.csv"),
                                  "questions_bytes_identical": questions_same, **rows,
                                  "identical": wide_same or (rows["cells_differing"] == 0 and rows["personas_only_in_one"] == 0)}
    for name in CMP_OUTPUTS:
        ours, theirs = out_dir / "cmp" / name, earlier / "cmp" / name
        report["cmp"][name] = theirs.is_file() and ours.is_file() and sha256_of_file(ours) == sha256_of_file(theirs)
    ours_summary, theirs_summary = out_dir / "cmp" / "comparison_summary.csv", earlier / "cmp" / "comparison_summary.csv"
    if ours_summary.is_file() and theirs_summary.is_file():
        mine = {row["run_id"]: row for row in read_rows(ours_summary)[1]}
        other = {row["run_id"]: row for row in read_rows(theirs_summary)[1]}
        for run_id, row in mine.items():
            earlier_row = other.get(run_id)
            if earlier_row is None:
                report["summary"][run_id] = {"present": False, "identical": False}
                continue
            differences = {column: {"ours": row.get(column), "earlier": earlier_row.get(column)}
                           for column in SUMMARY_METRICS if row.get(column) != earlier_row.get(column)}
            report["summary"][run_id] = {"present": True, "identical": not differences, "differences": differences}
    report["all_identical"] = (all(entry.get("identical") for entry in report["runs"].values())
                               and all(report["cmp"].values())
                               and bool(report["summary"]) and all(entry.get("identical") for entry in report["summary"].values()))
    return report


def fmt(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if number != number else f"{number:.{digits}f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jev-run", type=Path, required=True,
                        help="the Jev run folder holding probabilities.csv (the Sept 24 ..._s1-jev-full run)")
    parser.add_argument("--real", type=Path, required=True, help="the AYTM raw-data CSV; read only by compare_real.py")
    parser.add_argument("--out", type=Path, required=True, help="output folder, outside the repository and the real-data folder")
    parser.add_argument("--real-ids", type=Path, default=None, help="score half of the split (lin-seed42/score_ids.txt)")
    parser.add_argument("--items", default=DEFAULT_ITEMS, help=f"compare_real.py --items (default {DEFAULT_ITEMS})")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS),
                        help="one drawn run per seed, named <prefix>_r1, _r2, ... in this order (default: the Oct 5 seeds)")
    parser.add_argument("--run-prefix", default=DEFAULT_RUN_PREFIX)
    parser.add_argument("--personas", type=Path, default=None,
                        help=f"the run's persona CSV; adds rho({INCOME_FIELD}, {INCOME_QUESTION}) and the 4-5 share to summary.csv")
    parser.add_argument("--check-against", type=Path, default=None, metavar="EARLIER_OUT",
                        help="an earlier output folder (<run>/answers_wide.csv and cmp/) to compare with; writes check.json")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    real_path = Path(args.real).expanduser().resolve()
    if not real_path.is_file():
        print(f"--real {real_path} is not a file", file=sys.stderr)
        return 2
    out_dir = make_real_split.assert_outside_repo(args.out, "--out")
    out_dir = realdata.assert_outside_real_folder(out_dir, real_path, "--out")
    jev_run = realdata.assert_outside_real_folder(args.jev_run, real_path, "--jev-run")
    personas = None if args.personas is None else realdata.assert_outside_real_folder(args.personas, real_path, "--personas")
    earlier = None if args.check_against is None else realdata.assert_outside_real_folder(args.check_against, real_path, "--check-against")
    if len(set(args.seeds)) != len(args.seeds):
        print("--seeds must be distinct", file=sys.stderr)
        return 2
    try:
        source = load_source(jev_run)
    except ValueError as error:
        print(f"jev_drawn_offline: {error}", file=sys.stderr)
        return 2
    print(f"source {jev_run.name}: {len(source['rows'])} personas, {len(source['likert_ids'])} likert items, "
          f"{len(source['odds'])} persona-items with odds")

    out_dir.mkdir(parents=True, exist_ok=True)
    run_dirs: List[Path] = []
    manifests: Dict[str, Dict[str, Any]] = {}
    for index, seed in enumerate(args.seeds, start=1):
        run_id = f"{args.run_prefix}_r{index}"
        manifest = write_drawn_run(out_dir / run_id, source=source, seed=seed, run_id=run_id, personas=personas)
        manifests[run_id] = manifest
        run_dirs.append(out_dir / run_id)
        draw = manifest["draw"]
        print(f"{run_id}: seed {seed}, {draw['cells_drawn']} cells drawn, {draw['cells_without_odds_kept_argmax']} kept "
              f"(no odds), {draw['persona_items_renormalized']} persona-items renormalized")

    cmp_argv = ["--real", str(real_path), "--runs", str(jev_run), *map(str, run_dirs), "--out", str(out_dir / "cmp"),
                "--items", args.items]
    if args.real_ids is not None:
        cmp_argv += ["--real-ids", str(args.real_ids)]
    code = compare_real.main(cmp_argv)
    if code != 0:
        print(f"jev_drawn_offline: compare_real.py exited {code}", file=sys.stderr)
        return code

    scores = {row["run_id"]: row for row in read_rows(out_dir / "cmp" / "comparison_summary.csv")[1]}
    source_run_id = source["rows"][0]["run_id"] if source["rows"] else jev_run.name
    arms: List[Tuple[str, str, str, List[Dict[str, str]]]] = [(source_run_id, "most probable answer", "", source["rows"])]
    arms += [(run_id, "drawn from the odds", str(manifests[run_id]["seed"]), read_rows(out_dir / run_id / "answers_wide.csv")[1])
             for run_id in manifests]
    incomes: Dict[str, float] = {}
    if personas is not None:
        incomes = load_incomes(personas)
        expected_sha = (source["manifest"].get("panel") or {}).get("personas_sha256")
        if expected_sha and sha256_of_file(personas) != expected_sha:
            print(f"WARNING: --personas sha256 differs from the source run's personas_sha256 ({expected_sha[:12]}...)", file=sys.stderr)

    summary_rows: List[List[Any]] = []
    for run_id, arm, seed, rows in arms:
        score = scores.get(run_id, {})
        answers = scale_answers(rows, INCOME_QUESTION)
        n, rho = income_link(incomes, answers) if incomes else (len(answers), float("nan"))
        top = sum(1 for value in answers.values() if value >= TOP_BOX) / len(answers) if answers else float("nan")
        summary_rows.append([run_id, arm, seed, score.get("mean_tv", ""), score.get("mean_spearman", ""), score.get("share_top_match", ""),
                             score.get("mean_js", ""), score.get("questions_compared", ""), n, fmt(rho, 4), fmt(top, 4)])
    if incomes:
        n, rho = income_link(incomes, expected_points(source["odds"], INCOME_QUESTION))
        summary_rows.append([f"{source_run_id} (stated odds)", f"expected {INCOME_QUESTION} under Jev's odds", "", "", "", "", "", "", n, fmt(rho, 4), ""])
    write_table(out_dir / "summary.csv", SUMMARY_COLUMNS, summary_rows)

    print(f"\n{'arm':44s} {'TV':>6s} {'rank':>6s} {'top':>6s} {'rho(inc,Q1)':>11s} {'Q1 4-5':>7s}")
    for row in summary_rows:
        print(f"{str(row[0])[-44:]:44s} {fmt(row[3]):>6s} {fmt(row[4]):>6s} {fmt(row[5]):>6s} {fmt(row[9], 2):>11s} "
              f"{(fmt(float(row[10]) * 100, 0) + '%') if row[10] else '':>7s}")

    if earlier is not None:
        report = check_against(out_dir, earlier, list(manifests))
        write_json(out_dir / "check.json", report)
        for run_id, entry in report["runs"].items():
            print(f"check {run_id}: answers_wide byte-identical={entry.get('answers_wide_bytes_identical')} "
                  f"cells differing={entry.get('cells_differing')}")
        print(f"check cmp/: {sum(report['cmp'].values())} of {len(report['cmp'])} outputs identical; "
              f"summary identical for {sum(1 for e in report['summary'].values() if e.get('identical'))} of {len(report['summary'])} runs")
        print(f"check: {'ALL IDENTICAL' if report['all_identical'] else 'DIFFERENCES FOUND (see check.json)'}")
        print(f"wrote {out_dir}")
        return 0 if report["all_identical"] else 1
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
