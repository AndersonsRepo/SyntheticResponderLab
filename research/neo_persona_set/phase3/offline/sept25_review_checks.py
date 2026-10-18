"""Sept 25 review checks behind EXPERIMENT_LOG.md (2026-09-25 entry), recovered from the review transcripts. Offline.

The Sept 25 review re-checked Yaza's Sept 23-24 results with scratch scripts that were never committed
(the review's own notes are in 0_logs/reviews/2026-09-25_review_of_Sept23-24_results/). This script
recovers the checks whose numbers the log quotes, reading the reorganized Assets folder
(5_experiments/2026-09-24_Yaza_ablations_models_styles) and, where a check scores against the real
survey, the real file given with --real. No API calls, no network.

  all-arms        rescore the 18 Sept 23-24 comparison folders with compare_real (each folder's own
                  manifest: runs, filters, close_tv), compare every value with the shipped
                  comparison_summary.csv / comparison_long.csv, and recompute the 38 ALL_ARMS rows
                  (mean of the per-run summaries per folder x model; spearman and top match to 3
                  decimals, TV to 4). Also R018b's rank, R017b Qwen's top match, close counts.
  bootstrap       paired persona bootstrap (1000 draws of 100 personas with replacement, seed 12345, the
                  same draw for every arm and both repeats): R018b minus the Qwen / DeepSeek baselines.
                  Plus the spread between the Sept 23 baselines and the identical Sept 17 runs.
  unstyled-mix    R018b's persona -> model deal, recovered by matching its rows to the R017b runs, applied
                  to the UNSTYLED runs of the same four models; and 200 random 25-per-model deals
                  (seed 20260925), styled minus unstyled on the same deal.
  money-strip     phase1_interview_matched600_s1_nomoney.csv against the original: sentences removed,
                  finance cues that survive (the review's curated patterns), removed sentences that are
                  not about money, and the money cues in the saved R019a prompt.
  random-control  which RANDOM columns are copies of the DeepSeek baseline r1 run, and the RANDOM scores
                  on the questions that really were randomized.
  shuffle         the compare_real summary metrics before and after shuffling answers across personas
                  (20 column shuffles and 20 row shuffles per run, seed 777).
  gradients       share of the baseline income gradient removed by R019a, within-style rho(income, Q1)
                  in R017b Gemini, r(Q1, concept likelihood) in the 13 styled arms, and (with --real)
                  the same correlation in the real survey, computed at run time.
  all             every check above.

How each check works is in its function's docstring. Every subcommand prints a logged-vs-reproduced
list and writes it, with the detail tables, to --out (default: <Sept 24 folder>/reproduced_2026-10-18).
The logged numbers are read from EXPERIMENT_LOG.md at run time; nothing logged is written into this file.
Only aggregates of the real file are computed; --out may not be inside the repository or the
real-data folder.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/sept25_review_checks.py all \\
        --real "../SyntheticResponderLab-Assets/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv"
    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/sept25_review_checks.py money-strip
"""

from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import historic_common as hc  # noqa: E402  (also puts phase3 on sys.path)
import compare_real  # noqa: E402
import crosswalk  # noqa: E402
import filter_qualified  # noqa: E402
import metrics  # noqa: E402
import realdata  # noqa: E402
import spread_diagnostics  # noqa: E402

CLOSE_TV = 0.10
SUMMARY_KEYS = ("questions_compared", "questions_close", "mean_tv", "median_tv", "mean_js", "share_top_match", "mean_spearman",
                "mean_abs_mean_diff", "questions_chi2_p_below_05")
QCOLS = ["S3", "Q0A", "Q0B", "Q1", "Q2", "Q3", "Q5_1", "Q5_2", "Q5_3", "Q5_4", "Q5_5", "Q5_6", "Q5_7", "Q6", "Q7", "Q9A", "Q9B", "Q10A", "Q10B",
         "Q11A", "Q11B", "Q12A", "Q12B", "Q13A", "Q13B", "Q14", "Q15", "Q16", "Q17", "Q18", "Q19", "Q20", "Q21", "Q22", "Q23", "Q24", "Q25", "Q26", "Q30"]
STYLES = ["unstyled", "enthusiastic", "indifferent", "pragmatic", "skeptical"]
MODELS = ["gemini", "qwen", "mistral", "gpt5mini"]
STYLED = {"gemini": "R017b_gemini", "qwen": "R017b_qwen", "mistral": "R017b_mistral", "gpt5mini": "R017b_gpt5mini"}
UNSTYLED = {"gemini": "R008_gemini", "qwen": "qwen_baseline", "mistral": "R008_mistral_medium", "gpt5mini": "R008_gpt5mini"}

# Arm -> (repeat 1, repeat 2) run folders. Sept 23-24 runs live in the Sept 24 folder's survey_runs,
# the identical Sept 17 baseline runs in the Sept 17 folder's survey_runs.
ARMS: Dict[str, Tuple[str, str]] = {
    "R018b_mixed_prereg": ("20260924T212905Z_mixed-panel_r1_s1-R018b-prereg", "20260924T212905Z_mixed-panel_r2_s1-R018b-prereg"),
    "R017b_qwen": ("20260924T211659Z_qwen3.7-plus_r1_s1-R017b-fixedstyles", "20260924T211810Z_qwen3.7-plus_r2_s1-R017b-fixedstyles"),
    "R017b_gemini": ("20260924T211348Z_gemini-3-flash-preview_r1_s1-R017b-fixedstyles", "20260924T211517Z_gemini-3-flash-preview_r2_s1-R017b-fixedstyles"),
    "R017b_mistral": ("20260924T211931Z_mistral-medium-3.1_r1_s1-R017b-fixedstyles", "20260924T212145Z_mistral-medium-3.1_r2_s1-R017b-fixedstyles"),
    "R017b_gpt5mini": ("20260924T212329Z_gpt-5-mini_r1_s1-R017b-fixedstyles", "20260924T212555Z_gpt-5-mini_r2_s1-R017b-fixedstyles"),
    "R008_mistral_medium": ("20260923T213612Z_mistral-medium-3.1_r1_s1-R008c-mistralmedium", "20260923T213743Z_mistral-medium-3.1_r2_s1-R008c-mistralmedium"),
    "R008_gemini": ("20260923T211949Z_gemini-3-flash-preview_r1_s1-R008-crossfamily", "20260923T212128Z_gemini-3-flash-preview_r2_s1-R008-crossfamily"),
    "R008_gpt5mini": ("20260923T212317Z_gpt-5-mini_r1_s1-R008b-gpt5mini", "20260923T212614Z_gpt-5-mini_r2_s1-R008b-gpt5mini"),
    "qwen_baseline": ("20260923T203542Z_qwen3.7-plus_r1_s1-baseline", "20260923T203654Z_qwen3.7-plus_r2_s1-baseline"),
    "deepseek_baseline": ("20260923T203058Z_deepseek-v4-pro-0813_r1_s1-baseline", "20260923T203312Z_deepseek-v4-pro-0813_r2_s1-baseline"),
    "RANDOM": ("20260924T205807Z_random-uniform_r1_s1-RANDOM", "20260924T205807Z_random-uniform_r2_s1-RANDOM"),
    "deepseek_R019a": ("20260924T205749Z_deepseek-v4-pro-0813_r1_s1-R019a-nomoney", "20260924T210023Z_deepseek-v4-pro-0813_r2_s1-R019a-nomoney"),
    "qwen_R019a": ("20260924T210325Z_qwen3.7-plus_r1_s1-R019a-nomoney", "20260924T210436Z_qwen3.7-plus_r2_s1-R019a-nomoney"),
    "deepseek_R019b": ("20260924T210551Z_deepseek-v4-pro-0813_r1_s1-R019b-censusonly", "20260924T210823Z_deepseek-v4-pro-0813_r2_s1-R019b-censusonly"),
    "qwen_R019b": ("20260924T211127Z_qwen3.7-plus_r1_s1-R019b-censusonly", "20260924T211236Z_qwen3.7-plus_r2_s1-R019b-censusonly"),
}
SEPT17_ARMS: Dict[str, Tuple[str, str]] = {
    "qwen_baseline_Sept17": ("20260917T184057Z_qwen3.7-plus_r1_p100_s1-baseline", "20260917T184202Z_qwen3.7-plus_r2_p100_s1-baseline"),
    "deepseek_baseline_Sept17": ("20260917T183553Z_deepseek-v4-pro-0813_r1_p100_s1-baseline", "20260917T183824Z_deepseek-v4-pro-0813_r2_p100_s1-baseline"),
}
STYLED_TAGS = ("R005-asspec", "R017-styles", "R017b-fixedstyles", "R018-mixed", "R018b-prereg")
RUN_NAME = re.compile(r"^(\d{8}T\d{6}Z)_(.+?)_r(\d)_s1-(.+)$")

