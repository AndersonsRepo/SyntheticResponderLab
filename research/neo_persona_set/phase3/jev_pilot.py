"""Pilot: run personas through TypeSafe's Jev classifier and measure the income gradient.

Jev is not a chat model. One request carries a `state` (the persona plus the product stimulus) and
a named map of questions; each question is answered in isolation and comes back as a probability
distribution over the options, not a single pick. Two consequences for this project:

  * A stance formed on Q1 cannot leak into Q2, because the questions never share a generation.
    R007 found that leakage is real for chat models; here it is absent by construction.
  * Every persona yields a distribution, so the population estimate is the average of the
    probability vectors rather than a histogram of argmax picks.

The pilot exists to answer one question cheaply before anyone builds a full adapter:

    Is rho(income, E[Q1]) near the real association, or near the chat models' (DeepSeek and Qwen on
    the S1 baseline, registry R010)?

Income is read from the persona file for the correlation but the exact figure is still sent to the
model here, exactly as the baseline sends it. This is the baseline condition for Jev, not an
ablation.

No real-survey value is written in this file. The real side is supplied at runtime and only
printed, never stored in the run folder: --real-from reads the real Q1 shares (and so the real
top-2 share) from a compare_real output folder, and --real-rho-income-q1 takes the real
rho(income, Q1), which needs respondent-level income and is recorded with R010 in the Assets folder
(0_logs/EXPERIMENT_LOG.md). Without them the real rows print a pointer instead.

The synthetic comparison points are not written in here either. --baseline NAME=RUN_DIR[,RUN_DIR]
computes a chat arm's rho(income, Q1) (as spread_diagnostics.py does) and its Q6 cost-top share
from that arm's run folders, before any request is sent. Incomes come from --baseline-personas
(default --personas), which must be the persona file the runs used; when a run's manifest.json
records that file's sha256, a different file is refused. The comparison the pilot was written
against is the DeepSeek and Qwen S1 baseline runs of registry R002, in the Assets folder under
5_experiments/2026-09-17_S1_prompt_and_sampling_tests/survey_runs/, run on the full matched 600
(4_persona_sets/matched_600_v2_S1-S6_2026-09-16/phase1_interview_matched600.csv).

Usage:
    python research/neo_persona_set/phase3/jev_pilot.py --limit 20 \\
        [--real-from <compare_real output folder>] [--real-rho-income-q1 <value from R010>] \\
        [--baseline DeepSeek=<run_r1>,<run_r2> --baseline Qwen=<run_r1>,<run_r2> \\
         --baseline-personas <persona file of those runs>]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import score_vs_real_marginals  # noqa: E402
import spread_diagnostics  # noqa: E402

API_ENV = REPO_ROOT / "apps/api/.env"
DEFAULT_PERSONAS = HERE.parent / "out" / "phase1_interview_matched600_s1.csv"
DEFAULT_OUT = HERE.parent / "out" / "jev_runs"

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# The product stimulus, matching what the chat runner sends before Q1.
PRODUCT = (
    "The Tahoe Mini by Neo Smart Living is a compact 117-square-foot factory-built backyard unit — "
    "a private standalone studio, workspace, or guest room, about 9ft x 13ft. It is delivered as "
    "flat-packed panels and installed in most backyards in about one day. The approximate price is "
    "$23,000 including sales tax, delivery, installation, and warranty. Wall panels are modular and "
    "configurable. It is NOT an ADU: no plumbing, no kitchen, classified as a non-habitable "
    "accessory structure. At 117 sq ft it sits under California's ~120 sq ft threshold, so it often "
    "does not require a building permit, though local ordinances and HOA rules still apply. Standard "
    "features include pre-wired electrical, a smart entry lock, dual-pane floor-to-ceiling glass, and "
    "a pitched roof."
)

# Wording copied from the survey file so the pilot is comparable to the chat runs.
QUESTIONS = {
    "Q1_purchase_interest": {
        "type": "score",
        "instructions": (
            "Based on the product description, how interested would this person be in purchasing "
            "and installing a Tahoe Mini at the approximately $23,000 delivered-and-installed price "
            "point?"
        ),
        "criteria": [
            "Not at all interested",
            "Slightly interested",
            "Moderately interested",
            "Very interested",
            "Extremely interested",
        ],
    },
    "Q2_purchase_likelihood": {
        "type": "score",
        "instructions": (
            "How likely is this person to purchase a Tahoe Mini within the next 24 months?"
        ),
        "criteria": [
            "Definitely would not",
            "Probably would not",
            "Might or might not",
            "Probably would",
            "Definitely would",
        ],
    },
    "Q6_greatest_barrier": {
        "type": "choice",
        "instructions": (
            "Which one barrier would be the single greatest obstacle preventing this person from "
            "purchasing a Tahoe Mini?"
        ),
        "criteria": {
            "The total cost (~$23,000)": "Price is the single biggest obstacle",
            "HOA restrictions or community rules": "Community rules would block or complicate it",
            "Uncertainty about whether a building permit is required": "Permitting uncertainty",
            "Limited backyard space or access": "Not enough usable space or access to install",
            "Lack of financing options": "Could manage it only with financing that is unavailable",
        },
    },
}

# Persona fields sent as the state. Kept close to what the chat runner sends so the two are
# comparable; the ablations will later drop subsets of these by name.
CENSUS_FIELDS = [
    "exact_age", "sex", "region", "state", "exact_household_income", "income_bucket",
    "household_size", "children_in_household", "household_type", "marital_status", "education",
    "occupation", "employment_status", "work_mode", "home_type", "tenure_detail", "bedrooms",
    "rooms", "year_built", "moved_in", "vehicles", "housing_cost_pct_of_income",
]
STORY_FIELDS = [
    "story_headline", "story_biography", "story_daily_routine", "story_weekend_routine",
    "story_household_and_home", "story_outdoor_space", "story_home_projects", "story_work_setup",
    "story_space_pressure", "story_money_decisions", "story_priorities", "story_financial_picture",
    "story_free_time", "story_communication_style",
]


def load_key() -> str:
    key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not key and API_ENV.exists():
        for line in API_ENV.read_text().splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit(f"TYPESAFE_API_KEY not set. Add it to {API_ENV}")
    return key


def build_state(persona: dict, drop_census: set[str], drop_story: set[str]) -> dict:
    """Assemble the state Jev reads. Dropping fields here is how the ablations will work."""
    state: dict = {"product": PRODUCT, "respondent": {}}
    for field in CENSUS_FIELDS:
        if field in drop_census:
            continue
        value = persona.get(field)
        if value not in (None, ""):
            state["respondent"][field] = value
    for field in STORY_FIELDS:
        if field in drop_story:
            continue
        value = persona.get(field)
        if value not in (None, ""):
            state["respondent"][field.removeprefix("story_")] = value
    return state


def ask(key: str, state: dict, timeout: int, retries: int = 4) -> dict:
    body = json.dumps({"model": MODEL, "state": state, "questions": QUESTIONS}).encode()
    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            ENDPOINT, data=body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            detail = error.read().decode()[:200]
            # 4xx other than rate limiting will not fix themselves; fail fast rather than retry.
            if error.code not in (408, 429) and error.code < 500:
                raise RuntimeError(f"HTTP {error.code}: {detail}") from error
            last = RuntimeError(f"HTTP {error.code}: {detail}")
        except Exception as error:  # noqa: BLE001 - retried below
            last = error
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def expected_score(answer: dict) -> float:
    """Jev returns `score` already probability-weighted; recompute as a check on the contract."""
    probabilities = answer.get("probabilities") or {}
    return sum(int(level) * share for level, share in probabilities.items())


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation, average ranks for ties. Hand-rolled to match phase3/metrics.py."""
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        index = 0
        while index < len(order):
            stop = index
            while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
                stop += 1
            average = (index + stop) / 2 + 1
            for position in range(index, stop + 1):
                out[order[position]] = average
            index = stop + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


