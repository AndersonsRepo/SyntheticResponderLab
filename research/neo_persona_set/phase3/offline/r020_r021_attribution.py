"""Recover the R020 / R020b / R021 / R021b analysis: pairing, Lin-standard scores, income link, verdicts.

The code behind these results was never committed. This rebuilds it from the session record so the
logged numbers can be re-derived offline: the inline analysis of 2026-10-01 (income rho on the drawn
Q1 and on the expected Q1 from probabilities.csv, the share answering Q1 4-5, R020's pass rule) and
analyze_r021.py of 2026-10-02/03 (the R021 / R021b attribution rule).

    apps/api/.venv/bin/python research/neo_persona_set/phase3/offline/r020_r021_attribution.py \\
        --real "../SyntheticResponderLab-Assets/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv"

R022, the S2 confirmation of R020 (pre-registered 2026-10-19), is scored by the same code with
--only R022: R022 against R022u under Dr. Lin's rule, on Dr. Lin's S2 personas
(4_persona_sets/hybrid_drivers/run_ready/s2lin_drv.csv, never the S1 default) with its own random
control. It needs none of the S1 panels, writes to <its folder>/lin_rule_verdict unless --out-name
says otherwise, and is not compared with the experiment log (it is not a reproduction). The default
run (no --only) is R020 and R021.

Per experiment (R020 and R021; --only picks one, or R022):
1. Finds the panels by run tag under <assets>/5_experiments/*/survey_runs (r1 and r2 of R018u,
   R018b, R020, R020b, R021, R021b and the random control; --run overrides). It builds nothing: a
   missing mixed panel is reported with the make_mixed_panel.py step that would make it, and
   nothing is scored.
2. Checks the persona -> model deal against the baseline, as the pre-registrations require: R020,
   R021 and R021b against R018u (model), R020b against R018b (model and style).
3. Scores every panel and the single-model arms behind them on Dr. Lin's standard with
   compare_real.py --items lin13-validation --real-ids <score_ids.txt>, into
   <experiment folder>/reproduced_2026-10-18/lin13-validation.
4. Per panel and repeat: Spearman rho between the persona's exact household income and (a) the
   drawn / point Q1 answer, (b) the expected Q1 = sum(option x probability) from probabilities.csv
   where the model stated odds; the share answering Q1 4 or 5; and per arm the pooled
   spread_diagnostics.py row (both repeats together).
5. Applies the rules pre-registered in registry.csv, read at run time from the hypothesis text (as
   committed at the pre-registration commit when git can show it, else the working file):
   - R020 / R020b, Dr. Lin's rule: rho(income, Q1) (spread_diagnostics.py, pooled) falls by at
     least X AND validation TV (repeat mean) falls by at least Y, against the named baseline.
     Styles are credited only if R020b beats R020 on mean_spearman beyond the run-to-run range,
     read here as every R020b repeat above every R020 repeat.
   - R021 / R021b, attribution: a component is credited with a metric when its panel moves it from
     R018u toward R020 by at least <fraction> of R020's gain, in both repeats. R020's gains are
     computed from the score files (repeat means), not copied: TV and mean_spearman from
     comparison_summary.csv, the income link on the models' stated belief (expected Q1 where the
     model gave odds, the answer otherwise). TV and mean_spearman moves are paired by repeat; the
     income-link move is measured from R018u's repeat mean, since the rule states one baseline
     value. The thresholds written in the registry are reported beside the computed ones, with the
     verdict under both.
6. Writes <prefix>_table.csv, <prefix>_spread_diagnostics.csv, <prefix>_verdict.json and
   <prefix>_reproduction_check.csv, which compares the recomputed values with the numbers in
   0_logs/EXPERIMENT_LOG.md (at the logged precision; read at run time, never copied here) and with
   the outputs saved at the time (real_comparison/*/comparison_summary.csv,
   spread_diagnostics_*.csv, attribution_R021.json).

Offline: no API calls, no network. Output folders are refused inside the repository
(make_real_split.assert_outside_repo) and inside the real-data folder. Nothing per respondent is
printed. Exit 2 when an input or rule is missing, 1 when a panel is not paired with its baseline.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
REPO_ROOT = PHASE3.parents[2]
if str(PHASE3) not in sys.path:
    sys.path.insert(0, str(PHASE3))

import compare_real  # noqa: E402
import make_real_split  # noqa: E402
import metrics  # noqa: E402
import realdata  # noqa: E402
import spread_diagnostics  # noqa: E402

DEFAULT_ASSETS = REPO_ROOT.parent / "SyntheticResponderLab-Assets"
DEFAULT_REGISTRY = PHASE3 / "registry.csv"
REAL_IDS_REL = Path("3_scoring_standard/real_splits/lin-seed42/score_ids.txt")
PERSONAS_REL = Path("4_persona_sets/hybrid_drivers/run_ready/s1_drv.csv")
# Dr. Lin's S2 (his seed 20260920): the persona file R022 runs on. R022u runs the same 100 persona rows
# of the matched-600 file, whose income columns equal this file's, so one file serves both arms.
PERSONAS_S2_REL = Path("4_persona_sets/hybrid_drivers/run_ready/s2lin_drv.csv")
LOG_REL = Path("0_logs/EXPERIMENT_LOG.md")
OUT_FOLDER = "reproduced_2026-10-18"
ITEMS = "lin13-validation"
ENC = "utf-8-sig"
REPEATS = (1, 2)
NAN = float("nan")
EPS = 1e-12

# Panel arms as (kind, run tag): a panel folder is named <stamp>_<kind>_r<repeat>_<tag>.
ARMS: Dict[str, Tuple[str, str]] = {
    "R018u": ("mixed-panel", "s1-R018u-unstyled"),
    "R018b": ("mixed-panel", "s1-R018b-prereg"),
    "R020": ("mixed-panel", "s1-R020-hybrid-mixed"),
    "R020b": ("mixed-panel", "s1-R020b-hybrid-mixed"),
    "R021": ("mixed-panel", "s1-R021-draw-mixed"),
    "R021b": ("mixed-panel", "s1-R021b-hybrid-mixed"),
    "random": ("random-uniform", "s1-RANDOM"),
    # R022 (S2): the run tags its pre-registration gives make_mixed_panel.py / make_random_panel.py.
    "R022u": ("mixed-panel", "s2lin-R022u-mixed"),
    "R022": ("mixed-panel", "s2lin-R022-hybrid-mixed"),
    "random_s2": ("random-uniform", "s2lin-RANDOM"),
}
# The single-model runs each new panel was dealt from (scored for the record, not used by the rules).
SINGLE_TAGS = {"R020": "s1-R020-hybrid-draw-unstyled", "R020b": "s1-R020b-hybrid-draw-styled",
               "R021": "s1-R021-draw-only", "R021b": "s1-R021b-hybrid-drivers-only",
               "R022": "s2lin-R022-hybrid-draw-unstyled", "R022u": "s2lin-R022u-single-unstyled"}
# Persona deal each panel must share with its baseline: (reference arm, fields that must agree).
PAIRING = {"R020": ("R018u", ("model",)), "R020b": ("R018b", ("model", "trait")),
           "R021": ("R018u", ("model",)), "R021b": ("R018u", ("model",)),
           "R022": ("R022u", ("model",))}
# personas: the persona CSV the income link is read from (relative to --assets; --personas overrides it).
# log_heading: the EXPERIMENT_LOG.md section the numbers are checked against; None for a new experiment.
# out_name: the output subfolder when --out-name is not given.
EXPERIMENTS: Dict[str, Dict[str, Any]] = {
    "R020": {"arms": ["R018u", "R018b", "R020", "R020b", "random"], "singles": ["R020", "R020b"], "prefix": "r020",
             "lin_rule": ["R020", "R020b"], "attribution": [], "log_heading": "R020 / R020b", "personas": PERSONAS_REL, "out_name": OUT_FOLDER},
    "R021": {"arms": ["R018u", "R021", "R021b", "R020", "random"], "singles": ["R021", "R021b"], "prefix": "r021",
             "lin_rule": [], "attribution": ["R021", "R021b"], "log_heading": "R021 / R021b", "personas": PERSONAS_REL, "out_name": OUT_FOLDER},
    "R022": {"arms": ["R022u", "R022", "random_s2"], "singles": ["R022", "R022u"], "prefix": "r022",
             "lin_rule": ["R022"], "attribution": [], "log_heading": None, "personas": PERSONAS_S2_REL, "out_name": "lin_rule_verdict"},
}
# Run when --only is not given: the reproductions. R022 is a new experiment, scored with --only R022.
DEFAULT_EXPERIMENTS = ("R020", "R021")
# R022 is pre-registered by the commit that adds its registry row; a commit cannot name itself, so its
# sha is added here afterwards. Until then its rule is read from the working registry (and the verdict
# records checked_against_commit: false).
PREREG_COMMITS = {"R020": "9caba69", "R020b": "9caba69", "R021": "c5bb11d", "R021b": "c5bb11d"}
# What each attribution hypothesis predicts (credited or not, per metric), and the registry phrase it
# comes from; the phrase must still be in the hypothesis or the script stops.
PREDICTIONS: Dict[str, Tuple[Tuple[str, ...], Dict[str, bool]]] = {
    "R021": (("accounts for R020's gain in distance and rank agreement but not for its drop in the income link",),
             {"tv": True, "spearman": True, "belief_rho": False}),
    "R021b": (("account for R020's drop in the models' income link", "but not for its gain in distance and rank agreement"),
              {"tv": False, "spearman": False, "belief_rho": True}),
}
ATTR_METRICS = (("tv", "validation TV"), ("spearman", "mean_spearman"), ("belief_rho", "rho(income, Q1) on the stated belief"))
METRIC_KEYS = {"mean_spearman": "spearman", "mean_tv": "tv", "share_top_match": "top_match"}
FRACTIONS = {"half": 0.5, "a third": 1.0 / 3.0, "a quarter": 0.25}

LIN_RULE = re.compile(r"rho\(income, Q1\) falls by at least ([0-9.]+) AND validation TV falls by at least ([0-9.]+),? (?:both )?against (R\w+)")
STYLE_RULE = re.compile(r"credited only if (R\w+) beats (R\w+) on (\w+) beyond the run-to-run range")
PASS_NEEDS = re.compile(r"pass needs rho <= ([0-9.]+) and TV <= ([0-9.]+)")
ATTR_RULE = re.compile(r"credited with a metric when its panel moves that metric from (R\w+) toward (R\w+) by at least "
                       r"(half|a third|a quarter|[0-9.]+) of \2's gain, in (both|all|either) repeats")
STATED_TV = re.compile(r"TV ([+-]?[0-9.]+) \(half ([0-9.]+)\)")
STATED_SP = re.compile(r"mean_spearman ([+-]?[0-9.]+) \(half ([0-9.]+)\)")
STATED_RHO = re.compile(r"stated belief ([+-]?[0-9.]+) \(([0-9.]+) to ([0-9.]+); half ([0-9.]+)\)")
EXPECTED_CLAUSE = "rho is judged on the expected Q1 from the odds"

SUMMARY_FIELDS = ("n_synth_after_filter", "questions_close", "mean_tv", "median_tv", "mean_js", "share_top_match", "mean_spearman", "n_real_respondents")
SPREAD_FIELDS = ("n_personas", "q1_ne_q2_share", "mean_sd", "top2_share", "repeat_agreement", "q1_concept_corr", "rho_income_q1")
TABLE_COLUMNS = ["experiment", "arm", "repeat", "run_id", "tv", "spearman", "top_match", "questions_close", "n_scored",
                 "rho_drawn", "rho_expected", "n_expected", "belief_rho", "q1_45_share", "n_q1", "paired_with", "paired_same", "paired_n"]
CHECK_COLUMNS = ["source", "what", "logged", "reproduced", "match", "note"]
# Arm names the 2026-10-03 attribution_R021.json used, and its keys for our measures.
LEGACY_ARM_NAMES = {"R018u": "R018u", "R021": "R021 drawing only", "R021b": "R021b drivers only", "R020": "R020 both", "random": "random"}
LEGACY_KEYS = {"tv": "tv", "spearman": "sp", "top_match": "top", "rho_drawn": "rho", "rho_expected": "rho_ev", "q1_45_share": "top45"}
LEGACY_VERDICT_KEYS = {"tv": "TV", "spearman": "Spearman", "belief_rho": "income link (belief)"}


class InputProblem(Exception):
    """A missing panel, file or rule: reported, never guessed around."""


# ---------- small helpers ----------

def _float(value: Any) -> float:
    try:
        text = str(value).strip()
        return float(text) if text else NAN
    except (TypeError, ValueError):
        return NAN


def _mean(values: Sequence[Optional[float]]) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals and len(vals) == len(values) else NAN


def _isnan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def fmt(value: Any, digits: int = 3) -> str:
    if value is None or _isnan(value):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def clean(value: Any) -> Any:
    """JSON-safe copy: NaN -> null, paths -> str."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if _isnan(value):
        return None
    return value