# The review's curated finance-cue patterns for the no-money persona file (Sept 25, curated_survivors.py),
# Tier A = financial status, Tier B = price sensitivity. One change: 'principal' is not counted in
# "principal research role" (the checker dropped that P084 hit by hand after reading it).
CUE_A = re.compile(r"401\s?\(k\)|403\s?\(b\)|\b529\b|\bIRA\b|brokerage|taxable|credit[- ]cards?|social security|\bincomes\b|\bearners\b|\bequity\b|mortgaged|"
                   r"retirement (?:contribution|account|asset|liquidity)s?|retirement contributions?|emergency (?:fund|reserve|cash)|replacement reserve|liquid reserve|from reserves|cash reserve|"
                   r"cash[- ]flow|available cash|cash allows|pays cash|paying cash|\bpays monthly\b|paying it off|\bpayments?\b|discretionary (?:spending|projects|use)|spending (?:limit|accounts)|"
                   r"\bsurplus(?:es)?\b|allowance|charitable giving|\bbudgeted\b|\bprincipal\b(?! research)|(?:travel|college|repair|emergency|maintenance) fund|\bfund 529\b|funding (?:plan|timeline)|education funding|funding roof|"
                   r"disability benefits|related to benefits|rental assistance|energy-assistance|set aside in a single month|wanted to spend|expenditures?|discretionary spending", re.I)
CUE_B = re.compile(r"(?:compar\w+|checking|check) (?:\w+ )?prices|prices (?:online|across|at)|quotes? (?:exceed|came in|come in|run higher)|quotes (?:she received )?exceeded|"
                   r"save (?:gas|heat|on heating|on utilities)|secondhand|when prices were lower|\bco-pays\b|prices, and timelines", re.I)
# The review's money-sense terms for sorting removed sentences (Sept 25, collateral.py), verbatim.
REMOVED_MONEY = re.compile(r"\$|\b\d+k\b|401|403\s?\(b\)|\b529\b|\bIRA\b|roth|\b(?:incomes?|salar\w*|wages?|paychecks?|earnings?|earned|earner\w*|earns?|afford\w*|budget\w*|costs?|costly|pric\w*|expens\w*|mortgage\w*|rent|rents|renting|loans?|debts?|savings?|pensions?|bills?|money|cash|funds?|funding|brokerage|"
                           r"equity|credit[- ]cards?|credit|social security|medicare|medicaid|taxes|premiums?|deductibles?|co-?pays?|payments?|paid off|paid-off|refinanc\w*|mortgage-free|financing|financed|dollars?|investments?|invested|annuit\w*|royalt\w*|dividends?|stipend|reserves?|surplus\w*|allowance|interest rates?|bala"
                           r"nces?|disability|benefits?|tuition|take-home|gross|discount\w*|spending|tax refunds?|refunds?|insurance (?:covered|premiums?|costs?|and)|financial (?:stability|cushion|simplicity|decisions|commitments|move|planner|services|picture|security|situation|margin|obligations)|managing (?:household )?financ"
                           r"es|budget)\b", re.I)
NOT_MONEY_CATEGORIES = ('space/physical "tight"', 'employment status ("works for pay")', "occupation description", "hobby/reading", "other")


# --------------------------------------------------------------------------- paths and loading

class Ctx:
    def __init__(self, args: argparse.Namespace) -> None:
        self.assets = Path(args.assets)
        self.sept24 = self.assets / hc.SEPT24_REL
        self.runs24 = self.sept24 / "survey_runs"
        self.runs17 = self.assets / hc.SEPT17_REL / "survey_runs"
        self.log = hc.LogText.read(Path(args.log) if args.log else self.assets / hc.LOG_REL)
        self.real_path: Optional[Path] = Path(args.real).expanduser().resolve() if getattr(args, "real", None) else None
        self.out = hc.resolve_out(args.out, self.sept24 / hc.OUT_FOLDER, self.real_path)
        self._real: Optional[realdata.RealSurvey] = None

    def real(self) -> realdata.RealSurvey:
        if self._real is None:
            self._real = realdata.load_real_survey(hc.real_file(self.real_path))
        return self._real

    def run_dir(self, name: str) -> Path:
        for root in (self.runs24, self.runs17):
            if (root / name).is_dir():
                return root / name
        raise SystemExit(f"run folder {name} is not in {self.runs24} or {self.runs17}")

    def arm_dirs(self, arm: str) -> Tuple[Path, Path]:
        names = ARMS.get(arm) or SEPT17_ARMS[arm]
        return self.run_dir(names[0]), self.run_dir(names[1])


def load(run_dir: Path) -> compare_real.RunData:
    return compare_real.load_run(Path(run_dir), require_outdoor_space=True, exclude_fallback=False)