# Printed where a real value would go when none is passed in; nothing derived from the AYTM file is committed.
REAL_POINTER = "see real_comparison/<condition>/comparison_by_question.md, or pass --real-from"
# Printed where the chat-model comparison would go when no --baseline is passed. Synthetic values are
# computed from run folders at runtime too, not written in (team rule: prefer the score files).
BASELINE_POINTER = "chat models: pass --baseline NAME=RUN_DIR[,RUN_DIR] (S1 baseline runs, registry R002)"
# Q6 option counted as a 'cost' top choice, for Jev's answers and for the --baseline runs alike.
COST_OPTION_PREFIX = "The total cost"


def _check_persona_file(name: str, run_dir: Path, personas: Path) -> None:
    """Stop when the run's manifest records a different persona file: persona ids are renumbered
    between persona files (the S1 subset file starts again at P001), so incomes would be joined to
    the wrong personas without any error."""
    manifest = run_dir / "manifest.json"
    if not manifest.is_file():
        return
    try:
        recorded = (json.loads(manifest.read_text(encoding="utf-8")).get("personas") or {}).get("sha256")
    except (ValueError, AttributeError):
        return
    if recorded and hashlib.sha256(personas.read_bytes()).hexdigest() != recorded:
        raise SystemExit(f"--baseline {name}: {run_dir.name} was run on a different persona file than {personas} "
                         f"(see personas.path in its manifest.json); pass that file with --baseline-personas")