def read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding=ENC) as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, header: List[str], rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding=ENC) as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None or _isnan(row.get(k)) else row.get(k)) for k in header})


def decimals_of(text: str) -> int:
    cleaned = text.strip().rstrip("%")
    return len(cleaned.split(".", 1)[1]) if "." in cleaned else 0


def matches_logged(logged: str, value: Optional[float], *, percent: bool = False) -> bool:
    """True when `logged` is a correct rounding of `value`: within half a unit of the last logged digit."""
    if value is None or _isnan(value):
        return False
    shown = value * 100.0 if percent else value
    return abs(shown - float(logged.replace("−", "-").rstrip("%"))) <= 0.5 * 10 ** (-decimals_of(logged)) + 1e-9


# ---------- 1. find the panels ----------

def find_panels(assets: Path, arm: str, overrides: Dict[str, List[Path]]) -> Dict[int, Optional[Path]]:
    if arm in overrides:
        dirs = overrides[arm]
        if len(dirs) != len(REPEATS):
            raise InputProblem(f"--run {arm}= needs {len(REPEATS)} folders (r1,r2), got {len(dirs)}")
        return {rep: (Path(d).resolve() if Path(d).is_dir() else None) for rep, d in zip(REPEATS, dirs)}
    kind, tag = ARMS[arm]
    found: Dict[int, Optional[Path]] = {}
    for rep in REPEATS:
        hits = sorted(p.resolve() for p in assets.glob(f"5_experiments/*/survey_runs/*_{kind}_r{rep}_{tag}") if p.is_dir() and not p.name.endswith("_failed"))
        if len(hits) > 1:
            raise InputProblem(f"{arm} r{rep}: {len(hits)} folders match *_{kind}_r{rep}_{tag}: {[str(h) for h in hits]}; pick one with --run {arm}=<r1>,<r2>")
        found[rep] = hits[0] if hits else None
    return found