def raw_rows(run_dir: Path) -> Dict[str, Dict[str, str]]:
    """answers_wide rows keyed by persona, WITHOUT the screener filter."""
    return {r["persona_id"]: r for r in filter_qualified.read_csv_rows(Path(run_dir) / "answers_wide.csv")[1]}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pctl(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile, as the review used."""
    xs = sorted(v for v in values if not math.isnan(v))
    if not xs:
        return hc.NAN
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# --------------------------------------------------------------------------- scoring

def official(real: realdata.RealSurvey, run: compare_real.RunData) -> Dict[str, Any]:
    """compare_real.compare_runs + summarize_run on one run (the published scoring path)."""
    return compare_real.summarize_run(run, compare_real.compare_runs(real, [run], CLOSE_TV))


class FastScorer:
    """compare_real's own per-question functions with the real side extracted once (it never changes).

    check_equal() asserts it reproduces the official path on a run before any resampling uses it.
    """

    def __init__(self, real: realdata.RealSurvey, template: compare_real.RunData, close_tv: float = CLOSE_TV) -> None:
        self.close_tv = close_tv
        self.items: List[Tuple[Any, Any, Any]] = []
        for qmap in crosswalk.CROSSWALK:
            if qmap.kind == "none" or not qmap.scored or qmap.our_id not in template.questions:
                continue
            spec = compare_real.build_spec(qmap, template.questions[qmap.our_id])
            real_x = compare_real.extract_real(real, qmap, spec)
            if real_x is not None:
                self.items.append((qmap, spec, real_x))

    def per_question(self, run: compare_real.RunData, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        shim = copy.copy(run)
        shim.rows = rows
        out = []
        for qmap, spec, real_x in self.items:
            question = run.questions.get(qmap.our_id)
            if question is None or compare_real.build_spec(qmap, question).labels != spec.labels:
                raise RuntimeError(f"question {qmap.our_id} differs in {run.run_id}")
            synth_x = compare_real.extract_synth(shim, qmap, spec)
            if real_x.n == 0 or synth_x.n == 0:
                continue
            stats = compare_real.score(qmap, real_x, synth_x, self.close_tv)
            stats["our_id"] = qmap.our_id
            out.append(stats)
        return out

    @staticmethod
    def summarize(per_q: List[Dict[str, Any]]) -> Dict[str, float]:
        count = len(per_q)
        spearmans = [s["spearman"] for s in per_q if not math.isnan(s["spearman"])]
        return {"questions_compared": count, "questions_close": sum(1 for s in per_q if s["close"]),
                "mean_tv": metrics.mean([s["tv"] for s in per_q]),
                "share_top_match": sum(1 for s in per_q if s["top_match"]) / count if count else hc.NAN,
                "mean_spearman": metrics.mean(spearmans)}

    def score_rows(self, run: compare_real.RunData, rows: List[Dict[str, str]]) -> Dict[str, float]:
        return self.summarize(self.per_question(run, rows))


def check_equal(scorer: FastScorer, real: realdata.RealSurvey, run: compare_real.RunData) -> None:
    off, fast = official(real, run), scorer.score_rows(run, run.rows)
    for key in ("questions_compared", "questions_close", "mean_tv", "share_top_match", "mean_spearman"):
        a, b = off[key], fast[key]
        if not (a == b or (isinstance(a, float) and math.isnan(a) and math.isnan(b))):
            raise AssertionError(f"{run.run_id} {key}: official {a} vs fast {b}")


def arm_mean(per_run: Sequence[Dict[str, float]], keys: Sequence[str] = ("mean_spearman", "share_top_match", "mean_tv", "questions_close")) -> Dict[str, float]:
    return {k: sum(float(s[k]) for s in per_run) / len(per_run) for k in keys}


# --------------------------------------------------------------------------- pure helpers (tested)

def all_arms_rows(folder: str, summaries: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    """ALL_ARMS rows for one comparison folder: mean of the per-run summary values (as written, 4 decimals)
    per model slug, in first-seen order; spearman / top match rounded to 3, TV to 4, close to 1."""
    groups: "collections.OrderedDict[str, List[Dict[str, str]]]" = collections.OrderedDict()
    for s in summaries:
        groups.setdefault(s["model"].split("/")[-1], []).append(s)
    rows = []
    for slug, group in groups.items():
        mean = lambda key: sum(float(g[key]) for g in group) / len(group)  # noqa: E731
        rows.append({"folder": folder, "model": slug, "runs": len(group), "mean_spearman": round(mean("mean_spearman"), 3),
                     "share_top_match": round(mean("share_top_match"), 3), "mean_tv": round(mean("mean_tv"), 4),
                     "questions_close": round(mean("questions_close"), 1), "questions_compared": round(mean("questions_compared"), 1)})
    return rows


def recover_assignment(mixed: Dict[str, Dict[str, str]], sources: Dict[str, Dict[str, Dict[str, str]]], columns: Sequence[str] = QCOLS) -> Tuple[Dict[str, str], int, int]:
    """persona -> source arm whose row is identical on every answer column; (assignment, ambiguous, unmatched)."""
    assignment, ambiguous, unmatched = {}, 0, 0
    for pid, row in mixed.items():
        hits = [name for name, rows in sources.items() if pid in rows and all(rows[pid].get(q) == row.get(q) for q in columns)]
        if hits:
            assignment[pid] = hits[0]
            ambiguous += len(hits) > 1
        else:
            unmatched += 1
    return assignment, ambiguous, unmatched


def sentences(text: str, column: str) -> List[str]:
    """The review's split: story_priorities on ';', every other story section after . ! or ? plus whitespace."""
    if column == "story_priorities":
        return [s.strip() for s in text.split(";") if s.strip()]
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def removed_sentences(original: Sequence[Dict[str, str]], stripped: Sequence[Dict[str, str]]) -> Tuple[List[Dict[str, str]], int, int]:
    """Sentences in the original story sections that the stripped file no longer has (multiset difference,
    persona by persona). Returns (removed rows, sentences in the original, sentences added by the strip)."""
    by_id = {r["persona_id"]: r for r in stripped}
    removed, total, added = [], 0, 0
    for row in original:
        other = by_id[row["persona_id"]]
        for column in [c for c in row if c.startswith("story_")]:
            orig = sentences(row.get(column) or "", column)
            kept = collections.Counter(sentences(other.get(column) or "", column))
            total += len(orig)
            for s in orig:
                if kept[s] > 0:
                    kept[s] -= 1
                else:
                    removed.append({"persona_id": row["persona_id"], "section": column[len("story_"):], "sentence": s})
            added += sum(kept.values())
    return removed, total, added


def finance_cues(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Sentences of the story sections that still carry a curated finance cue (tier A) or price cue (tier B)."""
    hits = []
    for row in rows:
        for column in [c for c in row if c.startswith("story_")]:
            for s in sentences(row.get(column) or "", column):
                a, b = [m.group(0) for m in CUE_A.finditer(s)], [m.group(0) for m in CUE_B.finditer(s)]
                if a or b:
                    hits.append({"persona_id": row["persona_id"], "section": column[len("story_"):], "tier": "A" if a else "B",
                                 "match": "|".join(a + b), "sentence": s})
    return hits


def removed_category(sentence: str) -> str:
    """The review's sort of removed sentences (collateral.py). 'money (weak)' holds the two sentences the
    checker read as money although no money-sense term matches (a cheaper grocery run, paid in installments)."""
    if REMOVED_MONEY.search(sentence):
        return "money"
    if re.search(r"\btight\b", sentence, re.I) or re.search(r"weather-tight", sentence, re.I):
        return 'space/physical "tight"'
    if re.search(r"\b(work(s|ed)? for pay|paid (job|employment|position|work))\b", sentence, re.I):
        return 'employment status ("works for pay")'
    if re.search(r"financial advisor|insurance (office|field)|tax examiner", sentence, re.I):
        return "occupation description"
    if re.search(r"\btax\b|\binsurance\b|finances", sentence, re.I):
        return "paperwork / desk items (tax, insurance forms, household finances)"
    if re.search(r"financial history|personal interest", sentence, re.I):
        return "hobby/reading"
    if re.search(r"\bcheaper\b|\binstallments?\b", sentence, re.I):
        return "money (weak)"
    return "other"


def rho_by_style(rows: Sequence[Dict[str, str]], incomes: Dict[str, float]) -> Dict[str, float]:
    """Spearman rho(exact income, Q1) per response style (blank trait = unstyled) and pooled."""
    groups: Dict[str, Tuple[List[float], List[float]]] = {s: ([], []) for s in STYLES + ["pooled"]}
    for row in rows:
        try:
            q1 = float(str(row.get("Q1")).strip())
        except ValueError:
            continue
        if row.get("persona_id") not in incomes:
            continue
        style = (row.get("trait") or "").strip() or "unstyled"
        for key in (style, "pooled"):
            if key in groups:
                groups[key][0].append(incomes[row["persona_id"]])
                groups[key][1].append(q1)
    return {k: spread_diagnostics._spearman(x, y) if len(x) >= 3 else hc.NAN for k, (x, y) in groups.items()}


# --------------------------------------------------------------------------- checks

def check_all_arms(ctx: Ctx) -> List[Dict[str, str]]:
    """Rescore every Sept 23-24 comparison folder and recompute ALL_ARMS.csv from the rescored summaries.

    A folder reproduces when every value the shipped comparison_summary.csv and comparison_long.csv
    hold (columns present in both, compared as written) equals the rescored one. Current compare_real
    adds two summary columns (item_set, n_real_respondents) and long column 'scored', so files are not
    compared byte for byte any more; values are.
    """
    real = ctx.real()
    real_sha = sha256_of(hc.real_file(ctx.real_path))
    folders = sorted(p for p in ctx.sept24.glob("2026092[34]T*_s1-*") if p.is_dir() and (p / "manifest.json").exists())
    folder_rows, recomputed = [], []
    for folder in folders:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        run_dirs = [ctx.run_dir(Path(r["run_dir"]).name) for r in manifest["runs"]]
        inputs_ok = all(sha256_of(d / name) == digest for d, r in zip(run_dirs, manifest["runs"]) for name, digest in r["sha256"].items())
        filters = manifest.get("filters", {})
        runs = [compare_real.load_run(d, require_outdoor_space=bool(filters.get("require_outdoor_space", True)),
                                      exclude_fallback=bool(filters.get("exclude_fallback", False))) for d in run_dirs]
        compare_real.assign_labels(runs)
        results = compare_real.compare_runs(real, runs, float(manifest.get("thresholds", {}).get("close_tv", CLOSE_TV)))
        mine = {}
        for run in runs:
            s = compare_real.summarize_run(run, results)
            mine[run.run_id] = {k: (v if isinstance(v, str) else compare_real.num(v)) for k, v in s.items()}
        shipped = hc.read_csv(folder / "comparison_summary.csv")
        s_cols = [c for c in shipped[0] if c in compare_real.SUMMARY_COLUMNS]
        s_cells = s_bad = 0
        for row in shipped:
            for c in s_cols:
                s_cells += 1
                s_bad += mine.get(row["run_id"], {}).get(c) != row[c]
        long_mine = {(r["run_id"], r["our_id"]): r for r in (compare_real.long_row(x) for x in results)}
        shipped_long = hc.read_csv(folder / "comparison_long.csv")
        l_cols = [c for c in shipped_long[0] if c in compare_real.LONG_COLUMNS]
        l_cells = l_bad = 0
        for row in shipped_long:
            for c in l_cols:
                l_cells += 1
                l_bad += long_mine.get((row["run_id"], row["our_id"]), {}).get(c) != row[c]
        folder_rows.append({"folder": folder.name, "runs": len(runs), "real_sha256_matches_manifest": manifest["real"]["sha256"] == real_sha,
                            "input_sha256_match": inputs_ok, "summary_cells": s_cells, "summary_mismatches": s_bad,
                            "long_cells": l_cells, "long_mismatches": l_bad,
                            "reproduces": s_bad == 0 and l_bad == 0 and inputs_ok and len(shipped) == len(runs) and manifest["real"]["sha256"] == real_sha})
        recomputed += all_arms_rows(folder.name, [mine[run.run_id] for run in runs])
        print(f"  {folder.name:52s} runs={len(runs):2d} summary mismatches={s_bad}/{s_cells} long mismatches={l_bad}/{l_cells} "
              f"inputs sha ok={inputs_ok} real sha ok={manifest['real']['sha256'] == real_sha}")

    published = {(r["folder"], r["model"]): r for r in hc.read_csv(ctx.sept24 / "ALL_ARMS.csv")}
    n_equal = 0
    for row in recomputed:
        pub = published.get((row["folder"], row["model"]))
        equal = pub is not None and int(pub["runs"]) == row["runs"] and all(
            abs(float(pub[k]) - row[k]) < 1e-9 for k in ("mean_spearman", "share_top_match", "mean_tv", "questions_close"))
        row.update({f"published_{k}": (pub or {}).get(k, "") for k in ("mean_spearman", "share_top_match", "mean_tv", "questions_close")})
        row["equal"] = equal
        n_equal += equal
    hc.write_csv(ctx.out / "all_arms_folders.csv", folder_rows)
    hc.write_csv(ctx.out / "all_arms_recomputed.csv", recomputed)

    by_sp = sorted(recomputed, key=lambda r: -r["mean_spearman"])
    r018b = next(r for r in recomputed if r["folder"].endswith("R018b-prereg"))
    rank = 1 + sum(1 for r in recomputed if r["mean_spearman"] > r018b["mean_spearman"])
    r017b_qwen = next(r for r in recomputed if r["folder"].endswith("R017b-fixedstyles") and r["model"].startswith("qwen"))
    baselines = [r for r in recomputed if r["folder"].endswith("_s1-baseline")]
    log = ctx.log
    counts = log.groups(r"All (\d+) comparison folders reproduce exactly; all (\d+) `ALL_ARMS` rows recompute")
    n_rep = sum(1 for f in folder_rows if f["reproduces"])
    checks = [
        hc.check_row("all-arms", "comparison folders that reproduce", None if counts is None else counts[0], f"{n_rep} of {len(folder_rows)}",
                     counts is not None and n_rep == len(folder_rows) == int(counts[0]), "every shared summary and long value equal, inputs sha256 equal"),
        hc.check_row("all-arms", "ALL_ARMS rows that recompute", None if counts is None else counts[1], f"{n_equal} of {len(recomputed)} (published {len(published)})",
                     counts is not None and n_equal == len(recomputed) == len(published) == int(counts[1])),
    ]
    rank_logged = log.groups(r"\| (\d+)(?:st|nd|rd|th) on Spearman")
    checks.append(hc.check_row("all-arms", "R018b rank on mean_spearman (of all ALL_ARMS rows)", None if rank_logged is None else rank_logged[0], str(rank),
                               rank_logged is not None and rank == int(rank_logged[0]), "higher: " + ", ".join(f"{r['folder'][15:]} {r['model']} {r['mean_spearman']:.3f}" for r in by_sp[:rank - 1])))
    top_logged = log.groups(r"Qwen R017b beats it on top match \(([\d.]+)\)")
    checks.append(hc.numeric_check("all-arms", "R017b Qwen share_top_match", None if top_logged is None else top_logged[0], r017b_qwen["share_top_match"], digits=3,
                                   note=f"R018b {r018b['share_top_match']:.3f}"))
    close_logged = log.groups(r'"Only (\d+) of (\d+) close"')
    base_close = sorted({r["questions_close"] for r in baselines})
    checks.append(hc.check_row("all-arms", "baseline questions_close", None if close_logged is None else close_logged[0], "/".join(f"{v:g}" for v in base_close),
                               close_logged is not None and base_close == [float(close_logged[0])], "DeepSeek and Qwen baseline arms"))
    r018b_close = log.groups(r"R018b has ([\d.]+)")
    checks.append(hc.numeric_check("all-arms", "R018b questions_close", None if r018b_close is None else r018b_close[0], r018b["questions_close"], digits=1))
    return checks


def check_bootstrap(ctx: Ctx, reps: int = 1000, seed: int = 12345) -> List[Dict[str, str]]:
    """Paired persona bootstrap of arm-level mean_spearman / share_top_match (Sept 25, step2_bootstrap.py).

    Each draw takes 100 persona ids with replacement from the sorted s1 ids (P001..P100, from the Qwen
    baseline r1 answers before the screener filter); the same draw goes to every arm and both repeats.
    Arm value = mean over r1 and r2 of the metric on the drawn rows (personas the screener dropped from a
    run are absent from it, as in compare_real). Only the draw uses the random stream, so scoring fewer
    arms than the review did leaves every draw, and the contrasts reported here, unchanged.
    """
    real = ctx.real()
    arms = ["R018b_mixed_prereg", "qwen_baseline", "deepseek_baseline"]
    runs = {(a, i): load(d) for a in arms for i, d in enumerate(ctx.arm_dirs(a))}
    scorer = FastScorer(real, runs[("qwen_baseline", 0)])
    for run in runs.values():
        check_equal(scorer, real, run)
    index = {k: {r["persona_id"]: r for r in run.rows} for k, run in runs.items()}
    ids = sorted(raw_rows(ctx.arm_dirs("qwen_baseline")[0]))

    def value(arm: str, sample: Sequence[str]) -> Dict[str, float]:
        per = [scorer.score_rows(runs[(arm, i)], [index[(arm, i)][p] for p in sample if p in index[(arm, i)]]) for i in (0, 1)]
        return arm_mean(per, ("mean_spearman", "share_top_match"))

    point = {a: value(a, ids) for a in arms}
    rng = random.Random(seed)
    boot: Dict[str, List[Dict[str, float]]] = {a: [] for a in arms}
    for _ in range(reps):
        sample = [rng.choice(ids) for _ in ids]
        for a in arms:
            boot[a].append(value(a, sample))
    rows = []
    for other in ("qwen_baseline", "deepseek_baseline"):
        for metric in ("mean_spearman", "share_top_match"):
            diffs = [x[metric] - y[metric] for x, y in zip(boot["R018b_mixed_prereg"], boot[other])]
            obs = point["R018b_mixed_prereg"][metric] - point[other][metric]
            rows.append({"contrast": f"R018b_mixed_prereg - {other}", "metric": metric, "observed": obs, "ci_2.5": pctl(diffs, 0.025),
                         "ci_97.5": pctl(diffs, 0.975), "share_le_0": sum(1 for d in diffs if d <= 0) / len(diffs), "reps": reps, "seed": seed})
            print(f"  R018b - {other:18s} {metric:15s} {obs:+.4f}  95% [{rows[-1]['ci_2.5']:+.4f}, {rows[-1]['ci_97.5']:+.4f}]  P(d<=0)={rows[-1]['share_le_0']:.3f}")
    noise = []
    for model in ("qwen", "deepseek"):
        a = arm_mean([official(real, load(d)) for d in ctx.arm_dirs(f"{model}_baseline")])
        b = arm_mean([official(real, load(d)) for d in ctx.arm_dirs(f"{model}_baseline_Sept17")])
        noise.append({"model": model, "sept23_mean_spearman": a["mean_spearman"], "sept17_mean_spearman": b["mean_spearman"],
                      "abs_diff": abs(a["mean_spearman"] - b["mean_spearman"]),
                      "abs_diff_of_3dp_arm_values": abs(round(a["mean_spearman"], 3) - round(b["mean_spearman"], 3))})
        print(f"  same configuration rerun, {model}: Sept 23 {a['mean_spearman']:.4f} vs Sept 17 {b['mean_spearman']:.4f} (|diff| {noise[-1]['abs_diff']:.4f})")
    hc.write_csv(ctx.out / "bootstrap_contrasts.csv", rows)
    hc.write_csv(ctx.out / "bootstrap_noise_floor.csv", noise)

    qwen_sp = next(r for r in rows if r["contrast"].endswith("qwen_baseline") and r["metric"] == "mean_spearman")
    logged = ctx.log.groups(r"R018b minus Qwen baseline \+([\d.]+) Spearman \(95% interval ([−-][\d.]+) to \+([\d.]+)\)")
    spread = ctx.log.groups(r"shifts Spearman by ([\d.]+)–([\d.]+)")
    diffs = sorted(n["abs_diff"] for n in noise)
    diffs3 = sorted(n["abs_diff_of_3dp_arm_values"] for n in noise)
    return [
        hc.numeric_check("bootstrap", "R018b - Qwen baseline, mean_spearman", None if logged is None else "+" + logged[0], qwen_sp["observed"]),
        hc.numeric_check("bootstrap", "  95% interval, lower", None if logged is None else logged[1], qwen_sp["ci_2.5"], note=f"{reps} paired persona draws, seed {seed}"),
        hc.numeric_check("bootstrap", "  95% interval, upper", None if logged is None else "+" + logged[2], qwen_sp["ci_97.5"]),
        hc.numeric_check("bootstrap", "same-config rerun shift, smallest", None if spread is None else spread[0], diffs[0], digits=5,
                         note="Sept 23 vs Sept 17 baseline arms, full-precision arm means"),
        hc.numeric_check("bootstrap", "same-config rerun shift, largest", None if spread is None else spread[1], diffs[-1], digits=5),
        hc.numeric_check("bootstrap", "  smallest, from 3-decimal arm values", None if spread is None else spread[0], diffs3[0], digits=3,
                         note="difference of the ALL_ARMS-style rounded arm means"),
        hc.numeric_check("bootstrap", "  largest, from 3-decimal arm values", None if spread is None else spread[1], diffs3[-1], digits=3),
    ]


def check_unstyled_mix(ctx: Ctx, n_deals: int = 200, seed: int = 20260925) -> List[Dict[str, str]]:
    """Ensemble control (Sept 25, step5_ensemble_control.py).

    (a) Each R018b row (before the screener filter) is matched to the R017b run of the same repeat whose
    row for that persona is identical on all 39 answers; that is R018b's persona -> model deal. The same
    deal applied to the unstyled runs of the four models (Gemini R008, Qwen baseline, Mistral Medium
    R008c, GPT-5-mini R008b), r1 with r1 and r2 with r2, is scored with compare_real.
    (b) n_deals random balanced deals (25 per model; ids shuffled with random.Random(seed)), the same
    deal for the styled and the unstyled mix: styled minus unstyled top match.
    """
    real = ctx.real()
    need = list(STYLED.values()) + list(UNSTYLED.values()) + ["R018b_mixed_prereg"]
    dirs = {a: ctx.arm_dirs(a) for a in need}
    runs = {(a, i): load(dirs[a][i]) for a in need for i in (0, 1)}
    index = {k: {r["persona_id"]: r for r in run.rows} for k, run in runs.items()}
    assign: Dict[int, Dict[str, str]] = {}
    notes = []
    for i in (0, 1):
        a, ambiguous, unmatched = recover_assignment(raw_rows(dirs["R018b_mixed_prereg"][i]), {m: raw_rows(dirs[STYLED[m]][i]) for m in MODELS})
        assign[i] = a
        counts = collections.Counter(a.values())
        notes.append(f"r{i + 1}: matched {len(a)}, ambiguous {ambiguous}, unmatched {unmatched}, per model {dict(counts)}")
        print(f"  R018b deal {notes[-1]}")
    ids = sorted(assign[0])

    def build(source: Dict[str, str], deal: Dict[str, str], i: int) -> List[Dict[str, str]]:
        return [index[(source[deal[p]], i)][p] for p in ids if p in index[(source[deal[p]], i)]]

    def mix_official(source: Dict[str, str]) -> Dict[str, float]:
        per = []
        for i in (0, 1):
            tmpl = copy.copy(runs[(source["qwen"], i)])
            tmpl.rows = build(source, assign[i], i)
            per.append(official(real, tmpl))
        return arm_mean(per)

    styled, unstyled = mix_official(STYLED), mix_official(UNSTYLED)
    print(f"  R018b rebuilt from R017b with its deal: spearman {styled['mean_spearman']:.4f} top {styled['share_top_match']:.4f} tv {styled['mean_tv']:.4f}")
    print(f"  UNSTYLED mix, same deal:               spearman {unstyled['mean_spearman']:.4f} top {unstyled['share_top_match']:.4f} tv {unstyled['mean_tv']:.4f}")
    scorer = FastScorer(real, runs[("qwen_baseline", 0)])
    for run in runs.values():
        check_equal(scorer, real, run)
    rng = random.Random(seed)
    deals = []
    for _ in range(n_deals):
        order = ids[:]
        rng.shuffle(order)
        deal = {p: MODELS[j % 4] for j, p in enumerate(order)}
        out = {}
        for kind, source in (("styled", STYLED), ("unstyled", UNSTYLED)):
            per = []
            for i in (0, 1):
                tmpl = copy.copy(runs[(source["qwen"], i)])
                per.append(scorer.score_rows(tmpl, build(source, deal, i)))
            out[kind] = arm_mean(per, ("mean_spearman", "share_top_match"))
        deals.append({"styled_spearman": out["styled"]["mean_spearman"], "unstyled_spearman": out["unstyled"]["mean_spearman"],
                      "styled_top": out["styled"]["share_top_match"], "unstyled_top": out["unstyled"]["share_top_match"]})
    d_top = [d["styled_top"] - d["unstyled_top"] for d in deals]
    d_sp = [d["styled_spearman"] - d["unstyled_spearman"] for d in deals]
    summary = [{"what": "R018b rebuilt (styled, its own deal)", **styled}, {"what": "unstyled mix, R018b's deal", **unstyled}]
    summary.append({"what": f"styled - unstyled over {n_deals} random deals (seed {seed}), top match", "mean_spearman": "", "share_top_match": sum(d_top) / len(d_top),
                    "mean_tv": "", "questions_close": f"2.5% {pctl(d_top, 0.025):+.4f}, 97.5% {pctl(d_top, 0.975):+.4f}"})
    summary.append({"what": f"styled - unstyled over {n_deals} random deals (seed {seed}), spearman", "mean_spearman": sum(d_sp) / len(d_sp), "share_top_match": "",
                    "mean_tv": "", "questions_close": f"2.5% {pctl(d_sp, 0.025):+.4f}, 97.5% {pctl(d_sp, 0.975):+.4f}"})
    print(f"  styled - unstyled, {n_deals} deals: top {sum(d_top) / len(d_top):+.4f} [{pctl(d_top, 0.025):+.4f}, {pctl(d_top, 0.975):+.4f}]; "
          f"spearman {sum(d_sp) / len(d_sp):+.4f} [{pctl(d_sp, 0.025):+.4f}, {pctl(d_sp, 0.975):+.4f}]")
    hc.write_csv(ctx.out / "unstyled_mix.csv", summary, ["what", "mean_spearman", "share_top_match", "mean_tv", "questions_close"])
    hc.write_csv(ctx.out / "unstyled_mix_random_deals.csv", deals)

    logged = ctx.log.groups(r"\*\*unstyled\*\* reaches Spearman ([\d.]+) \(above ([\d.]+)\)")
    styles = ctx.log.groups(r"Styles add about \+([\d.]+) top match, interval down to ([\d.]+)")
    return [
        hc.numeric_check("unstyled-mix", "unstyled mix (R018b's deal), mean_spearman", None if logged is None else logged[0], unstyled["mean_spearman"], digits=5,
                         note="; ".join(notes)),
        hc.numeric_check("unstyled-mix", "R018b rebuilt from R017b, mean_spearman", None if logged is None else logged[1], styled["mean_spearman"], digits=5),
        hc.numeric_check("unstyled-mix", "styles add (top match), mean over deals", None if styles is None else "+" + styles[0], sum(d_top) / len(d_top), note=f"{n_deals} deals, seed {seed}"),
        hc.numeric_check("unstyled-mix", "  interval lower end (2.5%)", None if styles is None else styles[1], pctl(d_top, 0.025)),
    ]


def check_money_strip(ctx: Ctx) -> List[Dict[str, str]]:
    """Money-strip audit (Sept 25, count_removed.py, curated_survivors.py, collateral.py, audit_prompts.py).

    Removed = sentences of the original story sections missing from the no-money file. Surviving cues =
    sentences of the no-money file matching the curated tier A (financial status) or tier B (price) patterns.
    Removed sentences are sorted by the review's money-sense terms; 'not about money' = the physical
    'tight', employment-status, occupation, hobby and other categories.
    """
    original = hc.read_csv(ctx.sept24 / "phase1_interview_matched600_s1.csv")
    stripped = hc.read_csv(ctx.sept24 / "phase1_interview_matched600_s1_nomoney.csv")
    removed, total, added = removed_sentences(original, stripped)
    cues = finance_cues(stripped)
    tier_a = [c for c in cues if c["tier"] == "A"]
    personas_a = {c["persona_id"] for c in tier_a}
    personas_any = {c["persona_id"] for c in cues}
    for r in removed:
        r["category"] = removed_category(r["sentence"])
    cats = collections.Counter(r["category"] for r in removed)
    not_money = [r for r in removed if r["category"] in NOT_MONEY_CATEGORIES]
    tight_space = sum(1 for r in removed if r["category"] == 'space/physical "tight"' and r["section"] == "space_pressure")
    prompt_hits: List[str] = []
    prompt_files = sorted(ctx.runs24.glob("*_s1-R019a-nomoney/prompt_sample.txt"))
    for path in prompt_files[:1]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith('{"persona_profile"'):
                profile = json.dumps(json.loads(line)["persona_profile"], ensure_ascii=False)
                prompt_hits = [m.group(0) for m in CUE_A.finditer(profile)]
    print(f"  story sentences {total}, removed {len(removed)} ({len(removed) / total:.1%}), added by the strip {added}")
    print(f"  surviving cues: tier A {len(tier_a)} sentences in {len(personas_a)} personas; tier B only {len(cues) - len(tier_a)}; any cue {len(personas_any)} personas")
    print(f"  removed by category: {dict(cats)}; not about money {len(not_money)} ({len(not_money) / len(removed):.1%}); 'tight' in space_pressure {tight_space}")
    print(f"  saved R019a prompt ({prompt_files[0].parent.name if prompt_files else 'none'}): finance cues {prompt_hits}")
    hc.write_csv(ctx.out / "money_strip_removed_sentences.csv", removed, ["persona_id", "section", "category", "sentence"])
    hc.write_csv(ctx.out / "money_strip_surviving_cues.csv", cues, ["persona_id", "section", "tier", "match", "sentence"])
    per_section = collections.Counter(r["section"] for r in removed)
    hc.write_csv(ctx.out / "money_strip_summary.csv", [{"what": f"removed, {k}", "value": v} for k, v in sorted(per_section.items())]
                 + [{"what": f"category, {k}", "value": v} for k, v in cats.items()]
                 + [{"what": "tier A sentences", "value": len(tier_a)}, {"what": "tier A personas", "value": len(personas_a)},
                    {"what": "personas with any cue", "value": len(personas_any)}, {"what": "R019a prompt cues", "value": "|".join(prompt_hits)}], ["what", "value"])

    log = ctx.log
    count = log.groups(r"the ([\d,]+) removed sentences")
    survivors = log.groups(r"About (\d+) personas keep finance cues")
    collateral = log.groups(r"About (\d+)% of removed sentences were not about money \((\d+) \"space is tight\"\)")
    prompt_logged = "contains them" if log.contains("the saved prompt contains them") else None
    return [
        hc.check_row("money-strip", "removed sentences", count[0] if count else None, str(len(removed)), bool(count) and len(removed) == hc.to_number(count[0]),
                     f"of {total}; added by the strip {added}"),
        hc.check_row("money-strip", "personas keeping finance cues (tier A)", survivors[0] if survivors else None, str(len(personas_a)),
                     bool(survivors) and len(personas_a) == int(survivors[0]), f"{len(tier_a)} sentences; {len(personas_any)} personas with a tier A or B cue"),
        hc.check_row("money-strip", "saved R019a prompt has finance cues", prompt_logged, f"{len(prompt_hits)} cues: " + "|".join(prompt_hits),
                     prompt_logged is not None and bool(prompt_hits)),
        hc.numeric_check("money-strip", "share of removed sentences not about money", collateral[0] + "%" if collateral else None, len(not_money) / len(removed),
                         percent=True, digits=1, note=f"{len(not_money)} of {len(removed)}"),
        hc.check_row("money-strip", "removed 'tight' sentences in space_pressure", collateral[1] if collateral else None, str(tight_space),
                     bool(collateral) and tight_space == int(collateral[1])),
    ]


def check_random_control(ctx: Ctx) -> List[Dict[str, str]]:
    """RANDOM arm (Sept 25, random_inspect.py, random_split.py): columns identical to the DeepSeek baseline
    r1 run for all 100 personas are copies; its mean per-question Spearman over the other scored questions."""
    real = ctx.real()
    template = raw_rows(ctx.arm_dirs("deepseek_baseline")[0])
    scored = [q.our_id for q in crosswalk.CROSSWALK if q.kind != "none" and q.scored]
    held_by_run, per_run = [], []
    for d in ctx.arm_dirs("RANDOM"):
        rows = raw_rows(d)
        held = [q for q in QCOLS if all(p in template and rows[p].get(q) == template[p].get(q) for p in rows)]
        held_by_run.append(held)
        run = load(d)
        results = [r for r in compare_real.compare_runs(real, [run], CLOSE_TV) if r.status == compare_real.STATUS_OK and r.qmap.scored]
        held_scored = [q for q in held if q in scored]
        rest = [r.stats["spearman"] for r in results if r.qmap.our_id not in held_scored and not math.isnan(r.stats["spearman"])]
        per_run.append({"run": d.name, "copied_columns": "|".join(held), "copied_scored": "|".join(held_scored),
                        "randomized_scored_questions": len([r for r in results if r.qmap.our_id not in held_scored]), "mean_spearman_randomized": metrics.mean(rest)})
        print(f"  {d.name}: copied {held} (scored {held_scored}); mean spearman on the other {per_run[-1]['randomized_scored_questions']} = {per_run[-1]['mean_spearman_randomized']:.4f}")
    hc.write_csv(ctx.out / "random_control.csv", per_run)
    copied = [q for q in QCOLS if all(q in h for h in held_by_run) and q in scored]
    sps = sorted(r["mean_spearman_randomized"] for r in per_run)
    logged = ctx.log.groups(r"(\d+) scored questions \(([^)]+)\) are copied from DeepSeek\. On the (\d+) random questions Spearman is ([\d.]+)–([\d.]+)")
    logged_list = None if logged is None else [q.strip() for q in logged[1].split(",")]
    n_rand = sorted({r["randomized_scored_questions"] for r in per_run})
    return [
        hc.check_row("random-control", "scored questions copied from DeepSeek r1", None if logged is None else f"{logged[0]} ({logged[1]})", f"{len(copied)} ({', '.join(copied)})",
                     logged is not None and copied == logged_list and len(copied) == int(logged[0])),
        hc.check_row("random-control", "randomized scored questions", None if logged is None else logged[2], "/".join(map(str, n_rand)), logged is not None and n_rand == [int(logged[2])]),
        hc.numeric_check("random-control", "mean spearman on them, lower run", None if logged is None else logged[3], sps[0]),
        hc.numeric_check("random-control", "mean spearman on them, higher run", None if logged is None else logged[4], sps[-1]),
    ]


def check_shuffle(ctx: Ctx, n: int = 20, seed: int = 777) -> List[Dict[str, str]]:
    """Shuffle invariance (Sept 25, step4_permutation.py): permute each question column across personas, or
    whole rows across persona ids, and rescore with compare_real; count runs whose nine summary metrics are
    bit-identical. rho(income, Q1) is reported before and after to show the shuffles do break persona links."""
    real = ctx.real()
    incomes = {r["persona_id"]: float(r["exact_household_income"]) for r in hc.read_csv(ctx.sept24 / "phase1_interview_matched600_s1.csv")}
    rng = random.Random(seed)
    rows_out, identical, total = [], 0, 0
    for arm in ("R018b_mixed_prereg", "qwen_baseline"):
        for d in ctx.arm_dirs(arm):
            run = load(d)
            base = official(real, run)
            rho0 = rho_by_style(run.rows, incomes)["pooled"]
            for mode in ("columns", "rows"):
                same, rhos = 0, []
                for _ in range(n):
                    shuffled = copy.copy(run)
                    rows = [dict(r) for r in run.rows]
                    if mode == "columns":
                        for q in QCOLS:
                            values = [r[q] for r in rows]
                            rng.shuffle(values)
                            for r, v in zip(rows, values):
                                r[q] = v
                    else:
                        pids = [r["persona_id"] for r in rows]
                        rng.shuffle(pids)
                        for r, p in zip(rows, pids):
                            r["persona_id"] = p
                    shuffled.rows = rows
                    s = official(real, shuffled)
                    same += all(s[k] == base[k] or (s[k] != s[k] and base[k] != base[k]) for k in SUMMARY_KEYS)
                    rhos.append(rho_by_style(rows, incomes)["pooled"])
                identical += same
                total += n
                rows_out.append({"run": d.name, "mode": mode, "shuffles": n, "summary_identical": same, "rho_income_q1_before": rho0,
                                 "rho_income_q1_after_mean": sum(rhos) / len(rhos)})
                print(f"  {d.name[-42:]:42s} {mode:7s} x{n}: 9 summary metrics identical in {same}/{n}; rho(income,Q1) {rho0:+.3f} -> mean {sum(rhos) / len(rhos):+.3f}")
    hc.write_csv(ctx.out / "shuffle_invariance.csv", rows_out)
    claim = "unchanged" if ctx.log.contains("These metrics do not change when answers are shuffled across personas") else None
    return [hc.check_row("shuffle", "summary metrics unchanged by shuffling", claim, f"identical in {identical} of {total} shuffles",
                         claim is not None and identical == total, f"seed {seed}; R018b and Qwen baseline, both repeats")]


def styled_arms(runs_dir: Path) -> Dict[str, Tuple[Path, ...]]:
    groups: Dict[str, Dict[int, Path]] = {}
    for d in sorted(runs_dir.iterdir()):
        m = RUN_NAME.match(d.name)
        if not m:
            continue
        tag = next((t for t in STYLED_TAGS if m.group(4) == t or m.group(4).startswith(t + "-")), None)
        if tag:
            groups.setdefault(f"{tag} {m.group(2)}", {})[int(m.group(3))] = d
    return {k: tuple(v[r] for r in sorted(v)) for k, v in groups.items()}


def real_q1_concept_corr(real: realdata.RealSurvey) -> Tuple[float, int]:
    """Pearson r between real Q6 (our Q1) and the mean of the real concept purchase items (our Q9B..Q13B
    through the crosswalk), over respondents with Q6 and at least one of them. Aggregate only."""
    keys = {q.our_id: q.real_key for q in crosswalk.CROSSWALK}
    q1 = real.find(keys["Q1"])
    concept = [real.find(keys[q]) for q in spread_diagnostics.CONCEPT_PURCHASE]
    xs, ys = [], []
    for row in real.rows:
        a = realdata.likert_label_to_int(row[q1])
        values = [realdata.likert_label_to_int(row[c]) for c in concept if c]
        values = [v for v in values if v is not None]
        if a is not None and values:
            xs.append(float(a))
            ys.append(sum(values) / len(values))
    return metrics.pearson(xs, ys), len(xs)


def check_gradients(ctx: Ctx) -> List[Dict[str, str]]:
    """Persona-level checks (Sept 25, run_cli.py over spread_diagnostics.py and traits.py), both repeats pooled,
    income = exact_household_income from the s1 persona file: share of the baseline rho(income, Q1) removed
    by R019a and R019b, within-style rho in R017b Gemini, and r(Q1, concept likelihood) in the 13 styled arms."""
    personas = ctx.sept24 / "phase1_interview_matched600_s1.csv"
    rho = {a: spread_diagnostics.diagnose_arm(a, list(ctx.arm_dirs(a)), personas)["rho_income_q1"]
           for a in ("deepseek_baseline", "qwen_baseline", "deepseek_R019a", "qwen_R019a", "deepseek_R019b", "qwen_R019b")}
    removed = {m: {x: 1 - rho[f"{m}_{x}"] / rho[f"{m}_baseline"] for x in ("R019a", "R019b")} for m in ("deepseek", "qwen")}
    for m in ("deepseek", "qwen"):
        print(f"  {m}: rho baseline {rho[m + '_baseline']:.4f}, R019a {rho[m + '_R019a']:.4f} ({removed[m]['R019a']:.1%} removed), R019b {rho[m + '_R019b']:.4f} ({removed[m]['R019b']:.1%})")
    incomes = {r["persona_id"]: float(r["exact_household_income"]) for r in hc.read_csv(personas)}
    gem_rows = [r for d in ctx.arm_dirs("R017b_gemini") for r in raw_rows(d).values()]
    within = rho_by_style(gem_rows, incomes)
    print("  R017b Gemini within-style rho: " + ", ".join(f"{s} {within[s]:.3f}" for s in STYLES + ["pooled"]))
    corr = {name: spread_diagnostics.diagnose_arm(name, list(d), None)["q1_concept_corr"] for name, d in styled_arms(ctx.runs24).items()}
    below = sorted(name for name, r in corr.items() if r < 0.9)
    r018b = next(r for name, r in corr.items() if name.startswith("R018b-prereg"))
    print(f"  r(Q1, concept) in {len(corr)} styled arms; below 0.9: {below}")
    real_corr, n_real = (real_q1_concept_corr(ctx.real()) if ctx.real_path else (None, 0))
    if real_corr is not None:
        print(f"  real 600: r(Q6, mean concept purchase) = {real_corr:.3f} (n={n_real})")
    table = [{"what": f"rho(income, Q1) {k}", "value": v} for k, v in rho.items()]
    table += [{"what": f"share of baseline rho removed, {m} {x}", "value": v} for m, d in removed.items() for x, v in d.items()]
    table += [{"what": f"R017b gemini within-style rho, {s}", "value": within[s]} for s in STYLES + ["pooled"]]
    table += [{"what": f"r(Q1, concept) {name}", "value": r} for name, r in sorted(corr.items())]
    if real_corr is not None:
        table.append({"what": "real 600 r(Q6, mean concept purchase)", "value": real_corr})
    hc.write_csv(ctx.out / "gradients.csv", table, ["what", "value"])

    log = ctx.log
    money = log.groups(r"Money text alone: (\d+)% \(DeepSeek\) / (\d+)% \(Qwen\)")
    styles = log.groups(r"R017b Gemini: ([\d.]+) / ([\d.]+) / ([\d.]+) / ([\d.]+) / ([\d.]+)")
    concept = log.groups(r"False for (\d+) of (\d+) styled arms, R018b ([\d.]+); real 600 score ([\d.]+)")
    checks = [hc.numeric_check("gradients", f"rho removed by R019a, {m}", None if money is None else money[i] + "%", removed[m]["R019a"], percent=True, digits=1)
              for i, m in enumerate(("deepseek", "qwen"))]
    checks += [hc.numeric_check("gradients", f"R017b Gemini within-style rho, {s}", None if styles is None else styles[i], within[s], digits=3) for i, s in enumerate(STYLES)]
    checks.append(hc.check_row("gradients", "styled arms with r(Q1, concept) < 0.9", None if concept is None else f"{concept[0]} of {concept[1]}", f"{len(below)} of {len(corr)}",
                               concept is not None and len(below) == int(concept[0]) and len(corr) == int(concept[1]), ", ".join(below)))
    checks.append(hc.numeric_check("gradients", "R018b r(Q1, concept)", None if concept is None else concept[2], r018b, digits=3))
    checks.append(hc.numeric_check("gradients", "real 600 r(Q6, concept)", None if concept is None else concept[3], real_corr, digits=3,
                                   note="computed from the real file at run time" if real_corr is not None else "needs --real"))
    return checks


CHECKS: Dict[str, Tuple[Callable[..., List[Dict[str, str]]], bool, str]] = {
    "all-arms": (check_all_arms, True, "rescore the 18 Sept 23-24 comparison folders and recompute ALL_ARMS"),
    "bootstrap": (check_bootstrap, True, "paired persona bootstrap, R018b minus the baselines; same-config rerun spread"),
    "unstyled-mix": (check_unstyled_mix, True, "R018b's deal applied to the unstyled runs; styled minus unstyled over random deals"),
    "money-strip": (check_money_strip, False, "audit of the no-money persona file"),
    "random-control": (check_random_control, True, "RANDOM arm: copied columns and the randomized-only scores"),
    "shuffle": (check_shuffle, True, "summary metrics under shuffles across personas"),
    "gradients": (check_gradients, False, "income-gradient shares, within-style rho, r(Q1, concept); real r with --real"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, needs_real, help_text) in list(CHECKS.items()) + [("all", (None, True, "every check"))]:  # type: ignore[list-item]
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--assets", type=Path, default=hc.DEFAULT_ASSETS, help="the reorganized research data folder (default: next to the repo)")
        p.add_argument("--log", type=Path, default=None, help="EXPERIMENT_LOG.md to read the logged numbers from (default: <assets>/0_logs/EXPERIMENT_LOG.md)")
        p.add_argument("--out", type=Path, default=None, help="output folder, outside the repo (default: <Sept 24 folder>/reproduced_2026-10-18)")
        p.add_argument("--real", type=Path, required=needs_real and name != "gradients", default=None, help="the AYTM raw-data CSV (read for aggregates only)")
        if name in ("bootstrap", "all"):
            p.add_argument("--reps", type=int, default=1000)
            p.add_argument("--seed", type=int, default=12345)
        if name in ("unstyled-mix", "all"):
            p.add_argument("--deals", type=int, default=200)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = Ctx(args)
    names = list(CHECKS) if args.command == "all" else [args.command]
    rows: List[Dict[str, str]] = []
    for name in names:
        func = CHECKS[name][0]
        print(f"== {name}")
        if name == "bootstrap":
            got = func(ctx, reps=args.reps, seed=args.seed)
        elif name == "unstyled-mix":
            got = func(ctx, n_deals=args.deals)
        else:
            got = func(ctx)
        hc.write_csv(ctx.out / f"checks_{name}.csv", got, hc.CHECK_COLUMNS)
        print("  logged vs reproduced:")
        hc.print_checks(got)
        rows += got
    if args.command == "all":
        hc.write_csv(ctx.out / "checks_all.csv", rows, hc.CHECK_COLUMNS)
    print(f"{sum(1 for r in rows if r['match'] == 'true')} of {len(rows)} logged numbers reproduced; wrote {ctx.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