def baseline_reference(spec: str, personas: Path | None) -> dict:
    """One synthetic comparison arm, NAME=RUN_DIR[,RUN_DIR...], computed at runtime from its run folders.

    rho_income_q1 is spread_diagnostics' (Spearman over every answer in the runs, incomes from
    `personas`, which must be the persona file the runs used); q6_cost_top_share is the share of Q6
    answers that pick the total-cost option.
    """
    name, _, paths = spec.partition("=")
    name = name.strip()
    run_dirs = [Path(p.strip()).expanduser() for p in paths.split(",") if p.strip()]
    if not name or not run_dirs:
        raise SystemExit(f"--baseline {spec!r}: expected NAME=RUN_DIR[,RUN_DIR...]")
    if personas is not None and not Path(personas).is_file():
        raise SystemExit(f"--baseline {name}: persona file {personas} not found (pass --baseline-personas)")
    for run_dir in run_dirs:
        if not (run_dir / "answers_wide.csv").is_file():
            raise SystemExit(f"--baseline {name}: no answers_wide.csv in {run_dir}")
        if personas is not None:
            _check_persona_file(name, run_dir, Path(personas))
    q6 = [(row.get("Q6") or "").strip() for run_dir in run_dirs for row in spread_diagnostics.read_wide(run_dir)]
    q6 = [answer for answer in q6 if answer]
    rho = spread_diagnostics.diagnose_arm(name, run_dirs, personas_csv=personas)["rho_income_q1"]
    return {
        "name": name,
        "runs": [run_dir.name for run_dir in run_dirs],
        "rho_income_q1": None if math.isnan(rho) else round(rho, 4),
        "q6_cost_top_share": round(sum(a.startswith(COST_OPTION_PREFIX) for a in q6) / len(q6), 4) if q6 else None,
    }


def _baseline_text(baselines: list[dict] | None, key: str) -> str:
    if not baselines:
        return BASELINE_POINTER
    return " | ".join(f"{b['name']} {b[key]:.3f}" if b.get(key) is not None else f"{b['name']} n/a" for b in baselines)


def real_q1_shares(folder: Path) -> list[float]:
    """Real Q1 shares for levels 1-5, read at runtime from a compare_real output folder."""
    q1 = score_vs_real_marginals.load_real_marginals(Path(folder)).get("Q1")
    if not q1:
        raise SystemExit(f"no Q1 rows in {Path(folder) / 'comparison_options.csv'}")
    return [q1.get(str(level), 0.0) for level in range(1, 6)]