def missing_message(arm: str, rep: int) -> str:
    kind, tag = ARMS[arm]
    where = f"no 5_experiments/*/survey_runs/*_{kind}_r{rep}_{tag}"
    if kind != "mixed-panel":
        return f"{arm} r{rep}: run missing ({where})"
    single = SINGLE_TAGS.get(arm, "<its single-model runs>")
    return (f"{arm} r{rep}: mixed panel missing ({where}); not built here. To build it: make_mixed_panel.py --keep-arm-order "
            f"--repeat {rep} --run-tag {tag} --arm <the four r{rep} *_{single} runs, in the pre-registered (R018u's) model order: "
            f"qwen, gemini, gpt-5-mini, mistral>")


def find_singles(survey_runs: Path, arms: Sequence[str]) -> List[Path]:
    """The single-model runs behind each panel, named '<time>_<model>_r<k>[_n<N>][_p<N>]_<tag>'.

    phase2/run_survey.make_run_id adds _n<N> under --limit and _p<N> under --persona-ids, so R022u's runs
    (the same 100 rows picked from the matched-600 file) are '<time>_<model>_r<k>_p100_s2lin-R022u-single-unstyled'.
    """
    out: List[Path] = []
    for arm in arms:
        tag = SINGLE_TAGS[arm]
        for rep in REPEATS:
            name = re.compile(rf"_r{rep}(?:_n\d+)?(?:_p\d+)?_{re.escape(tag)}$")
            out += sorted(p.resolve() for p in survey_runs.glob(f"*_r{rep}_*{tag}")
                          if p.is_dir() and name.search(p.name) and "mixed-panel" not in p.name and not p.name.endswith("_failed"))
    return out


# ---------- 2. pairing ----------

def persona_deal(run_dir: Path, fields: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    """persona -> (model, trait, ...): the model per persona from answers_long.csv (a panel's wide file says 'mixed panel')."""
    models: Dict[str, str] = {}
    if "model" in fields:
        for row in read_csv(run_dir / "answers_long.csv"):
            model = (row.get("model") or "").split("/")[-1]
            if models.setdefault(row["persona_id"], model) != model:
                raise InputProblem(f"{run_dir.name}: persona {row['persona_id']} has answers from two models")
    wide = {row["persona_id"]: row for row in spread_diagnostics.read_wide(run_dir)}
    return {pid: tuple(models.get(pid, "") if f == "model" else (row.get(f) or "").strip() for f in fields) for pid, row in wide.items()}


def check_pairing(arm: str, panels: Dict[int, Path], reference: str, ref_panels: Dict[int, Path], fields: Sequence[str]) -> Dict[str, Any]:
    per_repeat = []
    for rep in REPEATS:
        mine, ref = persona_deal(panels[rep], fields), persona_deal(ref_panels[rep], fields)
        same = sum(1 for pid in ref if pid in mine and mine[pid] == ref[pid])
        per_repeat.append({"repeat": rep, "same": same, "n_reference": len(ref), "n_panel": len(mine)})
    ok = all(x["same"] == x["n_reference"] == x["n_panel"] for x in per_repeat)
    return {"arm": arm, "reference": reference, "fields": list(fields), "per_repeat": per_repeat, "ok": ok}


# ---------- 3. scores ----------

def score_runs(real: Path, real_ids: Path, run_dirs: Sequence[Path], out_dir: Path) -> Dict[str, Dict[str, str]]:
    """compare_real.py on Dr. Lin's standard; returns its summary rows keyed by run folder path."""
    code = compare_real.main(["--real", str(real), "--runs", *map(str, run_dirs), "--items", ITEMS, "--real-ids", str(real_ids), "--out", str(out_dir)])
    if code:
        raise InputProblem(f"compare_real.py stopped with exit code {code}")
    summary = {row["run_id"]: row for row in read_csv(out_dir / "comparison_summary.csv")}
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    return {str(Path(run["run_dir"]).resolve()): summary[run["run_id"]] for run in manifest["runs"]}


# ---------- 4. income link and the 4-5 share ----------

def q1_answers(run_dir: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in spread_diagnostics.read_wide(run_dir):
        value = (row.get("Q1") or "").strip()
        if value[:1].isdigit():
            out[row["persona_id"]] = int(value[:1])
    return out


def q1_expected(run_dir: Path) -> Optional[Dict[str, float]]:
    """persona -> sum(option x probability) over Q1's stated odds; None without probabilities.csv or Q1 odds."""
    path = run_dir / "probabilities.csv"
    if not path.is_file():
        return None
    expected: Dict[str, float] = defaultdict(float)
    for row in read_csv(path):
        if row.get("question_id") == "Q1" and (row.get("probability") or "").strip():
            expected[row["persona_id"]] += int(row["option"]) * float(row["probability"])
    return dict(expected) or None


def income_rho(values: Optional[Dict[str, float]], incomes: Dict[str, int]) -> Optional[float]:
    if values is None:
        return None
    keys = sorted(k for k in values if k in incomes)
    if len(keys) < 3:
        return NAN
    return metrics.spearman([float(incomes[k]) for k in keys], [float(values[k]) for k in keys])


def share_45(answers: Dict[str, int]) -> float:
    return sum(1 for v in answers.values() if v >= 4) / len(answers) if answers else NAN


def measure_run(arm: str, rep: int, run_dir: Path, summary: Dict[str, str], incomes: Dict[str, int]) -> Dict[str, Any]:
    drawn, expected = q1_answers(run_dir), q1_expected(run_dir)
    return {"arm": arm, "repeat": rep, "run_id": run_dir.name, "run_dir": str(run_dir),
            "tv": _float(summary.get("mean_tv")), "spearman": _float(summary.get("mean_spearman")), "top_match": _float(summary.get("share_top_match")),
            "questions_close": summary.get("questions_close"), "n_scored": summary.get("n_synth_after_filter"),
            "rho_drawn": income_rho(drawn, incomes), "n_q1": len(drawn),
            "rho_expected": income_rho(expected, incomes), "n_expected": len(expected or {}), "q1_45_share": share_45(drawn)}


def belief(row: Dict[str, Any], on_expected: bool) -> Optional[float]:
    """The models' stated belief: rho on the expected Q1 where there are odds, on the answer otherwise."""
    return row["rho_expected"] if on_expected and row.get("rho_expected") is not None else row["rho_drawn"]


# ---------- 5. rules from the registry ----------

def read_registry(path: Path) -> Dict[str, Dict[str, str]]:
    return {row["registry_id"]: row for row in read_csv(path)}


def prereg_hypothesis(registry: Path, commit: str, registry_id: str) -> Optional[str]:
    """The hypothesis text as committed at the pre-registration commit, or None when git cannot show it."""
    try:
        top = subprocess.run(["git", "-C", str(registry.resolve().parent), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        rel = registry.resolve().relative_to(Path(top).resolve()).as_posix()
        blob = subprocess.run(["git", "-C", top, "show", f"{commit}:{rel}"], capture_output=True, check=True).stdout.decode("utf-8-sig")
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    return next((row.get("hypothesis") for row in csv.DictReader(io.StringIO(blob)) if row.get("registry_id") == registry_id), None)


def rule_text(registry: Path, rows: Dict[str, Dict[str, str]], registry_id: str) -> Tuple[str, Dict[str, Any]]:
    if registry_id not in rows:
        raise InputProblem(f"registry {registry} has no row {registry_id}")
    current = rows[registry_id]["hypothesis"]
    commit = PREREG_COMMITS.get(registry_id, "")
    committed = prereg_hypothesis(registry, commit, registry_id) if commit else None
    source = {"registry": str(registry), "prereg_commit": commit or None,
              "checked_against_commit": committed is not None, "unchanged_since_prereg": None if committed is None else committed == current}
    if committed is not None and committed != current:
        print(f"WARNING: {registry_id}'s hypothesis changed after its pre-registration ({commit}); the committed text is used.", file=sys.stderr)
        return committed, source
    return current, source


def parse_lin_rule(text: str, condition: str, registry_id: str) -> Dict[str, Any]:
    match = LIN_RULE.search(text)
    if not match:
        raise InputProblem(f"{registry_id}: no 'rho(income, Q1) falls by at least .. AND validation TV falls by at least .. against ..' in its hypothesis")
    rule: Dict[str, Any] = {"rho_drop_min": float(match.group(1)), "tv_drop_min": float(match.group(2)), "baseline": match.group(3), "text": match.group(0)}
    stated = PASS_NEEDS.search(condition or "")
    rule["stated"] = {"rho_max": stated.group(1), "tv_max": stated.group(2)} if stated else None
    styles = STYLE_RULE.search(text)
    rule["styles"] = {"arm": styles.group(1), "against": styles.group(2), "metric": styles.group(3), "text": styles.group(0)} if styles else None
    return rule


def parse_attribution_rule(text: str, registry_id: str) -> Dict[str, Any]:
    match = ATTR_RULE.search(text)
    if not match:
        raise InputProblem(f"{registry_id}: no attribution rule ('credited with a metric when its panel moves that metric from .. toward .. by at least .. of ..'s gain, in .. repeats') in its hypothesis")
    word = match.group(3)
    rule: Dict[str, Any] = {"baseline": match.group(1), "target": match.group(2), "fraction": FRACTIONS.get(word) or float(word),
                            "fraction_text": word, "repeats": match.group(4), "belief_on_expected": EXPECTED_CLAUSE in text, "text": match.group(0)}
    stated: Dict[str, Dict[str, str]] = {}
    tv, sp, rho = STATED_TV.search(text), STATED_SP.search(text), STATED_RHO.search(text)
    if tv:
        stated["tv"] = {"gain": tv.group(1).lstrip("+-"), "threshold": tv.group(2)}
    if sp:
        stated["spearman"] = {"gain": sp.group(1).lstrip("+-"), "threshold": sp.group(2)}
    if rho:
        stated["belief_rho"] = {"gain": rho.group(1).lstrip("+-"), "baseline": rho.group(2), "target": rho.group(3), "threshold": rho.group(4)}
    rule["stated"] = stated
    phrases, predicted = PREDICTIONS[registry_id]
    missing = [p for p in phrases if p not in text]
    if missing:
        raise InputProblem(f"{registry_id}: the hypothesis no longer says {missing[0]!r}, so its prediction cannot be read; update PREDICTIONS")
    rule["predicted"] = predicted
    return rule


def lin_verdict(arm: str, rule: Dict[str, Any], table: Dict[str, List[Dict[str, Any]]], spread: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    base = rule["baseline"]
    tv_base, tv_arm = _mean([r["tv"] for r in table[base]]), _mean([r["tv"] for r in table[arm]])
    rho_base, rho_arm = spread[base]["rho_income_q1"], spread[arm]["rho_income_q1"]
    out: Dict[str, Any] = {
        "arm": arm, "baseline": base, "rule": rule["text"],
        "tv_mean": tv_arm, "tv_baseline_mean": tv_base, "tv_drop": tv_base - tv_arm, "tv_drop_min": rule["tv_drop_min"],
        "rho_pooled": rho_arm, "rho_baseline_pooled": rho_base, "rho_drop": rho_base - rho_arm, "rho_drop_min": rule["rho_drop_min"],
        "rho_repeat_mean": _mean([r["rho_drawn"] for r in table[arm]]), "rho_baseline_repeat_mean": _mean([r["rho_drawn"] for r in table[base]]),
    }
    out["tv_ok"] = out["tv_drop"] >= rule["tv_drop_min"] - EPS
    out["rho_ok"] = out["rho_drop"] >= rule["rho_drop_min"] - EPS
    out["pass"] = out["tv_ok"] and out["rho_ok"]
    stated = rule.get("stated")
    if stated:
        computed = {"rho_max": rho_base - rule["rho_drop_min"], "tv_max": tv_base - rule["tv_drop_min"]}
        out["stated_thresholds"] = {k: {"stated": v, "computed": computed[k], "agree_at_stated_precision": matches_logged(v, computed[k])} for k, v in stated.items()}
        out["pass_under_stated_thresholds"] = tv_arm <= float(stated["tv_max"]) + EPS and rho_arm <= float(stated["rho_max"]) + EPS
    return out


def styles_verdict(rule: Dict[str, Any], table: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    key = METRIC_KEYS.get(rule["metric"], rule["metric"])
    mine, other = [r[key] for r in table[rule["arm"]]], [r[key] for r in table[rule["against"]]]
    return {"arm": rule["arm"], "against": rule["against"], "metric": rule["metric"], "rule": rule["text"], "values": mine, "against_values": other,
            "reading": f"every {rule['arm']} repeat above every {rule['against']} repeat", "credited": min(mine) > max(other)}


def attribution_verdict(component: str, rule: Dict[str, Any], table: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    base_rows, target_rows, rows = table[rule["baseline"]], table[rule["target"]], table[component]
    on_ev = rule["belief_on_expected"]
    need_all = rule["repeats"] in ("both", "all")

    def value(row: Dict[str, Any], metric: str) -> Optional[float]:
        return belief(row, on_ev) if metric == "belief_rho" else row[metric]

    def credited(moves: List[float], threshold: float) -> bool:
        oks = [m >= threshold - EPS for m in moves]
        return all(oks) if need_all else any(oks)

    out: Dict[str, Any] = {"component": component, "baseline": rule["baseline"], "target": rule["target"], "rule": rule["text"],
                           "fraction": rule["fraction"], "metrics": {}}
    for metric, label in ATTR_METRICS:
        base_mean, target_mean = _mean([value(r, metric) for r in base_rows]), _mean([value(r, metric) for r in target_rows])
        direction = 1.0 if target_mean >= base_mean else -1.0
        gain = abs(target_mean - base_mean)
        threshold = rule["fraction"] * gain
        if metric == "belief_rho":
            moves = [(value(r, metric) - base_mean) * direction for r in rows]
        else:
            moves = [(value(r, metric) - value(b, metric)) * direction for b, r in zip(base_rows, rows)]
        entry: Dict[str, Any] = {"label": label, "values": [value(r, metric) for r in rows], "baseline_mean": base_mean, "target_mean": target_mean,
                                 "gain": gain, "threshold": threshold, "moves": moves, "credited": credited(moves, threshold)}
        stated = rule["stated"].get(metric)
        if stated:
            stated_base = float(stated["baseline"]) if metric == "belief_rho" else None
            stated_moves = moves if stated_base is None else [(value(r, metric) - stated_base) * direction for r in rows]
            entry["stated"] = dict(stated, credited=credited(stated_moves, float(stated["threshold"])),
                                   gain_agrees=matches_logged(stated["gain"], gain), threshold_agrees=matches_logged(stated["threshold"], threshold))
        out["metrics"][metric] = entry
    out["credited"] = {m: out["metrics"][m]["credited"] for m, _ in ATTR_METRICS}
    out["predicted"] = rule["predicted"]
    out["supported"] = out["credited"] == rule["predicted"]
    stated_credits = {m: out["metrics"][m].get("stated", {}).get("credited") for m, _ in ATTR_METRICS}
    out["supported_under_stated_thresholds"] = None if None in stated_credits.values() else stated_credits == rule["predicted"]
    return out


# ---------- 6. reproduction checks ----------

def log_section(text: str, heading: str) -> Optional[str]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("### ") and heading in line), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith(("### ", "## ")) or lines[j].strip() == "---"), len(lines))
    return "\n".join(lines[start:end])


def log_table(section: str) -> List[Dict[str, str]]:
    """The first markdown table in the section whose header has a TV column, as dicts keyed by header text."""
    blocks: List[List[str]] = []
    current: List[str] = []
    for line in section.splitlines() + [""]:
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    for block in blocks:
        cells = [[c.strip().replace("**", "") for c in line.strip().strip("|").split("|")] for line in block]
        if "TV" in cells[0]:
            return [dict(zip(cells[0], row)) for row in cells[2:]]
    return []


def log_arm(label: str) -> Optional[str]:
    if label.lower().startswith("random"):
        return "random"
    match = re.match(r"(R\d+\w*)\b", label)
    return match.group(1) if match else None  # "Real vs real" and anything else is skipped


def _logged_values(cell: str) -> List[Optional[str]]:
    return [None if p.strip() in ("", "—", "-", "–") else p.strip() for p in cell.split("/")]


def check(source: str, what: str, logged: Optional[str], value: Any, match: bool, note: str = "") -> Dict[str, str]:
    shown = value if isinstance(value, str) else ("" if value is None or _isnan(value) else (str(value) if isinstance(value, (bool, int)) else f"{value:.6g}"))
    return {"source": source, "what": what, "logged": "NOT FOUND" if logged is None else logged, "reproduced": shown, "match": "true" if match else "false", "note": note}


def log_checks(log_path: Path, heading: str, table: Dict[str, List[Dict[str, Any]]], spread: Dict[str, Dict[str, Any]],
               verdict_words: Dict[str, str], thresholds: Dict[str, float]) -> List[Dict[str, str]]:
    src = LOG_REL.as_posix()
    if not log_path.is_file():
        return [check(src, "experiment log", None, "", False, f"{log_path} not found")]
    section = log_section(log_path.read_text(encoding="utf-8"), heading)
    if section is None:
        return [check(src, f"section '{heading}'", None, "", False, "heading not found")]
    out: List[Dict[str, str]] = []
    for row in log_table(section):
        arm = log_arm(next(iter(row.values()), ""))
        if arm not in table:
            continue
        for header, cell in row.items():
            if header == "TV":
                key, percent = "tv", False
            elif header == "Spearman":
                key, percent = "spearman", False
            elif header == "Top match":
                key, percent = "top_match", False
            elif header.startswith("ρ(income"):
                key, percent = "rho_drawn", False
            elif "expected" in header:
                key, percent = "rho_expected", False
            elif header.startswith("Q1 4"):
                key, percent = "q1_45_share", True
            else:
                continue
            logged = _logged_values(cell)
            if key == "rho_drawn" and len(logged) == 1:  # one number: spread_diagnostics' pooled rho over both repeats
                if logged[0] is not None:
                    value = spread[arm]["rho_income_q1"]
                    out.append(check(src, f"{arm} {header} (pooled r1+r2)", logged[0], value, matches_logged(logged[0], value)))
                continue
            for rep, text in zip(REPEATS, logged):
                if text is not None:
                    value = table[arm][rep - 1][key]
                    out.append(check(src, f"{arm} r{rep} {header}", text, value, matches_logged(text, value, percent=percent)))
    for arm, word in re.findall(r"\*\*(R\d+\w*)(?: \([^)]*\))?: (pass|fail|supported|not supported)\b", section, flags=re.I):
        if arm in verdict_words:
            out.append(check(src, f"{arm} verdict", word.lower(), verdict_words[arm], word.lower() == verdict_words[arm]))
    stated = re.search(r"TV ≥ ([0-9.]+), rank agreement ≥ ([0-9.]+), income link in the stated belief ≥ ([0-9.]+)", section)
    if stated and thresholds:
        for key, text in zip(("tv", "spearman", "belief_rho"), stated.groups()):
            ok = matches_logged(text, thresholds[key])
            note = "" if ok else "the log halves R020's gain after rounding it; the verdict does not depend on it (see the verdict under the stated thresholds)"
            out.append(check(src, f"attribution threshold {key}", text, thresholds[key], ok, note))
    return out


def _same_number(old: str, new: Any) -> bool:
    a, b = _float(old), _float(new)
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-9


def saved_checks(exp_dir: Path, summaries: Dict[str, Dict[str, str]], spread_rows: List[Dict[str, Any]],
                 table: Dict[str, List[Dict[str, Any]]], attributions: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    new_by_id = {row["run_id"]: row for row in summaries.values()}
    for path in sorted(exp_dir.glob("real_comparison/*/comparison_summary.csv")):
        src = path.relative_to(exp_dir).as_posix()
        for old in read_csv(path):
            new = new_by_id.get(old["run_id"])
            if new is None or old.get("item_set") != new.get("item_set"):
                continue
            for field in SUMMARY_FIELDS:
                out.append(check(src, f"{old['run_id']} {field}", old.get(field, ""), new.get(field, ""), old.get(field, "") == new.get(field, "")))
    ours = {row["runs"]: row for row in spread_rows}
    for path in sorted(exp_dir.glob("real_comparison/spread_diagnostics_*.csv")):
        src = path.relative_to(exp_dir).as_posix()
        for old in read_csv(path):
            new = ours.get(old["runs"])
            if new is None:
                continue
            for field in SPREAD_FIELDS:
                out.append(check(src, f"{old['arm']} {field}", old[field], new[field], _same_number(old[field], new[field])))
    path = exp_dir / "real_comparison" / "attribution_R021.json"
    if path.is_file() and attributions:
        src = path.relative_to(exp_dir).as_posix()
        saved = json.loads(path.read_text(encoding="utf-8"))
        for arm, name in LEGACY_ARM_NAMES.items():
            for rep, old in zip(REPEATS, saved.get("table", {}).get(name, [])):
                for key, old_key in LEGACY_KEYS.items():
                    old_value = old.get(old_key)
                    if old_value is None or _isnan(old_value) or arm not in table:
                        continue  # not computed then (the random control's income link)
                    new_value = table[arm][rep - 1][key]
                    out.append(check(src, f"{name} r{rep} {old_key}", repr(old_value), new_value, _same_number(old_value, new_value)))
        for component, verdict in attributions.items():
            old = saved.get("verdict", {}).get(LEGACY_ARM_NAMES.get(component, component))
            if not old:
                continue
            for metric, old_key in LEGACY_VERDICT_KEYS.items():
                out.append(check(src, f"{component} credited {old_key}", str(old.get(old_key)), verdict["credited"][metric], old.get(old_key) == verdict["credited"][metric]))
            for rep, (old_value, new_value) in enumerate(zip(old.get("belief rho", []), verdict["metrics"]["belief_rho"]["values"]), start=1):
                out.append(check(src, f"{component} r{rep} belief rho", repr(old_value), new_value, _same_number(old_value, new_value)))
    return out


# ---------- run one experiment ----------

def print_table(table: Dict[str, List[Dict[str, Any]]], spread: Dict[str, Dict[str, Any]]) -> None:
    print(f"{'arm':7s} {'rep':3s} {'TV':>6s} {'Spearman':>8s} {'top':>6s} {'rho Q1':>7s} {'rho E[Q1]':>9s} {'Q1 4-5':>6s}  pooled rho, Q1!=Q2, repeat agreement")
    for arm, rows in table.items():
        for row in rows:
            share = "—" if _isnan(row["q1_45_share"]) else f"{row['q1_45_share']:.0%}"
            pooled = spread[arm] if row["repeat"] == REPEATS[0] else None
            extra = f"  {fmt(pooled['rho_income_q1'], 2)}, {fmt(pooled['q1_ne_q2_share'], 2)}, {fmt(pooled['repeat_agreement'], 2)}" if pooled else ""
            print(f"{arm:7s} r{row['repeat']:<2d} {fmt(row['tv']):>6s} {fmt(row['spearman']):>8s} {fmt(row['top_match']):>6s} "
                  f"{fmt(row['rho_drawn']):>7s} {fmt(row['rho_expected']):>9s} {share:>6s}{extra}")


def load_rules(name: str, registry: Path, registry_rows: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    spec = EXPERIMENTS[name]
    rules: Dict[str, Any] = {}
    for rid in spec["lin_rule"]:
        text, source = rule_text(registry, registry_rows, rid)
        rules[rid] = dict(parse_lin_rule(text, registry_rows[rid].get("condition", ""), rid), source=source)
    for rid in spec["attribution"]:
        text, source = rule_text(registry, registry_rows, rid)
        rules[rid] = dict(parse_attribution_rule(text, rid), source=source)
    return rules


def run_experiment(name: str, panels: Dict[str, Dict[int, Path]], args: argparse.Namespace, rules: Dict[str, Any], personas: Path) -> int:
    spec = EXPERIMENTS[name]
    exp_dir = panels[name][REPEATS[0]].parent.parent
    if any(panels[name][rep].parent.parent != exp_dir for rep in REPEATS):
        raise InputProblem(f"{name}'s r1 and r2 panels are in different experiment folders")
    incomes = spread_diagnostics.read_incomes(personas)

    out_dir = realdata.assert_not_real_data_path(exp_dir / (args.out_name or spec["out_name"]), "--out-name")
    out_dir = make_real_split.assert_outside_repo(out_dir, "--out-name")
    out_dir = realdata.assert_outside_real_folder(out_dir, args.real, "--out-name")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {name}: {exp_dir}")

    # 2
    pairing = {}
    for arm in spec["arms"]:
        if arm in PAIRING:
            reference, fields = PAIRING[arm]
            ref_panels = panels[reference] if reference in panels else None
            if ref_panels is None:
                continue
            pairing[arm] = check_pairing(arm, panels[arm], reference, ref_panels, fields)
            for x in pairing[arm]["per_repeat"]:
                print(f"pairing {arm} r{x['repeat']} vs {reference} ({'+'.join(fields)}): {x['same']}/{x['n_reference']}" + ("" if pairing[arm]["ok"] else "  NOT PAIRED"))

    # 3
    singles = [] if args.no_singles else find_singles(exp_dir / "survey_runs", spec["singles"])
    run_dirs = [panels[arm][rep] for arm in spec["arms"] for rep in REPEATS] + singles
    summaries = score_runs(args.real, args.real_ids, run_dirs, out_dir / ITEMS)

    # 4
    table = {arm: [measure_run(arm, rep, panels[arm][rep], summaries[str(panels[arm][rep])], incomes) for rep in REPEATS] for arm in spec["arms"]}
    spread_rows = [spread_diagnostics.diagnose_arm(arm, [panels[arm][rep] for rep in REPEATS], personas_csv=personas) for arm in spec["arms"]]
    spread = {row["arm"]: row for row in spread_rows}
    on_ev = any(rules[rid].get("belief_on_expected") for rid in spec["attribution"])
    for arm, rows in table.items():
        for row in rows:
            row["belief_rho"] = belief(row, on_ev)
            if arm in pairing:
                rep = pairing[arm]["per_repeat"][row["repeat"] - 1]
                row.update(paired_with=pairing[arm]["reference"], paired_same=rep["same"], paired_n=rep["n_reference"])
    print_table(table, spread)

    # 5
    verdicts: Dict[str, Any] = {}
    words: Dict[str, str] = {}
    for rid in spec["lin_rule"]:
        verdicts[rid] = lin_verdict(rid, rules[rid], table, spread)
        words[rid] = "pass" if verdicts[rid]["pass"] else "fail"
        if rules[rid]["styles"]:
            verdicts[rid]["styles"] = styles_verdict(rules[rid]["styles"], table)
        v = verdicts[rid]
        print(f"{rid} vs {v['baseline']}: TV drop {v['tv_drop']:.3f} (needs {v['tv_drop_min']}), rho drop {v['rho_drop']:.3f} (needs {v['rho_drop_min']}) "
              f"-> {words[rid].upper()}" + (f"; styles credited: {fmt(v['styles']['credited'])}" if "styles" in v else ""))
    attributions: Dict[str, Any] = {}
    thresholds: Dict[str, float] = {}
    for rid in spec["attribution"]:
        attributions[rid] = verdicts[rid] = attribution_verdict(rid, rules[rid], table)
        words[rid] = "supported" if verdicts[rid]["supported"] else "not supported"
        thresholds = {m: verdicts[rid]["metrics"][m]["threshold"] for m, _ in ATTR_METRICS}
        credits = ", ".join(f"{m} {'credited' if c else 'not credited'}" for m, c in verdicts[rid]["credited"].items())
        print(f"{rid}: {credits} -> {words[rid].upper()}")
    if thresholds:
        print("attribution thresholds (computed from the score files): " + ", ".join(f"{m} {t:.4f}" for m, t in thresholds.items()))

    # 6
    prefix = spec["prefix"]
    checks = [] if args.no_check else (
        (log_checks(args.assets / LOG_REL, spec["log_heading"], table, spread, words, thresholds) if spec["log_heading"] else [])
        + saved_checks(exp_dir, summaries, spread_rows, table, attributions))
    table_rows = [dict(row, experiment=name) for rows in table.values() for row in rows]
    write_csv(out_dir / f"{prefix}_table.csv", TABLE_COLUMNS, table_rows)
    write_csv(out_dir / f"{prefix}_spread_diagnostics.csv", spread_diagnostics.COLUMNS, spread_rows)
    write_csv(out_dir / f"{prefix}_reproduction_check.csv", CHECK_COLUMNS, checks)
    matched = sum(1 for c in checks if c["match"] == "true")
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(), "experiment": name, "experiment_folder": exp_dir,
        "script": {"path": "research/neo_persona_set/phase3/offline/r020_r021_attribution.py", **compare_real.git_info()},
        "inputs": {"real": args.real, "real_ids": args.real_ids, "items": ITEMS, "personas": personas, "registry": args.registry,
                   "comparison": out_dir / ITEMS},
        "panels": {arm: [panels[arm][rep] for rep in REPEATS] for arm in spec["arms"]}, "singles": singles,
        "pairing": pairing, "pairing_ok": all(p["ok"] for p in pairing.values()),
        "table": table, "spread": spread, "rules": rules, "verdicts": verdicts, "verdict_words": words,
        "reproduction_check": {"checked": len(checks), "matched": matched, "mismatches": [c for c in checks if c["match"] != "true"]},
    }
    (out_dir / f"{prefix}_verdict.json").write_text(json.dumps(clean(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if checks:
        print(f"reproduction check: {matched} of {len(checks)} values match the log and the outputs saved at the time")
        for c in checks:
            if c["match"] != "true":
                print(f"  DIFF {c['source']}: {c['what']}: logged {c['logged']}, reproduced {c['reproduced']}  {c['note']}")
    print(f"wrote {out_dir}")
    return 0 if payload["pairing_ok"] else 1


def parse_overrides(specs: Sequence[str]) -> Dict[str, List[Path]]:
    out: Dict[str, List[Path]] = {}
    for spec in specs:
        arm, _, paths = spec.partition("=")
        if arm.strip() not in ARMS:
            raise InputProblem(f"--run {spec}: unknown arm {arm!r} (one of {', '.join(ARMS)})")
        out[arm.strip()] = [Path(p.strip()).expanduser() for p in paths.split(",") if p.strip()]
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real", type=Path, required=True, help="the AYTM raw-data CSV (read by compare_real.py only; never copied)")
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS, help="the research data folder (default: next to the repository)")
    parser.add_argument("--real-ids", type=Path, default=None, help=f"Dr. Lin's val half (default: <assets>/{REAL_IDS_REL.as_posix()})")
    parser.add_argument("--personas", type=Path, default=None,
                        help=f"persona CSV with exact_household_income (default: per experiment, <assets>/{PERSONAS_REL.as_posix()} "
                             f"for R020 and R021, <assets>/{PERSONAS_S2_REL.as_posix()} for R022)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--only", choices=sorted(EXPERIMENTS), default=None, help=f"one experiment (default: {' and '.join(DEFAULT_EXPERIMENTS)})")
    parser.add_argument("--run", action="append", default=[], metavar="ARM=R1_DIR,R2_DIR", help="use these folders instead of finding the arm by run tag")
    parser.add_argument("--out-name", default=None,
                        help=f"subfolder of each experiment folder for the outputs (default: {OUT_FOLDER} for R020 and R021, "
                             f"{EXPERIMENTS['R022']['out_name']} for R022)")
    parser.add_argument("--no-singles", action="store_true", help="score only the panels, not the single-model runs behind them")
    parser.add_argument("--no-check", action="store_true", help="skip the comparison with the log and the saved outputs")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    args.assets = Path(args.assets).expanduser().resolve()
    args.real = Path(args.real).expanduser().resolve()
    args.real_ids = Path(args.real_ids or args.assets / REAL_IDS_REL).expanduser().resolve()
    args.personas = Path(args.personas).expanduser().resolve() if args.personas else None
    args.registry = Path(args.registry).expanduser().resolve()
    names = [args.only] if args.only else list(DEFAULT_EXPERIMENTS)
    # Each experiment reads incomes from its own persona file (R022: S2, never the S1 default).
    personas = {name: args.personas or (args.assets / EXPERIMENTS[name]["personas"]).resolve() for name in names}
    try:
        if args.personas and len({EXPERIMENTS[name]["personas"] for name in names}) > 1:
            raise InputProblem("--personas would replace different persona files for " + ", ".join(names) + "; pick one with --only")
        for label, path in [("--real", args.real), ("--real-ids", args.real_ids), ("--registry", args.registry)] + [(f"--personas ({n})", p) for n, p in personas.items()]:
            if not path.is_file():
                raise InputProblem(f"{label} {path} is not a file")
        overrides = parse_overrides(args.run)
        wanted = sorted({arm for n in names for arm in EXPERIMENTS[n]["arms"]} | {PAIRING[a][0] for n in names for a in EXPERIMENTS[n]["arms"] if a in PAIRING})
        found = {arm: find_panels(args.assets, arm, overrides) for arm in wanted}
        missing = [missing_message(arm, rep) for arm in wanted for rep in REPEATS if found[arm][rep] is None]
        if missing:
            print("Nothing scored; missing:\n  " + "\n  ".join(missing), file=sys.stderr)
            return 2
        panels = {arm: {rep: p for rep, p in reps.items() if p is not None} for arm, reps in found.items()}
        registry_rows = read_registry(args.registry)
        rules = {name: load_rules(name, args.registry, registry_rows) for name in names}  # every rule read before anything is written
        codes = [run_experiment(name, panels, args, rules[name], personas[name]) for name in names]
    except InputProblem as problem:
        print(f"r020_r021_attribution: {problem}", file=sys.stderr)
        return 2
    return max(codes)


if __name__ == "__main__":
    raise SystemExit(main())