def report_lines(summary: dict, shares: list[float], real_shares: list[float] | None = None,
                 real_rho: float | None = None, baselines: list[dict] | None = None) -> list[str]:
    """The console table. Real values and the chat-model baselines appear only when passed in at
    runtime (baselines from baseline_reference); otherwise a pointer."""
    if real_shares:
        real_row = f"  {'real 600':<20}" + "".join(f"{s:>7.2f}" for s in real_shares)
        real_top2 = f"real {real_shares[3] + real_shares[4]:.2f}"
    else:
        real_row = f"  {'real 600':<20}{REAL_POINTER}"
        real_top2 = "real: pass --real-from"
    real_rho_text = f"real {real_rho:.2f}" if real_rho is not None else "real: pass --real-rho-income-q1"
    return [
        f"\n{'':22}{'1':>7}{'2':>7}{'3':>7}{'4':>7}{'5':>7}",
        f"  {'Jev expected shares':<20}" + "".join(f"{s:>7.2f}" for s in shares),
        real_row,
        "",
        f"  rho(income, E[Q1])    {summary['rho_income_q1']:>6}   "
        f"({real_rho_text} | {_baseline_text(baselines, 'rho_income_q1')})",
        f"  rho(income, E[Q2])    {summary['rho_income_q2']:>6}",
        f"  top-2 share (4+5)     {summary['q1_top2_share']:>6}   ({real_top2})",
        f"  mean confidence       {summary['q1_mean_confidence']:>6}",
        f"  Q6 'cost' top choice  {summary['q6_cost_top_share']:>6}   ({_baseline_text(baselines, 'q6_cost_top_share')})",
        f"  cost ~= ${summary['approx_usd']:.4f}   {summary['elapsed_seconds']}s",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personas", type=Path, default=DEFAULT_PERSONAS)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tag", default="pilot")
    parser.add_argument("--drop-census-fields", default="", help="comma-separated, for ablations")
    parser.add_argument("--drop-story-fields", default="", help="comma-separated, for ablations")
    parser.add_argument("--real-from", type=Path, default=None,
                        help="compare_real output folder; the real Q1 shares are read from it and printed, never stored")
    parser.add_argument("--real-rho-income-q1", type=float, default=None,
                        help="the real rho(income, Q1), recorded with R010 in the Assets folder; printed, never stored")
    parser.add_argument("--baseline", action="append", default=[], metavar="NAME=RUN_DIR[,RUN_DIR...]",
                        help="a chat-model arm to compare against (repeatable), e.g. the DeepSeek and Qwen S1 baseline "
                             "runs of registry R002; its rho(income, Q1) and Q6 cost-top share are computed from the runs")
    parser.add_argument("--baseline-personas", type=Path, default=None,
                        help="persona file the --baseline runs used, for their incomes (default: --personas); the R002 runs "
                             "used the full matched 600 (4_persona_sets/matched_600_v2_S1-S6_2026-09-16/phase1_interview_matched600.csv)")
    args = parser.parse_args()
    # Read before any request, so a wrong folder fails before anything is spent.
    real_shares = real_q1_shares(args.real_from) if args.real_from else None
    baselines = [baseline_reference(spec, args.baseline_personas or args.personas) for spec in args.baseline]

    drop_census = {f.strip() for f in args.drop_census_fields.split(",") if f.strip()}
    drop_story = {f.strip() for f in args.drop_story_fields.split(",") if f.strip()}

    with args.personas.open(encoding="utf-8-sig") as handle:
        personas = list(csv.DictReader(handle))
    if args.limit:
        personas = personas[: args.limit]
    print(f"{len(personas)} personas from {args.personas.name}")
    if drop_census or drop_story:
        print(f"  dropping census={sorted(drop_census)} story={sorted(drop_story)}")

    key = load_key()
    results: list[dict] = []
    failures: list[tuple[str, str]] = []

    def work(persona: dict) -> tuple[dict, dict | None, str | None]:
        try:
            state = build_state(persona, drop_census, drop_story)
            return persona, ask(key, state, args.timeout), None
        except Exception as error:  # noqa: BLE001 - reported per persona
            return persona, None, f"{type(error).__name__}: {error}"

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(work, p) for p in personas]
        for done, future in enumerate(as_completed(futures), start=1):
            persona, payload, error = future.result()
            if error:
                failures.append((persona["persona_id"], error))
                continue
            answers = payload["answers"]
            q1, q2 = answers["Q1_purchase_interest"], answers["Q2_purchase_likelihood"]
            q6 = answers["Q6_greatest_barrier"]
            results.append({
                "persona_id": persona["persona_id"],
                "income": float(persona["exact_household_income"]),
                "income_bucket": persona["income_bucket"],
                "age": int(persona["exact_age"]),
                "q1_score": q1["score"],
                "q1_check": round(expected_score(q1), 4),
                "q1_confidence": q1["confidence"],
                "q1_probs": q1["probabilities"],
                "q2_score": q2["score"],
                "q2_confidence": q2["confidence"],
                "q6_choice": q6["choice"],
                "q6_cost_prob": q6["probabilities"].get("The total cost (~$23,000)", 0.0),
                "input_tokens": payload["usage"]["input_tokens"],
                "output_tokens": payload["usage"]["output_tokens"],
            })
            if done % 5 == 0 or done == len(personas):
                print(f"  {done}/{len(personas)}")

    if failures:
        print(f"\n{len(failures)} failed:")
        for persona_id, error in failures[:5]:
            print(f"  {persona_id}  {error[:110]}")
    if not results:
        raise SystemExit("no usable answers")

    results.sort(key=lambda r: r["persona_id"])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
    run_dir = args.out_dir / f"{stamp}_{args.tag}"
    run_dir.mkdir(parents=True, exist_ok=True)

    with (run_dir / "answers.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "persona_id", "income", "income_bucket", "age", "q1_score", "q1_confidence",
            "q1_p1", "q1_p2", "q1_p3", "q1_p4", "q1_p5", "q2_score", "q2_confidence",
            "q6_choice", "q6_cost_prob",
        ])
        for r in results:
            p = r["q1_probs"]
            writer.writerow([
                r["persona_id"], r["income"], r["income_bucket"], r["age"],
                r["q1_score"], r["q1_confidence"],
                p.get("0", 0), p.get("1", 0), p.get("2", 0), p.get("3", 0), p.get("4", 0),
                r["q2_score"], r["q2_confidence"], r["q6_choice"], r["q6_cost_prob"],
            ])

    # Expected shares: average the probability vectors rather than counting argmax picks.
    shares = [statistics.mean(r["q1_probs"].get(str(k), 0.0) for r in results) for k in range(5)]
    rho = spearman([r["income"] for r in results], [r["q1_score"] for r in results])
    rho_q2 = spearman([r["income"] for r in results], [r["q2_score"] for r in results])
    tokens_in = sum(r["input_tokens"] for r in results)

    summary = {
        "run": run_dir.name,
        "model": MODEL,
        "personas": len(results),
        "failed": len(failures),
        "dropped_census_fields": sorted(drop_census),
        "dropped_story_fields": sorted(drop_story),
        "q1_expected_shares": [round(s, 4) for s in shares],
        "q1_top2_share": round(shares[3] + shares[4], 4),
        "q1_mean_score": round(statistics.mean(r["q1_score"] for r in results), 4),
        "q1_score_sd": round(statistics.pstdev([r["q1_score"] for r in results]), 4),
        "q1_mean_confidence": round(statistics.mean(r["q1_confidence"] for r in results), 4),
        "rho_income_q1": round(rho, 4),
        "rho_income_q2": round(rho_q2, 4),
        "q1_eq_q2_argmax_share": round(
            sum(1 for r in results if round(r["q1_score"]) == round(r["q2_score"])) / len(results), 4
        ),
        "q6_cost_top_share": round(
            sum(1 for r in results if r["q6_choice"].startswith(COST_OPTION_PREFIX)) / len(results), 4
        ),
        "q6_mean_cost_probability": round(statistics.mean(r["q6_cost_prob"] for r in results), 4),
        "input_tokens": tokens_in,
        "approx_usd": round(tokens_in / 1e6 * 0.042, 6),
        "elapsed_seconds": round(time.time() - started, 1),
        "reference": {
            # Real-side values are neither hardcoded nor stored here (this folder defaults to inside the
            # repository); --real-from / --real-rho-income-q1 only print them.
            "real_reference": REAL_POINTER,
            # Synthetic chat-model arms, computed from their run folders at the start of this run.
            "baselines": baselines or BASELINE_POINTER,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (run_dir / "raw_questions.json").write_text(json.dumps(QUESTIONS, indent=2) + "\n")

    for line in report_lines(summary, shares, real_shares, args.real_rho_income_q1, baselines):
        print(line)
    print(f"\nWrote {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
